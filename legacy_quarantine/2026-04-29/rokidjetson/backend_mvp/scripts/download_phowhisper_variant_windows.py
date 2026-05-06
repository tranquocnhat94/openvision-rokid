#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> int:
    parser = argparse.ArgumentParser(description="Download one PhoWhisper ct2 variant into a Windows model directory.")
    parser.add_argument("--repo", default="quocphu/PhoWhisper-ct2-FasterWhisper")
    parser.add_argument("--variant", required=True, choices=["tiny", "base", "small", "medium", "large"])
    parser.add_argument("--models-dir", required=True)
    args = parser.parse_args()

    models_dir = Path(args.models_dir).expanduser().resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    subdir = f"PhoWhisper-{args.variant}-ct2-fasterWhisper"
    snapshot_download(
        repo_id=args.repo,
        local_dir=str(models_dir),
        allow_patterns=[f"{subdir}/*"],
    )
    print(models_dir / subdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
