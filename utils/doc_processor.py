import re
import uuid
from collections import Counter
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import pandas as pd



# ---------------------------------------------------------------------------
# Company identity signals: maps canonical name → (NSE tickers, keywords)
# Add more entries here as the supported universe grows.
# ---------------------------------------------------------------------------
COMPANY_SIGNALS: dict[str, tuple[list[str], list[str]]] = {
    "Reliance Industries Limited": (
        ["RELIANCE.NS"],
        ["reliance industries", "ril", "jio", "reliance retail", "reliance petro"]
    ),
    "State Bank of India": (
        ["SBIN.NS"],
        ["state bank of india", "sbi", "sbin"]
    ),
    "Tata Consultancy Services": (
        ["TCS.NS"],
        ["tata consultancy", "tcs"]
    ),
    "Infosys Limited": (
        ["INFY.NS"],
        ["infosys", "infy"]
    ),
    "HDFC Bank": (
        ["HDFCBANK.NS"],
        ["hdfc bank", "hdfcbank"]
    ),
    "ICICI Bank": (
        ["ICICIBANK.NS"],
        ["icici bank", "icici"]
    ),
    "Tata Motors": (
        ["TATAMOTORS.NS", "TMCV.NS", "TMPV.NS"],
        ["tata motors", "tatamotors", "jaguar land rover", "jlr"]
    ),
    "Wipro Limited": (
        ["WIPRO.NS"],
        ["wipro"]
    ),
    "HCL Technologies": (
        ["HCLTECH.NS"],
        ["hcl technologies", "hcltech", "hcl tech"]
    ),
    "Bharti Airtel": (
        ["BHARTIARTL.NS"],
        ["bharti airtel", "airtel"]
    ),
    "ITC Limited": (
        ["ITC.NS"],
        ["itc limited", "itc"]
    ),
    "Larsen & Toubro": (
        ["LT.NS"],
        ["larsen & toubro", "larsen and toubro", "l&t", "l & t"]
    ),
    "Axis Bank": (
        ["AXISBANK.NS"],
        ["axis bank", "axisbank"]
    ),
    "Kotak Mahindra Bank": (
        ["KOTAKBANK.NS"],
        ["kotak mahindra", "kotak bank", "kotakbank"]
    ),
    "Maruti Suzuki": (
        ["MARUTI.NS"],
        ["maruti suzuki", "maruti"]
    ),
    "Sun Pharmaceutical": (
        ["SUNPHARMA.NS"],
        ["sun pharma", "sun pharmaceutical"]
    ),
    "Bajaj Finance": (
        ["BAJFINANCE.NS"],
        ["bajaj finance", "bajfinance"]
    ),
    "Asian Paints": (
        ["ASIANPAINT.NS"],
        ["asian paints"]
    ),
    "Zomato": (
        ["ZOMATO.NS"],
        ["zomato"]
    ),
    "Jio Financial Services": (
        ["JIOFIN.NS"],
        ["jio financial", "jiofin"]
    ),
}


def extract_financial_year(text: str) -> int:
    """
    Scans text for financial year references and returns the most prominent year.
    Priority order: FY-notation > range notation > standalone 4-digit year.
    Defaults to 2026 if nothing is found.
    """
    years = []

    # Highest priority: FY24 -> 2024, FY2026 -> 2026
    fy_short = re.findall(r'\bFY(\d{2})\b', text, re.IGNORECASE)
    for m in fy_short:
        years.extend([2000 + int(m)] * 3)  # Weight FY notation heavily

    fy_full = re.findall(r'\bFY(20\d{2})\b', text, re.IGNORECASE)
    for m in fy_full:
        years.extend([int(m)] * 3)

    # Medium priority: 2024-25 -> 2025 (Indian fiscal year notation)
    fy_range_short = re.findall(r'\b20\d{2}-(\d{2})\b', text)
    for m in fy_range_short:
        years.extend([2000 + int(m)] * 2)

    # Medium priority: 2024-2025 -> 2025
    fy_range_full = re.findall(r'\b20\d{2}-(20\d{2})\b', text)
    for m in fy_range_full:
        years.extend([int(m)] * 2)

    # Base priority: standalone 4-digit years (20xx)
    year_matches = re.findall(r'\b(20\d{2})\b', text)
    for m in year_matches:
        years.append(int(m))

    if not years:
        return 2026

    counter = Counter(years)
    return counter.most_common(1)[0][0]


def extract_company_identity(text: str) -> tuple[str | None, list[str]]:
    """
    Scans text (typically the first 3 chunks of a document) for known company
    keywords and returns:
      - canonical_name : str | None  — e.g. "Reliance Industries Limited"
      - tickers        : list[str]   — e.g. ["RELIANCE.NS"]

    The match is case-insensitive; the first signal that scores the most hits
    wins.  Returns (None, []) when no company can be identified.
    """
    lower_text = text.lower()
    best_name: str | None = None
    best_tickers: list[str] = []
    best_hits = 0

    for company_name, (tickers, keywords) in COMPANY_SIGNALS.items():
        hits = sum(1 for kw in keywords if kw in lower_text)
        if hits > best_hits:
            best_hits = hits
            best_name = company_name
            best_tickers = tickers

    return best_name, best_tickers


# ---------------------------------------------------------------------------
# Screener.in section-header keywords in the "Data Sheet" first column.
# The parser uses these to slice the flat sheet into logical financial sections.
# ---------------------------------------------------------------------------
_SCREENER_SECTION_KEYWORDS: list[str] = [
    "PROFIT & LOSS",
    "BALANCE SHEET",
    "CASH FLOW",
    "QUARTERS",
]

# Generic sheets that carry no financial data — skipped in the fallback path.
# Note: "Data Sheet" is NOT in this set; it is handled explicitly by the
# Screener-native path below.
_SKIP_SHEETS: frozenset[str] = frozenset({
    "Customization", "Cover", "Readme", "Notes", "Assumptions",
})

# Maximum rows per chunk in the generic fallback path.
_MAX_ROWS_PER_CHUNK = 30


def _extract_year_from_date_columns(columns) -> int:
    """
    Given a sequence of column labels (e.g. Timestamps, date strings like
    '2024-03-31', or plain text like 'Mar 2024'), returns the maximum calendar
    year found.  Falls back to extract_financial_year() on a joined string,
    then to 2026 if nothing is found.
    """
    years: list[int] = []
    for col in columns:
        col_str = str(col)
        # pandas Timestamp or datetime-like stringified to "YYYY-MM-DD ..."
        ts_match = re.match(r"(\d{4})-\d{2}-\d{2}", col_str)
        if ts_match:
            years.append(int(ts_match.group(1)))
            continue
        # Plain 4-digit year anywhere in the label
        plain = re.findall(r"\b(20\d{2})\b", col_str)
        years.extend(int(y) for y in plain)

    if years:
        return max(years)
    # Fallback: scan all column strings as a blob of text
    return extract_financial_year(" ".join(str(c) for c in columns))


def _df_to_markdown_safe(df: "pd.DataFrame") -> str:
    """Render a DataFrame as a Markdown table; fall back to plain text."""
    try:
        return df.to_markdown(index=False)
    except Exception:
        return df.to_string(index=False)


def _build_chunk(
    section_name: str,
    file_name: str,
    source_name: str,
    df_section: "pd.DataFrame",
    extracted_year: int,
    detected_company: "str | None",
    detected_tickers: list,
    period_range: str = "",
) -> dict:
    """Assemble a single chunk dict from a prepared DataFrame slice."""
    header_lines = [
        f"Financial Statement Section: {section_name}",
        f"Source: {file_name}",
    ]
    if period_range:
        header_lines.append(f"Period coverage: {period_range}")

    chunk_text = "\n".join(header_lines) + "\n\n" + _df_to_markdown_safe(df_section)

    meta: dict = {
        "source":        source_name,
        "Document_Type": "uploaded_document",
        "file_name":     file_name,
        "sheet":         section_name,
        "year":          int(extracted_year),
        "data_type":     "excel_financial_data",
    }
    if detected_company:
        meta["detected_company"] = detected_company
        meta["detected_tickers"] = ",".join(detected_tickers)

    return {
        "id":         str(uuid.uuid4()),
        "text_chunk": chunk_text,
        "metadata":   meta,
    }


def process_excel_file(uploaded_file) -> list:
    """
    Two-path Excel parser for FinTemporal RAG.

    PATH 1 — Screener-native (preferred)
    ──────────────────────────────────────
    Screener.in exports hide raw numbers in a hidden "Data Sheet" tab.
    The visible P&L / Balance Sheet tabs contain only un-evaluated Excel
    formulas that pandas reads as NaN.  This path:
      1. Loads the flat "Data Sheet".
      2. Slices it vertically on section-header keywords
         (PROFIT & LOSS, BALANCE SHEET, CASH FLOW, QUARTERS).
      3. Within each slice, finds the "Report Date" row and promotes it
         to column headers so every value is labelled with its fiscal year.
      4. Extracts max_year from those date column headers.
      5. Serialises each slice to a labelled Markdown chunk.

    PATH 2 — Generic fallback
    ──────────────────────────
    When no "Data Sheet" is present (non-Screener exports), iterates all
    visible non-metadata sheets, drops fully-empty rows/cols, extracts the
    year from column headers, and splits large sheets into sub-chunks.

    Both paths attach full metadata compatible with ChromaDBManager.store_data().
    """
    if uploaded_file is None:
        return []

    source_name = f"Uploaded Document ({uploaded_file.name})"
    file_name   = uploaded_file.name
    all_chunks: list[dict] = []

    # Company identity: scan filename first; enriched per-sheet below if possible
    detected_company, detected_tickers = extract_company_identity(file_name)

    try:
        xls = pd.ExcelFile(uploaded_file)
    except Exception as exc:
        print(f"[PROCESSOR] Could not open '{file_name}': {exc}")
        return []

    sheet_names = xls.sheet_names

    # ══════════════════════════════════════════════════════════════════════════
    # PATH 1 — Screener-native: "Data Sheet" contains the raw numbers
    # ══════════════════════════════════════════════════════════════════════════
    if "Data Sheet" in sheet_names:
        print(f"[PROCESSOR] Screener-native path detected for '{file_name}'")
        try:
            raw_df = pd.read_excel(xls, sheet_name="Data Sheet", header=None)
        except Exception as exc:
            print(f"[PROCESSOR] Cannot read 'Data Sheet': {exc} — falling back")
            raw_df = None

        if raw_df is not None and not raw_df.empty:
            # Locate the row indices where each section header keyword appears
            # in the first column (col 0).  We match case-insensitively.
            first_col = raw_df.iloc[:, 0].astype(str).str.upper().str.strip()

            section_starts: list[tuple[int, str]] = []
            for kw in _SCREENER_SECTION_KEYWORDS:
                matches = first_col[first_col == kw.upper()].index.tolist()
                for idx in matches:
                    section_starts.append((idx, kw.title()))

            # Sort by row position so we can compute end boundaries
            section_starts.sort(key=lambda x: x[0])

            if not section_starts:
                print(f"[PROCESSOR] No section keywords found in 'Data Sheet' — falling back")
                raw_df = None   # signal fallback
            else:
                for i, (start_row, section_name) in enumerate(section_starts):
                    # End boundary = next section start - 1, or end of sheet
                    end_row = (
                        section_starts[i + 1][0]
                        if i + 1 < len(section_starts)
                        else len(raw_df)
                    )
                    # Slice out this section (skip the header keyword row itself)
                    section_raw = raw_df.iloc[start_row + 1 : end_row].copy()
                    section_raw = (
                        section_raw
                        .dropna(how="all")
                        .dropna(axis=1, how="all")
                        .reset_index(drop=True)
                    )

                    if section_raw.empty:
                        print(f"[PROCESSOR] Section '{section_name}' is empty — skipped")
                        continue

                    # ── Promote "Report Date" row to column headers ──────────
                    # Screener stores a row labelled "Report Date" whose values
                    # are the fiscal year-end dates.  We use this as the header.
                    first_col_local = (
                        section_raw.iloc[:, 0].astype(str).str.strip().str.lower()
                    )
                    report_date_mask = first_col_local == "report date"
                    report_date_rows = section_raw[report_date_mask].index.tolist()

                    if report_date_rows:
                        hdr_idx     = report_date_rows[0]
                        new_columns = section_raw.iloc[hdr_idx].tolist()
                        # Data rows = everything after the Report Date row
                        section_raw = section_raw.iloc[hdr_idx + 1 :].copy()
                        section_raw.columns = [str(c) for c in new_columns]
                        section_raw = (
                            section_raw
                            .dropna(how="all")
                            .reset_index(drop=True)
                        )
                        year_cols  = section_raw.columns[1:]  # skip metric-label col
                        extracted_year = _extract_year_from_date_columns(year_cols)
                        date_strs  = [str(c) for c in year_cols if re.search(r"\b20\d{2}\b", str(c))]
                        period_range = f"{date_strs[0]} – {date_strs[-1]}" if len(date_strs) >= 2 else ""
                    else:
                        # No Report Date row — use column headers directly
                        extracted_year = _extract_year_from_date_columns(section_raw.columns)
                        date_strs = [str(c) for c in section_raw.columns if re.search(r"\b20\d{2}\b", str(c))]
                        period_range = f"{date_strs[0]} – {date_strs[-1]}" if len(date_strs) >= 2 else ""

                    # Refine company identity from the section content
                    identity_scan = section_raw.head(5).to_string(index=False)
                    dc, dt = extract_company_identity(file_name + " " + identity_scan)
                    if dc:
                        detected_company, detected_tickers = dc, dt

                    all_chunks.append(_build_chunk(
                        section_name    = section_name,
                        file_name       = file_name,
                        source_name     = source_name,
                        df_section      = section_raw,
                        extracted_year  = extracted_year,
                        detected_company= detected_company,
                        detected_tickers= detected_tickers,
                        period_range    = period_range,
                    ))

        if raw_df is None or raw_df.empty:
            # Screener path produced nothing — fall through to generic path
            pass
        elif all_chunks:
            # PATH 1 succeeded — return immediately, skip generic path
            print(
                f"[DEBUG PROCESSOR]: Screener '{file_name}' → "
                f"{len(all_chunks)} section chunks"
            )
            return all_chunks

    # ══════════════════════════════════════════════════════════════════════════
    # PATH 2 — Generic fallback: iterate all visible non-metadata sheets
    # ══════════════════════════════════════════════════════════════════════════
    print(f"[PROCESSOR] Generic fallback path for '{file_name}'")

    for sheet_name in sheet_names:
        if sheet_name in _SKIP_SHEETS or sheet_name == "Data Sheet":
            continue

        try:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=0)
        except Exception as exc:
            print(f"[PROCESSOR] Cannot read sheet '{sheet_name}': {exc}")
            continue

        df = df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
        if df.empty:
            continue

        col_blob       = " ".join(str(c) for c in df.columns)
        first_row_str  = " ".join(str(v) for v in df.iloc[0].values) if len(df) else ""
        extracted_year = extract_financial_year(col_blob + " " + first_row_str + " " + file_name)

        date_strs    = [str(c) for c in df.columns if re.search(r"\b20\d{2}\b", str(c))]
        period_range = f"{date_strs[0]} – {date_strs[-1]}" if len(date_strs) >= 2 else ""

        # Refine company identity using sheet content
        dc, dt = extract_company_identity(file_name + " " + df.head(5).to_string(index=False))
        if dc:
            detected_company, detected_tickers = dc, dt

        total_rows  = len(df)
        total_parts = -(-total_rows // _MAX_ROWS_PER_CHUNK)

        for part_idx, chunk_start in enumerate(range(0, total_rows, _MAX_ROWS_PER_CHUNK), 1):
            chunk_df = df.iloc[chunk_start : chunk_start + _MAX_ROWS_PER_CHUNK]
            sec_name = sheet_name if total_parts == 1 else f"{sheet_name} (part {part_idx}/{total_parts})"
            all_chunks.append(_build_chunk(
                section_name    = sec_name,
                file_name       = file_name,
                source_name     = source_name,
                df_section      = chunk_df,
                extracted_year  = extracted_year,
                detected_company= detected_company,
                detected_tickers= detected_tickers,
                period_range    = period_range,
            ))

    print(
        f"[DEBUG PROCESSOR]: Generic Excel '{file_name}' → "
        f"{len(all_chunks)} chunks across {len(sheet_names)} sheets"
    )
    return all_chunks


def process_uploaded_file(uploaded_file) -> list:
    """
    Universal entry-point for all uploaded financial documents.
    Routes:
      • .xlsx / .xls  →  process_excel_file()  (tabular-to-text chunking)
      • .pdf / .txt   →  standard text splitter path (below)
    Returns a list of chunk dicts ready for ChromaDBManager.store_data().
    """
    if uploaded_file is None:
        return []

    file_name = uploaded_file.name.lower()

    # ── Route Excel files to the dedicated tabular parser ───────────────────
    if file_name.endswith((".xlsx", ".xls")):
        return process_excel_file(uploaded_file)

    # ── PDF / TXT path (original logic preserved below) ─────────────────────
    text = ""

    if file_name.endswith(".pdf"):
        pdf_reader = PdfReader(uploaded_file)
        # Read ALL pages — never stop early
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    elif file_name.endswith(".txt"):
        text = uploaded_file.getvalue().decode("utf-8")
    else:
        # Fallback: attempt UTF-8 decode
        text = uploaded_file.getvalue().decode("utf-8", errors="ignore")

    if not text.strip():
        return []

    # Split the FULL document text into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    raw_chunks = text_splitter.split_text(text)

    if not raw_chunks:
        return []

    # Scan the first 3 chunks (cover page + intro) for the most accurate year signal.
    # Using only raw_chunks[0] risks picking up the document date instead of the FY.
    scan_text = " ".join(raw_chunks[:3])
    extracted_year = extract_financial_year(scan_text)

    # Detect the company identity from the same opening text window.
    detected_company, detected_tickers = extract_company_identity(scan_text)

    source_name = f"Uploaded Document ({uploaded_file.name})"

    # Build the full list — iterate over ALL raw_chunks, no slicing, no break
    all_chunks = []
    for chunk_text in raw_chunks:
        # UUID-based ID ensures no upsert collision across multiple uploads / queries
        chunk_id = str(uuid.uuid4())
        chunk_meta: dict = {
            'source': source_name,
            'Document_Type': 'uploaded_document',
            'year': int(extracted_year),           # Always cast to int
            'file_name': uploaded_file.name,        # Preserve original filename
        }
        # Attach company identity only when detected — keeps metadata lean for
        # documents where no known company signal was found.
        if detected_company:
            chunk_meta['detected_company'] = detected_company
            chunk_meta['detected_tickers'] = ",".join(detected_tickers)
        all_chunks.append({
            'id': chunk_id,
            'text_chunk': chunk_text,
            'metadata': chunk_meta,
        })

    # Mandatory debug log: verify total chunk count, year, and detected company
    print(
        f"[DEBUG PROCESSOR]: Document '{uploaded_file.name}' processed into "
        f"{len(all_chunks)} total chunks | year={extracted_year} | "
        f"company={detected_company or 'undetected'}"
    )

    return all_chunks
