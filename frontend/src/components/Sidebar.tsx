"use client";

import { useState } from "react";
import { signOut, useSession } from "next-auth/react";
import { Database, LogOut, MessageSquare } from "lucide-react";
import type { SearchScope, StatusMessage } from "@/lib/types";
import type { Diagnostics, SessionsStore } from "@/lib/api";
import StockSelector from "./StockSelector";
import SearchScopeToggle from "./SearchScopeToggle";
import FileUploader from "./FileUploader";
import YoutubeIngestForm from "./YoutubeIngestForm";
import DiagnosticsPanel from "./DiagnosticsPanel";
import ChatHistoryList from "./ChatHistoryList";

// Two-tab sidebar: "Home" (chat history) and "Sources" (target asset, search
// scope, knowledge base, diagnostics) — split out so the sidebar doesn't run
// long. Profile + sign-out are shared, pinned below both tabs.

type SidebarTab = "home" | "sources";

export default function Sidebar({
  stock,
  onStockChange,
  scope,
  onScopeChange,
  ready,
  onFilesSelected,
  onAllFilesRemoved,
  onYoutubeStatus,
  onYoutubeIngested,
  diagnostics,
  onDiagnosticsExpand,
  onClearData,
  clearingData,
  sessionsStore,
  currentSessionId,
  sessionsDisabled,
  onNewChat,
  onSwitchSession,
  onDeleteSession,
}: {
  stock: string;
  onStockChange: (s: string) => void;
  scope: SearchScope;
  onScopeChange: (s: SearchScope) => void;
  ready: boolean;
  onFilesSelected: (files: File[]) => Promise<void>;
  onAllFilesRemoved: () => void;
  onYoutubeStatus: (status: StatusMessage) => void;
  onYoutubeIngested: () => void;
  diagnostics: Diagnostics | null;
  onDiagnosticsExpand: () => void;
  onClearData: () => void;
  clearingData: boolean;
  sessionsStore: SessionsStore | null;
  currentSessionId: string | null;
  sessionsDisabled: boolean;
  onNewChat: () => void;
  onSwitchSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
}) {
  const [tab, setTab] = useState<SidebarTab>("home");
  const { data: session } = useSession();
  const displayName = session?.user?.name ?? session?.user?.email?.split("@")[0] ?? "Guest";
  const avatarLetter = displayName.charAt(0).toUpperCase();

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-border bg-sidebar">
      <div className="flex gap-1 p-3">
        <button
          type="button"
          onClick={() => setTab("home")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
            tab === "home" ? "bg-card text-foreground shadow-sm" : "text-muted hover:text-foreground"
          }`}
        >
          <MessageSquare size={14} />
          Home
        </button>
        <button
          type="button"
          onClick={() => setTab("sources")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
            tab === "sources" ? "bg-card text-foreground shadow-sm" : "text-muted hover:text-foreground"
          }`}
        >
          <Database size={14} />
          Sources
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {tab === "home" ? (
          <ChatHistoryList
            store={sessionsStore}
            currentSessionId={currentSessionId}
            disabled={sessionsDisabled}
            onNewChat={onNewChat}
            onSwitchSession={onSwitchSession}
            onDeleteSession={onDeleteSession}
          />
        ) : (
          <div className="space-y-5">
            <StockSelector value={stock} onChange={onStockChange} />
            <SearchScopeToggle value={scope} onChange={onScopeChange} />
            <FileUploader
              disabled={!ready}
              onFilesSelected={onFilesSelected}
              onAllRemoved={onAllFilesRemoved}
            />
            <YoutubeIngestForm
              disabled={!ready}
              activeCompany={stock}
              onStatus={onYoutubeStatus}
              onIngested={onYoutubeIngested}
            />
            <DiagnosticsPanel
              diagnostics={diagnostics}
              onExpand={onDiagnosticsExpand}
              onClearData={onClearData}
              clearing={clearingData}
            />
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 border-t border-border p-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground text-sm font-medium text-background">
          {avatarLetter}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{displayName}</p>
          <p className="truncate text-xs text-muted">{session?.user?.email ?? "Not signed in"}</p>
        </div>
        <button
          type="button"
          onClick={() => signOut({ redirectTo: "/" })}
          aria-label="Sign out"
          className="shrink-0 rounded-md p-1.5 text-muted transition-colors hover:bg-danger-soft hover:text-danger"
        >
          <LogOut size={15} />
        </button>
      </div>
    </aside>
  );
}
