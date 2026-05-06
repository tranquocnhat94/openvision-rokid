#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.voice_runtime import VoiceOrchestrator  # noqa: E402


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class DummySession:
    session_id: str
    control_connected: bool = True
    audio_connected: bool = True
    video_connected: bool = False
    last_audio_timestamp_ms: int | None = None
    latest_audio_stats: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._audio_buffer_lock = threading.Lock()
        self._audio_buffer = bytearray()
        self._audio_buffer_start_offset = 0

    @property
    def active(self) -> bool:
        return self.control_connected or self.audio_connected or self.video_connected

    def append_audio_payload(self, payload: bytes, *, max_buffer_bytes: int) -> None:
        if not payload:
            return
        with self._audio_buffer_lock:
            self._audio_buffer.extend(payload)
            overflow = len(self._audio_buffer) - max(1, max_buffer_bytes)
            if overflow > 0:
                del self._audio_buffer[:overflow]
                self._audio_buffer_start_offset += overflow

    def read_audio_window(self, start_offset: int, max_bytes: int | None = None) -> tuple[int, int, bytes]:
        with self._audio_buffer_lock:
            buffer_start = self._audio_buffer_start_offset
            buffer_end = buffer_start + len(self._audio_buffer)
            normalized_start = max(start_offset, buffer_start)
            normalized_end = buffer_end if max_bytes is None else min(buffer_end, normalized_start + max_bytes)
            relative_start = max(0, normalized_start - buffer_start)
            relative_end = max(relative_start, normalized_end - buffer_start)
            payload = bytes(self._audio_buffer[relative_start:relative_end])
        return normalized_start, normalized_end, payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark local PhoWhisper partial/final latency through VoiceOrchestrator.")
    parser.add_argument("wav_path", type=Path, help="Path to a 16 kHz mono WAV file")
    parser.add_argument("--chunk-ms", type=int, default=120, help="PCM chunk size to feed")
    parser.add_argument("--pace", choices=("realtime", "fast"), default="realtime")
    parser.add_argument("--warm-first", action="store_true", help="Warm the worker before feeding audio")
    parser.add_argument("--settle-ms", type=int, default=2500, help="Extra settle time after feeding audio")
    parser.add_argument("--min-segment-ms", type=int, default=900)
    parser.add_argument("--max-segment-ms", type=int, default=1800)
    parser.add_argument("--idle-flush-ms", type=int, default=220)
    parser.add_argument("--fast-min-segment-ms", type=int, default=320)
    parser.add_argument("--rolling-flush-ms", type=int, default=520)
    parser.add_argument("--segment-overlap-ms", type=int, default=200)
    parser.add_argument("--local-partial-probe-ms", type=int, default=280)
    parser.add_argument("--local-partial-min-ms", type=int, default=320)
    parser.add_argument("--local-partial-window-ms", type=int, default=1200)
    parser.add_argument("--local-partial-idle-clear-ms", type=int, default=1400)
    parser.add_argument("--local-partial-beam-size", type=int, default=5)
    parser.add_argument("--local-partial-vad-filter", action="store_true", default=True)
    parser.add_argument("--no-local-partial-vad-filter", dest="local_partial_vad_filter", action="store_false")
    parser.add_argument("--min-voiced-segment-ms", type=int, default=640)
    parser.add_argument("--min-voiced-hold-idle-ms", type=int, default=260)
    return parser.parse_args()


def load_wav_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        if channels != 1 or width != 2 or rate != 16_000:
            raise SystemExit(f"Expected 16kHz mono s16 WAV, got channels={channels} width={width} rate={rate}")
        return wav.readframes(wav.getnframes())


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return float(ordered[index])


def main() -> int:
    args = parse_args()
    pcm = load_wav_pcm(args.wav_path)
    if not pcm:
        raise SystemExit("WAV payload is empty")

    session = DummySession(session_id="bench_local_partial")
    sessions = {session.session_id: session}
    speech_events: list[dict[str, Any]] = []
    command_events: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    start_monotonic = time.perf_counter()

    def rel_ms() -> int:
        return int((time.perf_counter() - start_monotonic) * 1000)

    def log_handler(session_id: str, event: str, payload: dict[str, Any]) -> None:
        logs.append({"atMs": rel_ms(), "event": event, "payload": dict(payload)})

    def speech_handler(payload: dict[str, Any]) -> None:
        speech_events.append({"atMs": rel_ms(), **dict(payload)})

    def command_handler(payload: dict[str, Any]) -> None:
        command_events.append({"atMs": rel_ms(), **dict(payload)})

    orchestrator = VoiceOrchestrator(
        root_dir=ROOT,
        session_provider=lambda: sessions,
        scene_context_provider=lambda _session_id: {},
        vision_context_provider=lambda _session_id, _target_query, _selected_track_id: {},
        command_handler=command_handler,
        log_handler=log_handler,
        speech_handler=speech_handler,
    )

    try:
        orchestrator.update_config(
            {
                "asrBackend": "local_http",
                "enableOpenAI": False,
                "allowOpenAITranscriptionFallback": False,
                "allowOpenAIRouterFallback": False,
                "routeSpeechHudEnabled": True,
                "localPartialEnabled": True,
                "localHealthCacheMs": 1000,
                "localPartialProbeMs": args.local_partial_probe_ms,
                "localPartialMinMs": args.local_partial_min_ms,
                "localPartialWindowMs": args.local_partial_window_ms,
                "localPartialIdleClearMs": args.local_partial_idle_clear_ms,
                "localPartialBeamSize": args.local_partial_beam_size,
                "localPartialVadFilter": args.local_partial_vad_filter,
                "autoWakeOnSession": True,
                "minSegmentMs": args.min_segment_ms,
                "maxSegmentMs": args.max_segment_ms,
                "idleFlushMs": args.idle_flush_ms,
                "fastMinSegmentMs": args.fast_min_segment_ms,
                "rollingFlushMs": args.rolling_flush_ms,
                "segmentOverlapMs": args.segment_overlap_ms,
                "minVoicedSegmentMs": args.min_voiced_segment_ms,
                "minVoicedHoldIdleMs": args.min_voiced_hold_idle_ms,
            }
        )

        if args.warm_first:
            orchestrator._warm_local_backend()
            time.sleep(0.2)

        chunk_bytes = max(1, int(16_000 * 2 * args.chunk_ms / 1000))
        max_buffer_bytes = max(chunk_bytes * 120, 16_000 * 2 * 20)

        feed_started_at = time.perf_counter()
        next_deadline = feed_started_at
        first_voice_ms: int | None = None
        for offset in range(0, len(pcm), chunk_bytes):
            chunk = pcm[offset : offset + chunk_bytes]
            if not chunk:
                continue
            energy = orchestrator._analyze_audio_energy(chunk)
            session.latest_audio_stats = {
                "avgAbs": energy.avg_abs,
                "peakAbs": energy.peak_abs,
                "nonSilentRatio": round(energy.non_silent_ratio, 4),
            }
            session.last_audio_timestamp_ms = now_ms()
            session.append_audio_payload(chunk, max_buffer_bytes=max_buffer_bytes)
            if first_voice_ms is None and orchestrator._has_voice_energy(energy):
                first_voice_ms = rel_ms()
            if args.pace == "realtime":
                next_deadline += args.chunk_ms / 1000.0
                sleep_s = next_deadline - time.perf_counter()
                if sleep_s > 0:
                    time.sleep(sleep_s)

        audio_end_ms = rel_ms()
        time.sleep(max(0.2, args.settle_ms / 1000.0))

        partial_events = [
            item for item in speech_events
            if str(item.get("source") or "").startswith("local_http") and item.get("transcriptHint")
        ]
        clear_events = [
            item for item in speech_events
            if str(item.get("source") or "") == "local_partial_clear"
        ]
        final_logs = [item for item in logs if item["event"] == "voice_transcript"]
        partial_logs = [item for item in logs if item["event"] == "voice_local_partial"]
        final_text = final_logs[-1]["payload"].get("transcript") if final_logs else None
        partial_texts = [str(item.get("transcriptHint") or "") for item in partial_events]
        unique_partials = [text for index, text in enumerate(partial_texts) if index == 0 or text != partial_texts[index - 1]]
        partial_latencies = [item["atMs"] - (first_voice_ms or 0) for item in partial_events if first_voice_ms is not None]

        result = {
            "wavPath": str(args.wav_path),
            "pace": args.pace,
            "warmFirst": bool(args.warm_first),
            "config": {
                "minSegmentMs": args.min_segment_ms,
                "maxSegmentMs": args.max_segment_ms,
                "idleFlushMs": args.idle_flush_ms,
                "fastMinSegmentMs": args.fast_min_segment_ms,
                "rollingFlushMs": args.rolling_flush_ms,
                "segmentOverlapMs": args.segment_overlap_ms,
                "localPartialProbeMs": args.local_partial_probe_ms,
                "localPartialMinMs": args.local_partial_min_ms,
                "localPartialWindowMs": args.local_partial_window_ms,
                "localPartialIdleClearMs": args.local_partial_idle_clear_ms,
                "localPartialBeamSize": args.local_partial_beam_size,
                "localPartialVadFilter": bool(args.local_partial_vad_filter),
                "minVoicedSegmentMs": args.min_voiced_segment_ms,
                "minVoicedHoldIdleMs": args.min_voiced_hold_idle_ms,
            },
            "audioDurationMs": int(len(pcm) / (16_000 * 2) * 1000),
            "firstVoiceMs": first_voice_ms,
            "audioEndMs": audio_end_ms,
            "speechEventCount": len(speech_events),
            "partialEventCount": len(partial_events),
            "partialLogCount": len(partial_logs),
            "partialUniqueTexts": unique_partials,
            "firstPartialAfterVoiceMs": partial_latencies[0] if partial_latencies else None,
            "medianPartialAfterVoiceMs": statistics.median(partial_latencies) if partial_latencies else None,
            "p95PartialAfterVoiceMs": percentile(partial_latencies, 0.95) if partial_latencies else None,
            "clearEventCount": len(clear_events),
            "finalEventCount": len(final_logs),
            "finalText": final_text,
            "finalAfterAudioEndMs": (final_logs[-1]["atMs"] - audio_end_ms) if final_logs else None,
            "recentSpeechEvents": speech_events[-8:],
            "recentLogs": logs[-12:],
            "commandEvents": command_events,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        orchestrator.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
