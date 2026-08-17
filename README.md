# FinTemporal RAG

A private, hallucination-guarded financial co-pilot: live NSE/BSE market data fused
with your own uploaded annual reports / Excel exports / YouTube transcripts, ranked
by recency, running entirely on local infrastructure (ChromaDB + a local Ollama LLM).

## Architecture

The UI was migrated from Streamlit to Next.js. **All business logic, retrieval,
guardrails, and prompts are unchanged** — the Next.js app talks to a thin FastAPI
layer that wraps the exact same `utils/*` Python modules the original Streamlit
app used directly.

```
frontend/   Next.js (TypeScript, App Router, Tailwind) — the UI
            Auth.js (Google OAuth) handles sign-in; a server-side proxy at
            app/api/backend/[...path]/route.ts injects the verified session
            email into every authenticated call to FastAPI.
backend/    FastAPI — thin transport layer, zero logic changes, wraps utils/*
utils/      Unchanged business logic: ChromaDB retrieval, Ollama generation,
            yfinance/GNews fetching, PDF/Excel/YouTube ingestion, guardrail
            prompts, chat-session persistence.
app.py      DEPRECATED legacy Streamlit UI — kept as a fallback for now (see
            "Legacy Streamlit fallback" below). Imports the same utils/*.
data/       Shared, gitignored: chat_histories/*.json (one file per user) and
            chroma_db/ (per-user vector collections). Both the new stack and
            the legacy Streamlit app read/write the same files — no migration
            needed if you switch between them.
```

## Prerequisites

- **Python**: a conda environment named `ChatBot` with the dependencies in
  `requirements.txt` plus `fastapi` and `python-multipart` installed.
- **Node.js** (v20+) for the `frontend/` app.
- **Ollama** running locally with the model referenced by `OLLAMA_MODEL` in
  `.env` pulled (`ollama pull <model>`).

## Setup

1. **Root `.env`** (Python backend + legacy Streamlit) — see `.env` for the
   full list: `FMP_API_KEY`, `OLLAMA_MODEL`, `OLLAMA_BASE_URL`, `CHROMA_DB_DIR`,
   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.
   - If this machine sits behind a proxy that intercepts localhost traffic,
     `NO_PROXY=localhost,127.0.0.1` (and lowercase `no_proxy`) must be set here
     too, or every Ollama call will 504.
2. **`frontend/.env.local`** (Next.js):
   - `NEXT_PUBLIC_API_BASE_URL` — where FastAPI is reachable (`http://localhost:8000`)
   - `AUTH_SECRET` — random secret for Auth.js session signing (`openssl rand -base64 32`)
   - `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` — same OAuth client as the root `.env`
   - `AUTH_TRUST_HOST=true` — required for `next start` (production mode); Auth.js
     only auto-trusts the request host under `next dev`, and rejects every
     request as `UntrustedHost` without this otherwise
   - `NO_PROXY` / `no_proxy` — same proxy caveat as above; Node's native `fetch`
     doesn't read these automatically the way Python's `requests` does, so
     `frontend/src/instrumentation.ts` installs a proxy-aware dispatcher at
     startup using them.
3. **Google Cloud Console**: the OAuth client needs **both** redirect URIs
   registered if you want to run old and new side by side:
   - `http://localhost:8501/` (legacy Streamlit)
   - `http://localhost:3000/api/auth/callback/google` (Next.js / Auth.js)

## Running (development)

```bash
./scripts/dev.sh
```

Starts FastAPI on `:8000` and Next.js on `:3000` together (Ctrl+C stops both).
Or run them separately:

```bash
# Terminal 1 — backend
conda activate ChatBot
uvicorn backend.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:3000**.

## Running (production-style)

```bash
cd frontend && npm run build && npm start   # :3000
conda activate ChatBot && uvicorn backend.main:app --host 127.0.0.1 --port 8000  # :8000
```

## Legacy Streamlit fallback

The original Streamlit UI still works and shares the same data:

```bash
./scripts/legacy-streamlit.sh   # http://localhost:8501
```

It shows a deprecation banner. Once you're confident in the Next.js/FastAPI
stack, retire it by deleting `app.py` and removing `streamlit`,
`streamlit-oauth`, and `extra-streamlit-components` from `requirements.txt`.

## Known issues (pre-existing, not introduced by this migration)

- **`FMP_API_KEY` appears to be invalid/expired** — quantitative-metrics
  fetches log a 401 from Financial Modeling Prep and silently fall back to
  yfinance (by design). Renew the key if FMP was meant to be the primary
  source.
- **YouTube ingestion gatekeeper**: `qwen2.5:7b-instruct` doesn't always
  follow the gatekeeper's strict JSON-only schema on richer transcripts,
  which the code fail-closes to a rejection (by design, for safety). This is
  a model/prompt behavior in unchanged code (`utils/youtube_ingestion.py`),
  not a regression from the migration.
- **`langchain_community.llms.Ollama`** in `utils/llm_engine.py` is
  deprecated upstream in favor of `langchain_ollama.OllamaLLM` — still works,
  just emits a warning.
