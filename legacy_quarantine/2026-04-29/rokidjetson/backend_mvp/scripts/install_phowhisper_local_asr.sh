#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROKID_ROOT_DIR:-/mnt/ssd/ai-security-ds/rokid}"
VOICE_DIR="$ROOT_DIR/runtime/voice/phowhisper_ct2"
VENV_DIR="$VOICE_DIR/venv"
MODELS_DIR="$VOICE_DIR/models"
MODEL_VARIANT="${1:-small}"
MODEL_SUBDIR="PhoWhisper-${MODEL_VARIANT}-ct2-fasterWhisper"
MODEL_REPO="${ROKID_PHOWHISPER_REPO:-quocphu/PhoWhisper-ct2-FasterWhisper}"
TARGET_DIR="$MODELS_DIR/$MODEL_SUBDIR"

mkdir -p "$MODELS_DIR"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip setuptools wheel
pip install faster-whisper huggingface_hub

export MODEL_REPO MODEL_SUBDIR MODELS_DIR
python - <<'PY'
import os
from huggingface_hub import snapshot_download

repo_id = os.environ["MODEL_REPO"]
model_subdir = os.environ["MODEL_SUBDIR"]
models_dir = os.environ["MODELS_DIR"]

snapshot_download(
    repo_id=repo_id,
    local_dir=models_dir,
    allow_patterns=[f"{model_subdir}/*"],
)
PY

echo
echo "Installed PhoWhisper runtime at: $VENV_DIR"
echo "Downloaded model at: $TARGET_DIR"
du -sh "$TARGET_DIR"

echo
echo "Suggested command template:"
echo "  source $VENV_DIR/bin/activate && python $ROOT_DIR/apps/backend_mvp/scripts/transcribe_phowhisper_local.py {wav_path}"
