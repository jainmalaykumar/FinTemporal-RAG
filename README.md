# FinTemporal RAG

A hallucination-guarded financial research co-pilot. It fuses **live NSE/BSE
market data** with **your own uploaded annual reports, Excel exports, and
YouTube transcripts**, ranks everything by recency and company relevance, and
refuses to answer rather than guess when the evidence isn't there — all on
local infrastructure (ChromaDB + a self-hosted Ollama LLM, no data leaves the
machine).

**[Live demo](https://finrag.me)** · Next.js + FastAPI, Python retrieval/guardrail core

## Key features

- **Temporal-aware retrieval** — a custom reranker combines semantic
  similarity with an exponential recency-decay curve (20% score penalty per
  year of chunk age), so a 2024 filing is naturally outweighed by a 2026 one
  for the same query, instead of stale data winning on similarity alone.
- **Company-scoped retrieval** — documents and YouTube transcripts carry
  detected-company metadata; a soft boost/demote pass reorders retrieved
  chunks so the selected stock's data leads the answer even when a
  differently-worded competitor chunk scores higher on raw similarity.
- **Multi-tenant, per-user isolation** — Google OAuth sign-in, with every
  user's documents and market data stored in separate ChromaDB collections
  (`docs_{email}`, `market_{email}`) — no cross-user data leakage.
- **JIT dual-ingestion** — every query in "All Sources" mode fetches live
  quantitative metrics (yfinance, with an FMP fallback) and the 5 most recent
  news articles for the selected ticker, embeds them on the fly, and blends
  them with prior uploads via a guaranteed-slot merge (4 document + 2 market
  chunks) so neither source starves the other.
- **Actionable refusals, not dead ends** — when context is genuinely
  insufficient, the assistant says so explicitly (never fabricates a figure)
  and appends a concrete next step: which mode to switch to, or what to
  upload.
- **Citation highlighting** — numeric figures in an answer are traced back
  and highlighted inline inside the retrieved context, so you can verify
  exactly which sentence a number came from.
- **Live ingestion progress** — YouTube ingestion (transcript fetch → content
  gatekeeper → entity extraction → chunk storage) reports its stage in
  real time instead of a blind 60–90s spinner.

## Architecture

```
frontend/   Next.js (TypeScript, App Router, Tailwind) — the UI
            Auth.js (Google OAuth) handles sign-in; a server-side proxy at
            app/api/backend/[...path]/route.ts injects the verified session
            email into every authenticated call to FastAPI.
backend/    FastAPI — thin transport layer over the Python retrieval core
utils/      Retrieval and generation core: ChromaDB vector store + custom
            time/company-aware reranker, Ollama generation, yfinance/GNews
            fetching, PDF/Excel/YouTube ingestion, guardrail prompts,
            chat-session persistence.
data/       Gitignored: chat_histories/*.json (one file per user) and
            chroma_db/ (per-user vector collections).
```

**Retrieval**: ChromaDB cosine-similarity search over-fetches `fetch_k=20`
candidates, which a custom Python reranker scores as
`similarity × 0.8^age_years × company_match_boost` before slicing to the
top-6 sent to the LLM — not a generic off-the-shelf reranker, purpose-built
for a domain where a metric's age and the company it belongs to both matter
as much as its semantic match.

**Generation & guardrails**: a locally-hosted, quantized Qwen 2.5 (7B,
Q4_K_M, 4.7 GB, 32K context) model via Ollama answers strictly from the
supplied context. Each of the 12 curated financial-analysis query templates
carries its own precedence rules (extract → derive from raw components →
refuse), enforced through prompt design plus backend-side detection of the
refusal phrase to append an actionable tip — not a third-party guardrail
framework, a purpose-built prompt contract per query type.

## Prerequisites

- **Python**: a conda environment named `ChatBot` with the dependencies in
  `requirements.txt` plus `fastapi` and `python-multipart` installed.
- **Node.js** (v20+) for the `frontend/` app.
- **Ollama** running locally with the model referenced by `OLLAMA_MODEL` in
  `.env` pulled (`ollama pull <model>`).

## Setup

1. **Root `.env`** — see `.env.example` for the full list: `FMP_API_KEY`,
   `OLLAMA_MODEL`, `OLLAMA_BASE_URL`, `CHROMA_DB_DIR`, `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.
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
3. **Google Cloud Console**: register the OAuth redirect URI
   `http://localhost:3000/api/auth/callback/google`.

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