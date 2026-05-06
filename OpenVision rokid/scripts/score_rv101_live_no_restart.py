#!/usr/bin/env python3
"""Score a bounded RV101 live_video smoke window for Jetson restarts.

By default this script is read-only: it samples /api/health twice and reports
whether the Jetson runtime epoch stayed stable. Use --start-live only when the
RV101 app is foreground/interactive and you intentionally want to send one
bounded live_video MediaCommand.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jetson" / "agent"))

from openvision_jetson.live_video_scorecard import build_live_video_no_restart_scorecard  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="Jetson FastAPI base URL")
    parser.add_argument("--session-id", help="RV101 session id to score")
    parser.add_argument("--command-id", help="Existing live_video command id to score")
    parser.add_argument("--start-live", action="store_true", help="Send one bounded live_video command before scoring")
    parser.add_argument("--timeout-ms", type=int, default=5000, help="live_video timeout when --start-live is used")
    parser.add_argument("--fps", type=float, default=8.0, help="live_video FPS when --start-live is used")
    parser.add_argument("--width", type=int, default=640, help="live_video width when --start-live is used")
    parser.add_argument("--height", type=int, default=360, help="live_video height when --start-live is used")
    parser.add_argument("--wait-s", type=float, default=None, help="Seconds to wait between before/after samples")
    parser.add_argument("--min-video-frames", type=int, default=1, help="Minimum frames required when --session-id is set")
    args = parser.parse_args()

    if args.start_live and not args.session_id:
        parser.error("--start-live requires --session-id")

    base_url = _normalize_base_url(args.base_url)
    wait_s = args.wait_s if args.wait_s is not None else max(1.0, args.timeout_ms / 1000.0 + 3.0)

    before_health = _get_json(base_url, "/api/health")
    command_id = args.command_id
    if args.start_live:
        command = _post_json(
            base_url,
            "/api/media/commands",
            {
                "mode": "live_video",
                "session_id": args.session_id,
                "skill_id": "diagnostics_live_no_restart",
                "reason": "bounded RV101 live_video no-restart scorecard",
                "timeout_ms": args.timeout_ms,
                "fps": args.fps,
                "resolution": {"width": args.width, "height": args.height},
                "params": {"action": "start", "scorecard": "rv101_live_no_restart"},
            },
        )
        command_id = command.get("command", {}).get("command_id")

    time.sleep(max(0.0, wait_s))

    after_health = _get_json(base_url, "/api/health")
    media = _get_json(base_url, "/api/media").get("media", [])
    media_commands = _get_json(base_url, "/api/media/commands").get("media_commands", {})
    scorecard = build_live_video_no_restart_scorecard(
        before_health=before_health,
        after_health=after_health,
        media=media,
        media_commands=media_commands,
        session_id=args.session_id,
        command_id=command_id,
        min_video_frames=args.min_video_frames,
    )
    scorecard["inputs"] = {
        "base_url": base_url,
        "session_id": args.session_id,
        "command_id": command_id,
        "start_live": args.start_live,
        "wait_s": wait_s,
    }
    print(json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if scorecard["status"] == "pass" else 1 if scorecard["status"] == "warn" else 2


def _normalize_base_url(value: str) -> str:
    value = value.rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise SystemExit("--base-url must start with http:// or https://")
    return value


def _get_json(base_url: str, path: str) -> dict[str, Any]:
    return _request_json(Request(urljoin(base_url + "/", path.lstrip("/")), method="GET"))


def _post_json(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    return _request_json(
        Request(
            urljoin(base_url + "/", path.lstrip("/")),
            data=data,
            headers={"content-type": "application/json"},
            method="POST",
        ),
    )


def _request_json(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310 - operator-supplied local/tailnet URL.
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {request.full_url}: {body}") from exc
    except (URLError, TimeoutError) as exc:
        raise SystemExit(f"Request failed for {request.full_url}: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
