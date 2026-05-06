#!/usr/bin/env python3
"""Export a redacted session replay plus scorecard to runtime/replays.

The script is read-only against Jetson HTTP. It saves local artifacts under the
ignored runtime directory so test evidence can be compared without committing
private user/session data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jetson" / "agent"))

from openvision_jetson.contracts import utc_now  # noqa: E402
from openvision_jetson.session_replay import build_session_scorecard  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "runtime" / "replays"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="Jetson FastAPI base URL")
    parser.add_argument("--session-id", help="Optional session id to export")
    parser.add_argument("--limit", type=int, default=1000, help="Replay event limit")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact output directory")
    parser.add_argument("--retention-days", type=int, default=14, help="Delete exported bundles older than this many days")
    parser.add_argument("--keep-latest", type=int, default=100, help="Keep at most this many newest exported bundles")
    parser.add_argument("--input-replay", help="Score an existing replay JSON instead of fetching Jetson HTTP")
    parser.add_argument("--no-write", action="store_true", help="Print scorecard only; do not write an artifact")
    args = parser.parse_args()

    if args.input_replay:
        replay = _load_replay(Path(args.input_replay))
        scorecard = build_session_scorecard(replay)
        source = {"type": "file", "path": str(Path(args.input_replay).expanduser())}
    else:
        base_url = _normalize_base_url(args.base_url)
        replay = _fetch_replay(base_url=base_url, session_id=args.session_id, limit=args.limit)
        scorecard = _fetch_scorecard(base_url=base_url, session_id=args.session_id, limit=args.limit)
        source = {"type": "http", "base_url": base_url}

    bundle = {
        "schema_version": "openvision.replay_export.v1",
        "generated_at": utc_now(),
        "source": source,
        "session_id": replay.get("session_id"),
        "replay": replay,
        "scorecard": scorecard,
    }
    output_path = None
    if not args.no_write:
        output_dir = Path(args.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = _write_bundle(output_dir=output_dir, bundle=bundle)
        _apply_retention(output_dir=output_dir, retention_days=args.retention_days, keep_latest=args.keep_latest)

    result = {
        "status": scorecard.get("status"),
        "score": scorecard.get("score"),
        "session_id": scorecard.get("session_id"),
        "skill_eval_status": scorecard.get("metrics", {}).get("skill_eval_status"),
        "skill_eval_score": scorecard.get("metrics", {}).get("skill_eval_score"),
        "output_path": str(output_path) if output_path else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    status = str(scorecard.get("status") or "fail")
    return 0 if status == "pass" else 1 if status == "warn" else 2


def _fetch_replay(*, base_url: str, session_id: str | None, limit: int) -> dict[str, Any]:
    path = f"/api/replay/{quote(session_id)}" if session_id else "/api/replay"
    payload = _get_json(base_url, path, limit=limit)
    replay = payload.get("replay") if isinstance(payload.get("replay"), dict) else payload
    if not isinstance(replay, dict):
        raise SystemExit("Replay endpoint did not return an object")
    return replay


def _fetch_scorecard(*, base_url: str, session_id: str | None, limit: int) -> dict[str, Any]:
    path = f"/api/scorecard/{quote(session_id)}" if session_id else "/api/scorecard"
    payload = _get_json(base_url, path, limit=limit)
    scorecard = payload.get("scorecard") if isinstance(payload.get("scorecard"), dict) else payload
    if not isinstance(scorecard, dict):
        raise SystemExit("Scorecard endpoint did not return an object")
    return scorecard


def _get_json(base_url: str, path: str, *, limit: int) -> dict[str, Any]:
    separator = "&" if "?" in path else "?"
    request = Request(urljoin(base_url + "/", f"{path.lstrip('/')}{separator}limit={max(1, limit)}"), method="GET")
    try:
        with urlopen(request, timeout=8) as response:  # noqa: S310 - operator-supplied local/tailnet URL.
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {request.full_url}: {body}") from exc
    except (URLError, TimeoutError) as exc:
        raise SystemExit(f"Request failed for {request.full_url}: {exc}") from exc


def _load_replay(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if isinstance(payload.get("replay"), dict):
        return payload["replay"]
    if isinstance(payload, dict):
        return payload
    raise SystemExit("--input-replay must be a replay object or exported replay bundle")


def _write_bundle(*, output_dir: Path, bundle: dict[str, Any]) -> Path:
    session = _safe_slug(str(bundle.get("session_id") or "all"))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"{timestamp}_{session}_replay_scorecard.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _apply_retention(*, output_dir: Path, retention_days: int, keep_latest: int) -> None:
    bundles = sorted(output_dir.glob("*_replay_scorecard.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    keep_latest = max(1, keep_latest)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
    for index, path in enumerate(bundles):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if index >= keep_latest or mtime < cutoff:
            path.unlink(missing_ok=True)


def _normalize_base_url(value: str) -> str:
    value = value.rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise SystemExit("--base-url must start with http:// or https://")
    return value


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "session"


if __name__ == "__main__":
    raise SystemExit(main())
