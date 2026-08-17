#!/usr/bin/env bash
# Starts the current (Next.js + FastAPI) stack for local development.
# Requires: conda env "ChatBot" with backend deps installed, Node installed,
# Ollama running locally with the model set in .env (OLLAMA_MODEL).
set -e
cd "$(dirname "$0")/.."

# `npm run dev` spawns a grandchild `next dev` -> `next-server` process that
# doesn't reliably receive signals sent to just its parent job (especially
# outside an interactive shell with job control). Sweep by port instead of
# relying on process-group signal propagation, so Ctrl+C reliably frees both.
cleanup() {
  lsof -ti :8000 -ti :3000 2>/dev/null | xargs kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate ChatBot

echo "Starting FastAPI backend on http://localhost:8000 ..."
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload &

echo "Starting Next.js frontend on http://localhost:3000 ..."
(cd frontend && npm run dev) &

wait
