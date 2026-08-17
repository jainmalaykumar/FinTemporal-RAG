"""
FastAPI backend for FinTemporal RAG.

This is a thin transport layer only — every endpoint calls straight into the
existing utils/* modules (ChromaDBManager, FinRAGGenerator, FinancialDataFetcher,
doc_processor, youtube_ingestion) with zero logic changes. It exists so the new
Next.js frontend can drive the exact same pipeline app.py (Streamlit) drives.

⚠️ SECURITY NOTE (temporary, Phase 1 only): `user_email` is currently accepted
as a plain client-supplied field on every request, with no verification. This
is safe ONLY because the server binds to localhost and the frontend runs on
the same machine. Phase 3 (NextAuth.js) will replace this with a trusted
server-to-server header set by Node only after verifying the Google session —
until then, do not expose this API beyond localhost.
"""
import io
import logging
import time

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
        # Catch-all so an unexpected failure anywhere in the pipeline (e.g. a
        # transient Ollama/network hiccup surfacing as a bare RuntimeError)
        # always reaches the client as a clear message instead of an
        # unhandled 500 with a generic body.
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
            context_chunks = db_manager.search_pdfs_only(query=req.query_text, k=6, fetch_k=20)
            if not context_chunks:
                warning_msg = (
                    "Please upload a PDF or Excel file to use Documents Only mode, "
                    "or no documents have finished indexing yet."
                )
                messages.append({"role": "assistant", "content": warning_msg, "context": []})
                save_session_messages(req.user_email, req.session_id, messages, stock=req.selected_stock)
                return QueryResponse(response=warning_msg, context=[], messages=messages)

        elif req.search_scope == _SCOPE_YT:
            context_chunks = db_manager.search_youtube_only(query=req.query_text, k=6, fetch_k=20)

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

        formatted_chunks = []
        for i, chunk in enumerate(context_chunks, 1):
            source_name = chunk.get("metadata", {}).get("source", "Unknown")
            chunk_text = chunk.get("text_chunk", "")
            formatted_chunks.append(f"**Chunk {i}** *(Source: {source_name})*: {chunk_text}")

        response = llm_engine.generate_response(user_query=req.query_text, context_chunks=formatted_chunks)

        messages.append({"role": "assistant", "content": response, "context": formatted_chunks})
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
