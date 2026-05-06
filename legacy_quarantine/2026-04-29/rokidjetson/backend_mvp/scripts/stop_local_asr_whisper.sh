#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROKID_ROOT_DIR:-/mnt/ssd/ai-security-ds/rokid}"
VOICE_DIR="$ROOT_DIR/runtime/voice/whisper_cpp"
PID_FILE="$VOICE_DIR/whisper_server.pid"

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" >/dev/null 2>&1; then
    kill "$PID" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE"
fi

pkill -f "whisper-server" >/dev/null 2>&1 || true
echo "Stopped whisper-server"
