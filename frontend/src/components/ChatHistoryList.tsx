"use client";

import { MessageSquare, Plus, Trash2 } from "lucide-react";
import type { SessionsStore } from "@/lib/api";

// Ports app.py's sidebar "Chat History" section, wired to real session CRUD
// (POST/GET/DELETE /api/backend/sessions*). Lives in the "Home" sidebar tab.

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

export default function ChatHistoryList({
  store,
  currentSessionId,
  disabled,
  onNewChat,
  onSwitchSession,
  onDeleteSession,
}: {
  store: SessionsStore | null;
  currentSessionId: string | null;
  disabled: boolean;
  onNewChat: () => void;
  onSwitchSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
}) {
  const order = store?.session_order ?? [];

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onNewChat}
        disabled={disabled}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-foreground px-3 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Plus size={15} />
        New chat
      </button>
      {order.length === 0 ? (
        <p className="px-1 text-xs text-muted">No saved sessions yet.</p>
      ) : (
        <ul className="space-y-0.5">
          {order.map((sid) => {
            const sess = store?.sessions[sid];
            if (!sess) return null;
            const isActive = sid === currentSessionId;
            return (
              <li key={sid} className="group">
                <div
                  className={`flex items-center gap-1 rounded-lg px-2 py-1.5 transition-colors ${
                    isActive ? "bg-muted-soft" : "hover:bg-muted-soft"
                  }`}
                >
                  <button
                    type="button"
                    title={sess.label}
                    disabled={disabled}
                    onClick={() => !isActive && onSwitchSession(sid)}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-not-allowed"
                  >
                    <MessageSquare size={14} className="shrink-0 text-muted" />
                    <span className="min-w-0 flex-1">
                      <span
                        className={`block truncate text-xs ${isActive ? "font-medium text-foreground" : "text-foreground/80"}`}
                      >
                        {sess.label}
                      </span>
                      {sess.created && (
                        <span className="block text-[0.65rem] text-muted">
                          {formatTimestamp(sess.created)}
                        </span>
                      )}
                    </span>
                  </button>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onDeleteSession(sid)}
                    aria-label="Delete chat"
                    className="shrink-0 rounded-md p-1 text-muted opacity-0 transition-opacity group-hover:opacity-100 hover:text-danger disabled:cursor-not-allowed"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
