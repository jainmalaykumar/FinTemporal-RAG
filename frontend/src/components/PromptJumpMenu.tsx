"use client";

import type { ChatMessage } from "@/lib/types";

// ChatGPT-style message navigator: a vertical stack of short horizontal
// ticks on the right edge of the chat, one per user prompt. Clicking (or the
// hover preview) jumps smoothly to that message. Ports app.py's "floating
// prompt jump menu", re-styled to match this app's redesigned chat UI.

export default function PromptJumpMenu({ messages }: { messages: ChatMessage[] }) {
  const prompts = messages
    .map((m, index) => ({ ...m, index }))
    .filter((m) => m.role === "user");

  if (prompts.length < 2) return null;

  function jumpTo(index: number) {
    document
      .getElementById(`prompt-anchor-${index}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  return (
    <div className="pointer-events-none fixed top-1/2 right-3 z-20 hidden -translate-y-1/2 flex-col items-end gap-2 lg:flex">
      {prompts.map((p) => (
        <button
          key={p.index}
          type="button"
          onClick={() => jumpTo(p.index)}
          title={p.content}
          className="group pointer-events-auto flex items-center gap-2"
        >
          <span className="hidden max-w-[200px] truncate rounded-md border border-border bg-card px-2.5 py-1 text-xs text-muted shadow-sm group-hover:block">
            {p.content}
          </span>
          <span className="h-0.5 w-4 rounded-full bg-border transition-all group-hover:w-6 group-hover:bg-brand" />
        </button>
      ))}
    </div>
  );
}
