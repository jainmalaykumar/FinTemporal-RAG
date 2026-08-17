"use client";

import { useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2 } from "lucide-react";
import Sidebar from "@/components/Sidebar";
import SuggestedQueries from "@/components/SuggestedQueries";
import ChatThread from "@/components/ChatThread";
import ChatInput from "@/components/ChatInput";
import StatusBanner from "@/components/StatusBanner";
import PromptJumpMenu from "@/components/PromptJumpMenu";
import {
  ApiError,
  clearData,
  createSession,
  deleteSession,
  getDiagnostics,
  getOrCreateActiveSession,
  ingestDocuments,
  listSessions,
  sendQuery,
  switchStock,
  type Diagnostics,
  type SessionsStore,
} from "@/lib/api";
import type { ChatMessage, SearchScope, StatusMessage } from "@/lib/types";

// Ports app.py's render_dashboard(): sidebar + chat pipeline, all now wired
// to the real FastAPI backend via the authenticated proxy.

const SCOPE_LABEL: Record<SearchScope, string> = {
  all: "Hybrid",
  youtube: "YouTube only",
  docs: "Documents only",
};

function bareTicker(t: string) {
  return t.trim().replace(/\.NS$/i, "").replace(/\.BO$/i, "").toUpperCase();
}

export default function DashboardPage() {
  const { status } = useSession();

  const [stock, setStock] = useState("RELIANCE.NS");
  const [scope, setScope] = useState<SearchScope>("all");

  const [sessionsStore, setSessionsStore] = useState<SessionsStore | null>(null);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [bootstrapped, setBootstrapped] = useState(false);

  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [clearingData, setClearingData] = useState(false);
  const [queryLoading, setQueryLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<StatusMessage | null>(null);

  const [detectedDocCompany, setDetectedDocCompany] = useState<string | null>(null);
  const [detectedDocTickers, setDetectedDocTickers] = useState<string[]>([]);

  const previousStock = useRef<string | null>(null);
  const currentSessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  // ── Bootstrap: reuse newest empty session or create one ──────────────────
  useEffect(() => {
    if (status !== "authenticated" || bootstrapped) return;
    (async () => {
      const { session_id, store } = await getOrCreateActiveSession();
      setSessionsStore(store);
      setCurrentSessionId(session_id);
      setMessages(store.sessions[session_id]?.messages ?? []);
      previousStock.current = stock;
      setBootstrapped(true);
      getDiagnostics().then(setDiagnostics).catch(() => {});
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, bootstrapped]);

  // ── Stock-switch detection: clears market collection + starts a new session
  useEffect(() => {
    if (!bootstrapped || !currentSessionId) return;
    const oldStock = previousStock.current;
    if (oldStock === null || oldStock === stock) return;

    (async () => {
      const leavingSessionId = currentSessionId;
      const leavingWasEmpty = messages.length === 0;
      const { new_session_id } = await switchStock(leavingSessionId, messages, stock, oldStock);
      if (leavingWasEmpty) {
        // Don't leave an empty ghost session behind from the stock we just left —
        // at most one empty session should ever exist, and only while it's open.
        await deleteSession(leavingSessionId);
      }
      const store = await listSessions();
      setSessionsStore(store);
      setCurrentSessionId(new_session_id);
      setMessages([]);
      previousStock.current = stock;
      setStatusMessage({
        type: "success",
        text: `Switched to ${stock}. Market data cleared and a new chat session started.`,
      });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stock, bootstrapped]);

  const ready = bootstrapped && currentSessionId !== null;

  async function refreshSessions() {
    const store = await listSessions();
    setSessionsStore(store);
    return store;
  }

  // Deletes the currently-open session if it has no messages yet — called
  // before navigating away from it, so an empty "New Chat" never lingers in
  // the sidebar once you've moved on to something else.
  async function cleanupCurrentIfEmpty() {
    if (currentSessionId && messages.length === 0) {
      await deleteSession(currentSessionId);
    }
  }

  async function handleSend(displayText: string, queryText: string = displayText) {
    if (!currentSessionId || queryLoading) return;
    const askedSessionId = currentSessionId;
    setMessages((prev) => [...prev, { role: "user", content: displayText }]);
    setQueryLoading(true);
    try {
      const result = await sendQuery({
        sessionId: askedSessionId,
        queryText,
        displayText,
        searchScope: scope,
        selectedStock: stock,
      });
      // Guard against a race with session switching while this was in flight —
      // only apply the response if we're still looking at the session it answered.
      if (currentSessionIdRef.current === askedSessionId) {
        setMessages(result.messages);
      }
      refreshSessions();
    } catch (err) {
      if (currentSessionIdRef.current === askedSessionId) {
        setMessages((prev) => prev.slice(0, -1));
      }
      const message = err instanceof ApiError ? err.message : "Unexpected pipeline error.";
      setStatusMessage({ type: "error", text: message });
    } finally {
      setQueryLoading(false);
    }
  }

  async function handleNewChat() {
    await cleanupCurrentIfEmpty();
    const { session_id } = await createSession();
    await refreshSessions();
    setCurrentSessionId(session_id);
    setMessages([]);
  }

  async function handleSwitchSession(id: string) {
    if (id === currentSessionId) return;
    await cleanupCurrentIfEmpty();
    const store = await refreshSessions();
    setCurrentSessionId(id);
    setMessages(store.sessions[id]?.messages ?? []);
  }

  async function handleDeleteSession(id: string) {
    const { next_session_id } = await deleteSession(id);
    const store = await refreshSessions();
    if (next_session_id) {
      setCurrentSessionId(next_session_id);
      setMessages(store.sessions[next_session_id]?.messages ?? []);
    } else {
      const { session_id } = await createSession();
      await refreshSessions();
      setCurrentSessionId(session_id);
      setMessages([]);
    }
  }

  async function handleFilesSelected(files: File[]) {
    const result = await ingestDocuments(files);
    if (result.chunks_ingested > 0) {
      setStatusMessage({
        type: "success",
        text: `Ingested ${result.chunks_ingested} chunks from ${result.files_ingested.length} document(s).`,
      });
      if (result.detected_company) {
        setDetectedDocCompany(result.detected_company);
        setDetectedDocTickers(result.detected_tickers);
      }
      getDiagnostics().then(setDiagnostics).catch(() => {});
    }
  }

  function handleAllFilesRemoved() {
    setDetectedDocCompany(null);
    setDetectedDocTickers([]);
  }

  async function handleClearData() {
    if (!currentSessionId) return;
    setClearingData(true);
    try {
      const { success } = await clearData(currentSessionId);
      if (success) {
        setMessages([]);
        setDetectedDocCompany(null);
        setDetectedDocTickers([]);
        await refreshSessions();
        getDiagnostics().then(setDiagnostics).catch(() => {});
        setStatusMessage({ type: "success", text: "Database and chat history cleared." });
      } else {
        setStatusMessage({ type: "error", text: "Clear failed — check server logs." });
      }
    } finally {
      setClearingData(false);
    }
  }

  const selectedBare = bareTicker(stock);
  const showMismatchBanner =
    detectedDocCompany &&
    detectedDocTickers.length > 0 &&
    !detectedDocTickers.map(bareTicker).includes(selectedBare);

  if (status === "loading" || !ready) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted">
        Loading your workspace…
      </div>
    );
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      <Sidebar
        stock={stock}
        onStockChange={setStock}
        scope={scope}
        onScopeChange={setScope}
        ready={ready}
        onFilesSelected={handleFilesSelected}
        onAllFilesRemoved={handleAllFilesRemoved}
        onYoutubeStatus={setStatusMessage}
        onYoutubeIngested={() => getDiagnostics().then(setDiagnostics).catch(() => {})}
        diagnostics={diagnostics}
        onDiagnosticsExpand={() => getDiagnostics().then(setDiagnostics).catch(() => {})}
        onClearData={handleClearData}
        clearingData={clearingData}
        sessionsStore={sessionsStore}
        currentSessionId={currentSessionId}
        sessionsDisabled={queryLoading}
        onNewChat={handleNewChat}
        onSwitchSession={handleSwitchSession}
        onDeleteSession={handleDeleteSession}
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between border-b border-border px-6 py-3.5">
          <span className="text-sm font-medium text-foreground">FinTemporal RAG</span>
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className="rounded-full border border-border px-2.5 py-1 font-medium text-foreground">
              {stock}
            </span>
            <span className="rounded-full border border-border px-2.5 py-1">{SCOPE_LABEL[scope]}</span>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-6">
            {showMismatchBanner && (
              <div className="mb-3">
                <StatusBanner
                  message={{
                    type: "warning",
                    text: `The uploaded document belongs to ${detectedDocCompany} (${detectedDocTickers.join(", ")}), but the selected stock is ${stock}. Analysis will proceed, but context may not align.`,
                  }}
                  onDismiss={() => setDetectedDocCompany(null)}
                />
              </div>
            )}

            {statusMessage && (
              <div className="mb-3">
                <StatusBanner message={statusMessage} onDismiss={() => setStatusMessage(null)} />
              </div>
            )}

            <SuggestedQueries onSelect={handleSend} />

            <div className="mt-6">
              <ChatThread messages={messages} />
              {queryLoading && (
                <div className="flex items-center gap-2 py-3 text-xs text-muted">
                  <Loader2 size={13} className="animate-spin" />
                  Synthesizing response…
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="border-t border-border p-4">
          <div className="mx-auto max-w-3xl">
            <ChatInput onSend={handleSend} disabled={queryLoading} />
          </div>
        </div>
      </main>

      <PromptJumpMenu messages={messages} />
    </div>
  );
}
