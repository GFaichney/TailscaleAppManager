#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -d .venv ]; then
  echo "Virtual environment missing. Run ./setup.sh first."
  exit 1
fi

source .venv/bin/activate

PORT="${WRAPPER_PORT:-8080}"
WEB_PATH="${WRAPPER_WEB_PATH:-wrapper}"

if command -v tailscale >/dev/null 2>&1; then
  tailscale serve --bg --set-path "/${WEB_PATH}" "http://127.0.0.1:${PORT}" >/dev/null 2>&1 || true
  echo "Tailscale route configured on /${WEB_PATH} -> 127.0.0.1:${PORT}"
else
  echo "Warning: tailscale CLI not found; continuing without route setup"
fi

python app.py
