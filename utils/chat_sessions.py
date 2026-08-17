"""
MULTI-SESSION PERSISTENT CHAT HISTORY — per-user JSON files

Storage layout (one file per Google account):
  ./data/chat_histories/<safe_email>.json
  {
    "sessions": {
      "<uuid>": {"label": "...", "created": "ISO-8601", "messages": [...]},
      ...
    },
    "session_order": ["<uuid>", ...]   # newest first
  }

If the file contains a bare list (old single-session format) it is
migrated automatically into the new dict structure on first load.

Extracted verbatim from app.py (Streamlit) so both the FastAPI backend and
app.py share one source of truth — no behavior change, pure relocation.
"""
import json
import os
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

CHAT_HISTORY_DIR = "./data/chat_histories"
os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)


def _safe_email_key(user_email: str) -> str:
    return user_email.replace("@", "_at_").replace(".", "_")


def get_user_chat_file(user_email: str) -> str:
    """Absolute path to the multi-session store for this user."""
    return os.path.join(CHAT_HISTORY_DIR, f"{_safe_email_key(user_email)}.json")


def load_sessions_store(user_email: str) -> dict:
    """
    Returns the full sessions store dict:
      {"sessions": {...}, "session_order": [...]}
    Handles missing file, corruption, and old flat-list format transparently.
    """
    filepath = get_user_chat_file(user_email)
    if not os.path.exists(filepath):
        return {"sessions": {}, "session_order": []}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # --- Migrate old flat-list format ---
        if isinstance(raw, list):
            if raw:          # non-empty old history → wrap as a single session
                sid   = str(uuid.uuid4())
                label = _session_label_from_messages(raw)
                store = {
                    "sessions": {sid: {
                        "label":    label,
                        "created":  datetime.now().isoformat(),
                        "messages": raw,
                    }},
                    "session_order": [sid],
                }
            else:
                store = {"sessions": {}, "session_order": []}
            # Immediately write the migrated format so we never hit this branch again
            _write_store(filepath, store)
            return store
        # Validate expected keys
        if "sessions" in raw and "session_order" in raw:
            return raw
        return {"sessions": {}, "session_order": []}
    except Exception:
        return {"sessions": {}, "session_order": []}


def _write_store(filepath: str, store: dict) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)


def save_sessions_store(user_email: str, store: dict) -> None:
    """Persist the full sessions store to disk."""
    _write_store(get_user_chat_file(user_email), store)


def _session_label_from_messages(
    messages: list,
    stock: str | None = None,
    max_chars: int = 40,
) -> str:
    """
    Derive a human-readable label from the first user message in a session,
    prefixed with the stock ticker that was active when the conversation
    started (e.g. "RELIANCE.NS — What is the Debt-to-Equity ratio?") so the
    sidebar reads clearly once multiple stocks/sessions pile up.
    """
    for m in messages:
        if m.get("role") == "user":
            text = m.get("content", "").strip()
            question = text[:max_chars] + ("…" if len(text) > max_chars else "")
            return f"{stock} — {question}" if stock else question
    return "New Chat"


def create_new_session(user_email: str) -> str:
    """
    Creates a brand-new empty session, prepends it to session_order, saves,
    and returns the new session_id.
    """
    store = load_sessions_store(user_email)
    sid   = str(uuid.uuid4())
    now   = datetime.now().strftime("%d %b %Y, %H:%M")
    store["sessions"][sid] = {
        "label":    f"New Chat — {now}",
        "created":  datetime.now().isoformat(),
        "messages": [],
    }
    store["session_order"].insert(0, sid)   # newest first
    save_sessions_store(user_email, store)
    return sid


def save_session_messages(
    user_email: str,
    session_id: str,
    messages: list,
    stock: str | None = None,
) -> None:
    """
    Updates the message list for a specific session and refreshes its label
    from the first user message (so the sidebar title improves after the
    first reply). ``stock`` is optional so existing call sites (e.g. the
    legacy Streamlit app) keep working unchanged with the old label format.
    """
    store = load_sessions_store(user_email)
    if session_id not in store["sessions"]:
        return
    store["sessions"][session_id]["messages"] = messages
    store["sessions"][session_id]["label"]    = _session_label_from_messages(
        messages,
        stock=stock,
        max_chars=40,
    ) or store["sessions"][session_id]["label"]
    save_sessions_store(user_email, store)


def delete_session(user_email: str, session_id: str) -> str | None:
    """
    Removes the given session from the store.
    Returns the session_id of the next session to activate, or None if the
    store is now empty.
    """
    store = load_sessions_store(user_email)
    if session_id in store["sessions"]:
        del store["sessions"][session_id]
    if session_id in store["session_order"]:
        store["session_order"].remove(session_id)
    save_sessions_store(user_email, store)
    return store["session_order"][0] if store["session_order"] else None


def get_or_create_active_session(user_email: str) -> str:
    """
    "Check Before Create" — returns the session_id the UI should activate,
    guaranteeing at most ONE empty (0-message) session exists at any time.

    Algorithm
    ---------
    1. Load the full sessions store for *user_email*.
    2. Partition every session into two buckets:
         • empty_sessions  — sessions whose ``messages`` list has length 0
         • active_sessions — sessions with at least one message
    3. If one-or-more empty sessions exist:
         a. Keep the most-recently-created empty session (index 0 in
            ``session_order``, which is always newest-first).
         b. Delete every *other* empty session from the store (garbage
            collection — these are phantom sessions from previous page reloads).
         c. Return the kept session's id.
    4. If NO empty sessions exist (user's last session has messages):
         • Create a fresh empty session and return its id.

    This replaces the naive ``if _order: use _order[0] else create_new_session()``
    pattern, which created a new ghost UUID on every cold Streamlit reload even
    when an unused empty session was already sitting in the store.
    """
    store = load_sessions_store(user_email)
    sessions      = store.get("sessions", {})
    session_order = store.get("session_order", [])

    # ── Step 1: Partition into empty vs. active ──────────────────────────────
    empty_sids = [
        sid for sid in session_order
        if len(sessions.get(sid, {}).get("messages", [])) == 0
    ]
    # (active sessions are left untouched throughout)

    # ── Step 2: At least one empty session exists — reuse the newest ─────────
    if empty_sids:
        keeper = empty_sids[0]          # session_order is newest-first → [0] is most recent
        ghosts = empty_sids[1:]         # every other empty session is a phantom

        if ghosts:
            # Garbage-collect the phantoms in a single store mutation + one save
            for ghost_sid in ghosts:
                sessions.pop(ghost_sid, None)
                if ghost_sid in session_order:
                    session_order.remove(ghost_sid)

            store["sessions"]      = sessions
            store["session_order"] = session_order
            save_sessions_store(user_email, store)
            logger.info(
                "get_or_create_active_session: GC removed %d ghost session(s) for %r",
                len(ghosts),
                user_email,
            )

        logger.info(
            "get_or_create_active_session: reusing empty session %r for %r",
            keeper,
            user_email,
        )
        return keeper

    # ── Step 3: Every existing session has messages — create a fresh one ──────
    new_sid = create_new_session(user_email)
    logger.info(
        "get_or_create_active_session: created new session %r for %r",
        new_sid,
        user_email,
    )
    return new_sid
