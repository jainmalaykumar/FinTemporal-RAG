"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { fetchStocks } from "@/lib/api";
import { CUSTOM_STOCK_SENTINEL } from "@/lib/types";

// Ports app.py's sidebar "Target Asset" block: a type-to-filter combobox over
// NIFTY_500_STOCKS (served live from GET /api/stocks), falling back to a free
// -text custom ticker input when the CUSTOM sentinel is chosen.

export default function StockSelector({
  value,
  onChange,
}: {
  value: string;
  onChange: (ticker: string) => void;
}) {
  const [stocks, setStocks] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [customTicker, setCustomTicker] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchStocks()
      .then(setStocks)
      .catch(() => setStocks([]));
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const filtered = useMemo(() => {
    if (!query.trim()) return stocks.slice(0, 50);
    const q = query.toLowerCase();
    return stocks.filter((s) => s.toLowerCase().includes(q)).slice(0, 50);
  }, [stocks, query]);

  function selectOption(option: string) {
    setSelectedOption(option);
    setQuery(option);
    setOpen(false);
    if (option === CUSTOM_STOCK_SENTINEL) {
      onChange(customTicker ? normalizeCustom(customTicker) : "CUSTOM");
    } else {
      onChange(option.split(" - ")[0]);
    }
  }

  function normalizeCustom(raw: string) {
    const upper = raw.trim().toUpperCase();
    if (!upper) return "CUSTOM";
    return upper.endsWith(".NS") || upper.endsWith(".BO") ? upper : `${upper}.NS`;
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold tracking-wide text-muted uppercase">Target asset</p>
      <div ref={containerRef} className="relative">
        <Search size={14} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder="Search Nifty 500 stocks"
          className="w-full rounded-lg border border-border bg-card py-2 pr-3 pl-8 text-sm text-foreground placeholder:text-muted focus:border-foreground/30 focus:outline-none"
        />
        {open && filtered.length > 0 && (
          <ul className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-border bg-card shadow-lg">
            {filtered.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  onClick={() => selectOption(s)}
                  className="block w-full truncate px-3 py-2 text-left text-sm text-foreground hover:bg-muted-soft"
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {selectedOption === CUSTOM_STOCK_SENTINEL && (
        <input
          type="text"
          value={customTicker}
          onChange={(e) => {
            setCustomTicker(e.target.value);
            onChange(normalizeCustom(e.target.value));
          }}
          placeholder="TATACAPITAL"
          className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground uppercase placeholder:text-muted focus:border-foreground/30 focus:outline-none"
        />
      )}

      <p className="text-xs text-muted">
        Selected <span className="font-medium text-foreground">{value || "—"}</span>
      </p>
    </div>
  );
}
