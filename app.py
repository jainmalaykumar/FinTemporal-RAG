# ===========================================================================
# ⚠️  DEPRECATED — this Streamlit UI has been superseded by frontend/ (Next.js)
#     + backend/ (FastAPI), which wrap the exact same utils/* pipeline below.
#     Kept running intentionally as a fallback during the migration's
#     verification window. Once you're confident in the new stack, this file
#     (and streamlit / streamlit-oauth / extra-streamlit-components in
#     requirements.txt) can be removed — see README.md.
# ===========================================================================
import streamlit as st
import time
import base64
import json
import os
from streamlit_oauth import OAuth2Component
import extra_streamlit_components as stx

# Import backend pipeline modules
from utils.data_ingestion import FinancialDataFetcher
from utils.vector_store import ChromaDBManager
from utils.llm_engine import FinRAGGenerator
from utils.doc_processor import process_uploaded_file, COMPANY_SIGNALS
from utils.youtube_ingestion import (
    process_youtube_url,
    VideoRejectedError,
    TranscriptFetchError,
)
from utils.stock_list import NIFTY_500_STOCKS
from utils.chat_sessions import (
    load_sessions_store,
    save_sessions_store,
    create_new_session,
    save_session_messages,
    delete_session,
    get_or_create_active_session,
)
from utils.query_templates import ENHANCED_QUERY_PROMPTS, QUERY_TABS

# ---------------------------------------------------------------------------
# Backward-compat shim so old call-sites in the codebase keep working.
# ---------------------------------------------------------------------------
def save_user_chat_history(user_email: str, messages: list) -> None:
    """
    Shim: saves *messages* into the *current* session tracked by session_state.
    Falls back to a no-op when no session is active yet (e.g. stock-switch
    clear that fires before the dashboard has fully initialised).
    """
    sid = st.session_state.get("current_session_id")
    if sid:
        save_session_messages(user_email, sid, messages)

# --- Page Configuration ---
st.set_page_config(
    page_title="FinTemporal RAG",
    page_icon="📈",
    layout="wide",
)

# ---------------------------------------------------------------------------
# GOOGLE OAUTH LOGIN GATE
# The entire app is blocked behind this check.  Only authenticated users
# (those whose email is stored in st.session_state["user_email"]) proceed.
# ---------------------------------------------------------------------------
CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
REDIRECT_URI  = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8501/")

AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT     = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT    = "https://oauth2.googleapis.com/revoke"

# ---------------------------------------------------------------------------
# COOKIE-BASED AUTH PERSISTENCE
# On every page load (including hard refreshes) we check whether a valid
# session cookie was left from a previous login.  If found, we restore
# user_email into session_state so the user doesn't have to re-authenticate.
# CookieManager must be instantiated ONCE at the module level; subsequent
# calls with the same key reuse the same browser cookie store.
# ---------------------------------------------------------------------------
_cookie_manager = stx.CookieManager(key="fintemporal_auth")

# FORCE WAIT FOR COOKIES TO LOAD
# The cookie manager needs one execution cycle to pull from the browser.
# Without this guard the get() call below races against the async JS bridge
# and always returns None on a hard reload, forcing the user to re-login.
if not _cookie_manager.cookies:
    time.sleep(0.5)

# Now safely check for the saved session
_saved_email = _cookie_manager.get("user_email")

# Hydrate ONLY if the cookie holds a real email AND the user didn't just
# click Logout (explicit_logout flag prevents zombie-cookie re-login).
if _saved_email and _saved_email != "":
    if not st.session_state.get("explicit_logout"):
        if st.session_state.get("user_email") != _saved_email:
            st.session_state["user_email"] = _saved_email
            st.rerun()  # Force a rerun to hydrate the rest of the app state

if "user_email" not in st.session_state:
    st.session_state["user_email"] = None

# --- Backend Initialization (Caching, keyed per authenticated user) ---
@st.cache_resource
def get_db_manager(user_email: str) -> ChromaDBManager:
    """Returns a ChromaDBManager scoped to the authenticated user's collections."""
    return ChromaDBManager(user_email=user_email)

@st.cache_resource
def load_llm_engine() -> FinRAGGenerator:
    return FinRAGGenerator()


# ===========================================================================
# RENDER FUNCTIONS
# ===========================================================================

def render_landing_page():
    """
    Premium SaaS landing page for unauthenticated visitors.
    Tells the Why, the What, and the How — then gates behind Google OAuth.
    Uses only native Streamlit elements (no custom CSS blocks).
    """
    # ── Additive UI Polish — purely CSS, zero structural changes ─────────────
    st.markdown("""
        <style>
        /* ── 1. Premium Font — Inter via Google Fonts ─────────────────────── */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        html, body, [class*="st-"], .stMarkdown, .stCaption, .stMetric,
        .stAlert, button, input, select, textarea {
            font-family: 'Inter', sans-serif !important;
        }

        /* ── 2. Push content flush to top — override Streamlit's default padding */
        .block-container {
            padding-top: 2rem !important;
            padding-bottom: 0rem !important;
        }

        /* ── 3. Page-load Fade-in Animation ────────────────────────────────── */
        @keyframes finPageFadeIn {
            from { opacity: 0; transform: translateY(12px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        section[data-testid="stMainBlockContainer"] > div:first-child {
            animation: finPageFadeIn 0.55s ease both;
        }

        /* ── 4. Metric Cards — hover lift + soft blue glow ─────────────────── */
        [data-testid="metric-container"] {
            background: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid rgba(59, 130, 246, 0.15) !important;
            border-radius: 12px !important;
            padding: 1rem 1.2rem !important;
            transition: transform 0.2s ease, box-shadow 0.2s ease,
                        border-color 0.2s ease !important;
        }
        [data-testid="metric-container"]:hover {
            transform: translateY(-4px) !important;
            box-shadow: 0 8px 28px rgba(59, 130, 246, 0.18) !important;
            border-color: rgba(59, 130, 246, 0.5) !important;
        }
        /* Keep the metric value readable on white bg */
        [data-testid="metric-container"] [data-testid="stMetricValue"] {
            color: #1e293b !important;
        }
        [data-testid="metric-container"] [data-testid="stMetricLabel"] {
            color: #475569 !important;
        }

        /* ── 5. Alert Boxes (success / info / warning) — hover lift + shimmer  */
        div[data-testid="stAlert"] {
            border-radius: 12px !important;
            border-width: 1px !important;
            transition: transform 0.22s ease, box-shadow 0.22s ease !important;
            backdrop-filter: blur(4px) !important;
        }
        div[data-testid="stAlert"]:hover {
            transform: translateY(-3px) !important;
            box-shadow: 0 6px 22px rgba(0, 0, 0, 0.25) !important;
        }
        /* Success → green tint */
        div[data-testid="stAlert"][data-baseweb="notification"][kind="positive"]:hover {
            box-shadow: 0 6px 22px rgba(34, 197, 94, 0.2) !important;
        }
        /* Info → blue tint */
        div[data-testid="stAlert"][data-baseweb="notification"][kind="info"]:hover {
            box-shadow: 0 6px 22px rgba(59, 130, 246, 0.2) !important;
        }
        /* Warning → amber tint */
        div[data-testid="stAlert"][data-baseweb="notification"][kind="warning"]:hover {
            box-shadow: 0 6px 22px rgba(251, 191, 36, 0.2) !important;
        }

        /* ── 6. Section headings — subtle left accent bar ───────────────────── */
        .stMarkdown h3 {
            border-left: 3px solid #3b82f6;
            padding-left: 0.6rem;
            margin-top: 0.4rem !important;
            color: #1e293b !important;
        }

        /* ── 7. Dividers — thinner, more refined ───────────────────────────── */
        hr {
            border: none !important;
            border-top: 1px solid rgba(0, 0, 0, 0.1) !important;
            margin: 1.5rem 0 !important;
        }

        /* ── 8. Footer caption — softer muted tone ──────────────────────────── */
        .stCaption {
            color: #475569 !important;
            text-align: center;
            letter-spacing: 0.02em;
        }
        </style>
    """, unsafe_allow_html=True)

    # ── Navigation bar — floating pill design ────────────────────────────────
    # Build the Google OAuth URL directly to render a plain <a> tag.
    import asyncio
    from streamlit_oauth import OAuth2Component as _OAuth2Component
    _oauth_client = _OAuth2Component(
        CLIENT_ID, CLIENT_SECRET,
        AUTHORIZE_ENDPOINT, TOKEN_ENDPOINT, TOKEN_ENDPOINT, REVOKE_ENDPOINT
    )
    auth_url = asyncio.run(
        _oauth_client.client.get_authorization_url(
            redirect_uri=REDIRECT_URI,
            scope=["openid", "email", "profile"],
            extras_params={"prompt": "consent", "access_type": "offline"},
        )
    )
    # IMPORTANT: No blank lines inside any <div> — Streamlit converts blank lines
    # to <p> tags which breaks flexbox and stacks children vertically.
    st.markdown(f"""
        <style>
        .floating-nav {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: #ffffff;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
            border: 1px solid #E5E7EB;
            margin-bottom: 2rem;
            margin-top: 0;
        }}
        .nav-brand-title {{
            color: #2563EB !important;
            font-size: 1.5rem;
            font-weight: 800;
            margin: 0 !important;
            line-height: 1.2;
        }}
        .nav-brand-subtitle {{
            color: #6B7280 !important;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 1px;
            margin: 0 !important;
        }}
        .nav-right-cluster {{
            display: flex;
            align-items: center;
        }}
        .nav-trust-badge {{
            color: #3B82F6 !important;
            font-size: 0.9rem;
            font-weight: 600;
            margin-right: 15px;
        }}
        .nav-login-btn {{
            background-color: #2563EB !important;
            color: #ffffff !important;
            padding: 0.5rem 1.2rem;
            border-radius: 6px;
            text-decoration: none !important;
            font-weight: 600;
            transition: all 0.2s ease;
            border: none;
            white-space: nowrap;
        }}
        .nav-login-btn:hover {{
            background-color: #1D4ED8 !important;
            transform: translateY(-2px);
            color: #ffffff !important;
            text-decoration: none !important;
        }}
        </style>
        <div class="floating-nav">
            <div>
                <p class="nav-brand-title">📈 FinTemporal RAG</p>
                <p class="nav-brand-subtitle">FINANCIAL INTELLIGENCE PLATFORM</p>
            </div>
            <div class="nav-right-cluster">
                <span class="nav-trust-badge">Secure · Private · Real-time</span>
                <a href="{auth_url}" target="_self" class="nav-login-btn">Sign In</a>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # ── OAuth Callback Catcher ────────────────────────────────────────────────
    # When the custom HTML <a> link redirects back from Google, the browser
    # lands on REDIRECT_URI with ?code=...&state=... in the URL.
    # The old authorize_button() widget handled this automatically; we must
    # now catch it manually since we replaced it with a plain <a> tag.
    if "code" in st.query_params:
        try:
            _code = st.query_params["code"]
            # Exchange the authorization code for tokens using the same
            # _oauth_client instance built above (no PKCE was used for the
            # plain link flow, so no code_verifier is needed).
            _token_response = asyncio.run(
                _oauth_client.client.get_access_token(
                    code=_code,
                    redirect_uri=REDIRECT_URI,
                )
            )
            # Decode the JWT id_token payload (middle segment) to get the email.
            # Matches the exact base64 pattern used elsewhere in this app.
            _id_token = _token_response["id_token"]
            _payload  = _id_token.split(".")[1]
            _payload += "=" * (-len(_payload) % 4)   # re-pad to valid base64
            _user_info = json.loads(base64.b64decode(_payload))
            _email = _user_info["email"]

            # Persist the authenticated email in session state and browser cookie.
            st.session_state["user_email"] = _email
            _cookie_manager.set("user_email", _email, key="set_email_cookie_callback")
            time.sleep(0.5)   # let the JS cookie bridge write before rerun

            # Clear the OAuth params from the URL, then route to the dashboard.
            st.query_params.clear()
            st.rerun()
        except Exception as _cb_err:
            st.error(
                f"Login failed during callback: {_cb_err}. "
                "Please try signing in again."
            )
            st.query_params.clear()

    st.markdown(
        "<p style='text-align:center; font-size:1.15rem; color:#555; "
        "max-width:700px; margin:0 auto 1.2rem auto;'>"
        "Your private, hallucination-guarded financial co-pilot — "
        "combining <strong>live NSE/BSE market data</strong> with "
        "<strong>your own annual reports</strong>, ranked by recency."
        "</p>",
        unsafe_allow_html=True,
    )

    # ── Value proposition stats ───────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stocks Covered",  "500+",  help="Full Nifty 500 index searchable")
    m2.metric("Data Sources",    "3",     help="Yahoo Finance · GNews · Your uploads")
    m3.metric("Query Templates", "12",    help="Pre-built Fundamental Analysis queries")
    m4.metric("Data Isolation",  "100%",  help="Per-user ChromaDB collections via OAuth")

    st.divider()

    # ── The WHY — storytelling row ────────────────────────────────────────────
    st.markdown("### 💡 Why FinTemporal RAG?")
    why1, why2, why3 = st.columns(3)

    with why1:
        st.success(
            "**For Financial Analysts** 🏦\n\n"
            "Stop copy-pasting numbers from PDFs. Upload a Screener.in Excel "
            "export or an SEBI annual report and ask plain-English questions. "
            "The AI fuses tables + narrative into a single grounded answer — "
            "with citations from the retrieved chunks."
        )
    with why2:
        st.info(
            "**For Retail Investors** 📊\n\n"
            "The internet is full of stale data. FinTemporal RAG fetches live "
            "Yahoo Finance metrics *at query time* and ranks retrieved context "
            "by age — so you always see the most recent quarter first, not a "
            "2019 filing buried in the index."
        )
    with why3:
        st.warning(
            "**For M.Tech / MBA Research** 🎓\n\n"
            "Need to benchmark operating margins, map dividend history, or "
            "identify risk factors across 5 years of reports? Use the 12 "
            "structured query templates as a research accelerator — each "
            "backed by an explicit EXTRACT → DERIVE → REFUSE logic chain."
        )

    st.divider()

    # ── The WHAT — capability walkthrough ────────────────────────────────────
    st.markdown("### 🛠️ What you can do once you log in")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            "- 📡 **Chat with live market data** — type any Nifty 500 ticker "
            "and ask earnings, valuation, or governance questions backed by "
            "real-time Yahoo Finance + GNews retrieval.\n"
            "- 📂 **Upload private documents** — your PDFs and Excel sheets "
            "are ingested into *your own isolated* ChromaDB collection. "
            "No other user on the platform can see or query your files.\n"
            "- 🔀 **Switch between Hybrid and BYOD modes** — Hybrid blends "
            "live JIT data with your uploads; BYOD sandboxes the AI strictly "
            "to your documents only."
        )
    with c2:
        st.markdown(
            "- 🕒 **Temporal re-ranking** — every retrieved chunk carries a "
            "recency score so a Q4-2024 filing always outranks a Q2-2022 "
            "chunk, even if both are semantically similar.\n"
            "- 💬 **Persistent chat history** — your conversation survives "
            "page refreshes and browser restarts. Log out, come back later, "
            "and pick up exactly where you left off.\n"
            "- 🧠 **12 structured query templates** — pre-engineered prompts "
            "for PEG ratio, D/E ratio, ROE, FCF trend, segment revenue, "
            "market share, peer margin comparison, dividend history, "
            "management changes, risk factors, and growth drivers."
        )

    st.divider()

    # ── Footer caption ────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.caption(
        "FinTemporal RAG · Built with Streamlit, ChromaDB & Sentence-Transformers "
        "· Indian Fiscal Year aware · All data processed locally"
    )

# ---------------------------------------------------------------------------

def render_dashboard():
    """
    Authenticated dashboard. All backend resources are initialised here.
    Layout: Sidebar (profile → target → knowledge base → diagnostics) |
            Main (header, tabbed queries, avatared chat + input).
    """
    user_email = st.session_state["user_email"]

    # ── Backend init (cached per user) ────────────────────────────────────────
    db_manager   = get_db_manager(user_email=user_email)
    llm_engine   = load_llm_engine()
    data_fetcher = FinancialDataFetcher()

    # ── Multi-session bootstrap ───────────────────────────────────────────────
    # ``get_or_create_active_session`` implements "Check Before Create" garbage
    # collection: it reuses the most-recent empty session instead of blindly
    # minting a new UUID on every Streamlit rerun, eliminating ghost sessions.
    if "sessions_store" not in st.session_state:
        _active_sid = get_or_create_active_session(user_email)
        _store      = load_sessions_store(user_email)   # reload after potential GC
        st.session_state.sessions_store     = _store
        st.session_state.current_session_id = _active_sid
        st.session_state.messages = (
            _store["sessions"]
            .get(_active_sid, {})
            .get("messages", [])
        )

    if st.session_state.get("_switch_to_session_id"):
        _target = st.session_state.pop("_switch_to_session_id")
        _store   = load_sessions_store(user_email)
        st.session_state.sessions_store      = _store
        st.session_state.current_session_id  = _target
        st.session_state.messages = (
            _store["sessions"].get(_target, {}).get("messages", [])
        )

    # =========================================================================
    # SIDEBAR  (order: Target Asset → Knowledge Base → Diagnostics →
    #           Chat History → User Profile / Sign Out)
    # =========================================================================
    with st.sidebar:

        # ── 1. Analysis Target ────────────────────────────────────────────────
        st.subheader("📊 Target Asset")
        CUSTOM_SENTINEL = "CUSTOM / OTHER (Enter Custom Ticker)"

        selected_option = st.selectbox(
            "🔍 Search Indian Stock (Nifty 500)",
            options=NIFTY_500_STOCKS,
            help="Start typing a ticker symbol or company name to filter.",
            label_visibility="collapsed",
        )

        if selected_option == CUSTOM_SENTINEL:
            raw_custom = st.text_input(
                "Enter Custom Symbol (e.g. TATACAPITAL)",
                placeholder="TATACAPITAL",
                help="Any valid NSE symbol — '.NS' is appended automatically if omitted."
            ).strip().upper()
            if raw_custom and not raw_custom.endswith((".NS", ".BO")):
                raw_custom += ".NS"
            selected_stock = raw_custom if raw_custom else "CUSTOM"
        else:
            selected_stock = selected_option.split(" - ")[0]

        # ── 2. Knowledge Base ─────────────────────────────────────────────────
        st.sidebar.divider()
        st.subheader("📁 Knowledge Base")

        # ── Search Scope — single routing control (replaces old BYOD toggle) ────
        # Determines which ChromaDB collection(s) are queried and whether the
        # JIT yfinance/news pipeline fires.  Three modes:
        #   🌐 All Sources  — hybrid: JIT fetch + full vector DB (default)
        #   📺 YouTube Only — document_collection filtered to youtube_transcript
        #   📄 Docs Only    — document_collection filtered to non-YouTube uploads
        _SCOPE_ALL  = "🌐 All Sources (Auto)"
        _SCOPE_YT   = "📺 YouTube Videos Only"
        _SCOPE_DOCS = "📄 Documents Only"

        search_scope = st.radio(
            "🔍 Search Scope",
            options=[_SCOPE_ALL, _SCOPE_YT, _SCOPE_DOCS],
            index=0,
            help=(
                "🌐 **All Sources** — hybrid retrieval: live JIT market data + full vector DB.\n\n"
                "📺 **YouTube Only** — queries ONLY ingested transcript chunks; "
                "yfinance/news tools are disabled.\n\n"
                "📄 **Documents Only** — queries ONLY uploaded PDF/Excel files; "
                "yfinance/news tools are disabled."
            ),
            key="search_scope_radio",
        )

        uploaded_files = st.file_uploader(
            "Upload Financial Document (PDF / TXT / Excel)",
            type=["pdf", "txt", "xlsx", "xls"],
            accept_multiple_files=True,
            help="Supports Annual Reports (PDF), plain text, and Screener.in Excel exports.",
            label_visibility="collapsed",
        )

        # ── YouTube Ingestion ──────────────────────────────────────────────────
        st.markdown(
            """
            <div style='
                margin-top: 0.9rem;
                margin-bottom: 0.35rem;
                display: flex;
                align-items: center;
                gap: 0.4rem;
            '>
                <span style='font-size:1rem;'>📺</span>
                <span style='font-weight:700; font-size:0.88rem;
                             color:#1e293b; letter-spacing:0.01em;'>
                    YouTube News Ingestion
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        yt_url = st.text_input(
            "YouTube Video URL",
            placeholder="https://www.youtube.com/watch?v=...",
            label_visibility="collapsed",
            key="yt_url_input",
            help="Paste any YouTube video URL. The AI gatekeeper will verify it's financial content before ingesting.",
        )

        if st.button(
            "📺 Ingest YouTube News",
            use_container_width=True,
            key="yt_ingest_btn",
            help="Fetch transcript, run AI gatekeeper, extract entities, and store in vector DB.",
        ):
            if not yt_url or not yt_url.strip():
                st.warning("⚠️ Please paste a YouTube URL first.")
            else:
                with st.spinner("Fetching transcript & running AI gatekeeper..."):
                    try:
                        result    = process_youtube_url(
                            yt_url.strip(),
                            active_company=selected_stock,
                        )
                        _n_chunks = result["chunks"]
                        _meta     = result["metadata"]
                        _channel  = _meta.get("channel", "Unknown Channel")
                        _pub_date = _meta.get("publish_date", "")
                        _title    = _meta.get("title", "video")

                        if _n_chunks:
                            db_manager.store_data(result["chunk_list"])
                            if result.get("warning"):
                                st.warning(
                                    f"⚠️ **Ingested with Warning:** {result['warning']}"
                                )
                                st.success(
                                    f"Ingested **{_n_chunks} chunks** from "
                                    f"*{_title}* anyway. "
                                    f"(📡 {_channel} · 🗓 {_pub_date})"
                                )
                            else:
                                st.success(
                                    f"✅ Successfully ingested **{_n_chunks} chunks** from "
                                    f"*{_title}* "
                                    f"(📡 {_channel} · 🗓 {_pub_date})"
                                )
                        else:
                            st.warning("⚠️ No transcript content was produced for this video.")
                    except VideoRejectedError as _vr:
                        st.error(
                            f"🚫 **Video rejected by AI gatekeeper.**\n\n{_vr}"
                        )
                    except TranscriptFetchError as _tf:
                        st.warning(
                            f"⚠️ **Transcript unavailable.**\n\n{_tf}"
                        )
                    except ValueError as _ve:
                        st.error(
                            f"❌ **Invalid YouTube URL.**\n\n{_ve}"
                        )
                    except Exception as _ex:
                        st.error(
                            f"❌ **Unexpected error during ingestion.**\n\n{_ex}"
                        )

        # ── 3. System Diagnostics (hidden by default) ─────────────────────────
        with st.sidebar.expander("⚙️ System Diagnostics", expanded=False):
            st.success("🟢 Server: Ubuntu (CPU-Only) — Active")

            # ─ Granular source-type breakdown ───────────────────────────────
            # Uses ChromaDB where-filter queries so numbers are always exact.
            try:
                src_counts = db_manager.get_source_type_counts()
                col_yt, col_doc = st.columns(2)
                with col_yt:
                    st.metric("📺 Video Chunks",  src_counts["youtube_chunks"])
                with col_doc:
                    st.metric("📄 Doc Chunks",    src_counts["document_chunks"])
                st.metric("📰 Live Market",  src_counts["market_chunks"],
                          help="JIT yfinance + news chunks (cleared on stock switch)")
            except Exception as _diag_err:
                # Fall back to the coarser total counts so diagnostics
                # never crash even if get_source_type_counts() fails.
                counts = db_manager.get_collection_counts()
                st.metric("📄 Total Doc Chunks", counts["uploaded_documents"])
                st.metric("📰 Market Chunks",    counts["market_data"])
                st.caption(f"⚠️ Granular split unavailable: {_diag_err}")

            st.divider()
            if st.button("🗑️ Clear All Data", use_container_width=True,
                         help="Wipe both vector collections and reset the chat session."):
                with st.spinner("Purging databases…"):
                    success = db_manager.clear_all_data()
                if success:
                    st.cache_resource.clear()
                    _cur = st.session_state.get("current_session_id")
                    if _cur:
                        save_session_messages(user_email, _cur, [])
                    st.session_state.messages         = []
                    st.session_state.ingested_files   = set()
                    st.session_state.pending_query    = None
                    st.session_state.pop("detected_doc_company", None)
                    st.session_state.pop("detected_doc_tickers",  None)
                    st.session_state.pop("previous_stock",         None)
                    st.session_state.pop("sessions_store",         None)
                    st.sidebar.success("✅ Database and chat history cleared!")
                    st.rerun()
                else:
                    st.sidebar.error("❌ Clear failed — check server logs.")

        # ── 4. Chat History ───────────────────────────────────────────────────
        st.sidebar.divider()

        st.markdown(
            "<div style='display:flex; align-items:center; gap:0.45rem;"
            " margin-bottom:0.55rem;'>"
            "<span style='font-size:1.05rem;'>💬</span>"
            "<span style='font-weight:700; font-size:0.92rem;"
            " color:#1e293b; letter-spacing:0.01em;'>Chat History</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        if st.button(
            "➕ New Chat",
            use_container_width=True,
            key="new_chat_btn",
            help="Start a fresh conversation — current chat is auto-saved",
        ):
            _new_sid = create_new_session(user_email)
            save_session_messages(
                user_email,
                st.session_state.current_session_id,
                st.session_state.messages,
            )
            st.session_state._switch_to_session_id = _new_sid
            st.session_state.pop("pending_query", None)
            st.session_state.pop("previous_stock", None)
            st.session_state.pop("ingested_files", None)
            st.rerun()

        # Shared compact-button CSS
        st.markdown("""
            <style>
            div[data-testid="stSidebar"] button[kind="secondary"] {
                border-radius: 7px !important;
                font-size: 0.80rem !important;
                padding: 0.30rem 0.5rem !important;
                border: 1px solid rgba(59,130,246,0.13) !important;
                background: rgba(248,250,252,0.9) !important;
                color: #334155 !important;
                transition: background 0.13s ease, border-color 0.13s ease,
                            color 0.13s ease !important;
                white-space: nowrap !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
            }
            div[data-testid="stSidebar"] button[kind="secondary"]:hover {
                background: rgba(219,234,254,0.7) !important;
                border-color: rgba(59,130,246,0.38) !important;
                color: #1e40af !important;
            }
            .sess-ts {
                font-size: 0.67rem;
                color: #94a3b8;
                margin: -0.35rem 0 0.3rem 0.15rem;
                line-height: 1;
            }
            </style>
        """, unsafe_allow_html=True)

        _live_store    = load_sessions_store(user_email)
        _session_order = _live_store.get("session_order", [])
        _sessions_map  = _live_store.get("sessions", {})
        _current_sid   = st.session_state.get("current_session_id", "")

        if _session_order:
            st.markdown(
                "<div style='font-size:0.70rem; color:#64748b;"
                " letter-spacing:0.06em; margin:0.2rem 0 0.25rem 0;'>"
                "SESSIONS</div>",
                unsafe_allow_html=True,
            )

            for _sid in _session_order:
                _sess      = _sessions_map.get(_sid, {})
                _raw_label = _sess.get("label", "New Chat")
                _created   = _sess.get("created", "")
                _is_active = (_sid == _current_sid)

                # Clean icon: 💬 active · 🗨️ inactive  (no blue dots, no brackets)
                _icon    = "💬" if _is_active else "🗨️"
                _display = f"{_icon}  {_raw_label}"

                # Muted timestamp shown as sub-caption below the row
                try:
                    _dt         = datetime.fromisoformat(_created)
                    _ts_caption = _dt.strftime("%d %b %Y · %H:%M")
                except Exception:
                    _ts_caption = ""

                # Inline row: [session title button | trash icon]
                _col_sess, _col_del = st.columns([0.82, 0.18], gap="small")

                with _col_sess:
                    if st.button(
                        _display,
                        key=f"sess_btn_{_sid}",
                        use_container_width=True,
                        help=_raw_label,
                        type="secondary",
                    ):
                        if not _is_active:
                            save_session_messages(
                                user_email,
                                _current_sid,
                                st.session_state.messages,
                            )
                            st.session_state._switch_to_session_id = _sid
                            st.session_state.pop("pending_query", None)
                            st.rerun()

                with _col_del:
                    if st.button(
                        "🗑️",
                        key=f"del_{_sid}",
                        help="Delete this chat",
                        use_container_width=True,
                        type="secondary",
                    ):
                        _next = delete_session(user_email, _sid)
                        if _sid == _current_sid:
                            if _next:
                                st.session_state._switch_to_session_id = _next
                            else:
                                _fresh = create_new_session(user_email)
                                st.session_state._switch_to_session_id = _fresh
                            st.session_state.pop("pending_query",  None)
                            st.session_state.pop("previous_stock", None)
                            st.session_state.pop("ingested_files", None)
                        st.session_state.pop("sessions_store", None)
                        st.rerun()

                if _ts_caption:
                    st.markdown(
                        f"<p class='sess-ts'>{_ts_caption}</p>",
                        unsafe_allow_html=True,
                    )
        else:
            st.caption("No saved sessions yet.")

        # ── 5. User Profile Badge & Sign Out (always at the bottom) ──────────
        st.sidebar.divider()

        display_name  = user_email.split("@")[0].replace(".", " ").title()
        avatar_letter = display_name[0].upper()

        badge_l, badge_r = st.columns([1, 4])
        with badge_l:
            st.markdown(
                f"<div style='background:#1565C0; color:white; border-radius:50%;"
                f" width:2.4rem; height:2.4rem; display:flex; align-items:center;"
                f" justify-content:center; font-size:1.1rem; font-weight:700;"
                f" margin-top:0.15rem;'>{avatar_letter}</div>",
                unsafe_allow_html=True,
            )
        with badge_r:
            st.markdown(
                f"**{display_name}**  \n"
                f"<span style='font-size:0.72rem; color:#888;'>{user_email}</span>",
                unsafe_allow_html=True,
            )

        if st.button(
            "Sign out", use_container_width=False, key="logout_btn",
            help="Clear session and return to the login screen",
            type="secondary",
        ):
            _cookie_manager.set("user_email", "", key="logout_empty_cookie")
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.session_state["user_email"]      = None
            st.session_state["explicit_logout"] = True
            st.cache_resource.clear()
            st.rerun()

    # =========================================================================
    # STOCK-SWITCH DETECTION
    # Runs on every re-run; clears market DB and chat when the stock changes.
    # doc-company state is intentionally NOT cleared here — the mismatch banner
    # must stay visible until the user removes the file.
    # =========================================================================
    if "previous_stock" not in st.session_state:
        st.session_state.previous_stock = selected_stock

    if selected_stock != st.session_state.previous_stock:
        db_manager.clear_market_collection()
        # Save the old session as-is, then start a brand-new session for the
        # new stock so history from different tickers stays clearly separated.
        save_session_messages(
            user_email,
            st.session_state.current_session_id,
            st.session_state.messages,
        )
        _switched_sid = create_new_session(user_email)
        st.session_state.sessions_store     = load_sessions_store(user_email)
        st.session_state.current_session_id = _switched_sid
        st.session_state.messages           = []
        st.session_state.previous_stock     = selected_stock
        st.sidebar.success(
            f"✅ Switched to **{selected_stock}**. "
            f"Market data cleared and a new chat session started."
        )

    # =========================================================================
    # EARLY INGESTION BLOCK
    # Process and store uploaded documents BEFORE any query or search() runs.
    # ingested_files (a set) prevents re-processing on every Streamlit re-run.
    # =========================================================================
    if "ingested_files" not in st.session_state:
        st.session_state.ingested_files = set()

    if uploaded_files:
        newly_uploaded = [
            uf for uf in uploaded_files
            if uf.name not in st.session_state.ingested_files
        ]
        if newly_uploaded:
            with st.spinner(f"Ingesting {len(newly_uploaded)} new document(s) into vector store..."):
                all_doc_chunks = []
                for uf in newly_uploaded:
                    chunks = process_uploaded_file(uf)
                    all_doc_chunks.extend(chunks)
                    st.session_state.ingested_files.add(uf.name)
                if all_doc_chunks:
                    db_manager.store_data(all_doc_chunks)
                    st.sidebar.success(
                        f"✅ Ingested {len(all_doc_chunks)} chunks from "
                        f"{len(newly_uploaded)} document(s)."
                    )

            # Persist detected company identity for the mismatch banner
            for chunk in all_doc_chunks:
                dc     = chunk.get("metadata", {}).get("detected_company")
                dt_raw = chunk.get("metadata", {}).get("detected_tickers", "")
                if dc:
                    st.session_state.detected_doc_company = dc
                    st.session_state.detected_doc_tickers = (
                        dt_raw.split(",") if isinstance(dt_raw, str) else dt_raw
                    )
                    break

    else:
        # User removed all files — clear doc-company state
        st.session_state.pop("detected_doc_company", None)
        st.session_state.pop("detected_doc_tickers",  None)
        st.session_state.ingested_files = set()

    # =========================================================================
    # QUERY PROCESSING PIPELINE
    # =========================================================================
    def process_user_query(query_text: str, display_text: str | None = None):
        """
        Executes the full JIT RAG pipeline: Scrape → Store → Retrieve → Generate.

        Args:
            query_text   : Full (potentially enriched) prompt sent to the LLM
                           and used for vector-store retrieval.
            display_text : Clean short label shown in the chat UI and stored in
                           chat history. Falls back to query_text when not provided.
        """
        user_facing = display_text if display_text else query_text

        st.chat_message("user", avatar="🧑‍💼").write(user_facing)
        st.session_state.messages.append({"role": "user", "content": user_facing})
        save_user_chat_history(user_email, st.session_state.messages)

        with st.chat_message("assistant", avatar="🏛️"):
            try:
                # ══════════════════════════════════════════════════════════════
                # RETRIEVAL ROUTING  (search_scope is the single authority)
                # ══════════════════════════════════════════════════════════════
                if search_scope == _SCOPE_DOCS:
                    # ── Branch 1: Docs Only — PDFs/Excel, no JIT ───────────────
                    if not uploaded_files:
                        warning_msg = "Please upload a PDF or Excel file to use Documents Only mode."
                        st.warning(warning_msg)
                        st.session_state.messages.append({"role": "assistant", "content": warning_msg, "context": []})
                        save_user_chat_history(user_email, st.session_state.messages)
                        return

                    with st.spinner("Searching uploaded documents..."):
                        doc_context_chunks = db_manager.search_pdfs_only(
                            query=query_text, k=6, fetch_k=20
                        )
                        if not doc_context_chunks:
                            raw = []
                            for uf in uploaded_files:
                                raw.extend(process_uploaded_file(uf))
                            doc_context_chunks = raw[:6]

                    context_chunks = doc_context_chunks[:6]

                elif search_scope == _SCOPE_YT:
                    # ── Branch 2: YouTube Only — no JIT, no PDF chunks ─────────
                    with st.spinner("Searching ingested YouTube transcripts..."):
                        context_chunks = db_manager.search_youtube_only(
                            query=query_text, k=6, fetch_k=20
                        )
                    if not context_chunks:
                        st.info(
                            "📺 No YouTube transcripts found in the vector store. "
                            "Ingest a video first using the YouTube News Ingestion panel."
                        )

                elif search_scope == _SCOPE_DOCS:
                    # ── Branch 3: Documents Only — no JIT, no YouTube chunks ───
                    with st.spinner("Searching uploaded PDF / Excel documents..."):
                        context_chunks = db_manager.search_pdfs_only(
                            query=query_text, k=6, fetch_k=20
                        )
                    if not context_chunks:
                        st.info(
                            "📄 No PDF or Excel documents found in the vector store. "
                            "Upload a financial document using the Knowledge Base panel."
                        )

                else:
                    # ── Branch 4: All Sources hybrid — full JIT pipeline ────────
                    with st.spinner("Fetching live market data & searching documents..."):
                        quant_chunks = data_fetcher.fetch_quantitative_metrics(selected_stock)
                        news_chunks  = data_fetcher.fetch_qualitative_news(selected_stock, query_text)
                        all_market_chunks = quant_chunks + news_chunks
                        if all_market_chunks:
                            db_manager.store_data(all_market_chunks)

                        doc_context_chunks, jit_context_chunks = db_manager.search_all(
                            query=query_text,
                            ticker=selected_stock,
                            doc_k=6,
                            market_k=3,
                            fetch_k=20,
                        )

                    # Guaranteed-slot merge — prevents either domain starving
                    DOC_SLOTS    = 4
                    MARKET_SLOTS = 2
                    TOTAL_CAP    = 6

                    final_doc_chunks    = doc_context_chunks[:DOC_SLOTS]
                    final_market_chunks = jit_context_chunks[:MARKET_SLOTS]

                    doc_used    = len(final_doc_chunks)
                    market_used = len(final_market_chunks)
                    spare       = TOTAL_CAP - (doc_used + market_used)

                    if spare > 0:
                        if doc_used < DOC_SLOTS:
                            extra_market = jit_context_chunks[MARKET_SLOTS : MARKET_SLOTS + spare]
                            final_market_chunks = final_market_chunks + extra_market
                        elif market_used < MARKET_SLOTS:
                            extra_doc = doc_context_chunks[DOC_SLOTS : DOC_SLOTS + spare]
                            final_doc_chunks = final_doc_chunks + extra_doc

                    context_chunks = (final_doc_chunks + final_market_chunks)[:TOTAL_CAP]

                formatted_chunks = []
                for i, chunk in enumerate(context_chunks, 1):
                    source_name    = chunk.get("metadata", {}).get("source", "Unknown")
                    chunk_text     = chunk.get("text_chunk", "")
                    formatted_chunk = f"**Chunk {i}** *(Source: {source_name})*: {chunk_text}"
                    formatted_chunks.append(formatted_chunk)

                with st.spinner("Synthesizing financial response..."):
                    response = llm_engine.generate_response(
                        user_query=query_text, context_chunks=formatted_chunks
                    )

                st.write(response)

                with st.expander("🔍 View Retrieved Context"):
                    if formatted_chunks:
                        for chunk in formatted_chunks:
                            st.markdown(chunk)
                    else:
                        st.info("No context chunks retrieved.")

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response,
                    "context": formatted_chunks
                })
                save_user_chat_history(user_email, st.session_state.messages)

            except Exception as e:
                # ── Orphan-prompt rollback ────────────────────────────────────
                # The user message was already appended above; if the pipeline
                # failed before an assistant reply was saved we must remove it
                # so the session never persists an unanswered prompt.
                if (
                    st.session_state.messages
                    and st.session_state.messages[-1]["role"] == "user"
                ):
                    st.session_state.messages.pop()

                error_msg = f"⚠️ Pipeline error: {e}"
                st.error(error_msg)
                # Do NOT append this technical error to the permanent history;
                # it is shown in the UI only so the user can retry cleanly.
                save_user_chat_history(user_email, st.session_state.messages)

    # =========================================================================
    # MAIN DASHBOARD UI
    # =========================================================================

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        "<h1 style='margin-bottom:0.1rem;'>📈 FinTemporal RAG</h1>",
        unsafe_allow_html=True
    )
    mode_badge = (
        "📺 YouTube"   if search_scope == _SCOPE_YT   else
        "📄 Docs Only" if search_scope == _SCOPE_DOCS else
        "🟢 Hybrid"
    )
    st.markdown(
        f"**Stock:** `{selected_stock}` &nbsp;|&nbsp; **Mode:** `{mode_badge}` &nbsp;|&nbsp; **Scope:** `{search_scope}`",
        unsafe_allow_html=True
    )

    # ── Document mismatch banner ───────────────────────────────────────────────
    _doc_company = st.session_state.get("detected_doc_company")
    _doc_tickers = st.session_state.get("detected_doc_tickers", [])
    if _doc_company and _doc_tickers:
        selected_bare = selected_stock.replace(".NS", "").replace(".BO", "").upper()
        known_bare    = [
            t.strip().replace(".NS", "").replace(".BO", "").upper()
            for t in _doc_tickers
        ]
        if selected_bare not in known_bare:
            ticker_display = ", ".join(_doc_tickers)
            st.warning(
                f"⚠️ **Document Mismatch:** The uploaded document belongs to "
                f"**{_doc_company}** ({ticker_display}), but the selected stock is "
                f"**{selected_stock}**. Analysis will proceed, but context may not align."
            )

    st.divider()

    # ── Suggested queries — collapsible, tabbed by category ───────────────────
    with st.expander("💡 Suggested Fundamental Analysis Queries", expanded=False):
        tab_val, tab_perf, tab_mkt, tab_gov = st.tabs(
            ["📐 Valuation", "📊 Performance", "🏭 Market", "🏛️ Governance"]
        )

        def _render_query_buttons(queries: list[str], tab_prefix: str):
            cols = st.columns(2)
            for i, q in enumerate(queries):
                with cols[i % 2]:
                    if st.button(q, key=f"btn_{tab_prefix}_{i}", use_container_width=True):
                        st.session_state.pending_query = {
                            "display": q,
                            "llm":     ENHANCED_QUERY_PROMPTS.get(q, q),
                        }

        with tab_val:
            _render_query_buttons(QUERY_TABS["valuation"], "val")
        with tab_perf:
            _render_query_buttons(QUERY_TABS["performance"], "perf")
        with tab_mkt:
            _render_query_buttons(QUERY_TABS["market"], "mkt")
        with tab_gov:
            _render_query_buttons(QUERY_TABS["governance"], "gov")

    st.divider()

    # ── Chat session ──────────────────────────────────────────────────────────

    # ── On-load sanitization: strip any trailing unanswered user prompt ───────
    # A dangling user message (no assistant reply directly after it) can survive
    # in JSON if a previous run crashed after appending but before saving the
    # assistant reply.  We purge it once here, at render time, before display.
    def _sanitize_messages(msgs: list) -> list:
        """
        Remove trailing user messages that have no immediately following
        assistant reply.  Only the very last message is ever dangling;
        mid-conversation gaps are legitimate (e.g. BYOD warning messages).
        """
        if msgs and msgs[-1].get("role") == "user":
            msgs = msgs[:-1]
        return msgs

    _clean = _sanitize_messages(list(st.session_state.messages))
    if len(_clean) != len(st.session_state.messages):
        st.session_state.messages = _clean
        save_user_chat_history(user_email, st.session_state.messages)

    # ── ChatGPT-style accent lines ────────────────────────────────────────────
    st.markdown("""
        <style>
        div[data-testid="stChatMessage"] {
            border-left: 3px solid #10a37f !important;
            padding-left: 16px !important;
            margin-bottom: 14px !important;
            background-color: rgba(247, 247, 248, 0.6) !important;
            border-radius: 0px 8px 8px 0px !important;
            transition: border-color 0.15s ease, background-color 0.15s ease !important;
        }
        div[data-testid="stChatMessage"]:has(
            [data-testid="stChatMessageAvatarUser"]
        ) {
            border-left: 3px solid #2b6cb0 !important;
            background-color: rgba(235, 244, 255, 0.45) !important;
        }
        div[data-testid="stChatMessage"]:has(
            [data-testid="stChatMessageAvatarAssistant"]
        ):hover {
            background-color: rgba(240, 253, 250, 0.7) !important;
            border-left-color: #0d8a6a !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # ── Chat history replay ───────────────────────────────────────────────────
    st.markdown("### 💬 Chat Session")

    # ── Floating Prompt Jump Menu ─────────────────────────────────────────────
    _user_prompts = [
        (i, msg["content"])
        for i, msg in enumerate(st.session_state.messages)
        if msg.get("role") == "user"
    ]

    # Only render the jump menu when there are ≥ 2 user prompts
    if len(_user_prompts) >= 2:
        _link_items = ""
        for _seq, (msg_idx, prompt_text) in enumerate(_user_prompts, start=1):
            _short = prompt_text[:52] + ("…" if len(prompt_text) > 52 else "")
            _link_items += (
                f"<li>"
                f"<a href='#prompt-anchor-{msg_idx}' class='pjm-link'>"
                f"<span class='pjm-num'>{_seq}</span>"
                f"<span class='pjm-text'>{_short}</span>"
                f"</a>"
                f"</li>"
            )

        st.markdown(f"""
            <style>
            /* ── Native smooth scrolling — no JS needed ─────────────────────── */
            html {{
                scroll-behavior: smooth !important;
            }}

            /* ── Outer fixed anchor ─────────────────────────────────────────── */
            .pjm-wrapper {{
                position: fixed;
                right: 18px;
                top: 130px;
                z-index: 9999;
                max-height: calc(100vh - 200px);
                display: flex;
                flex-direction: column;
                align-items: flex-end;
            }}

            /* ── Container: the hover trigger ──────────────────────────────── */
            .pjm-container {{
                position: relative;
                display: inline-flex;
                flex-direction: column;
                align-items: flex-end;
            }}

            /* ── Pill (always visible) ──────────────────────────────────────── */
            .pjm-pill {{
                display: flex;
                align-items: center;
                gap: 6px;
                background: rgba(255,255,255,0.85);
                backdrop-filter: blur(10px);
                -webkit-backdrop-filter: blur(10px);
                border: 1px solid rgba(59,130,246,0.24);
                border-radius: 20px;
                padding: 6px 13px 6px 10px;
                box-shadow: 0 2px 12px rgba(0,0,0,0.10);
                font-size: 0.74rem;
                font-weight: 600;
                color: #334155;
                letter-spacing: 0.02em;
                user-select: none;
                white-space: nowrap;
                cursor: default;
                transition: background 0.18s ease, box-shadow 0.18s ease,
                            color 0.18s ease, border-color 0.18s ease;
            }}
            .pjm-container:hover .pjm-pill {{
                background: rgba(235,244,255,0.97);
                box-shadow: 0 4px 20px rgba(59,130,246,0.20);
                color: #1e40af;
                border-color: rgba(59,130,246,0.45);
            }}
            .pjm-pill-icon {{
                font-size: 0.88rem;
                line-height: 1;
            }}

            /* ── Popover card — hidden by default, shown on parent hover ────── */
            .pjm-popover {{
                visibility: hidden;
                opacity: 0;
                pointer-events: none;
                position: absolute;
                right: 0;
                top: calc(100% + 8px);
                width: 310px;
                max-height: 420px;
                overflow-y: auto;
                background: rgba(255,255,255,0.96);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                border: 1px solid rgba(59,130,246,0.18);
                border-radius: 14px;
                box-shadow: 0 10px 36px rgba(0,0,0,0.13);
                padding: 10px 6px 12px 10px;
                scrollbar-width: thin;
                scrollbar-color: rgba(59,130,246,0.22) transparent;
                transition: opacity 0.20s ease-in-out,
                            visibility 0.20s ease-in-out,
                            transform 0.20s ease-in-out;
                transform: translateY(-6px);
            }}
            .pjm-container:hover .pjm-popover {{
                visibility: visible;
                opacity: 1;
                pointer-events: auto;
                transform: translateY(0);
            }}
            .pjm-popover::-webkit-scrollbar {{
                width: 4px;
            }}
            .pjm-popover::-webkit-scrollbar-thumb {{
                background: rgba(59,130,246,0.28);
                border-radius: 4px;
            }}

            /* Popover header label */
            .pjm-header {{
                font-size: 0.67rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                color: #64748b;
                text-transform: uppercase;
                padding: 0 6px 8px 4px;
                border-bottom: 1px solid rgba(0,0,0,0.07);
                margin-bottom: 6px;
            }}

            /* Link list */
            .pjm-popover ul {{
                list-style: none;
                margin: 0;
                padding: 0;
            }}
            .pjm-popover ul li {{
                margin-bottom: 1px;
            }}
            a.pjm-link {{
                display: flex;
                align-items: flex-start;
                gap: 8px;
                padding: 6px 8px;
                border-radius: 8px;
                text-decoration: none !important;
                color: #334155;
                font-size: 0.78rem;
                line-height: 1.4;
                transition: background 0.13s ease, color 0.13s ease;
            }}
            a.pjm-link:hover {{
                background: rgba(219,234,254,0.65);
                color: #1e40af;
            }}
            .pjm-num {{
                flex-shrink: 0;
                font-size: 0.68rem;
                font-weight: 700;
                color: #94a3b8;
                min-width: 16px;
                padding-top: 1px;
            }}
            .pjm-text {{
                flex: 1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            </style>

            <!-- Floating prompt jump menu — pure CSS, zero JavaScript -->
            <div class="pjm-wrapper">
              <div class="pjm-container">
                <div class="pjm-pill" title="Hover to browse prompts">
                  <span class="pjm-pill-icon">&#x1F5C2;&#xFE0F;</span>
                  <span>{len(_user_prompts)} prompts</span>
                </div>
                <div class="pjm-popover">
                  <div class="pjm-header">&#x2195; Jump to prompt</div>
                  <ul>
                    {_link_items}
                  </ul>
                </div>
              </div>
            </div>
        """, unsafe_allow_html=True)

    # ── Message replay with per-message anchors ───────────────────────────────
    for i, msg in enumerate(st.session_state.messages):
        # Inject a zero-height anchor div before every message so the jump
        # menu can scroll directly to it.  The anchor id matches the index
        # used when building the _user_prompts list above.
        st.markdown(
            f"<div id='prompt-anchor-{i}' "
            f"style='position:relative; top:-80px; visibility:hidden; "
            f"pointer-events:none; height:0; overflow:hidden;'></div>",
            unsafe_allow_html=True,
        )
        avatar = "🧑‍💼" if msg["role"] == "user" else "🏛️"
        with st.chat_message(msg["role"], avatar=avatar):
            st.write(msg["content"])
            if msg["role"] == "assistant" and msg.get("context"):
                with st.expander("🔍 View Retrieved Context"):
                    for chunk in msg["context"]:
                        st.markdown(chunk)

    # ── Chat input (INSIDE render_dashboard — never shown to unauthenticated users)
    custom_query = st.chat_input("Ask any question about the selected stock…")
    if custom_query:
        # Custom free-text queries are sent to the LLM verbatim — no augmentation.
        st.session_state.pending_query = {"display": custom_query, "llm": custom_query}

    # Execute the pending query at the very bottom to avoid duplicate UI rendering.
    # pending_query is set by either the chat input above or a suggested-query button.
    if st.session_state.get("pending_query"):
        pending = st.session_state.pending_query
        st.session_state.pending_query = None   # clear immediately to prevent re-run loop
        if isinstance(pending, dict):
            process_user_query(query_text=pending["llm"], display_text=pending["display"])
        else:
            process_user_query(query_text=pending)


# ===========================================================================
# ROUTER — sole entry point
# ===========================================================================
st.warning(
    "⚠️ **This Streamlit UI is deprecated.** FinTemporal RAG now runs on "
    "Next.js + FastAPI (see README.md) — this page is kept only as a "
    "fallback during the migration's verification window.",
    icon="⚠️",
)

if not st.session_state.get("user_email"):
    render_landing_page()
else:
    render_dashboard()
