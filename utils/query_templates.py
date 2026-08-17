"""
ENHANCED QUERY PROMPTS
Maps each preset button label to a structured LLM prompt that enforces:
  • Strict context adherence  (hallucination guardrail)
  • Date-to-quarter reasoning (YYYY-MM-DD header mapping)
  • Data fusion               (Excel tables ↔ PDF/news qualitative text)
The clean short label is still shown in the chat UI; only the LLM receives
the enriched version.

Extracted verbatim from app.py (Streamlit) so both the FastAPI backend and
app.py share one source of truth — no behavior change, pure relocation.
"""

_GUARDRAIL = (
    "Answer strictly based on the provided context chunks. "
    "If the retrieved context lacks sufficient evidence or exact numbers, "
    "explicitly state: 'I do not have sufficient context to answer this "
    "question accurately.' Do NOT fabricate figures."
)
_DATE_MAP = (
    "Date-to-quarter mapping for Indian fiscal year: "
    "YYYY-03-31 → Q4/Annual end, YYYY-06-30 → Q1, "
    "YYYY-09-30 → Q2, YYYY-12-31 → Q3. "
    "Treat the most recent date column as the 'latest' period."
)
_FUSION = (
    "Synthesize quantitative figures from Excel Markdown tables "
    "with qualitative commentary from PDF annual reports and news articles."
)
_PREAMBLE = f"{_GUARDRAIL}\n{_DATE_MAP}\n{_FUSION}\n\n"

ENHANCED_QUERY_PROMPTS: dict[str, str] = {

    # ==================== VALUATION & RATIOS ====================

    "What is the current PEG ratio?": _PREAMBLE + """
    Target: State the current Price/Earnings-to-Growth (PEG) ratio.

    Precedence Rules:
    1. EXTRACT: If 'PEG ratio' is explicitly stated in the context text (e.g. Market/Yahoo chunk), output that exact number immediately. DO NOT attempt to calculate anything.
    2. REFUSE: If the explicit PEG ratio is missing from the context, reply strictly: "I do not have sufficient context to determine the current PEG ratio."
    """,

    "What is the Debt-to-Equity ratio?": _PREAMBLE + """
    Target: State the Debt-to-Equity ratio.

    Precedence Rules:
    1. EXTRACT: If 'Debt-to-Equity ratio' is explicitly stated in the context text, output that value directly and stop.
    2. DERIVE: If missing, look for 'Total Debt' (Borrowings) and 'Total Equity' in the financial tables to compute it for the latest period.
    3. REFUSE: If neither the explicit ratio nor the balance sheet components exist, reply strictly: "I do not have sufficient context to determine the Debt-to-Equity ratio."
    """,

    "What is the Return on Equity (ROE)?": _PREAMBLE + """
    Target: State the Return on Equity (ROE).

    Precedence Rules:
    1. EXTRACT: If 'Return on Equity' or 'ROE' is explicitly stated in the context, output that value directly. (If context states ROE is 'N/A', state that ROE is currently N/A).
    2. DERIVE: If missing, calculate (Net Profit / Total Equity) using the latest period numbers from the Excel tables.
    3. REFUSE: If no explicit value or financial tables exist, reply strictly: "I do not have sufficient context to determine the Return on Equity (ROE)."
    """,

    # ==================== FINANCIAL PERFORMANCE ====================

    "Summarize the latest quarterly earnings report": _PREAMBLE + """
    Target: Provide a concise summary of the latest quarterly earnings performance.

    Precedence Rules:
    1. EXTRACT & SYNTHESIZE: Identify the latest date column in the 'Quarters' table (e.g. YYYY-06-30 is Q1). Extract Revenue/Sales, Operating Profit, and Net Profit. Combine with qualitative operational notes from transcripts or news if present.
    2. REFUSE: If no quarterly performance tables or transcript chunks exist in the context, reply strictly: "I do not have sufficient context to summarize the latest quarterly report."
    """,

    "What is the Free Cash Flow trend?": _PREAMBLE + """
    Target: Analyze the Free Cash Flow (FCF) trend over time.

    Precedence Rules:
    1. EXTRACT: If Free Cash Flow figures are explicitly stated, list them in chronological order and state the trend (growing, declining, or volatile).
    2. DERIVE: If explicit FCF is absent, calculate approximate FCF for each year as (Operating Cash Flow + Investing Cash Flow) using the Cash Flow table.
    3. REFUSE: If no cash flow data is present, reply strictly: "I do not have sufficient context to analyze the Free Cash Flow trend."
    """,

    "Provide segment-wise revenue": _PREAMBLE + """
    Target: List revenue broken down by business segments.

    Precedence Rules:
    1. EXTRACT: Search for explicit segment revenue breakdowns or segment growth figures in the uploaded document text or news.
    2. REFUSE: Do not guess or infer segments from general description text. If segment data is not explicitly provided in the context, reply strictly: "I do not have sufficient context to provide segment-wise revenue."
    """,

    # ==================== COMPETITIVE & MARKET ANALYSIS ====================

    "Compare the Operating Margin with industry peers": _PREAMBLE + """
    Target: Compare the selected company's Operating Margin against peers in the retrieved context.

    Precedence Rules:
    1. EXTRACT: Get the target company's Operating Margin from the context. Check if any peer company operating margins are explicitly stated in the news/document chunks.
    2. CONDITIONAL OUTPUT: If peer data exists, present the comparison. If peer data is absent, state the target company's margin and add: "No direct peer operating margin data was found in the retrieved context to perform a comparison."
    3. REFUSE: If even the target company's margin is missing, reply strictly: "I do not have sufficient context to compare operating margins."
    """,

    "What is the company's market share in its primary segment?": _PREAMBLE + """
    Target: State the company's market share percentage.

    Precedence Rules:
    1. EXTRACT: Look for explicit 'market share' percentages or market position statements in the text chunks.
    2. REFUSE: Do not estimate or calculate market share from revenue figures. If not explicitly stated, reply strictly: "I do not have sufficient context to determine the company's market share."
    """,

    # ==================== GOVERNANCE & FORWARD LOOKING ====================

    "Show the dividend yield history for the last 5 years": _PREAMBLE + """
    Target: Provide dividend history over recent years.

    Precedence Rules:
    1. EXTRACT: Extract dividend yields from market data OR pull 'Dividend Amount' values row by row from the Profit & Loss financial table for up to 5 years chronologically.
    2. REFUSE: If no dividend metrics or financial table rows exist, reply strictly: "I do not have sufficient context to provide the dividend yield history."
    """,

    "List recent management changes": _PREAMBLE + """
    Target: Identify executive or board member appointments and resignations.

    Precedence Rules:
    1. EXTRACT: Search news and transcript text chunks for appointments, resignations, or executive leadership updates (e.g. CEO, CFO, Board Director).
    2. REFUSE: If no executive or leadership changes are mentioned, reply strictly: "I do not have sufficient context regarding recent management changes."
    """,

    "What are the major risk factors mentioned in the Annual Report?": _PREAMBLE + """
    Target: Identify key risk factors, headwinds, or operational challenges.

    Precedence Rules:
    1. EXTRACT: Extract explicitly stated business risks, industry headwinds, regulatory challenges, or macro risks from the document text or news chunks.
    2. REFUSE: If no risks are explicitly mentioned in the context, reply strictly: "I do not have sufficient context to list major risk factors."
    """,

    "Identify key growth drivers from the management discussion": _PREAMBLE + """
    Target: Identify key strategic growth drivers and management priorities.

    Precedence Rules:
    1. EXTRACT: Extract forward-looking statements, CapEx plans, business expansions, or strategic growth initiatives from management discussion chunks, transcripts, or news.
    2. REFUSE: If no management discussion or forward-looking statements are in the context, reply strictly: "I do not have sufficient context to identify key growth drivers."
    """,
}

# Category → ordered list of preset labels, drives the tabbed "Suggested
# Fundamental Analysis Queries" UI (Valuation / Performance / Market / Governance).
QUERY_TABS: dict[str, list[str]] = {
    "valuation": [
        "What is the current PEG ratio?",
        "What is the Debt-to-Equity ratio?",
        "What is the Return on Equity (ROE)?",
    ],
    "performance": [
        "Summarize the latest quarterly earnings report",
        "What is the Free Cash Flow trend?",
        "Provide segment-wise revenue",
    ],
    "market": [
        "Compare the Operating Margin with industry peers",
        "What is the company's market share in its primary segment?",
    ],
    "governance": [
        "Show the dividend yield history for the last 5 years",
        "List recent management changes",
        "What are the major risk factors mentioned in the Annual Report?",
        "Identify key growth drivers from the management discussion",
    ],
}
