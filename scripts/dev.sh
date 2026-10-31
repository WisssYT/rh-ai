#!/usr/bin/env bash
# Start API (:8000), worker and frontend (:5173) for the local demo. Ctrl+C stops all three.
# Prerequisites: PostgreSQL + Mailpit running (docker compose up -d, or scripts/native-services.sh start),
# backend deps (cd backend && uv sync), frontend deps (cd frontend && npm install), migrations applied.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
trap 'kill 0' EXIT INT TERM
( cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 ) &
( cd "$ROOT/backend" && .venv/bin/python -m app.worker ) &
( cd "$ROOT/frontend" && npx vite --host 127.0.0.1 ) &
wait
