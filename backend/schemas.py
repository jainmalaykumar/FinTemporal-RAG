"""Pydantic request/response models for the FastAPI layer.

These are pure transport shapes — no business logic lives here. Every field
mirrors a value that already existed in app.py's Streamlit session_state.
"""
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str
    context: list[str] | None = None
    data_freshness: str | None = None


class UserScopedRequest(BaseModel):
    user_email: str


class NewSessionRequest(UserScopedRequest):
    pass


class ActiveSessionRequest(UserScopedRequest):
    pass


class ClearDataRequest(UserScopedRequest):
    session_id: str


class StockSwitchRequest(UserScopedRequest):
    session_id: str
    messages: list[ChatMessage]
    new_stock: str
    old_stock: str | None = None


class YoutubeIngestRequest(UserScopedRequest):
    url: str
    active_company: str


class QueryRequest(UserScopedRequest):
    session_id: str
    query_text: str
    display_text: str | None = None
    search_scope: str  # "all" | "youtube" | "docs"
    selected_stock: str


class QueryResponse(BaseModel):
    response: str
    context: list[str]
    messages: list[ChatMessage]
