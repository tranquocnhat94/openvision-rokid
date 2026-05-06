#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROKID_ROOT_DIR:-/mnt/ssd/ai-security-ds/rokid}"
VOICE_DIR="$ROOT_DIR/runtime/voice/whisper_cpp"
SRC_DIR="$VOICE_DIR/src/whisper.cpp"
BUILD_DIR="$SRC_DIR/build"
MODELS_DIR="$VOICE_DIR/models"
LOG_DIR="$VOICE_DIR/logs"
PID_FILE="$VOICE_DIR/whisper_server.pid"
MODEL_FILE="${ROKID_WHISPER_CPP_MODEL_FILE:-ggml-small.bin}"
HOST_PORT="${ROKID_LOCAL_ASR_PORT:-9200}"
LANGUAGE="${ROKID_VOICE_LANGUAGE_HINT:-vi}"

mkdir -p "$LOG_DIR"

if [ ! -x "$BUILD_DIR/bin/whisper-server" ]; then
  echo "whisper-server binary missing at $BUILD_DIR/bin/whisper-server" >&2
  exit 1
fi

if [ ! -f "$MODELS_DIR/$MODEL_FILE" ]; then
  echo "model missing at $MODELS_DIR/$MODEL_FILE" >&2
  exit 1
fi

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "whisper-server already running"
  exit 0
fi

nohup "$BUILD_DIR/bin/whisper-server" \
  --host 0.0.0.0 \
  --port "$HOST_PORT" \
  -m "$MODELS_DIR/$MODEL_FILE" \
  -l "$LANGUAGE" \
  >"$LOG_DIR/whisper_server.out" 2>"$LOG_DIR/whisper_server.err" &

echo $! >"$PID_FILE"
echo "Started whisper-server on http://127.0.0.1:${HOST_PORT}"
