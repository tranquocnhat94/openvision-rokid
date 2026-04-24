#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JETSON_HOST="${JETSON_HOST:-openvision-jetson.local}"
JETSON_USER="${JETSON_USER:-jetson}"
JETSON_PATH="${JETSON_PATH:-/opt/openvision-rokid}"

rsync -az --delete \
  --exclude ".venv/" \
  --exclude "runtime/" \
  --exclude "ops/secrets/" \
  --exclude "__pycache__/" \
  --exclude ".DS_Store" \
  "$ROOT/" "$JETSON_USER@$JETSON_HOST:$JETSON_PATH/"

ssh "$JETSON_USER@$JETSON_HOST" "cd '$JETSON_PATH' && bash scripts/bootstrap_jetson.sh"

echo "Deployed OpenVision v2 to $JETSON_USER@$JETSON_HOST:$JETSON_PATH"
