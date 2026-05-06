#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.voice_runtime import OpenAIRealtimeTranscriptionClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a raw 16 kHz mono PCM file into OpenAI Realtime transcription.")
    parser.add_argument("pcm_path", type=Path, help="Path to a pcm_s16le 16 kHz mono file")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "voice_settings.json")
    parser.add_argument("--session-id", default="bench_realtime")
    parser.add_argument("--chunk-ms", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--language", default=None)
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--vad-threshold", type=float, default=None)
    parser.add_argument("--vad-prefix-ms", type=int, default=None)
    parser.add_argument("--vad-silence-ms", type=int, default=None)
    parser.add_argument("--noise-reduction", default=None)
    parser.add_argument("--partial-debounce-ms", type=int, default=None)
    parser.add_argument("--tail-silence-ms", type=int, default=900)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--ready-timeout", type=float, default=15.0)
    parser.add_argument("--settle-timeout", type=float, default=8.0)
    parser.add_argument("--pace", choices=("realtime", "fast"), default="realtime")
    parser.add_argument("--turn-detection", choices=("server_vad", "manual"), default="server_vad")
    parser.add_argument("--manual-commit-ms", type=int, default=480)
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    api_key = str(payload.get("openaiApiKey") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("Missing OpenAI API key in config or OPENAI_API_KEY")
    payload["openaiApiKey"] = api_key
    payload.setdefault("openaiBaseUrl", "https://api.openai.com/v1")
    payload.setdefault("transcriptionModel", "gpt-4o-mini-transcribe")
    payload.setdefault("languageHint", "vi")
    payload.setdefault("openaiTranscriptionPrompt", "")
    payload.setdefault("realtimeChunkMs", 120)
    payload.setdefault("realtimeVadThreshold", 0.5)
    payload.setdefault("realtimeVadPrefixPaddingMs", 300)
    payload.setdefault("realtimeVadSilenceDurationMs", 500)
    payload.setdefault("realtimePartialDebounceMs", 120)
    payload.setdefault("realtimeNoiseReduction", "near_field")
    payload.setdefault("realtimeIncludeLogprobs", False)
    return payload


def apply_overrides(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    next_config = dict(config)
    if args.chunk_ms is not None:
        next_config["realtimeChunkMs"] = args.chunk_ms
    if args.model:
        next_config["transcriptionModel"] = args.model
    if args.language:
        next_config["languageHint"] = args.language
    if args.prompt is not None:
        next_config["openaiTranscriptionPrompt"] = args.prompt
    if args.vad_threshold is not None:
        next_config["realtimeVadThreshold"] = args.vad_threshold
    if args.vad_prefix_ms is not None:
        next_config["realtimeVadPrefixPaddingMs"] = args.vad_prefix_ms
    if args.vad_silence_ms is not None:
        next_config["realtimeVadSilenceDurationMs"] = args.vad_silence_ms
    if args.noise_reduction is not None:
        next_config["realtimeNoiseReduction"] = args.noise_reduction
    if args.partial_debounce_ms is not None:
        next_config["realtimePartialDebounceMs"] = args.partial_debounce_ms
    return next_config


def script_bucket(text: str) -> str:
    counts = {
        "latin": 0,
        "hangul": 0,
        "cjk": 0,
        "cyrillic": 0,
        "thai": 0,
        "other": 0,
    }
    for char in text:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        if "LATIN" in name:
            counts["latin"] += 1
        elif "HANGUL" in name:
            counts["hangul"] += 1
        elif "CJK UNIFIED" in name:
            counts["cjk"] += 1
        elif "CYRILLIC" in name:
            counts["cyrillic"] += 1
        elif "THAI" in name:
            counts["thai"] += 1
        else:
            counts["other"] += 1
    return max(counts, key=counts.get)


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return int(ordered[index])


def main() -> int:
    args = parse_args()
    config = apply_overrides(load_config(args.config), args)
    pcm = args.pcm_path.read_bytes()
    bytes_per_second = 16_000 * 2
    if args.max_seconds is not None:
        pcm = pcm[: int(max(0, args.max_seconds) * bytes_per_second)]
    if not pcm:
        raise SystemExit("PCM payload is empty")

    session_id = args.session_id
    chunk_ms = max(40, int(config.get("realtimeChunkMs") or 120))
    chunk_bytes = bytes_per_second * chunk_ms // 1000
    tail_silence_bytes = bytes_per_second * max(0, args.tail_silence_ms) // 1000

    lock = threading.Lock()
    first_append_at: float | None = None
    ready_at: float | None = None
    last_event_at: float = time.perf_counter()
    partials: list[dict[str, Any]] = []
    finals: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []

    def log_handler(_: str, event: str, fields: dict[str, Any]) -> None:
        nonlocal ready_at, last_event_at
        now = time.perf_counter()
        with lock:
            last_event_at = now
            logs.append({"event": event, "at": now, "fields": dict(fields)})
            if event == "voice_realtime_session_updated" and ready_at is None:
                ready_at = now

    def partial_handler(_: str, transcript: str, meta: dict[str, Any]) -> None:
        nonlocal last_event_at
        now = time.perf_counter()
        with lock:
            last_event_at = now
            partials.append(
                {
                    "at": now,
                    "transcript": transcript,
                    "length": len(transcript),
                    "meta": dict(meta),
                }
            )

    def final_handler(_: str, transcript: str, meta: dict[str, Any]) -> None:
        nonlocal last_event_at
        now = time.perf_counter()
        with lock:
            last_event_at = now
            finals.append(
                {
                    "at": now,
                    "transcript": transcript,
                    "meta": dict(meta),
                    "script": script_bucket(transcript),
                }
            )

    def status_handler(_: str, payload: dict[str, Any]) -> None:
        nonlocal last_event_at
        now = time.perf_counter()
        with lock:
            last_event_at = now
            statuses.append({"at": now, **dict(payload)})

    client = OpenAIRealtimeTranscriptionClient(
        session_id=session_id,
        config_provider=lambda: config,
        log_handler=log_handler,
        partial_handler=partial_handler,
        final_handler=final_handler,
        status_handler=status_handler,
        source_label="benchmark_realtime",
        task_label="benchmark",
        turn_detection_mode=args.turn_detection,
    )

    try:
        ready_deadline = time.perf_counter() + args.ready_timeout
        while time.perf_counter() < ready_deadline:
            if client.is_ready():
                break
            time.sleep(0.05)
        if not client.is_ready():
            raise SystemExit("Realtime session did not become ready")

        send_started_at = time.perf_counter()
        next_deadline = send_started_at
        bytes_since_commit = 0
        commit_bytes = bytes_per_second * max(80, args.manual_commit_ms) // 1000
        for offset in range(0, len(pcm), chunk_bytes):
            chunk = pcm[offset : offset + chunk_bytes]
            if not chunk:
                continue
            if first_append_at is None:
                first_append_at = time.perf_counter()
            client.append_pcm(chunk)
            bytes_since_commit += len(chunk)
            if args.turn_detection == "manual" and bytes_since_commit >= commit_bytes:
                client.commit_audio()
                bytes_since_commit = 0
            if args.pace == "realtime":
                next_deadline += chunk_ms / 1000.0
                sleep_s = next_deadline - time.perf_counter()
                if sleep_s > 0:
                    time.sleep(sleep_s)

        if tail_silence_bytes > 0:
            silence = b"\x00" * tail_silence_bytes
            for offset in range(0, len(silence), chunk_bytes):
                chunk = silence[offset : offset + chunk_bytes]
                if not chunk:
                    continue
                client.append_pcm(chunk)
                bytes_since_commit += len(chunk)
                if args.turn_detection == "manual" and bytes_since_commit >= commit_bytes:
                    client.commit_audio()
                    bytes_since_commit = 0
                if args.pace == "realtime":
                    next_deadline += chunk_ms / 1000.0
                    sleep_s = next_deadline - time.perf_counter()
                    if sleep_s > 0:
                        time.sleep(sleep_s)

        min_commit_bytes = bytes_per_second * 100 // 1000
        if args.turn_detection == "manual" and bytes_since_commit >= min_commit_bytes:
            client.commit_audio()

        send_finished_at = time.perf_counter()
        settle_deadline = send_finished_at + args.settle_timeout
        while time.perf_counter() < settle_deadline:
            with lock:
                quiet_for = time.perf_counter() - last_event_at
                final_count = len(finals)
            if final_count > 0 and quiet_for >= 1.0:
                break
            time.sleep(0.1)
    finally:
        client.close("benchmark_complete")

    if first_append_at is None:
        raise SystemExit("No audio chunks were sent")

    partial_latencies_ms = [int((item["at"] - first_append_at) * 1000) for item in partials]
    final_latencies_ms = [int((item["at"] - first_append_at) * 1000) for item in finals]
    non_empty_partials = [item for item in partials if str(item.get("transcript") or "").strip()]
    non_empty_finals = [item for item in finals if str(item.get("transcript") or "").strip()]
    non_empty_partial_latencies_ms = [int((item["at"] - first_append_at) * 1000) for item in non_empty_partials]
    non_empty_final_latencies_ms = [int((item["at"] - first_append_at) * 1000) for item in non_empty_finals]
    transcribe_latencies_ms = [
        int(item["meta"].get("transcribeMs") or 0)
        for item in finals
        if int(item["meta"].get("transcribeMs") or 0) > 0
    ]
    scripts: dict[str, int] = {}
    for item in finals:
        bucket = str(item["script"])
        scripts[bucket] = scripts.get(bucket, 0) + 1

    summary = {
        "sessionId": session_id,
        "pcmPath": str(args.pcm_path),
        "durationSec": round(len(pcm) / bytes_per_second, 3),
        "sendWallClockSec": round(send_finished_at - send_started_at, 3),
        "model": config["transcriptionModel"],
        "languageHint": config["languageHint"],
        "chunkMs": chunk_ms,
        "vadThreshold": float(config["realtimeVadThreshold"]),
        "vadPrefixPaddingMs": int(config["realtimeVadPrefixPaddingMs"]),
        "vadSilenceDurationMs": int(config["realtimeVadSilenceDurationMs"]),
        "noiseReduction": str(config.get("realtimeNoiseReduction") or ""),
        "turnDetection": args.turn_detection,
        "manualCommitMs": args.manual_commit_ms if args.turn_detection == "manual" else None,
        "partialCount": len(partials),
        "nonEmptyPartialCount": len(non_empty_partials),
        "finalCount": len(finals),
        "nonEmptyFinalCount": len(non_empty_finals),
        "firstPartialMs": partial_latencies_ms[0] if partial_latencies_ms else None,
        "firstNonEmptyPartialMs": non_empty_partial_latencies_ms[0] if non_empty_partial_latencies_ms else None,
        "firstFinalMs": final_latencies_ms[0] if final_latencies_ms else None,
        "firstNonEmptyFinalMs": non_empty_final_latencies_ms[0] if non_empty_final_latencies_ms else None,
        "medianFinalMs": int(statistics.median(final_latencies_ms)) if final_latencies_ms else None,
        "medianNonEmptyFinalMs": int(statistics.median(non_empty_final_latencies_ms)) if non_empty_final_latencies_ms else None,
        "medianTranscribeMs": int(statistics.median(transcribe_latencies_ms)) if transcribe_latencies_ms else None,
        "p95TranscribeMs": percentile(transcribe_latencies_ms, 0.95),
        "scriptCounts": scripts,
        "samplePartials": [item["transcript"] for item in non_empty_partials[:8]],
        "sampleFinals": [item["transcript"] for item in finals[:8]],
        "sampleNonEmptyFinals": [item["transcript"] for item in non_empty_finals[:8]],
        "statusTrail": statuses[-8:],
        "errorEvents": [item for item in logs if item["event"] == "voice_realtime_error"][-5:],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
