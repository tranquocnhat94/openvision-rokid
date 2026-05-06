#!/usr/bin/env bash
set -euo pipefail

APP_ID="com.example.rokidvideostream"
APK_PATH="app/build/outputs/apk/debug/app-debug.apk"
LAUNCH_ACTIVITY="com.example.cxrservicedemo.videostream.VideoStreamActivity"
JETSON_HOST="${ROKID_JETSON_HOST:-192.168.1.100}"
JETSON_CONTROL_PORT="${ROKID_JETSON_CONTROL_PORT:-9080}"

if [[ ! -f "env.sh" ]]; then
  echo "Run this script from project root (env.sh missing)." >&2
  exit 1
fi

source env.sh >/dev/null

if ! command -v adb >/dev/null 2>&1; then
  echo "adb not found on PATH. Check Android SDK platform-tools install." >&2
  exit 1
fi

if ! adb get-state >/dev/null 2>&1; then
  echo "No ADB device found. Connect glasses and enable debugging." >&2
  exit 1
fi

if [[ ! -f "$APK_PATH" ]]; then
  echo "APK not found at $APK_PATH. Building debug APK first..."
  ./gradlew :app:assembleDebug
fi

echo "Installing APK..."
adb install -r "$APK_PATH"

echo "Launching video-stream activity..."
adb shell am start \
  -n "${APP_ID}/${LAUNCH_ACTIVITY}" \
  --es jetson_host "$JETSON_HOST" \
  --ei jetson_control_port "$JETSON_CONTROL_PORT"

echo "Jetson VPN target: ${JETSON_HOST}:${JETSON_CONTROL_PORT}"
echo "Done."
