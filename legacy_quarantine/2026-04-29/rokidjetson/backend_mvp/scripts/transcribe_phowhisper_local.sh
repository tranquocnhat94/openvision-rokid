#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROKID_ROOT_DIR:-/mnt/ssd/ai-security-ds/rokid}"
VENV_DIR="$ROOT_DIR/runtime/voice/phowhisper_ct2/venv"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "missing PhoWhisper venv at $VENV_DIR" >&2
  exit 1
fi

source "$VENV_DIR/bin/activate"
python "$ROOT_DIR/apps/backend_mvp/scripts/transcribe_phowhisper_local.py" "$@"
