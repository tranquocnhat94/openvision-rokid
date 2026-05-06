#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV="$ROOT/.venv"

"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV/bin/python" -m pip install -r "$ROOT/jetson/agent/requirements.txt"
if [[ -f "$ROOT/jetson/perception/face_identity_requirements.txt" ]]; then
  "$VENV/bin/python" -m pip install -r "$ROOT/jetson/perception/face_identity_requirements.txt"
fi

echo "OpenVision v2 Jetson venv ready: $VENV"
