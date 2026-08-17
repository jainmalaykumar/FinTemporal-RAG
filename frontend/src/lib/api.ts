import type { ChatMessage, SearchScope } from "@/lib/types";

// Public, unauthenticated reference data goes straight to FastAPI (CORS-enabled
// for that purpose). Everything user-scoped goes through /api/backend/*, the
// authenticated same-origin proxy in app/api/backend/[...path]/route.ts, which
// injects the verified session email server-side.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface QueryTemplates {
  prompts: Record<string, string>;
  tabs: Record<string, string[]>;
}

export interface SessionSummary {
  label: string;
  created: string;
  messages: ChatMessage[];
}

export interface SessionsStore {
  sessions: Record<string, SessionSummary>;
  session_order: string[];
}

export interface Diagnostics {
  youtube_chunks?: number;
  document_chunks?: number;
  market_chunks?: number;
  uploaded_documents?: number;
  market_data?: number;
  granular_unavailable_reason?: string;
}

export interface QueryResult {
  response: string;
  context: string[];
  messages: ChatMessage[];
}

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail ?? `Request failed with ${res.status}`, res.status);
  }
  return res.json() as Promise<T>;
}

// ── Public reference data ─────────────────────────────────────────────────

export function fetchStocks(): Promise<string[]> {
  return fetch(`${API_BASE_URL}/api/stocks`).then((r) => unwrap<string[]>(r));
}

export function fetchQueryTemplates(): Promise<QueryTemplates> {
  return fetch(`${API_BASE_URL}/api/query-templates`).then((r) => unwrap<QueryTemplates>(r));
}

// ── Authenticated (proxied through /api/backend/*) ──────────────────────────

export function getOrCreateActiveSession(): Promise<{ session_id: string; store: SessionsStore }> {
  return fetch("/api/backend/sessions/active", { method: "POST" }).then((r) =>
    unwrap(r),
  );
}

export function listSessions(): Promise<SessionsStore> {
  return fetch("/api/backend/sessions").then((r) => unwrap<SessionsStore>(r));
}

export function createSession(): Promise<{ session_id: string }> {
  return fetch("/api/backend/sessions", { method: "POST" }).then((r) => unwrap(r));
}

export function deleteSession(sessionId: string): Promise<{ next_session_id: string | null }> {
  return fetch(`/api/backend/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  }).then((r) => unwrap(r));
}

export function ingestDocuments(
  files: File[],
): Promise<{
  chunks_ingested: number;
  files_ingested: string[];
  detected_company: string | null;
  detected_tickers: string[];
}> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return fetch("/api/backend/ingest/document", { method: "POST", body: form }).then((r) =>
    unwrap(r),
  );
}

export async function ingestYoutube(
  url: string,
  activeCompany: string,
): Promise<{ chunks: number; metadata: Record<string, string>; warning: string | null }> {
  // Ingestion runs a transcript fetch + up to 2 gatekeeper LLM calls + 1
  // extraction LLM call locally via Ollama, which can legitimately take a
  // couple of minutes. Give it a generous, explicit timeout so a genuine
  // hang produces a clear "timed out" message instead of an ambiguous
  // network-error one.
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 240_000);
  try {
    const res = await fetch("/api/backend/ingest/youtube", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, active_company: activeCompany }),
      signal: controller.signal,
    });
    return await unwrap(res);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Ingestion timed out after 4 minutes — the video may be unusually long, or Ollama may be stuck. Check the backend terminal for what it was doing.");
    }
    console.error("ingestYoutube failed:", err);
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

export function getDiagnostics(): Promise<Diagnostics> {
  return fetch("/api/backend/diagnostics").then((r) => unwrap<Diagnostics>(r));
}

export function clearData(sessionId: string): Promise<{ success: boolean }> {
  return fetch("/api/backend/data/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  }).then((r) => unwrap(r));
}

export function switchStock(
  sessionId: string,
  messages: ChatMessage[],
  newStock: string,
  oldStock: string,
): Promise<{ new_session_id: string }> {
  return fetch("/api/backend/stock/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      messages,
      new_stock: newStock,
      old_stock: oldStock,
    }),
  }).then((r) => unwrap(r));
}

export function sendQuery(params: {
  sessionId: string;
  queryText: string;
  displayText?: string;
  searchScope: SearchScope;
  selectedStock: string;
}): Promise<QueryResult> {
  return fetch("/api/backend/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: params.sessionId,
      query_text: params.queryText,
      display_text: params.displayText,
      search_scope: params.searchScope,
      selected_stock: params.selectedStock,
    }),
  }).then((r) => unwrap<QueryResult>(r));
}

export { ApiError };
