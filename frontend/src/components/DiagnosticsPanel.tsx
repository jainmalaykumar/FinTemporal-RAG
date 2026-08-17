"use client";

import { useEffect, useState } from "react";
import { ChevronDown, CircleDot, Trash2 } from "lucide-react";
import type { Diagnostics } from "@/lib/api";

// Ports app.py's "System Diagnostics" expander, wired to
// GET /api/backend/diagnostics and POST /api/backend/data/clear.

export default function DiagnosticsPanel({
  diagnostics,
  onExpand,
  onClearData,
  clearing,
}: {
  diagnostics: Diagnostics | null;
  onExpand: () => void;
  onClearData: () => void;
  clearing: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return;
    onExpand();
    // Refresh once per expand; parent owns the actual fetch/cache.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded]);

  const granular = diagnostics && "youtube_chunks" in diagnostics;

  return (
    <div className="rounded-xl border border-border bg-card">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-foreground"
      >
        <span>Diagnostics</span>
        <ChevronDown size={16} className={`text-muted transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>
      {expanded && (
        <div className="space-y-3 border-t border-border p-4">
          <p className="flex items-center gap-1.5 text-xs font-medium text-success">
            <CircleDot size={12} />
            Server connected
          </p>
          {!diagnostics ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : granular ? (
            <>
              <div className="grid grid-cols-2 gap-3 text-center">
                <div>
                  <p className="text-xs text-muted">Video chunks</p>
                  <p className="text-lg font-semibold text-foreground">{diagnostics.youtube_chunks}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Doc chunks</p>
                  <p className="text-lg font-semibold text-foreground">{diagnostics.document_chunks}</p>
                </div>
              </div>
              <div className="text-center">
                <p className="text-xs text-muted">Live market</p>
                <p className="text-lg font-semibold text-foreground">{diagnostics.market_chunks}</p>
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 text-center">
                <div>
                  <p className="text-xs text-muted">Total doc chunks</p>
                  <p className="text-lg font-semibold text-foreground">{diagnostics.uploaded_documents}</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Market chunks</p>
                  <p className="text-lg font-semibold text-foreground">{diagnostics.market_data}</p>
                </div>
              </div>
              {diagnostics.granular_unavailable_reason && (
                <p className="text-xs text-muted">
                  Granular split unavailable: {diagnostics.granular_unavailable_reason}
                </p>
              )}
            </>
          )}

          <div className="border-t border-border pt-3">
            <button
              type="button"
              onClick={onClearData}
              disabled={clearing}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-danger/20 bg-danger-soft px-3 py-1.5 text-sm font-medium text-danger transition-colors hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Trash2 size={14} />
              {clearing ? "Purging…" : "Clear all data"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
