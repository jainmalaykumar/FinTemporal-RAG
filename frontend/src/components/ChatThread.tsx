"use client";

import { useState } from "react";
import { ChevronDown, Landmark } from "lucide-react";
import type { ChatMessage } from "@/lib/types";

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

  return (
    <div id={`prompt-anchor-${index}`} className="flex items-start gap-3 scroll-mt-6">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-foreground text-background">
        <Landmark size={14} strokeWidth={2} />
      </div>
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
          {message.content}
        </p>
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
                    {chunk}
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
