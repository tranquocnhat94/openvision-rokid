#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${OPENVISION_SECRETS_DIR:-$ROOT/ops/secrets}"
OPENAI_KEY_FILE="${OPENAI_API_KEY_FILE:-$SECRETS_DIR/openai_api_key}"

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

if [[ "${1:-}" == "--write-openai-key" ]]; then
  umask 077
  read -r -s -p "OpenAI API key: " OPENAI_KEY
  printf "\n"
  if [[ -z "$OPENAI_KEY" ]]; then
    echo "No key written: empty input." >&2
    exit 1
  fi
  printf "%s\n" "$OPENAI_KEY" > "$OPENAI_KEY_FILE"
  chmod 600 "$OPENAI_KEY_FILE"
  echo "OpenAI key file ready: $OPENAI_KEY_FILE"
else
  echo "Secrets directory ready: $SECRETS_DIR"
  echo "OpenAI key file expected at: $OPENAI_KEY_FILE"
fi
