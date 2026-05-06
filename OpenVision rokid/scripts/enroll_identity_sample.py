#!/usr/bin/env python3
"""Enroll a local contact identity sample into the OpenVision runtime DB."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jetson" / "agent"))

from openvision_jetson.contact_identity import ContactIdentityStore  # noqa: E402
from openvision_jetson.face_identity_worker import (  # noqa: E402
    extract_identity_vector_from_image_path,
    load_face_identity_worker_settings,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enroll an OpenVision contact identity sample")
    parser.add_argument("--name", required=True, help="Display name, e.g. Trâm")
    parser.add_argument("--alias", action="append", default=[], help="Optional alias; can be repeated")
    parser.add_argument("--image", help="Image/crop path or /api/crops/... ref inside OPENVISION_RUNTIME_DIR")
    parser.add_argument(
        "--embedding-backend",
        choices=["image_fingerprint", "opencv_sface"],
        default="image_fingerprint",
        help="Use opencv_sface to store a real face embedding when local OpenCV models are installed.",
    )
    parser.add_argument("--runtime-dir", help="Override OpenVision runtime dir")
    parser.add_argument("--notes", default="", help="Optional local note")
    args = parser.parse_args(argv)

    if not args.image:
        parser.error("--image is required")

    runtime_dir = Path(args.runtime_dir).expanduser() if args.runtime_dir else None
    store = ContactIdentityStore(runtime_dir=runtime_dir)
    if args.embedding_backend == "opencv_sface":
        settings = load_face_identity_worker_settings()
        if runtime_dir:
            settings = replace(settings, runtime_dir=runtime_dir)
        image_path = _resolve_local_image_path(args.image, settings.runtime_dir)
        vector = extract_identity_vector_from_image_path(settings, image_path)
        result = store.enroll_sample(
            display_name=args.name,
            aliases=args.alias,
            notes=args.notes,
            vector=vector,
            source_note=f"opencv_sface:{image_path}",
        )
    else:
        result = store.enroll_sample(
            display_name=args.name,
            aliases=args.alias,
            notes=args.notes,
            image_ref=args.image,
            source_note=args.image,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _resolve_local_image_path(value: str, runtime_dir: Path) -> Path:
    if value.startswith("/api/crops/"):
        parts = [part for part in value.split("/") if part]
        if len(parts) >= 4:
            return runtime_dir / "crops" / parts[2] / parts[3]
    return Path(value).expanduser()


if __name__ == "__main__":
    raise SystemExit(main())
