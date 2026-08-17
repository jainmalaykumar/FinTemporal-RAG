"use client";

import { useState } from "react";
import { Loader2, Video } from "lucide-react";
import { ApiError, ingestYoutube } from "@/lib/api";
import type { StatusMessage } from "@/lib/types";

// Ports app.py's "YouTube News Ingestion" panel, wired to a real
// POST /api/backend/ingest/youtube call.

export default function YoutubeIngestForm({
  disabled,
  activeCompany,
  onStatus,
  onIngested,
}: {
  disabled: boolean;
  activeCompany: string;
  onStatus: (status: StatusMessage) => void;
  onIngested: () => void;
}) {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleIngest() {
    if (!url.trim()) {
      onStatus({ type: "warning", text: "Please paste a YouTube URL first." });
      return;
    }
    setLoading(true);
    try {
      const result = await ingestYoutube(url.trim(), activeCompany);
      const title = result.metadata?.title ?? "video";
      const channel = result.metadata?.channel ?? "Unknown channel";
      const pubDate = result.metadata?.publish_date ?? "";
      if (result.chunks) {
        if (result.warning) {
          onStatus({
            type: "warning",
            text: `Ingested with a warning: ${result.warning} — ${result.chunks} chunks from "${title}" (${channel} · ${pubDate})`,
          });
        } else {
          onStatus({
            type: "success",
            text: `Ingested ${result.chunks} chunks from "${title}" (${channel} · ${pubDate})`,
          });
        }
        onIngested();
        setUrl("");
      } else {
        onStatus({ type: "warning", text: "No transcript content was produced for this video." });
      }
    } catch (err) {
      // Surface whatever actually went wrong (e.g. a dropped connection on a
      // long-running ingest) instead of a generic message that can't be
      // diagnosed later.
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? `Unexpected error during ingestion: ${err.message}`
            : "Unexpected error during ingestion.";
      onStatus({ type: "error", text: message });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold tracking-wide text-muted uppercase">YouTube ingestion</p>
      <input
        type="text"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        disabled={disabled || loading}
        placeholder="https://youtube.com/watch?v=…"
        className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted focus:border-foreground/30 focus:outline-none disabled:opacity-50"
      />
      <button
        type="button"
        onClick={handleIngest}
        disabled={disabled || loading}
        className="flex w-full items-center justify-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-muted-soft disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? (
          <>
            <Loader2 size={14} className="animate-spin" />
            Running gatekeeper…
          </>
        ) : (
          <>
            <Video size={14} className="text-muted" />
            Ingest video
          </>
        )}
      </button>
    </div>
  );
}
