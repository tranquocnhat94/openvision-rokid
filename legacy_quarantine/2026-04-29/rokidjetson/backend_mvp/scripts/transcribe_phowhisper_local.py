#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from faster_whisper import WhisperModel


def _default_model_dir(root_dir: str, variant: str) -> Path:
    return Path(root_dir) / "runtime" / "voice" / "phowhisper_ct2" / "models" / f"PhoWhisper-{variant}-ct2-fasterWhisper"


def _resolve_model_dir(model_dir: Path) -> Path:
    if (model_dir / "model.bin").is_file():
        return model_dir
    nested = model_dir / model_dir.name
    if (nested / "model.bin").is_file():
        return nested
    return model_dir


def main() -> int:
    root_dir = os.getenv("ROKID_ROOT_DIR", "/mnt/ssd/ai-security-ds/rokid")
    parser = argparse.ArgumentParser(description="Transcribe a WAV file with PhoWhisper via faster-whisper.")
    parser.add_argument("wav_path", help="Absolute path to the WAV file")
    parser.add_argument("--variant", default=os.getenv("ROKID_PHOWHISPER_VARIANT", "small"))
    parser.add_argument("--model-dir", default=os.getenv("ROKID_PHOWHISPER_MODEL_DIR", ""))
    parser.add_argument("--device", default=os.getenv("ROKID_PHOWHISPER_DEVICE", "cpu"))
    parser.add_argument("--compute-type", default=os.getenv("ROKID_PHOWHISPER_COMPUTE_TYPE", "int8"))
    parser.add_argument("--beam-size", type=int, default=int(os.getenv("ROKID_PHOWHISPER_BEAM_SIZE", "5")))
    parser.add_argument("--language", default=os.getenv("ROKID_VOICE_LANGUAGE_HINT", "vi"))
    parser.add_argument("--vad-filter", action="store_true", default=os.getenv("ROKID_PHOWHISPER_VAD_FILTER", "1") != "0")
    parser.add_argument("--json", action="store_true", help="Print a JSON payload instead of raw text")
    args = parser.parse_args()

    wav_path = Path(args.wav_path).expanduser().resolve()
    model_dir = Path(args.model_dir).expanduser().resolve() if args.model_dir else _default_model_dir(root_dir, args.variant).resolve()
    if not wav_path.is_file():
        raise SystemExit(f"missing wav file: {wav_path}")
    model_dir = _resolve_model_dir(model_dir)
    if not model_dir.is_dir():
        raise SystemExit(f"missing model dir: {model_dir}")

    model = WhisperModel(
        str(model_dir),
        device=args.device,
        compute_type=args.compute_type,
        cpu_threads=max(1, os.cpu_count() or 1),
    )
    segments, info = model.transcribe(
        str(wav_path),
        language=args.language,
        beam_size=args.beam_size,
        condition_on_previous_text=False,
        vad_filter=args.vad_filter,
        temperature=0.0,
    )
    transcript = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
    if args.json:
        print(
            json.dumps(
                {
                    "text": transcript,
                    "language": getattr(info, "language", args.language),
                    "language_probability": getattr(info, "language_probability", None),
                    "model_dir": str(model_dir),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(transcript)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
