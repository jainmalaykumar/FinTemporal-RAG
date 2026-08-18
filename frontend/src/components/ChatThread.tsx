"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, Clock, Landmark } from "lucide-react";
import type { ChatMessage } from "@/lib/types";

// Pulls the numeric figures out of the LLM's answer (e.g. "0.41", "45.8%")
// so the "Retrieved context" viewer can highlight exactly where each cited
// number came from — connecting the claim to its source, not just showing
// the whole chunk and asking the reader to find it themselves.
function extractFigures(text: string): string[] {
  const matches = text.match(/\d[\d,]*\.?\d*%?/g) ?? [];
  const seen = new Set<string>();
  for (const m of matches) {
    const digitsOnly = m.replace(/\D/g, "");
    const isDecimalOrPercent = m.includes(".") || m.includes("%");
    // Skip trivial matches — a bare "3" or "12" is too generic to be a
    // meaningful citation anchor; require either a decimal/percent sign or
    // at least 3 significant digits.
    if (isDecimalOrPercent || digitsOnly.length >= 3) {
      seen.add(m);
    }
  }
  return Array.from(seen).sort((a, b) => b.length - a.length);
}

function highlightFigures(chunkText: string, figures: string[]): ReactNode {
  if (figures.length === 0) return chunkText;
  const escaped = figures.map((f) => f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp(`(${escaped.join("|")})`, "g");
  return chunkText.split(pattern).map((part, i) =>
    figures.includes(part) ? (
      <mark key={i} className="rounded bg-warning-soft px-0.5 text-foreground">
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

function MessageBubble({ message, index }: { message: ChatMessage; index: number }) {
  const [showContext, setShowContext] = useState(false);
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div id={`prompt-anchor-${index}`} className="flex justify-end scroll-mt-6">
        <div className="max-w-[70%] rounded-2xl bg-muted-soft px-4 py-2.5 text-sm text-foreground">
          {message.content}
        </div>
      </div>
    );
  }

  const figures = extractFigures(message.content);

  return (
    <div id={`prompt-anchor-${index}`} className="flex items-start gap-3 scroll-mt-6">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-foreground text-background">
        <Landmark size={14} strokeWidth={2} />
      </div>
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
          {message.content}
        </p>
        {message.data_freshness && (
          <p className="mt-1 flex items-center gap-1 text-xs text-muted">
            <Clock size={11} />
            {message.data_freshness}
          </p>
        )}
        {message.context && message.context.length > 0 && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setShowContext((v) => !v)}
              className="flex items-center gap-1 text-xs font-medium text-muted transition-colors hover:text-foreground"
            >
              <ChevronDown
                size={14}
                className={`transition-transform ${showContext ? "rotate-180" : ""}`}
              />
              Retrieved context
            </button>
            {showContext && (
              <div className="mt-2 space-y-2 rounded-lg border border-border bg-sidebar p-3">
                {message.context.map((chunk, i) => (
                  <p key={i} className="whitespace-pre-wrap text-xs text-muted">
                    {highlightFigures(chunk, figures)}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatThread({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-muted">
        Ask a question about the selected stock to get started.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} index={i} />
      ))}
    </div>
  );
}
