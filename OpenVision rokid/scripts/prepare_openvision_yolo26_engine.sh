#!/usr/bin/env bash
set -euo pipefail

# Build an OpenVision/Rokid-specific YOLO26 TensorRT engine. This script refuses
# protected Ring/security/surveillance paths and only writes into the OpenVision
# runtime tree by default.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${OPENVISION_RUNTIME_DIR:-/home/jay/openvision-rokid-v2/runtime}"
YOLO_DIR="${OPENVISION_YOLO26_RUNTIME_DIR:-$RUNTIME_DIR/yolo26}"
SOURCE_ONNX="${OPENVISION_YOLO26_SOURCE_ONNX:-}"
ENGINE_PATH="${OPENVISION_DEEPSTREAM_YOLO26_ENGINE_PATH:-${OPENVISION_YOLO26_ENGINE_PATH:-$YOLO_DIR/openvision_yolo26.engine}}"
TRTEXEC="${OPENVISION_TRTEXEC:-/usr/src/tensorrt/bin/trtexec}"

if [[ -z "$SOURCE_ONNX" ]]; then
  for candidate in \
    "$YOLO_DIR/openvision_yolo26.onnx" \
    "/home/jay/DeepStream-Yolo/yolo26s.onnx"; do
    if [[ -f "$candidate" ]]; then
      SOURCE_ONNX="$candidate"
      break
    fi
  done
fi

lower_paths="$(printf '%s\n%s\n' "$SOURCE_ONNX" "$ENGINE_PATH" | tr 'A-Z' 'a-z')"
case "$lower_paths" in
  *ring*|*security*|*surveillance*)
    echo "Refusing to use protected Ring/security/surveillance path." >&2
    exit 2
    ;;
esac

case "$(python3 - <<PY
from pathlib import Path
root = Path("$YOLO_DIR").expanduser().resolve()
out = Path("$ENGINE_PATH").expanduser().resolve()
print("yes" if root == out.parent or root in out.parents else "no")
PY
)" in
  yes) ;;
  *)
    echo "Refusing to write engine outside OpenVision YOLO runtime dir: $YOLO_DIR" >&2
    exit 2
    ;;
esac

if [[ -z "$SOURCE_ONNX" || ! -f "$SOURCE_ONNX" ]]; then
  echo "Missing YOLO26 ONNX source. Set OPENVISION_YOLO26_SOURCE_ONNX." >&2
  exit 3
fi

if [[ ! -x "$TRTEXEC" ]]; then
  echo "Missing TensorRT trtexec. Set OPENVISION_TRTEXEC." >&2
  exit 4
fi

mkdir -p "$(dirname "$ENGINE_PATH")"
echo "Building OpenVision YOLO26 TensorRT engine"
echo "source: $SOURCE_ONNX"
echo "engine: $ENGINE_PATH"

"$TRTEXEC" \
  --onnx="$SOURCE_ONNX" \
  --saveEngine="$ENGINE_PATH" \
  --fp16 \
  ${OPENVISION_YOLO26_TRTEXEC_EXTRA_ARGS:-}

ls -lh "$ENGINE_PATH"
echo "OpenVision YOLO26 TensorRT engine ready."
