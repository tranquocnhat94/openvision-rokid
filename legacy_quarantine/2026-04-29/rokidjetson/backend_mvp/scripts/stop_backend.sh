#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="rokid-backend"
HOST="0.0.0.0"
PORT="9080"

tmux kill-session -t "$SESSION_NAME" >/dev/null 2>&1 || true
pkill -f "uvicorn app.main:app --host $HOST --port $PORT" >/dev/null 2>&1 || true
