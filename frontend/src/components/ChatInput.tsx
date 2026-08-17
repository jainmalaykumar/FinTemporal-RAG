"use client";

import { useState, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";

export default function ChatInput({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") submit();
  }

  return (
    <div className="flex items-center gap-2 rounded-full border border-border bg-card py-1.5 pr-1.5 pl-4 shadow-sm">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="Ask a question about the selected stock…"
        className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted focus:outline-none disabled:opacity-50"
      />
      <button
        type="button"
        onClick={submit}
        disabled={disabled || !value.trim()}
        aria-label="Send"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ArrowUp size={16} strokeWidth={2.5} />
      </button>
    </div>
  );
}
