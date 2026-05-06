#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JETSON="$ROOT/jetson"
OPS_MINIPC="$ROOT/ops/minipc"
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
    "cloud_gateway/openvision_jetson",
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
if [[ -d "$OPS_MINIPC" ]]; then
  "$PY" -B - "$OPS_MINIPC" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
checked = 0
for path in sorted(root.rglob("*.py")):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    checked += 1
print(f"ops/minipc syntax OK: {checked} Python files")
PY
fi
(
  cd "$JETSON"
  "$PY" -B -m unittest discover -s tests
)
