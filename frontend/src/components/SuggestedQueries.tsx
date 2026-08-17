"use client";

import { useEffect, useState } from "react";
import { ChevronDown, Lightbulb } from "lucide-react";
import { fetchQueryTemplates } from "@/lib/api";

const TAB_META: Record<string, string> = {
  valuation: "Valuation",
  performance: "Performance",
  market: "Market",
  governance: "Governance",
};
const TAB_ORDER = ["valuation", "performance", "market", "governance"];

export default function SuggestedQueries({
  onSelect,
}: {
  // display label (shown in chat) and the enriched guardrail prompt actually
  // sent to the LLM — mirrors app.py's pending_query = {display, llm} split.
  onSelect: (display: string, queryText: string) => void;
}) {
  const [tabs, setTabs] = useState<Record<string, string[]>>({});
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [activeTab, setActiveTab] = useState("valuation");
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetchQueryTemplates()
      .then((data) => {
        setTabs(data.tabs);
        setPrompts(data.prompts);
      })
      .catch(() => setTabs({}));
  }, []);

  return (
    <div className="rounded-xl border border-border bg-card">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-foreground"
      >
        <span className="flex items-center gap-2">
          <Lightbulb size={16} className="text-muted" />
          Suggested queries
        </span>
        <ChevronDown size={16} className={`text-muted transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>
      {expanded && (
        <div className="border-t border-border p-4">
          <div className="mb-3 flex gap-1.5 overflow-x-auto">
            {TAB_ORDER.map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setActiveTab(key)}
                className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  activeTab === key
                    ? "bg-foreground text-background"
                    : "bg-muted-soft text-muted hover:text-foreground"
                }`}
              >
                {TAB_META[key]}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {(tabs[activeTab] ?? []).map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => onSelect(q, prompts[q] ?? q)}
                className="rounded-lg border border-border px-3 py-2 text-left text-xs text-foreground transition-colors hover:border-foreground/30 hover:bg-muted-soft"
              >
                {q}
              </button>
            ))}
            {tabs[activeTab] === undefined && (
              <p className="text-xs text-muted">Loading query templates…</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
