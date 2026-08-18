"""
FastAPI backend for FinTemporal RAG.

This is a thin transport layer only — every endpoint calls straight into the
existing utils/* modules (ChromaDBManager, FinRAGGenerator, FinancialDataFetcher,
doc_processor, youtube_ingestion) with zero logic changes. It exists so the new
Next.js frontend can drive the exact same pipeline app.py (Streamlit) drives.

Auth: `user_email` arrives as a plain field on every request, but every
caller is the authenticated Next.js proxy (see frontend/src/app/api/backend/
[...path]/route.ts), which overwrites whatever the browser sent with the
verified email from the Auth.js session before forwarding the request here.
This API is not meant to be reachable from anywhere except that proxy — it
binds to localhost and has no independent auth of its own.
"""
import io
import logging
import threading
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from utils.chat_sessions import (
    create_new_session,
    delete_session,
    get_or_create_active_session,
    load_sessions_store,
    save_session_messages,
)
from utils.doc_processor import process_uploaded_file
from utils.query_templates import ENHANCED_QUERY_PROMPTS, QUERY_TABS
from utils.stock_list import NIFTY_500_STOCKS
from utils.vector_store import _parse_date_published
from utils.youtube_ingestion import (
    TranscriptFetchError,
    VideoRejectedError,
    process_youtube_url,
)

from backend.deps import get_data_fetcher, get_db_manager, get_llm_engine
from backend.schemas import (
    ChatMessage,
    ClearDataRequest,
    NewSessionRequest,
    QueryRequest,
    QueryResponse,
    StockSwitchRequest,
    YoutubeIngestRequest,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="FinTemporal RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_SCOPE_ALL = "all"
_SCOPE_YT = "youtube"
_SCOPE_DOCS = "docs"


class _UploadedFileAdapter(io.BytesIO):
    """
    Makes a FastAPI-received file behave like Streamlit's UploadedFile, which
    is the interface utils/doc_processor.py's process_uploaded_file() and
    process_excel_file() were written against (`.name` attribute + `.getvalue()`
    + file-like `.read()` for PdfReader). Pure adapter — doc_processor.py is
    untouched.
    """

    def __init__(self, content: bytes, name: str):
        super().__init__(content)
        self.name = name


# ===========================================================================
# HEALTH / STATIC REFERENCE DATA
# ===========================================================================

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/stocks")
def get_stocks():
    return NIFTY_500_STOCKS


@app.get("/api/query-templates")
def get_query_templates():
    return {"prompts": ENHANCED_QUERY_PROMPTS, "tabs": QUERY_TABS}


# ===========================================================================
# CHAT SESSIONS
# ===========================================================================

@app.get("/api/sessions")
def list_sessions(user_email: str):
    return load_sessions_store(user_email)


@app.post("/api/sessions/active")
def get_active_session(req: NewSessionRequest):
    """Mirrors app.py's multi-session bootstrap: reuse the newest empty
    session (garbage-collecting phantom ones) or create a fresh one."""
    session_id = get_or_create_active_session(req.user_email)
    store = load_sessions_store(req.user_email)
    return {"session_id": session_id, "store": store}


@app.post("/api/sessions")
def new_session(req: NewSessionRequest):
    session_id = create_new_session(req.user_email)
    return {"session_id": session_id}


@app.delete("/api/sessions/{session_id}")
def remove_session(session_id: str, user_email: str):
    next_session_id = delete_session(user_email, session_id)
    return {"next_session_id": next_session_id}


# ===========================================================================
# KNOWLEDGE BASE — document + YouTube ingestion
# ===========================================================================

@app.post("/api/ingest/document")
async def ingest_documents(user_email: str = Form(...), files: list[UploadFile] = File(...)):
    db_manager = get_db_manager(user_email)

    all_chunks = []
    detected_company = None
    detected_tickers: list[str] = []

    for uf in files:
        content = await uf.read()
        adapter = _UploadedFileAdapter(content, uf.filename)
        chunks = process_uploaded_file(adapter)
        all_chunks.extend(chunks)

    if all_chunks:
        db_manager.store_data(all_chunks)
        for chunk in all_chunks:
            dc = chunk.get("metadata", {}).get("detected_company")
            dt_raw = chunk.get("metadata", {}).get("detected_tickers", "")
            if dc:
                detected_company = dc
                detected_tickers = dt_raw.split(",") if isinstance(dt_raw, str) else dt_raw
                break

    return {
        "chunks_ingested": len(all_chunks),
        "files_ingested": [uf.filename for uf in files],
        "detected_company": detected_company,
        "detected_tickers": detected_tickers,
    }


@app.post("/api/ingest/youtube")
def ingest_youtube(req: YoutubeIngestRequest):
    """
    Legacy synchronous path — kept for direct/scripted callers, but the UI
    uses the job-based /start + /status pair below instead so it can show
    live progress during the ~60-90s this can take.
    """
    db_manager = get_db_manager(req.user_email)

    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Please paste a YouTube URL first.")

    start = time.monotonic()
    logger.info("[YT INGEST] START url=%s company=%s", req.url.strip(), req.active_company)
    try:
        result = process_youtube_url(req.url.strip(), active_company=req.active_company)
    except VideoRejectedError as e:
        logger.info("[YT INGEST] REJECTED after %.1fs: %s", time.monotonic() - start, e)
        raise HTTPException(status_code=422, detail=f"Video rejected by AI gatekeeper. {e}")
    except TranscriptFetchError as e:
        logger.info("[YT INGEST] NO TRANSCRIPT after %.1fs: %s", time.monotonic() - start, e)
        raise HTTPException(status_code=422, detail=f"Transcript unavailable. {e}")
    except ValueError as e:
        logger.info("[YT INGEST] INVALID URL after %.1fs: %s", time.monotonic() - start, e)
        raise HTTPException(status_code=400, detail=f"Invalid YouTube URL. {e}")
    except Exception as e:
        logger.exception("[YT INGEST] FAILED after %.1fs", time.monotonic() - start)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")
    logger.info("[YT INGEST] SUCCESS after %.1fs — %d chunks", time.monotonic() - start, result["chunks"])

    n_chunks = result["chunks"]
    if n_chunks:
        db_manager.store_data(result["chunk_list"])

    return {
        "chunks": n_chunks,
        "metadata": result["metadata"],
        "warning": result.get("warning"),
    }


# ── Job-based ingestion (used by the UI) ────────────────────────────────────
# In-memory job store: fine for this single-worker local deployment, but
# wouldn't survive a worker restart or scale across multiple processes — a
# real deployment would swap this for Redis/Celery. Simple dict get/set is
# safe here without a lock: the GIL makes each individual access atomic, and
# only one field is ever touched at a time.
_ingest_jobs: dict[str, dict] = {}
_INGEST_JOB_TTL_SECONDS = 600


def _prune_old_ingest_jobs() -> None:
    now = time.monotonic()
    stale = [
        jid for jid, job in _ingest_jobs.items()
        if job.get("done") and (now - job.get("_created_at", now)) > _INGEST_JOB_TTL_SECONDS
    ]
    for jid in stale:
        _ingest_jobs.pop(jid, None)


@app.post("/api/ingest/youtube/start")
def start_ingest_youtube(req: YoutubeIngestRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Please paste a YouTube URL first.")

    _prune_old_ingest_jobs()
    job_id = str(uuid.uuid4())
    _ingest_jobs[job_id] = {
        "stage": "Starting…",
        "done": False,
        "result": None,
        "error": None,
        "_created_at": time.monotonic(),
    }

    def run() -> None:
        start = time.monotonic()
        url = req.url.strip()
        logger.info("[YT INGEST] START job=%s url=%s company=%s", job_id, url, req.active_company)
        try:
            def on_progress(stage: str) -> None:
                _ingest_jobs[job_id]["stage"] = stage

            result = process_youtube_url(url, active_company=req.active_company, on_progress=on_progress)
            n_chunks = result["chunks"]
            if n_chunks:
                _ingest_jobs[job_id]["stage"] = "Storing chunks…"
                db_manager = get_db_manager(req.user_email)
                db_manager.store_data(result["chunk_list"])
            _ingest_jobs[job_id]["result"] = {
                "chunks": n_chunks,
                "metadata": result["metadata"],
                "warning": result.get("warning"),
            }
            logger.info(
                "[YT INGEST] SUCCESS job=%s after %.1fs — %d chunks",
                job_id, time.monotonic() - start, n_chunks,
            )
        except VideoRejectedError as e:
            logger.info("[YT INGEST] REJECTED job=%s after %.1fs: %s", job_id, time.monotonic() - start, e)
            _ingest_jobs[job_id]["error"] = {"status": 422, "detail": f"Video rejected by AI gatekeeper. {e}"}
        except TranscriptFetchError as e:
            logger.info("[YT INGEST] NO TRANSCRIPT job=%s after %.1fs: %s", job_id, time.monotonic() - start, e)
            _ingest_jobs[job_id]["error"] = {"status": 422, "detail": f"Transcript unavailable. {e}"}
        except ValueError as e:
            logger.info("[YT INGEST] INVALID URL job=%s after %.1fs: %s", job_id, time.monotonic() - start, e)
            _ingest_jobs[job_id]["error"] = {"status": 400, "detail": f"Invalid YouTube URL. {e}"}
        except Exception as e:
            logger.exception("[YT INGEST] FAILED job=%s after %.1fs", job_id, time.monotonic() - start)
            _ingest_jobs[job_id]["error"] = {"status": 500, "detail": f"Ingestion failed: {e}"}
        finally:
            _ingest_jobs[job_id]["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/ingest/youtube/status/{job_id}")
def get_ingest_youtube_status(job_id: str):
    job = _ingest_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found (it may have expired).")
    if job["done"] and job["error"]:
        raise HTTPException(status_code=job["error"]["status"], detail=job["error"]["detail"])
    return {"stage": job["stage"], "done": job["done"], "result": job["result"]}


# ===========================================================================
# DIAGNOSTICS / DATA MANAGEMENT
# ===========================================================================

@app.get("/api/diagnostics")
def diagnostics(user_email: str):
    db_manager = get_db_manager(user_email)
    try:
        src_counts = db_manager.get_source_type_counts()
        return {
            "youtube_chunks": src_counts["youtube_chunks"],
            "document_chunks": src_counts["document_chunks"],
            "market_chunks": src_counts["market_chunks"],
        }
    except Exception as e:
        counts = db_manager.get_collection_counts()
        return {
            "uploaded_documents": counts["uploaded_documents"],
            "market_data": counts["market_data"],
            "granular_unavailable_reason": str(e),
        }


@app.post("/api/data/clear")
def clear_data(req: ClearDataRequest):
    db_manager = get_db_manager(req.user_email)
    success = db_manager.clear_all_data()
    if success:
        save_session_messages(req.user_email, req.session_id, [])
    return {"success": success}


@app.post("/api/stock/switch")
def switch_stock(req: StockSwitchRequest):
    db_manager = get_db_manager(req.user_email)
    db_manager.clear_market_collection()
    save_session_messages(
        req.user_email,
        req.session_id,
        [m.model_dump(exclude_none=True) for m in req.messages],
        stock=req.old_stock,
    )
    new_session_id = create_new_session(req.user_email)
    return {"new_session_id": new_session_id}


# ===========================================================================
# QUERY PIPELINE — Scrape → Store → Retrieve → Generate
# ===========================================================================

_REFUSAL_MARKER = "i do not have sufficient context"


def _refusal_suggestion(search_scope: str, had_context: bool) -> str:
    """
    The guardrail prompt in llm_engine.py makes the LLM refuse rather than
    hallucinate when context is thin — good — but the refusal text itself
    ("I do not have sufficient context...") is a dead end with no path
    forward. This appends a deterministic, context-aware suggestion instead
    of trusting a small local model to reliably format its own help text
    (the same reliability class of problem as the YouTube gatekeeper).
    """
    if not had_context:
        if search_scope == _SCOPE_DOCS:
            return (
                "\n\nTip: No matching documents were found. Try uploading the "
                "relevant PDF/Excel filing in the Sources tab, or switch to "
                '"All Sources" mode.'
            )
        if search_scope == _SCOPE_YT:
            return (
                "\n\nTip: No matching YouTube transcripts were found. Ingest a "
                'relevant video in the Sources tab, or switch to "All Sources" mode.'
            )
        return (
            "\n\nTip: Try uploading a relevant document, ingesting a YouTube "
            "video, or rephrasing your question — live market data alone may "
            "not cover this."
        )
    return (
        "\n\nTip: Relevant sources were found but didn't contain a clear "
        'answer. Try rephrasing your question, or check "Retrieved context" '
        "to see what was searched."
    )


@app.post("/api/query", response_model=QueryResponse)
def query(req: QueryRequest):
    db_manager = get_db_manager(req.user_email)
    llm_engine = get_llm_engine()
    data_fetcher = get_data_fetcher()

    store = load_sessions_store(req.user_email)
    messages = store["sessions"].get(req.session_id, {}).get("messages", [])

    user_facing = req.display_text if req.display_text else req.query_text
    messages.append({"role": "user", "content": user_facing})
    save_session_messages(req.user_email, req.session_id, messages, stock=req.selected_stock)

    try:
        # ── RETRIEVAL ROUTING (search_scope is the single authority) ────────
        if req.search_scope == _SCOPE_DOCS:
            context_chunks = db_manager.search_pdfs_only(
                query=req.query_text, k=6, fetch_k=20, target_ticker=req.selected_stock,
            )
            if not context_chunks:
                warning_msg = (
                    "Please upload a PDF or Excel file to use Documents Only mode, "
                    "or no documents have finished indexing yet."
                )
                messages.append({"role": "assistant", "content": warning_msg, "context": []})
                save_session_messages(req.user_email, req.session_id, messages, stock=req.selected_stock)
                return QueryResponse(response=warning_msg, context=[], messages=messages)

        elif req.search_scope == _SCOPE_YT:
            context_chunks = db_manager.search_youtube_only(
                query=req.query_text, k=6, fetch_k=20, target_ticker=req.selected_stock,
            )

        else:
            # ── Hybrid: All Sources — full JIT pipeline ──────────────────────
            quant_chunks = data_fetcher.fetch_quantitative_metrics(req.selected_stock)
            news_chunks = data_fetcher.fetch_qualitative_news(req.selected_stock, req.query_text)
            all_market_chunks = quant_chunks + news_chunks
            if all_market_chunks:
                db_manager.store_data(all_market_chunks)

            doc_context_chunks, jit_context_chunks = db_manager.search_all(
                query=req.query_text,
                ticker=req.selected_stock,
                doc_k=6,
                market_k=3,
                fetch_k=20,
            )

            # Guaranteed-slot merge — prevents either domain starving
            DOC_SLOTS = 4
            MARKET_SLOTS = 2
            TOTAL_CAP = 6

            final_doc_chunks = doc_context_chunks[:DOC_SLOTS]
            final_market_chunks = jit_context_chunks[:MARKET_SLOTS]

            doc_used = len(final_doc_chunks)
            market_used = len(final_market_chunks)
            spare = TOTAL_CAP - (doc_used + market_used)

            if spare > 0:
                if doc_used < DOC_SLOTS:
                    extra_market = jit_context_chunks[MARKET_SLOTS: MARKET_SLOTS + spare]
                    final_market_chunks = final_market_chunks + extra_market
                elif market_used < MARKET_SLOTS:
                    extra_doc = doc_context_chunks[DOC_SLOTS: DOC_SLOTS + spare]
                    final_doc_chunks = final_doc_chunks + extra_doc

            context_chunks = (final_doc_chunks + final_market_chunks)[:TOTAL_CAP]

        # ── Data freshness: surface the most recent JIT snapshot's timestamp
        # so the user can see whether the market data behind the answer is
        # fresh or a cached older snapshot. Only JIT (market/news) chunks
        # carry Date_Published — uploaded documents carry `year` instead —
        # so this naturally reflects "None" when the answer came from docs.
        freshest_dt = None
        freshest_source = None
        for chunk in context_chunks:
            meta = chunk.get("metadata", {})
            parsed = _parse_date_published(meta.get("Date_Published"))
            if parsed and (freshest_dt is None or parsed > freshest_dt):
                freshest_dt = parsed
                freshest_source = meta.get("source")
        data_freshness = None
        if freshest_dt:
            data_freshness = f"Data as of {freshest_dt.strftime('%d %b %Y, %H:%M')}"
            if freshest_source:
                data_freshness += f" via {freshest_source}"

        formatted_chunks = []
        for i, chunk in enumerate(context_chunks, 1):
            source_name = chunk.get("metadata", {}).get("source", "Unknown")
            chunk_text = chunk.get("text_chunk", "")
            formatted_chunks.append(f"**Chunk {i}** *(Source: {source_name})*: {chunk_text}")

        response = llm_engine.generate_response(user_query=req.query_text, context_chunks=formatted_chunks)

        if _REFUSAL_MARKER in response.lower():
            response = response.rstrip() + _refusal_suggestion(req.search_scope, bool(context_chunks))

        messages.append({
            "role": "assistant",
            "content": response,
            "context": formatted_chunks,
            "data_freshness": data_freshness,
        })
        save_session_messages(req.user_email, req.session_id, messages, stock=req.selected_stock)

        return QueryResponse(
            response=response,
            context=formatted_chunks,
            messages=[ChatMessage(**m) for m in messages],
        )

    except Exception as e:
        # ── Orphan-prompt rollback — never persist an unanswered prompt ─────
        if messages and messages[-1]["role"] == "user":
            messages.pop()
        save_session_messages(req.user_email, req.session_id, messages, stock=req.selected_stock)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")
