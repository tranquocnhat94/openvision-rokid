#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JETSON_HOST="${JETSON_HOST:-openvision-jetson.local}"
JETSON_USER="${JETSON_USER:-jay}"
JETSON_PATH="${JETSON_PATH:-/home/jay/openvision-rokid-v2}"
JETSON_BASE_URL="${JETSON_BASE_URL:-http://$JETSON_HOST:8765}"
OPENVISION_RESTART_SERVICE="${OPENVISION_RESTART_SERVICE:-1}"
OPENVISION_SYNC_SYSTEMD="${OPENVISION_SYNC_SYSTEMD:-1}"
OPENVISION_RUN_IPHONE_SIGNOFF="${OPENVISION_RUN_IPHONE_SIGNOFF:-1}"
OPENVISION_SIGNOFF_CLOUD_VISUAL="${OPENVISION_SIGNOFF_CLOUD_VISUAL:-0}"
OPENVISION_SIGNOFF_OUTPUT="${OPENVISION_SIGNOFF_OUTPUT:-$ROOT/runtime/signoff/iphone_backend_readiness_latest.json}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

ssh_target="$JETSON_USER@$JETSON_HOST"

rsync -az --delete \
  --exclude ".venv/" \
  --exclude "runtime/" \
  --exclude "ops/openvision.env" \
  --exclude "ops/secrets/" \
  --exclude "__pycache__/" \
  --exclude ".DS_Store" \
  "$ROOT/" "$ssh_target:$JETSON_PATH/"

ssh "$ssh_target" "cd '$JETSON_PATH' && bash scripts/bootstrap_jetson.sh"

if [[ "$OPENVISION_RESTART_SERVICE" == "1" ]]; then
  remote_service_script="/tmp/openvision_deploy_services_$$.sh"
  ssh "$ssh_target" "cat > '$remote_service_script'" <<'REMOTE'
set -euo pipefail

if [[ "$OPENVISION_SYNC_SYSTEMD" == "1" ]]; then
  for unit in openvision-jetson.service openvision-face-identity-worker.service openvision-deepstream-yolo26-worker.service; do
    if [[ -f "$JETSON_PATH/ops/systemd/$unit" ]]; then
      sudo cp "$JETSON_PATH/ops/systemd/$unit" "/etc/systemd/system/$unit"
    fi
  done
fi

sudo systemctl daemon-reload
sudo systemctl restart openvision-jetson

env_file="$JETSON_PATH/ops/openvision.env"
face_enabled=0
if [[ -f "$env_file" ]] && grep -Eiq '^OPENVISION_FACE_WORKER_ENABLED=(1|true|yes|on|enabled)$' "$env_file"; then
  face_enabled=1
fi
deepstream_yolo26_enabled=0
if [[ -f "$env_file" ]] && grep -Eiq '^OPENVISION_DEEPSTREAM_YOLO26_WORKER_ENABLED=(1|true|yes|on|enabled)$' "$env_file"; then
  deepstream_yolo26_enabled=1
fi

if systemctl list-unit-files openvision-face-identity-worker.service >/dev/null 2>&1; then
  sudo systemctl stop openvision-face-identity-worker.service >/dev/null 2>&1 || true
  pkill -TERM -u "$JETSON_USER" -f 'python -m openvision_jetson.face_identity_worker' >/dev/null 2>&1 || true
  sleep 1
  pkill -KILL -u "$JETSON_USER" -f 'python -m openvision_jetson.face_identity_worker' >/dev/null 2>&1 || true
  if [[ "$face_enabled" == "1" ]]; then
    sudo systemctl enable --now openvision-face-identity-worker.service
    sudo systemctl restart openvision-face-identity-worker.service
  else
    sudo systemctl disable openvision-face-identity-worker.service >/dev/null 2>&1 || true
  fi
fi

if systemctl list-unit-files openvision-yolo26-stream-worker.service >/dev/null 2>&1; then
  sudo systemctl stop openvision-yolo26-stream-worker.service >/dev/null 2>&1 || true
  pkill -TERM -u "$JETSON_USER" -f 'python -m openvision_jetson.yolo26_stream_worker' >/dev/null 2>&1 || true
  sleep 1
  pkill -KILL -u "$JETSON_USER" -f 'python -m openvision_jetson.yolo26_stream_worker' >/dev/null 2>&1 || true
  sudo systemctl disable openvision-yolo26-stream-worker.service >/dev/null 2>&1 || true
  sudo rm -f /etc/systemd/system/openvision-yolo26-stream-worker.service
  sudo systemctl daemon-reload
fi

if systemctl list-unit-files openvision-deepstream-yolo26-worker.service >/dev/null 2>&1; then
  sudo systemctl stop openvision-deepstream-yolo26-worker.service >/dev/null 2>&1 || true
  pkill -TERM -u "$JETSON_USER" -f 'python -m openvision_jetson.deepstream_yolo26_worker' >/dev/null 2>&1 || true
  pkill -TERM -u "$JETSON_USER" -f 'deepstream_yolo26_openvision/.*/deepstream_app_config.txt' >/dev/null 2>&1 || true
  pkill -TERM -u "$JETSON_USER" -f 'mosquitto_sub.*openvision/rv101/yolo26' >/dev/null 2>&1 || true
  sleep 1
  pkill -KILL -u "$JETSON_USER" -f 'python -m openvision_jetson.deepstream_yolo26_worker' >/dev/null 2>&1 || true
  pkill -KILL -u "$JETSON_USER" -f 'deepstream_yolo26_openvision/.*/deepstream_app_config.txt' >/dev/null 2>&1 || true
  pkill -KILL -u "$JETSON_USER" -f 'mosquitto_sub.*openvision/rv101/yolo26' >/dev/null 2>&1 || true
  if [[ "$deepstream_yolo26_enabled" == "1" ]]; then
    sudo systemctl enable --now openvision-deepstream-yolo26-worker.service
    sudo systemctl restart openvision-deepstream-yolo26-worker.service
  else
    sudo systemctl disable openvision-deepstream-yolo26-worker.service >/dev/null 2>&1 || true
  fi
fi
REMOTE
  ssh -t "$ssh_target" "JETSON_PATH='$JETSON_PATH' JETSON_USER='$JETSON_USER' OPENVISION_SYNC_SYSTEMD='$OPENVISION_SYNC_SYSTEMD' bash '$remote_service_script'; rm -f '$remote_service_script'"
else
  echo "Skipped openvision-jetson service restart because OPENVISION_RESTART_SERVICE=$OPENVISION_RESTART_SERVICE"
fi

if [[ "$OPENVISION_RUN_IPHONE_SIGNOFF" == "1" ]]; then
  signoff_args=(
    "$ROOT/scripts/score_iphone_backend_readiness.py"
    --base-url "$JETSON_BASE_URL"
    --json-output "$OPENVISION_SIGNOFF_OUTPUT"
  )
  if [[ "$OPENVISION_SIGNOFF_CLOUD_VISUAL" == "1" ]]; then
    signoff_args+=(--exercise-cloud-visual)
  fi
  "$PYTHON_BIN" "${signoff_args[@]}"
else
  echo "Skipped iPhone backend readiness signoff because OPENVISION_RUN_IPHONE_SIGNOFF=$OPENVISION_RUN_IPHONE_SIGNOFF"
fi

echo "Deployed OpenVision v2 to $ssh_target:$JETSON_PATH"
