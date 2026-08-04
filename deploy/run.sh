#!/usr/bin/env bash
# Start solar-server as the CURRENT user (appuser). No root, no sudo.
#
#   foreground:  bash deploy/run.sh            (Ctrl+C stops)
#   background:  nohup bash deploy/run.sh > server.log 2>&1 &
#   stop:        pkill -f 'uvicorn solar_server.main:app'
#
# Config lives in ./env at the repo root (created from deploy/env.template
# on first run). Requires uv on PATH; uv provides Python 3.13 itself.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

if [[ ! -f env ]]; then
    cp deploy/env.template env
    echo "Created ./env from deploy/env.template — review it, then re-run." >&2
    exit 1
fi

# Export every KEY=VALUE from env (SOLAR_URL_PREFIX is read by the app,
# SOLAR_HOST/SOLAR_PORT below).
set -a
. ./env
set +a

exec uv run uvicorn solar_server.main:app \
    --host "${SOLAR_HOST:-127.0.0.1}" \
    --port "${SOLAR_PORT:-14905}"
