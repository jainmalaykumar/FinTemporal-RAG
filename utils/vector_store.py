import os
import shutil
import logging
import chromadb
from collections import defaultdict, deque
from datetime import datetime
from chromadb.utils import embedding_functions

from utils.stock_list import tickers_match


# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _parse_date_published(value) -> "datetime | None":
    """
    Parses a JIT chunk's Date_Published metadata value, which may be either
    the old date-only format ("2026-08-17", from data stored before this
    fix) or the new full-datetime format ("2026-08-17 14:32:05"). Returns
    None if unparseable so callers can fall back gracefully.
    """
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def balance_chunks_by_source_and_year(scored_docs: list, max_k: int = 6) -> list:
    """
    In-memory source/year-balanced selection via Round-Robin.

    Groups the scored candidate pool by unique source document (falling back to
    year, then 'unknown') and interleaves one chunk at a time from each group
    until max_k slots are filled. This prevents a newer document from monopolising
    all top-k positions when multiple files span different financial years.

    Args:
        scored_docs: List of (adjusted_score, doc_text, metadata) tuples,
                     already sorted descending by adjusted_score so each group's
                     internal order is relevance-first.
        max_k:       Total number of balanced chunks to return.

    Returns:
        List of (adjusted_score, doc_text, metadata) tuples, balanced across
        sources and re-sorted by adjusted_score for final presentation order.
    """
    if not scored_docs:
        return []

    # ── Group by source filename (most specific) → year → 'unknown' ──────────
    grouped: dict[str, deque] = defaultdict(deque)
    for item in scored_docs:
        score, doc, meta = item
        group_key = meta.get("source") or str(meta.get("year", "unknown"))
        grouped[group_key].append(item)

    balanced: list = []
    keys = list(grouped.keys())

    # ── Round-robin: 1 chunk from each group in turn ──────────────────────────
    while len(balanced) < max_k and any(grouped[k] for k in keys):
        for key in keys:
            if grouped[key] and len(balanced) < max_k:
                balanced.append(grouped[key].popleft())

    # Re-sort final selection by adjusted_score (descending) so the LLM sees
    # the most relevant chunks first regardless of which file they came from.
    balanced.sort(key=lambda x: x[0], reverse=True)
    return balanced


class ChromaDBManager:
    def __init__(self, user_email: str, persist_directory: str = None):
        # ── Per-user collection naming ────────────────────────────────────────
        # Sanitize the email so it forms a valid ChromaDB collection name.
        # ChromaDB requires: 3-63 chars, alphanumeric / underscores / hyphens,
        # starting and ending with alphanumeric.
        safe_email = user_email.replace("@", "_at_").replace(".", "_")
        self.doc_collection_name    = f"docs_{safe_email}"
        self.market_collection_name = f"market_{safe_email}"

        self.persist_directory = persist_directory or os.getenv("CHROMA_DB_DIR", "./data/chroma_db")

        # Ensure the directory exists
        os.makedirs(self.persist_directory, exist_ok=True)

        try:
            # Initialize Persistent ChromaDB Client
            self.client = chromadb.PersistentClient(path=self.persist_directory)

            # Single embedding function used for BOTH collections.
            # Attaching it to each collection is the single source of truth —
            # ChromaDB embeds all documents and queries using the same model,
            # eliminating the embedding-mismatch / uniform-distance bug.
            self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

            # ── Collection 1: Live JIT market data (news, metrics) ──────────
            # Namespaced per user; filtered by Ticker_Symbol on retrieval.
            self.market_collection = self.client.get_or_create_collection(
                name=self.market_collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )

            # ── Collection 2: User-uploaded documents (PDFs, TXTs) ──────────
            # Namespaced per user; kept permanently separate so JIT upserts
            # NEVER touch this collection.
            self.document_collection = self.client.get_or_create_collection(
                name=self.doc_collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )

            logging.info(
                f"ChromaDBManager initialized for '{user_email}' "
                f"(collections: '{self.doc_collection_name}', "
                f"'{self.market_collection_name}')."
            )
        except Exception as e:
            logging.error(f"Failed to initialize ChromaDBManager: {e}")
            raise

    # ──────────────────────────────────────────────────────────────────────────
    # STORAGE
    # ──────────────────────────────────────────────────────────────────────────

    def store_data(self, chunks: list):
        """
        Routes chunks to the correct collection based on Document_Type:
          • 'uploaded_document'  → document_collection  (permanent, UUID IDs)
          • 'news' / 'metrics'  → market_collection     (JIT, date-stamped IDs)

        store_data() NEVER calls delete() or drop_collection().
        upsert() only overwrites a document if its ID already exists —
        uploaded docs use UUIDs so they are never overwritten by JIT upserts.
        """
        if not chunks:
            logging.warning("No data provided to store_data.")
            return

        doc_documents, doc_metadatas, doc_ids = [], [], []
        mkt_documents, mkt_metadatas, mkt_ids = [], [], []

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        for index, chunk in enumerate(chunks):
            text = chunk.get('text_chunk')
            meta = chunk.get('metadata')

            if not text or not meta:
                logging.warning("Skipping malformed chunk — must contain 'text_chunk' and 'metadata'.")
                continue

            doc_type = meta.get('Document_Type', 'unknown')

            if doc_type == 'uploaded_document':
                # UUID pre-assigned by doc_processor — never collides with JIT IDs
                chunk_id = chunk.get('id') or f"doc_{index}_{timestamp}"
                doc_documents.append(text)
                doc_metadatas.append(meta)
                doc_ids.append(chunk_id)
            else:
                # Date-stamped ID: re-running the same query on the same day
                # overwrites the stale JIT chunk (intentional deduplication).
                # Running on different days creates a NEW entry, preserving history.
                ticker = meta.get('Ticker_Symbol', 'UNKNOWN')
                date_stamp = datetime.now().strftime("%Y%m%d")
                chunk_id = f"{ticker}_{doc_type}_{date_stamp}_{index}"
                mkt_documents.append(text)
                mkt_metadatas.append(meta)
                mkt_ids.append(chunk_id)

        try:
            if doc_documents:
                self.document_collection.upsert(
                    documents=doc_documents,
                    metadatas=doc_metadatas,
                    ids=doc_ids
                )
                logging.info(
                    f"[DOCS] Successfully stored {len(doc_documents)} document chunks "
                    f"in 'uploaded_documents' collection."
                )

            if mkt_documents:
                self.market_collection.upsert(
                    documents=mkt_documents,
                    metadatas=mkt_metadatas,
                    ids=mkt_ids
                )
                logging.info(
                    f"[MARKET] Successfully stored {len(mkt_documents)} market chunks "
                    f"in 'market_data' collection."
                )
        except Exception as e:
            logging.error(f"Error storing data in ChromaDB: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # RETRIEVAL
    # ──────────────────────────────────────────────────────────────────────────

    def search(self, query: str, ticker: str, k: int = 5, fetch_k: int = 20) -> list:
        """
        Searches the market_data collection, strictly filtered by Ticker_Symbol.
        Applies time-weighted re-ranking and returns top k results.
        Used for JIT news/metrics retrieval.
        """
        if not query or not ticker:
            logging.warning("Query or ticker is missing for market search.")
            return []

        try:
            count = self.market_collection.count()
            if count == 0:
                logging.warning("market_data collection is empty.")
                return []

            # Clamp fetch_k to available document count to avoid ChromaDB error
            actual_fetch_k = min(fetch_k, count)

            results = self.market_collection.query(
                query_texts=[query],
                n_results=actual_fetch_k,
                where={"Ticker_Symbol": ticker},
                include=["documents", "metadatas", "distances"]
            )

            if not results or not results.get('documents') or len(results['documents'][0]) == 0:
                return []

            docs = results['documents'][0]
            metadatas = results['metadatas'][0]
            distances = results['distances'][0]

            print(f"[DEBUG SEARCH market]: Top 3 raw distances → {[round(d, 6) for d in distances[:3]]}")

            return self._time_weighted_rerank(docs, metadatas, distances, k)

        except Exception as e:
            logging.error(f"Error during market search: {e}")
            return []

    def search_documents(self, query: str, k: int = 6, fetch_k: int = 20, target_ticker: "str | None" = None) -> list:
        """
        Searches the uploaded_documents collection. ChromaDB itself applies no
        Ticker_Symbol filter here (document chunks don't carry that field —
        see detected_tickers instead), so company scoping happens in the
        reranker: when target_ticker is given, chunks confidently about a
        different company are strongly demoted rather than competing purely
        on semantic similarity. Retrieves fetch_k=20 candidates, applies
        time-decay + company-match scoring across ALL of them in-memory, then
        calls balance_chunks_by_source_and_year() to ensure equal
        representation from every uploaded file / financial year before
        slicing to k. This prevents newer documents from monopolising the context.
        """
        if not query:
            logging.warning("Query is missing for document search.")
            return []

        try:
            count = self.document_collection.count()
            if count == 0:
                logging.info("No uploaded documents in vector store yet.")
                return []

            # Fetch the wider candidate pool in a single DB call
            actual_fetch_k = min(fetch_k, count)

            results = self.document_collection.query(
                query_texts=[query],
                n_results=actual_fetch_k,
                include=["documents", "metadatas", "distances"]
            )

            if not results or not results.get('documents') or len(results['documents'][0]) == 0:
                return []

            docs = results['documents'][0]
            metadatas = results['metadatas'][0]
            distances = results['distances'][0]

            print(
                f"[DEBUG SEARCH docs]: Top 5 raw distances → "
                f"{[round(d, 6) for d in distances[:5]]}"
            )

            # Score ALL fetch_k candidates (returns raw tuples, not final dicts)
            all_scored = self._time_weighted_rerank(
                docs, metadatas, distances, k=actual_fetch_k, return_scored=True,
                target_ticker=target_ticker,
            )

            # Balance across sources/years, then take top k
            balanced = balance_chunks_by_source_and_year(all_scored, max_k=k)

            # Debug: verify which sources made the final cut
            selected_sources = [meta.get('source') for _, _, meta in balanced]
            print(
                f"[DEBUG BALANCER]: Selected {len(balanced)} chunks across "
                f"sources: {set(selected_sources)}"
            )

            if balanced:
                print(
                    f"[DEBUG RERANK]: Top chunk year={balanced[0][2].get('year')} | "
                    f"adjusted_score={balanced[0][0]:.6f}"
                )

            return [{'text_chunk': doc, 'metadata': meta} for _, doc, meta in balanced]

        except Exception as e:
            logging.error(f"Error during document search: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # SHARED RE-RANKING LOGIC
    # ──────────────────────────────────────────────────────────────────────────

    def _time_weighted_rerank(
        self,
        docs: list,
        metadatas: list,
        distances: list,
        k: int,
        return_scored: bool = False,
        target_ticker: "str | None" = None,
    ):
        """
        Scores each (doc, meta, distance) triple with time-decay weighting
        and, when target_ticker is given, a company-match adjustment.

        Chroma cosine space: distance ∈ [0, 2], lower = more similar.
        base_score = 1.0 - distance  →  similarity in [-1, 1].

        Recency:
            JIT chunks (market/news) carry a full Date_Published timestamp —
            age is computed in days (converted to fractional years) for
            day-level precision, since market data can go stale within days,
            not just years. Uploaded-document chunks only carry a
            whole-number `year` — age is computed in whole years, as before.
            A chunk with neither signal is treated as current (no penalty),
            matching the original behavior. Both paths share the same
            20%-per-year compound decay curve so the two scales stay
            consistent with each other.

        Company match (only meaningful when target_ticker is given — market
        search already hard-filters by Ticker_Symbol via a `where` clause
        before this ever runs, so this only affects search_documents /
        search_youtube_only / search_pdfs_only, which have no such filter):
            - No detected company on the chunk → neutral. Detection only
              scans part of a document/transcript, so plenty of legitimate
              chunks won't have this metadata — they shouldn't be punished
              for it.
            - Detected company matches target → boosted.
            - Detected company confidently does NOT match target → strongly
              demoted. This is the actual fix for cross-company bleed in
              document/YouTube retrieval (previously unfiltered by company
              at all). The match itself is thorough, not lenient — see
              stock_list.tickers_match — so it still yields when detection
              is genuinely inconclusive rather than guessing wrong.

        Args:
            return_scored: When True, returns the full sorted list of
                           (adjusted_score, doc, meta) tuples so the caller
                           (e.g. search_documents) can run additional selection
                           logic (balancing) before slicing to k.
                           When False (default), returns the final top-k dicts.
        """
        scored_docs = []
        now = datetime.now()
        current_year = now.year

        for doc, meta, dist in zip(docs, metadatas, distances):
            base_score = 1.0 - dist

            # ── Recency ──────────────────────────────────────────────────
            date_published = meta.get('Date_Published')
            parsed_date = _parse_date_published(date_published) if date_published else None

            if parsed_date is not None:
                age_days = max(0.0, (now - parsed_date).total_seconds() / 86400)
                age_years = age_days / 365.0
            else:
                raw_year = meta.get('year')
                if raw_year is not None and str(raw_year).strip().isdigit():
                    age_years = max(0, current_year - int(raw_year))
                else:
                    age_years = 0  # unknown date -> treat as current, as before

            time_boost = 0.8 ** age_years  # 20% compound penalty per year of age

            # ── Company match ───────────────────────────────────────────
            company_boost = 1.0
            if target_ticker:
                detected = meta.get('detected_tickers') or meta.get('detected_company')
                if detected:
                    company_boost = 1.3 if tickers_match(detected, target_ticker) else 0.15

            adjusted_score = base_score * time_boost * company_boost
            scored_docs.append((adjusted_score, doc, meta))

        scored_docs.sort(key=lambda x: x[0], reverse=True)

        if return_scored:
            # Return ALL scored tuples; caller decides how to slice/balance
            return scored_docs

        # Default path: slice to top-k and return formatted dicts
        top = scored_docs[:k]
        if top:
            print(
                f"[DEBUG RERANK]: Top chunk year={top[0][2].get('year')} | "
                f"adjusted_score={top[0][0]:.6f}"
            )
        return [{'text_chunk': doc, 'metadata': meta} for _, doc, meta in top]

    def clear_market_collection(self):
        """
        Purges ALL documents from this user's market collection by deleting and
        immediately re-creating it with the same schema.  The document collection
        is never touched.
        Called automatically whenever the user switches the selected stock so
        that stale JIT news / metrics from the old ticker do not pollute the new
        ticker's retrieval context.
        """
        try:
            self.client.delete_collection(self.market_collection_name)
            self.market_collection = self.client.get_or_create_collection(
                name=self.market_collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )
            logging.info(
                f"[MARKET] '{self.market_collection_name}' cleared and "
                f"re-created for new stock."
            )
        except Exception as e:
            logging.error(f"Failed to clear market collection: {e}")

    def clear_all_data(self) -> bool:
        """
        Safely drops and re-creates both ChromaDB collections using the native
        client API, avoiding the SQLite lock / read-only errors (code 1032) that
        shutil.rmtree() causes when ChromaDB file connections are still open.

        Flow:
          1. Delete each collection individually inside its own try/except so a
             missing collection doesn't abort the whole operation.
          2. Re-create both empty collections on the same live client with the
             same embedding function and HNSW config.
          3. Re-point self.market_collection and self.document_collection so
             every subsequent call (search, store, count) uses the fresh handles.

        Returns True on success, False on any unexpected error.
        """
        try:
            # ── Step 1: Drop each collection independently ────────────────────
            for name in (self.market_collection_name, self.doc_collection_name):
                try:
                    self.client.delete_collection(name)
                    logging.info(f"[CLEAR ALL] Dropped collection '{name}'.")
                except Exception as drop_err:
                    # Collection may already be absent — not a fatal error
                    logging.warning(
                        f"[CLEAR ALL] Could not drop '{name}' (may not exist): {drop_err}"
                    )

            # ── Step 2: Re-create empty collections on the same live client ───
            self.market_collection = self.client.get_or_create_collection(
                name=self.market_collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )
            self.document_collection = self.client.get_or_create_collection(
                name=self.doc_collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )
            logging.info(
                f"[CLEAR ALL] Both collections ('{self.market_collection_name}', "
                f"'{self.doc_collection_name}') dropped and re-created successfully."
            )
            return True

        except Exception as e:
            logging.error(f"[CLEAR ALL] Failed to clear collections: {e}")
            return False

    def get_collection_counts(self) -> dict:
        """
        Returns current chunk counts for both collections.
        Each count is wrapped in its own try/except so a transiently stale
        collection handle (e.g. immediately after clear_all_data()) returns 0
        instead of raising NotFoundError and crashing the sidebar.
        """
        doc_count = 0
        market_count = 0

        try:
            if self.document_collection:
                doc_count = self.document_collection.count()
        except Exception as e:
            logging.warning(f"[COUNTS] document_collection.count() failed: {e}")

        try:
            if self.market_collection:
                market_count = self.market_collection.count()
        except Exception as e:
            logging.warning(f"[COUNTS] market_collection.count() failed: {e}")

        return {
            "uploaded_documents": doc_count,
            "market_data":        market_count,
        }

    def get_source_type_counts(self) -> dict:
        """
        Breaks down the document_collection by source_type metadata field:
          - "youtube_transcript"  → video transcript chunks
          - everything else       → uploaded PDF / TXT / Excel chunks

        Uses ChromaDB get() with where filters so counts are always
        authoritative (not estimated from embeddings).  Falls back to 0
        on any collection error so the diagnostics panel never crashes.

        Returns
        -------
        dict with keys:
          "youtube_chunks"   : int  — chunks whose source_type == "youtube_transcript"
          "document_chunks"  : int  — chunks whose source_type != "youtube_transcript"
          "market_chunks"    : int  — total chunks in the live JIT market collection
        """
        youtube_count  = 0
        document_count = 0
        market_count   = 0

        try:
            if self.document_collection and self.document_collection.count() > 0:
                yt_result = self.document_collection.get(
                    where={"source_type": "youtube_transcript"},
                    include=[],          # IDs only — fastest possible query
                )
                youtube_count = len(yt_result.get("ids", []))

                doc_result = self.document_collection.get(
                    where={"source_type": {"$ne": "youtube_transcript"}},
                    include=[],
                )
                document_count = len(doc_result.get("ids", []))
        except Exception as e:
            logging.warning("[SOURCE COUNTS] document_collection query failed: %s", e)

        try:
            if self.market_collection:
                market_count = self.market_collection.count()
        except Exception as e:
            logging.warning("[SOURCE COUNTS] market_collection.count() failed: %s", e)

        return {
            "youtube_chunks":  youtube_count,
            "document_chunks": document_count,
            "market_chunks":   market_count,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # NAMED RETRIEVAL ALIASES (used by BYOD routing in app.py)
    # Both methods apply the same time-decay reranker so temporal math is
    # identical regardless of which retrieval path is active.
    # ──────────────────────────────────────────────────────────────────────────

    def search_docs_only(self, query: str, k: int = 6, fetch_k: int = 20, target_ticker: "str | None" = None) -> list:
        """
        BYOD path: searches ONLY the uploaded_documents collection.
        Identical to search_documents() — no market data is fetched or queried.
        Time-decay + company-match + source/year balancing still apply so the
        temporal/company ranking is fully consistent with the hybrid path.
        """
        return self.search_documents(query=query, k=k, fetch_k=fetch_k, target_ticker=target_ticker)

    def search_youtube_only(self, query: str, k: int = 6, fetch_k: int = 20, target_ticker: "str | None" = None) -> list:
        """
        Scope-filtered path: retrieves ONLY chunks whose source_type metadata
        field equals 'youtube_transcript'. PDF/Excel document chunks are excluded.

        Uses a ChromaDB `where` filter on the document collection so the
        embedding search is both precise and efficient — no post-filter needed.
        Time-decay reranking still applies for temporal consistency.
        """
        if not query:
            logging.warning("Query is missing for YouTube-only search.")
            return []

        try:
            count = self.document_collection.count()
            if count == 0:
                logging.info("No documents in vector store yet (YouTube-only scope).")
                return []

            actual_fetch_k = min(fetch_k, count)

            results = self.document_collection.query(
                query_texts=[query],
                n_results=actual_fetch_k,
                where={"source_type": "youtube_transcript"},
                include=["documents", "metadatas", "distances"],
            )

            if not results or not results.get("documents") or len(results["documents"][0]) == 0:
                return []

            docs      = results["documents"][0]
            metadatas = results["metadatas"][0]
            distances = results["distances"][0]

            logging.info(
                "[SCOPE:YouTube] %d candidates returned from document_collection.",
                len(docs),
            )

            all_scored = self._time_weighted_rerank(
                docs, metadatas, distances, k=actual_fetch_k, return_scored=True,
                target_ticker=target_ticker,
            )
            balanced = balance_chunks_by_source_and_year(all_scored, max_k=k)
            return [{"text_chunk": doc, "metadata": meta} for _, doc, meta in balanced]

        except Exception as e:
            logging.error("Error during YouTube-only search: %s", e)
            return []

    def search_pdfs_only(self, query: str, k: int = 6, fetch_k: int = 20, target_ticker: "str | None" = None) -> list:
        """
        Scope-filtered path: retrieves ONLY chunks whose source_type is NOT
        'youtube_transcript' (i.e. PDF, TXT, Excel uploads).

        ChromaDB's `where` clause uses `$ne` (not-equal) so this stays
        collection-native — no Python-side filtering.
        Time-decay + source/year balancing still apply.
        """
        if not query:
            logging.warning("Query is missing for PDF-only search.")
            return []

        try:
            count = self.document_collection.count()
            if count == 0:
                logging.info("No documents in vector store yet (PDF-only scope).")
                return []

            actual_fetch_k = min(fetch_k, count)

            results = self.document_collection.query(
                query_texts=[query],
                n_results=actual_fetch_k,
                where={"source_type": {"$ne": "youtube_transcript"}},
                include=["documents", "metadatas", "distances"],
            )

            if not results or not results.get("documents") or len(results["documents"][0]) == 0:
                return []

            docs      = results["documents"][0]
            metadatas = results["metadatas"][0]
            distances = results["distances"][0]

            logging.info(
                "[SCOPE:Docs] %d candidates returned from document_collection.",
                len(docs),
            )

            all_scored = self._time_weighted_rerank(
                docs, metadatas, distances, k=actual_fetch_k, return_scored=True,
                target_ticker=target_ticker,
            )
            balanced = balance_chunks_by_source_and_year(all_scored, max_k=k)
            return [{"text_chunk": doc, "metadata": meta} for _, doc, meta in balanced]

        except Exception as e:
            logging.error("Error during PDF-only search: %s", e)
            return []

    def search_all(
        self,
        query: str,
        ticker: str,
        doc_k: int = 4,
        market_k: int = 2,
        fetch_k: int = 20,
    ) -> tuple[list, list]:
        """
        Hybrid path: searches BOTH collections independently and returns them
        as a (doc_chunks, market_chunks) tuple so the caller can apply the
        guaranteed-slot merge logic.

        Time-decay reranking is applied inside each constituent search call,
        so both domains are scored on the same temporal basis before merging.
        `ticker` scopes both: market search hard-filters by it (unchanged),
        document search uses it to demote chunks confidently about a
        different company.
        """
        doc_chunks    = self.search_documents(query=query, k=doc_k,    fetch_k=fetch_k, target_ticker=ticker)
        market_chunks = self.search(query=query, ticker=ticker, k=market_k, fetch_k=fetch_k)
        return doc_chunks, market_chunks


if __name__ == "__main__":
    print("\n--- Initializing ChromaDBManager ---")
    try:
        db_manager = ChromaDBManager(user_email="test_user@example.com")
        print("ChromaDBManager initialized successfully.")
        print(f"Collection counts: {db_manager.get_collection_counts()}")
    except Exception as e:
        print(f"Failed to initialize ChromaDBManager: {e}")