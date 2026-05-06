#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROKID_ROOT_DIR:-/mnt/ssd/ai-security-ds/rokid}"
VOICE_DIR="$ROOT_DIR/runtime/voice/whisper_cpp"
SRC_DIR="$VOICE_DIR/src/whisper.cpp"
MODELS_DIR="$VOICE_DIR/models"
BUILD_DIR="$SRC_DIR/build"
WHISPER_REF="${ROKID_WHISPER_CPP_REF:-v1.8.1}"
MODEL_NAME="${1:-small}"

mkdir -p "$VOICE_DIR/src" "$MODELS_DIR"

if [ ! -d "$SRC_DIR/.git" ]; then
  git clone https://github.com/ggml-org/whisper.cpp.git "$SRC_DIR"
fi

git -C "$SRC_DIR" fetch --tags --force
git -C "$SRC_DIR" checkout "$WHISPER_REF"

cmake -S "$SRC_DIR" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" -j"$(nproc)"

"$SRC_DIR/models/download-ggml-model.sh" "$MODEL_NAME" "$MODELS_DIR"

echo
echo "Installed whisper.cpp at: $SRC_DIR"
echo "Built binaries at: $BUILD_DIR/bin"
echo "Models at: $MODELS_DIR"
ls -lh "$MODELS_DIR"

echo
echo "Suggested backend config:"
echo "  ROKID_ASR_BACKEND=local_http"
echo "  ROKID_LOCAL_ASR_TRANSCRIBE_URL=http://127.0.0.1:9200/inference"
echo "  ROKID_LOCAL_ASR_HEALTH_URL=http://127.0.0.1:9200/"
echo "  ROKID_LOCAL_ASR_START_CMD=$ROOT_DIR/apps/backend_mvp/scripts/start_local_asr_whisper.sh"
echo "  ROKID_LOCAL_ASR_STOP_CMD=$ROOT_DIR/apps/backend_mvp/scripts/stop_local_asr_whisper.sh"
