#!/usr/bin/env bash
# Start the AHDC Data Explorer: install deps, build the database if needed, start the server, open the browser.
#   ./run.sh            (PORT=8001 ./run.sh to use another port)
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
uv sync -q
[ -f data/ahdc.db ] || uv run python data/generate.py
if lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already listening on :$PORT (the server may already be running): http://127.0.0.1:$PORT"
  exit 0
fi
mkdir -p logs
( sleep 2; command -v open >/dev/null && open "http://127.0.0.1:$PORT/" ) &
echo "AHDC Data Explorer on http://127.0.0.1:$PORT   (offline fallback: http://127.0.0.1:$PORT/?replay=demo)"
uv run uvicorn server.app:app --port "$PORT" 2>&1 | tee logs/server.log
