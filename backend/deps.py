"""
Resource caching for the FastAPI layer — the direct equivalent of app.py's
``@st.cache_resource`` decorators. FastAPI has no built-in per-process resource
cache, so we hold simple module-level singletons/dicts instead. Same lifetime
semantics as Streamlit: one FinRAGGenerator and one FinancialDataFetcher for
the whole process, one ChromaDBManager per authenticated user email.
"""
from utils.data_ingestion import FinancialDataFetcher
from utils.llm_engine import FinRAGGenerator
from utils.vector_store import ChromaDBManager

_llm_engine: FinRAGGenerator | None = None
_data_fetcher: FinancialDataFetcher | None = None
_db_managers: dict[str, ChromaDBManager] = {}


def get_llm_engine() -> FinRAGGenerator:
    global _llm_engine
    if _llm_engine is None:
        _llm_engine = FinRAGGenerator()
    return _llm_engine


def get_data_fetcher() -> FinancialDataFetcher:
    global _data_fetcher
    if _data_fetcher is None:
        _data_fetcher = FinancialDataFetcher()
    return _data_fetcher


def get_db_manager(user_email: str) -> ChromaDBManager:
    if user_email not in _db_managers:
        _db_managers[user_email] = ChromaDBManager(user_email=user_email)
    return _db_managers[user_email]
