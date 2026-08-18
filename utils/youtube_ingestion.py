"""
utils/youtube_ingestion.py
==========================
YouTube transcript ingestion with a two-stage LLM gatekeeper pipeline.

Stage 1 — Gatekeeper
    • Fetches the video transcript via youtube-transcript-api.
    • Sends the title + first 1 000 chars to Ollama and asks it to classify
      whether the video is strictly about stock-market / financial analysis.
    • Parses the response as structured JSON via a Pydantic model.
    • Raises VideoRejectedError if the classification is False.

Stage 2 — Entity & Temporal Extraction
    • Sends the full transcript to Ollama and extracts:
        - company_names     : list[str]  (tickers / company names discussed)
        - temporal_references: list[str]  (e.g. "Q1 2024", "FY25", "last week")
    • Parses the response as structured JSON via a Pydantic model.

Output
    • Returns a list of chunk dicts whose metadata schema is identical to the
      chunks produced by doc_processor.py and data_ingestion.py so they can be
      stored in ChromaDB with db_manager.store_data() without modification.

Dependencies (add to requirements.txt):
    youtube-transcript-api>=0.6.2
    pydantic>=2.0
    yt-dlp>=2024.1.1
    (langchain-community, langchain_core, ollama already present)
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from langchain_community.llms import Ollama
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ValidationError
from youtube_transcript_api import (
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
import yt_dlp

from utils.stock_list import tickers_match

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — mirrors llm_engine.py so both share the same Ollama instance
# ---------------------------------------------------------------------------
_OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "qwen7b:latest")
_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Characters fed to the gatekeeper prompt (keeps the prompt small & fast)
_GATEKEEPER_PREVIEW_CHARS = 1_000

# RecursiveCharacterTextSplitter-equivalent chunk sizing (matches doc_processor)
_CHUNK_SIZE    = 800
_CHUNK_OVERLAP = 80


# ===========================================================================
# Custom exceptions
# ===========================================================================

class VideoRejectedError(ValueError):
    """Raised when the LLM gatekeeper decides a video is not financial content."""


class TranscriptFetchError(RuntimeError):
    """Raised when the transcript cannot be retrieved from YouTube."""


# ===========================================================================
# Pydantic models — strictly enforce LLM JSON output shapes
# ===========================================================================

class GatekeeperResult(BaseModel):
    """
    Expected JSON from the domain-only Gatekeeper prompt.

    The Gatekeeper now evaluates a SINGLE dimension:
      - is_financial_content : True if the video is fundamentally about finance,
                               stock markets, corporate earnings, or macroeconomics.

    Entity / company relevance is handled downstream by deterministic Python
    logic so that small local LLMs are not asked to perform negative-constraint
    reasoning they reliably fail at.

    Example output:
    {
        "is_financial_content": true
    }
    """
    is_financial_content: bool


class ExtractionResult(BaseModel):
    """
    Expected JSON from the Entity & Temporal Extraction stage.
    Example:
    {
        "company_names": ["Reliance Industries", "TCS"],
        "temporal_references": ["Q1 FY25", "March 2024", "last quarter"]
    }
    """
    company_names: list[str]
    temporal_references: list[str]


# ===========================================================================
# Helper utilities
# ===========================================================================

def _extract_video_id(url: str) -> str:
    """
    Robustly extract the YouTube video ID from any common URL format:
      • https://www.youtube.com/watch?v=VIDEO_ID
      • https://youtu.be/VIDEO_ID
      • https://www.youtube.com/embed/VIDEO_ID
      • https://www.youtube.com/shorts/VIDEO_ID
    """
    parsed = urlparse(url)

    # youtu.be short links
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return vid

    # Standard watch, embed, shorts paths
    qs = parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]

    # /embed/<id> or /shorts/<id>
    path_match = re.search(
        r"/(?:embed|shorts|v)/([A-Za-z0-9_-]{11})", parsed.path
    )
    if path_match:
        return path_match.group(1)

    raise ValueError(
        f"Could not extract a valid YouTube video ID from URL: {url!r}"
    )


def _fetch_video_metadata(video_id: str) -> dict:
    """
    Fetch exact video metadata (title, upload_date) using yt-dlp.

    yt-dlp exposes the true historical ``upload_date`` field (YYYYMMDD)
    which oEmbed never provides.  Accurate upload dates are critical for
    the temporal re-ranking layer in ChromaDB: a wrong date (e.g. "today")
    would make a 2-year-old earnings call appear as fresh live data.

    Fallback: if yt-dlp fails for any reason (network, private video, bot
    detection) the function logs a warning and returns safe placeholder
    values so the rest of the pipeline can still run with degraded accuracy
    rather than crashing entirely.
    """
    ydl_opts = {
        "skip_download":    True,     # never touch the video file
        "quiet":            True,     # suppress all yt-dlp console output
        "no_warnings":      True,
        "extract_flat":     False,    # we need the full info dict
        "socket_timeout":   12,       # seconds; prevents hanging on slow DNS
    }

    video_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

        # ── Title ─────────────────────────────────────────────────────────
        title = info.get("title") or f"YouTube Video {video_id}"

        # ── Channel / Uploader ─────────────────────────────────────────────
        # Prefer the human-readable channel name; fall back to uploader field
        # (which yt-dlp always populates even for personal accounts).
        channel = (
            info.get("channel")
            or info.get("uploader")
            or "Unknown Channel"
        )

        # ── Upload date ────────────────────────────────────────────────────
        # yt-dlp returns upload_date as a compact string "YYYYMMDD".
        # We reformat it to ISO-8601 "YYYY-MM-DD" to match the rest of the
        # metadata schema used throughout this codebase.
        raw_date = info.get("upload_date")   # e.g. "20240315"
        if raw_date and len(raw_date) == 8 and raw_date.isdigit():
            publish_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        else:
            # Graceful degradation: log clearly so the operator can investigate
            logger.warning(
                "yt-dlp did not return a valid upload_date for %s "
                "(got %r). Falling back to today's date — temporal "
                "ranking for this video may be inaccurate.",
                video_id,
                raw_date,
            )
            publish_date = datetime.now().strftime("%Y-%m-%d")

        logger.info(
            "yt-dlp metadata fetched: title=%r, channel=%r, "
            "upload_date=%r → publish_date=%r",
            title,
            channel,
            raw_date,
            publish_date,
        )
        return {"title": title, "channel": channel, "publish_date": publish_date}

    except Exception as exc:
        logger.warning(
            "yt-dlp metadata extraction failed for video %r (%s). "
            "Pipeline will continue with placeholder metadata.",
            video_id,
            exc,
        )
        return {
            "title":        f"YouTube Video {video_id}",
            "channel":      "Unknown Channel",
            "publish_date": datetime.now().strftime("%Y-%m-%d"),
        }


def _fetch_transcript(video_id: str, preferred_languages: list[str] | None = None) -> str:
    """
    Fetch and concatenate the full transcript text for a YouTube video.

    Strategy (most-reliable → least-reliable):
      1. Enumerate ALL available transcripts via the v1.2+ instance API:
         ``YouTubeTranscriptApi().list(video_id)``.
      2. Prefer any *manual* transcript whose language code starts with 'en'.
      3. Fall back to any *auto-generated* transcript whose language code
         starts with 'en' (covers en-US, en-GB, en-IN, en-orig, etc.).
      4. If nothing English exists at all, raise TranscriptFetchError with a
         clear message so the caller can surface it to the user.

    Returns the concatenated plain-text string, identical in shape to the
    previous implementation so the rest of the pipeline is unaffected.
    """
    ytt_api = YouTubeTranscriptApi()
    try:
        all_transcripts = ytt_api.list(video_id)
    except TranscriptsDisabled as exc:
        raise TranscriptFetchError(
            f"Transcripts are disabled for video {video_id!r}."
        ) from exc
    except Exception as exc:
        raise TranscriptFetchError(
            f"Could not retrieve transcript list for video {video_id!r}: {exc}"
        ) from exc

    # ── Pass 1: scan for manual and auto-generated English tracks ─────────
    manual_en: object | None = None
    auto_en:   object | None = None

    for t in all_transcripts:
        lang = (t.language_code or "").lower()
        if not lang.startswith("en"):
            continue
        if not t.is_generated:
            if manual_en is None:           # keep the first manual hit
                manual_en = t
        else:
            if auto_en is None:             # keep the first auto-generated hit
                auto_en = t

    chosen = manual_en or auto_en          # manual takes priority

    if chosen is None:
        available = ", ".join(
            f"{t.language_code}({'auto' if t.is_generated else 'manual'})"
            for t in all_transcripts
        ) or "none"
        raise TranscriptFetchError(
            f"No English transcript found for video {video_id!r}. "
            f"Available tracks: [{available}]. "
            "Consider adding an English caption track or using a different video."
        )

    track_type = "auto-generated" if chosen.is_generated else "manual"
    logger.info(
        "Using %s transcript '%s' for video %s.",
        track_type,
        chosen.language_code,
        video_id,
    )

    try:
        transcript_list = chosen.fetch()
    except Exception as exc:
        raise TranscriptFetchError(
            f"Failed to fetch {track_type} transcript "
            f"'{chosen.language_code}' for video {video_id!r}: {exc}"
        ) from exc

    # FetchedTranscript is iterable over FetchedTranscriptSnippet dataclass
    # objects — use .text attribute, NOT .get() which belongs to dicts.
    full_text = " ".join(
        snippet.text for snippet in transcript_list
    ).strip()

    if not full_text:
        raise TranscriptFetchError(
            f"Transcript was fetched but contained no text for video {video_id!r}."
        )

    logger.info(
        "Transcript fetched: %d characters, ~%d words.",
        len(full_text),
        len(full_text.split()),
    )
    return full_text


def _parse_llm_json(raw: str, model: type[BaseModel]) -> BaseModel:
    """
    Extract and validate a JSON object from a raw LLM string response.

    The LLM sometimes wraps JSON in markdown fences (```json ... ```).
    This helper strips fences, extracts the first `{...}` block, then
    validates it against the supplied Pydantic model.

    Raises:
        ValueError: If no valid JSON matching the model can be extracted.
    """
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip()

    # Find the first {...} block (greedy — handles nested objects)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(
            f"No JSON object found in LLM response.\nRaw response:\n{raw[:500]}"
        )

    try:
        parsed_dict = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned malformed JSON: {exc}\nExtracted text:\n{match.group()[:500]}"
        ) from exc

    try:
        return model(**parsed_dict)
    except ValidationError as exc:
        raise ValueError(
            f"LLM JSON does not match expected schema {model.__name__}: {exc}"
        ) from exc


# ===========================================================================
# LLM prompts
# ===========================================================================

# Gatekeeper prompt — DOMAIN VALIDATION ONLY.
# Entity / company relevance is checked deterministically in Python after the
# Extraction stage, so we no longer ask the LLM to reason about company names.
_GATEKEEPER_SYSTEM_PROMPT = """You are an enterprise AI gatekeeper for a financial \
Retrieval-Augmented Generation (RAG) system. Your objective is to validate incoming \
YouTube transcripts before they are ingested into a ChromaDB vector database.

You must evaluate the transcript based on ONE dimension only:
DOMAIN VALIDATION: Is the content fundamentally about finance, stock markets, \
corporate earnings, or macroeconomics?

You must output your evaluation STRICTLY as a JSON object matching the following schema. \
Do not output any conversational text, explanations outside the JSON, or markdown \
formatting blocks (like ```json).

{
  "is_financial_content": boolean
}

Set is_financial_content to false if the video is about general lifestyle, personal \
finance advice only, crypto without stock-market context, sports, entertainment, \
or any topic that does not directly concern listed equities or macro-finance."""

_GATEKEEPER_USER_PROMPT = PromptTemplate(
    input_variables=["transcript"],
    template="""<transcript>
{transcript}
</transcript>

Evaluate the transcript and provide the JSON output.""",
)

_EXTRACTION_PROMPT = PromptTemplate(
    input_variables=["transcript"],
    template="""You are a financial entity extractor.

Read the transcript below and extract:
1. company_names  : A list of company names or stock tickers explicitly discussed.
                    Include NSE/BSE tickers if mentioned (e.g. "RELIANCE.NS", "TCS").
                    Maximum 10 items. If none, return an empty list.
2. temporal_references: A list of all time-period references found in the transcript.
                    Examples: "Q1 FY25", "March 2024", "last quarter", "H1 2025",
                    "fiscal year 2024", "YTD", "TTM". Maximum 20 items.

TRANSCRIPT:
{transcript}

--- INSTRUCTIONS ---
Respond with ONLY a valid JSON object — no explanation, no markdown, no extra text.
Schema:
{{
  "company_names": ["<name or ticker>", ...],
  "temporal_references": ["<time reference>", ...]
}}
""",
)


# ===========================================================================
# Core pipeline class
# ===========================================================================

class YouTubeIngestionPipeline:
    """
    End-to-end pipeline:
        URL → transcript → gatekeeper → extraction → chunk list

    The returned chunks are directly compatible with ChromaDBManager.store_data()
    and share the same metadata schema as doc_processor.py chunks.

    Usage
    -----
    >>> pipeline = YouTubeIngestionPipeline()
    >>> chunks = pipeline.ingest("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    # VideoRejectedError raised if not financial content
    """

    def __init__(
        self,
        ollama_model: str | None = None,
        ollama_base_url: str | None = None,
        temperature: float = 0.05,
    ) -> None:
        self.model_name  = ollama_model    or _OLLAMA_MODEL
        self.base_url    = ollama_base_url or _OLLAMA_BASE_URL
        self.temperature = temperature

        try:
            self.llm = Ollama(
                model=self.model_name,
                base_url=self.base_url,
                temperature=self.temperature,
            )
            logger.info(
                "YouTubeIngestionPipeline initialised — model=%s, url=%s",
                self.model_name,
                self.base_url,
            )
        except Exception as exc:
            logger.error("Failed to initialise Ollama LLM: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(
        self,
        youtube_url: str,
        preferred_languages: list[str] | None = None,
        skip_gatekeeper: bool = False,
        active_company: str | None = None,
        on_progress: "Callable[[str], None] | None" = None,
    ) -> dict:
        """
        Full ingestion pipeline for a single YouTube URL.

        Parameters
        ----------
        youtube_url : str
            Any standard YouTube URL.
        preferred_languages : list[str] | None
            Transcript language preference order (default: English variants).
        skip_gatekeeper : bool
            Set True to bypass Stage 1 (useful for testing / trusted sources).
        active_company : str | None
            Ticker or company name currently selected in the dashboard UI.
            When provided, a deterministic Python check compares it against the
            company names extracted by the Extraction LLM.  A mismatch is a
            soft accept: chunks are stored and ``warning`` is set in the result.
        on_progress : Callable[[str], None] | None
            Optional callback invoked with a short human-readable stage label
            each time the pipeline moves to a new step (e.g. for a UI to show
            live progress during the ~60-90s this can take). Purely additive —
            omitting it changes nothing about how ingest() behaves.

        Returns
        -------
        dict with keys:
            ``success``    : bool  — always True (hard failures raise instead).
            ``chunks``     : int   — number of chunks produced.
            ``chunk_list`` : list[dict] — raw chunks for ChromaDBManager.store_data().
            ``warning``    : str | None — entity mismatch reason, or None.
            ``metadata``   : dict — video metadata (title, channel, publish_date).

        Raises
        ------
        VideoRejectedError
            Only when the Gatekeeper classifies the video as non-financial content
            (domain hard reject).  Company mismatches are NOT raised — they are
            surfaced via ``warning`` so chunks are always persisted.
        TranscriptFetchError
            If the transcript cannot be retrieved.
        """
        def _progress(stage: str) -> None:
            if on_progress:
                on_progress(stage)

        logger.info("=== YouTubeIngestionPipeline.ingest() START ===")
        logger.info("URL: %s", youtube_url)

        # ── Step 1: Extract video ID ───────────────────────────────────────
        _progress("Reading video URL…")
        video_id = _extract_video_id(youtube_url)
        logger.info("Video ID: %s", video_id)

        # ── Step 2: Fetch metadata (title, channel, publish_date) ────────────
        _progress("Fetching video metadata…")
        metadata = _fetch_video_metadata(video_id)
        title        = metadata["title"]
        channel      = metadata["channel"]
        publish_date = metadata["publish_date"]

        # ── Step 3: Fetch transcript ───────────────────────────────────────
        _progress("Fetching transcript…")
        transcript = _fetch_transcript(video_id, preferred_languages)

        # ── Step 4: Gatekeeper — DOMAIN VALIDATION ONLY (LLM) ────────────
        if not skip_gatekeeper:
            _progress("Checking whether this video is financial content…")
            gatekeeper_result = self._run_gatekeeper(title, transcript)
            if not gatekeeper_result.is_financial_content:
                raise VideoRejectedError(
                    "🚫 Hard Reject: This video is not about finance or the stock market."
                )
            logger.info("Gatekeeper PASSED — is_financial_content=True")

        # ── Step 5: Entity & Temporal Extraction ───────────────────────────
        _progress("Extracting companies and time periods…")
        extraction = self._run_extraction(transcript)
        logger.info(
            "Extraction complete — companies=%s, temporal=%s",
            extraction.company_names,
            extraction.temporal_references,
        )

        # ── Step 5b: Deterministic entity check (Python, no LLM) ──────────
        # Compare active_company against the extracted company list. This
        # avoids asking a small local model to reason about negative
        # constraints, and shares its matching logic (thorough, not lenient
        # — resolves the ticker to its Nifty 500 company name before
        # comparing) with vector_store.py's company-scoped retrieval.
        warning_message: str | None = None
        if active_company:
            match_found = tickers_match(extraction.company_names, active_company)
            if not match_found:
                companies_found = extraction.company_names or ["other companies"]
                warning_message = (
                    f"The video discusses "
                    f"{', '.join(companies_found)}, "
                    f"but your dashboard is set to {active_company}."
                )
                logger.warning(
                    "Entity mismatch (soft accept) — active=%r, found=%s",
                    active_company,
                    extraction.company_names,
                )

        # ── Step 6: Chunk the transcript ───────────────────────────────────
        _progress("Building and storing chunks…")
        chunks = self._build_chunks(
            transcript    = transcript,
            video_id      = video_id,
            title         = title,
            channel       = channel,
            publish_date  = publish_date,
            company_names = extraction.company_names,
            temporal_refs = extraction.temporal_references,
            youtube_url   = youtube_url,
        )

        logger.info(
            "=== YouTubeIngestionPipeline.ingest() DONE — %d chunks produced ===",
            len(chunks),
        )
        return {
            "success":    True,
            "chunks":     len(chunks),
            "chunk_list": chunks,
            "warning":    warning_message,
            "metadata":   metadata,
        }

    # ------------------------------------------------------------------
    # Stage 1 — Gatekeeper
    # ------------------------------------------------------------------

    def _run_gatekeeper(
        self,
        title: str,
        transcript: str,
    ) -> GatekeeperResult:
        """
        Domain-only classification via the LLM.

        Asks a single question: is this video about finance / stock markets /
        corporate earnings / macroeconomics?  Entity / company relevance is
        intentionally excluded — that check is done deterministically in Python
        after the Extraction stage.

        Returns a GatekeeperResult with only ``is_financial_content`` populated.
        Raises VideoRejectedError if the LLM response cannot be parsed (fail-safe).
        """
        user_prompt = _GATEKEEPER_USER_PROMPT.format(transcript=transcript)
        full_prompt = f"{_GATEKEEPER_SYSTEM_PROMPT}\n\n{user_prompt}"

        logger.info(
            "Running Gatekeeper LLM call (domain-only, transcript_chars=%d)…",
            len(transcript),
        )

        try:
            raw_response = self.llm.invoke(full_prompt)
        except Exception as exc:
            raise RuntimeError(f"Gatekeeper LLM call failed: {exc}") from exc

        logger.debug("Gatekeeper raw response: %s", raw_response[:300])

        try:
            return _parse_llm_json(raw_response, GatekeeperResult)  # type: ignore[return-value]
        except ValueError as exc:
            first_error = exc

        # ── Fallback 1: lenient scan ─────────────────────────────────────
        # Small local models sometimes ignore the "output ONLY
        # {is_financial_content}" instruction on content-rich transcripts and
        # free-form a detailed extraction-style response instead, wrapping or
        # burying the boolean (or omitting it, having answered "in spirit" by
        # extracting financial figures). A regex scan recovers the boolean
        # when it's present even if the rest of the JSON doesn't validate.
        lenient_match = re.search(
            r'"is_financial_content"\s*:\s*(true|false)', raw_response, re.IGNORECASE
        )
        if lenient_match:
            is_financial = lenient_match.group(1).lower() == "true"
            logger.warning(
                "Gatekeeper response didn't match the strict schema, but a "
                "lenient scan found is_financial_content=%s — using that.",
                is_financial,
            )
            return GatekeeperResult(is_financial_content=is_financial)

        # ── Fallback 2: one retry with a shorter, more forceful prompt ───
        # No boolean signal at all — give the model one more try with a
        # tighter instruction and a truncated transcript (less content to
        # get "excited" about and start extracting instead of classifying).
        logger.warning(
            "Gatekeeper response had no recoverable signal — retrying once "
            "with a stricter prompt. Original error: %s", first_error
        )
        retry_prompt = (
            "Reply with ONLY valid JSON — no markdown, no explanation, no "
            "extra keys, nothing else on any line:\n"
            '{"is_financial_content": true}\n'
            "or\n"
            '{"is_financial_content": false}\n\n'
            "Is the following transcript fundamentally about finance, stock "
            "markets, corporate earnings, or macroeconomics?\n\n"
            f"<transcript>\n{transcript[:1500]}\n</transcript>"
        )
        try:
            retry_response = self.llm.invoke(retry_prompt)
            result = _parse_llm_json(retry_response, GatekeeperResult)
            logger.info("Gatekeeper retry succeeded.")
            return result  # type: ignore[return-value]
        except Exception as retry_exc:
            logger.warning(
                "Gatekeeper retry also failed — defaulting to REJECT. Error: %s",
                retry_exc,
            )
            raise VideoRejectedError(
                f"Rejected: Gatekeeper LLM returned an unparseable response. "
                f"Raw output: {raw_response[:200]}"
            ) from first_error

    # ------------------------------------------------------------------
    # Stage 2 — Entity & Temporal Extraction
    # ------------------------------------------------------------------

    def _run_extraction(self, transcript: str) -> ExtractionResult:
        """
        Extract company names and temporal references from the full transcript.

        For very long transcripts the LLM receives the first 6 000 characters
        to avoid exceeding context limits on smaller Ollama models (e.g. 7 B).
        """
        # Truncate to stay within common context windows of small local models
        truncated = transcript[:6_000]
        prompt    = _EXTRACTION_PROMPT.format(transcript=truncated)

        logger.info("Running Extraction LLM call…")
        try:
            raw_response = self.llm.invoke(prompt)
        except Exception as exc:
            logger.warning(
                "Extraction LLM call failed (%s). Returning empty extraction.", exc
            )
            return ExtractionResult(company_names=[], temporal_references=[])

        logger.debug("Extraction raw response: %s", raw_response[:300])

        try:
            result = _parse_llm_json(raw_response, ExtractionResult)
        except ValueError as exc:
            logger.warning(
                "Extraction response unparseable (%s). Returning empty extraction.", exc
            )
            return ExtractionResult(company_names=[], temporal_references=[])

        return result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Step 6 — Chunking
    # ------------------------------------------------------------------

    def _build_chunks(
        self,
        *,
        transcript: str,
        video_id: str,
        title: str,
        channel: str,
        publish_date: str,
        company_names: list[str],
        temporal_refs: list[str],
        youtube_url: str,
    ) -> list[dict]:
        """
        Split the transcript into overlapping chunks and wrap each with the
        metadata schema expected by ChromaDBManager.store_data().

        Chunk dict schema (identical to doc_processor.py output):
        {
            "id": str,           # unique UUID
            "text_chunk": str,   # the raw text
            "metadata": {
                "source": str,
                "source_type": "youtube_transcript",
                "video_id": str,
                "youtube_url": str,
                "title": str,
                "channel": str,            # uploader / channel name
                "publish_date": str,       # YYYY-MM-DD
                "detected_company": str,   # first company or ""
                "detected_tickers": str,   # comma-joined company list
                "temporal_references": str,# comma-joined temporal list
                "chunk_index": int,
                "ingested_at": str,        # ISO-8601 timestamp
            }
        }
        """
        chunks: list[dict] = []
        ingested_at = datetime.now().isoformat()

        # Simple fixed-size overlap splitter (no external dependency)
        start  = 0
        index  = 0
        while start < len(transcript):
            end        = start + _CHUNK_SIZE
            chunk_text = transcript[start:end].strip()
            if chunk_text:
                chunks.append({
                    "id": str(uuid.uuid4()),
                    "text_chunk": chunk_text,
                    "metadata": {
                        "source":              title,
                        "source_type":         "youtube_transcript",
                        # Routing key: store_data() checks Document_Type to decide
                        # which ChromaDB collection to use.  Without this key the
                        # chunk falls into the market collection (JIT path), making
                        # YouTube content invisible to document-scoped searches and
                        # vulnerable to being overwritten by yfinance/news upserts.
                        "Document_Type":       "uploaded_document",
                        "video_id":            video_id,
                        "youtube_url":         youtube_url,
                        "title":               title,
                        "channel":             channel,
                        "publish_date":        publish_date,
                        "detected_company":    company_names[0] if company_names else "",
                        "detected_tickers":    ", ".join(company_names),
                        "temporal_references": ", ".join(temporal_refs),
                        "chunk_index":         index,
                        "ingested_at":         ingested_at,
                    },
                })
                index += 1
            # Advance with overlap
            start = end - _CHUNK_OVERLAP

        return chunks


# ===========================================================================
# Convenience function — mirrors process_uploaded_file() in doc_processor.py
# ===========================================================================

def process_youtube_url(
    youtube_url: str,
    ollama_model: str | None = None,
    ollama_base_url: str | None = None,
    preferred_languages: list[str] | None = None,
    skip_gatekeeper: bool = False,
    active_company: str | None = None,
    on_progress: "Callable[[str], None] | None" = None,
) -> dict:
    """
    Public convenience wrapper around YouTubeIngestionPipeline.ingest().

    Parameters
    ----------
    active_company : str | None
        Ticker or company name currently selected in the dashboard UI.
        Passed through to the two-gate gatekeeper.  A company mismatch
        (financial content but wrong entity) is a soft accept: chunks are
        still produced and the mismatch reason is surfaced via ``warning``.

    Returns
    -------
    dict
        ``success``    : bool       — always True (hard failures raise).
        ``chunks``     : int        — number of chunks produced.
        ``chunk_list`` : list[dict] — raw chunks; pass to db_manager.store_data().
        ``warning``    : str | None — company mismatch reason, or None.
        ``metadata``   : dict       — title, channel, publish_date from yt-dlp.

    Raises
    ------
    VideoRejectedError
        Non-financial video (Gate 1 hard reject only).
    TranscriptFetchError
        Transcript unavailable (disabled, private, or no English captions).
    ValueError
        Invalid YouTube URL.
    """
    pipeline = YouTubeIngestionPipeline(
        ollama_model=ollama_model,
        ollama_base_url=ollama_base_url,
    )
    return pipeline.ingest(
        youtube_url,
        preferred_languages=preferred_languages,
        skip_gatekeeper=skip_gatekeeper,
        active_company=active_company,
        on_progress=on_progress,
    )


# ===========================================================================
# CLI smoke-test  (python -m utils.youtube_ingestion <URL>)
# ===========================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m utils.youtube_ingestion <YouTube-URL>")
        sys.exit(1)

    url = sys.argv[1]
    print(f"\n{'='*60}")
    print(f"  YouTubeIngestionPipeline — smoke test")
    print(f"  URL : {url}")
    print(f"{'='*60}\n")

    try:
        result = process_youtube_url(url)
        if result.get("warning"):
            print(f"⚠️  Company mismatch (soft warning): {result['warning']}\n")
        print(f"✅ Ingestion successful — {result['chunks']} chunks produced.\n")
        first = result["chunk_list"][0]
        print("── First chunk preview ──────────────────────────────────────")
        print(f"  ID           : {first['id']}")
        print(f"  Text (100c)  : {first['text_chunk'][:100]}…")
        print(f"  Title        : {result['metadata']['title']}")
        print(f"  Publish date : {result['metadata']['publish_date']}")
        print(f"  Companies    : {first['metadata']['detected_tickers']}")
        print(f"  Temporal refs: {first['metadata']['temporal_references']}")
        print(f"  Chunks total : {result['chunks']}")

    except VideoRejectedError as e:
        print(f"🚫 {e}")
        sys.exit(2)
    except TranscriptFetchError as e:
        print(f"⚠️  {e}")
        sys.exit(3)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(4)
