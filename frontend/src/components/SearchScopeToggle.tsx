"use client";

import { FileText, Globe, Video } from "lucide-react";
import type { SearchScope } from "@/lib/types";

const OPTIONS: { value: SearchScope; label: string; help: string; icon: typeof Globe }[] = [
  {
    value: "all",
    label: "All sources",
    help: "Hybrid retrieval: live market data + full vector DB.",
    icon: Globe,
  },
  {
    value: "youtube",
    label: "YouTube only",
    help: "Queries only ingested transcript chunks.",
    icon: Video,
  },
  {
    value: "docs",
    label: "Documents only",
    help: "Queries only uploaded PDF/Excel files.",
    icon: FileText,
  },
];

export default function SearchScopeToggle({
  value,
  onChange,
}: {
  value: SearchScope;
  onChange: (scope: SearchScope) => void;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold tracking-wide text-muted uppercase">Search scope</p>
      <div className="space-y-1">
        {OPTIONS.map((opt) => {
          const Icon = opt.icon;
          const active = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              title={opt.help}
              onClick={() => onChange(opt.value)}
              className={`flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                active
                  ? "border-foreground/20 bg-muted-soft text-foreground"
                  : "border-transparent text-muted hover:bg-muted-soft"
              }`}
            >
              <Icon size={15} className={active ? "text-foreground" : "text-muted"} />
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
