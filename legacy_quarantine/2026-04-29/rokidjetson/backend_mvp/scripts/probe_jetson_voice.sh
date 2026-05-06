#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROKID_ROOT_DIR:-/mnt/ssd/ai-security-ds/rokid}"
VENV_DIR="$ROOT_DIR/runtime/venv"

echo "== Jetson =="
hostname
uname -a
cat /etc/nv_tegra_release 2>/dev/null || true
cat /proc/device-tree/model 2>/dev/null || true

echo
echo "== Memory =="
free -h

echo
echo "== Disk =="
df -h "$ROOT_DIR" 2>/dev/null || df -h /

echo
echo "== Docker =="
command -v docker >/dev/null 2>&1 && docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' || echo "docker not found"

echo
echo "== Python runtime =="
"$VENV_DIR/bin/python" - <<'PY'
mods = ["numpy", "torch", "transformers", "faster_whisper", "ctranslate2"]
for name in mods:
    try:
        module = __import__(name)
        print(f"{name}: OK {getattr(module, '__version__', '?')}")
    except Exception as error:
        print(f"{name}: ERR {type(error).__name__}: {error}")
PY

echo
echo "== Recommendation =="
echo "Jetson Orin Nano 8GB should avoid NVIDIA Speech NIM 16GB-class profiles."
echo "Use local-first low-power ASR with idle unload, and keep OpenAI only as fallback."
