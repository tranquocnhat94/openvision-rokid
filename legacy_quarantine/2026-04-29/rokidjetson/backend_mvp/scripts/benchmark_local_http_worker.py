#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark local HTTP STT workers with either JSON/base64 or raw WAV.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--mode", choices=("json_base64", "binary_wav"), required=True)
    parser.add_argument("--language", default="vi")
    parser.add_argument("--session-id", default="bench_http")
    parser.add_argument("--profile", default="")
    parser.add_argument("--beam-size", type=int, default=None)
    parser.add_argument("--vad-filter", choices=("true", "false"), default=None)
    parser.add_argument("--hotwords", default="")
    parser.add_argument("wav_paths", nargs="+")
    return parser.parse_args()


def build_request(args: argparse.Namespace, wav_path: Path) -> urllib.request.Request:
    wav_bytes = wav_path.read_bytes()
    if args.mode == "binary_wav":
        headers = {
            "Content-Type": "audio/wav",
            "X-Rokid-Session-Id": args.session_id,
            "X-Rokid-Language": args.language,
            "X-Rokid-Profile": args.profile,
        }
        if args.beam_size is not None:
            headers["X-Rokid-Beam-Size"] = str(args.beam_size)
        if args.vad_filter is not None:
            headers["X-Rokid-Vad-Filter"] = args.vad_filter
        if args.hotwords.strip():
            headers["X-Rokid-Hotwords-Base64"] = base64.b64encode(args.hotwords.strip().encode("utf-8")).decode("ascii")
        return urllib.request.Request(url=args.url, data=wav_bytes, method="POST", headers=headers)

    payload = {
        "sessionId": args.session_id,
        "language": args.language,
        "profile": args.profile,
        "audioBase64": base64.b64encode(wav_bytes).decode("ascii"),
    }
    if args.beam_size is not None:
        payload["beamSize"] = args.beam_size
    if args.vad_filter is not None:
        payload["vadFilter"] = args.vad_filter == "true"
    if args.hotwords.strip():
        payload["hotwords"] = args.hotwords.strip()
    body = json.dumps(payload).encode("utf-8")
    return urllib.request.Request(
        url=args.url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    results: list[dict[str, object]] = []
    for wav_path_raw in args.wav_paths:
        wav_path = Path(wav_path_raw).expanduser().resolve()
        if not wav_path.is_file():
            results.append({"wavPath": str(wav_path), "error": "missing_file"})
            continue
        request = build_request(args, wav_path)
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
        elapsed_s = time.perf_counter() - started
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"raw": body.decode("utf-8", errors="replace")}
        results.append(
            {
                "wavPath": str(wav_path),
                "mode": args.mode,
                "wallSec": round(elapsed_s, 3),
                "response": payload,
            }
        )

    print(json.dumps({"url": args.url, "mode": args.mode, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
