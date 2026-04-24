#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "Missing venv. Run: python3 -m venv \"$ROOT/.venv\" && \"$ROOT/.venv/bin/python\" -m pip install -r \"$ROOT/jetson/agent/requirements.txt\"" >&2
  exit 1
fi

cd "$ROOT/jetson/agent"
exec "$PY" -m uvicorn openvision_jetson.fastapi_app:app --host "${OPENVISION_HOST:-127.0.0.1}" --port "${OPENVISION_PORT:-8765}"
