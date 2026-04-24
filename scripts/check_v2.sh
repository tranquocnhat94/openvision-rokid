#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JETSON="$ROOT/jetson"
PY="$ROOT/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

"$PY" -B - "$JETSON" <<'PY'
from pathlib import Path
import sys

jetson = Path(sys.argv[1])
source_roots = [
    "agent/openvision_jetson",
    "audio_turns/openvision_jetson",
    "hud_authority/openvision_jetson",
    "lab_fallbacks/openvision_jetson",
    "media_gateway/openvision_jetson",
    "perception/openvision_jetson",
    "realtime_agent/openvision_jetson",
    "simulator_bridge/openvision_jetson",
    "skills/openvision_jetson",
    "tests",
]

checked = 0
for source_root in source_roots:
    for path in sorted((jetson / source_root).rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        checked += 1

print(f"syntax OK: {checked} Python files")
PY
(
  cd "$JETSON"
  "$PY" -B -m unittest discover -s tests
)
