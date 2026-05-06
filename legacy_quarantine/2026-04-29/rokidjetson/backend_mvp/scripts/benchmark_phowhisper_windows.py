#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark PhoWhisper variants on Windows mini PC.")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--language", default="vi")
    parser.add_argument("--vad-filter", action="store_true", default=True)
    parser.add_argument("--no-vad-filter", dest="vad_filter", action="store_false")
    parser.add_argument("--input-mode", choices=("file_path", "binary_io", "ndarray_wav"), default="file_path")
    parser.add_argument("--hotwords", default="")
    parser.add_argument("wav_paths", nargs="+")
    return parser.parse_args()


def audio_duration_seconds(path: Path) -> float:
    import wave

    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        return frames / float(rate)


def decode_wav_to_float32(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        if width != 2 or rate != 16_000:
            raise ValueError(f"expected 16kHz s16 wav, got width={width} rate={rate}")
        raw = wav.readframes(wav.getnframes())
    pcm = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        usable = (pcm.size // channels) * channels
        pcm = pcm[:usable].reshape(-1, channels).mean(axis=1).astype(np.int16)
    return pcm.astype(np.float32) / 32768.0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    model_dir = Path(args.model_dir).expanduser().resolve()
    if not (model_dir / "model.bin").is_file():
        raise SystemExit(f"missing model.bin: {model_dir}")

    started = time.perf_counter()
    model = WhisperModel(
        str(model_dir),
        device="cpu",
        compute_type=args.compute_type,
        cpu_threads=max(1, args.cpu_threads),
    )
    load_s = time.perf_counter() - started

    results: list[dict[str, object]] = []
    for wav_path_raw in args.wav_paths:
        wav_path = Path(wav_path_raw).expanduser().resolve()
        if not wav_path.is_file():
            results.append({"wavPath": str(wav_path), "error": "missing_file"})
            continue
        duration_s = audio_duration_seconds(wav_path)
        if args.input_mode == "binary_io":
            audio_input: object = io.BytesIO(wav_path.read_bytes())
        elif args.input_mode == "ndarray_wav":
            audio_input = decode_wav_to_float32(wav_path)
        else:
            audio_input = str(wav_path)
        t0 = time.perf_counter()
        segments, info = model.transcribe(
            audio_input,
            language=args.language,
            beam_size=max(1, args.beam_size),
            condition_on_previous_text=False,
            vad_filter=bool(args.vad_filter),
            temperature=0.0,
            hotwords=args.hotwords.strip() or None,
        )
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
        elapsed_s = time.perf_counter() - t0
        results.append(
            {
                "wavPath": str(wav_path),
                "inputMode": args.input_mode,
                "durationSec": round(duration_s, 3),
                "elapsedSec": round(elapsed_s, 3),
                "xRealtime": round(duration_s / elapsed_s, 3) if elapsed_s > 0 else None,
                "text": transcript,
                "language": getattr(info, "language", args.language),
                "languageProbability": getattr(info, "language_probability", None),
            }
        )

    print(
        json.dumps(
            {
                "modelDir": str(model_dir),
                "cpuThreads": args.cpu_threads,
                "computeType": args.compute_type,
                "beamSize": args.beam_size,
                "vadFilter": bool(args.vad_filter),
                "inputMode": args.input_mode,
                "hotwords": args.hotwords,
                "loadSec": round(load_s, 3),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
