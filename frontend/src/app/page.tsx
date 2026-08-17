import {
  ArrowUp,
  Briefcase,
  Clock,
  FolderLock,
  GraduationCap,
  Landmark,
  LineChart,
  ListChecks,
  MessageSquare,
  Radio,
  Shuffle,
  TrendingUp,
} from "lucide-react";
import { signIn } from "@/auth";

// Landing page — content ported from app.py's render_landing_page(), redesigned
// with a restrained, professional palette (no colorful cards, no emoji icons).
// The "Sign In" button triggers Auth.js's Google OAuth flow (replacing app.py's
// manual OAuth2Component + unverified JWT decode).

const STATS = [
  { label: "Stocks covered", value: "500+", help: "Full Nifty 500 index searchable" },
  { label: "Data sources", value: "3", help: "Yahoo Finance · GNews · Your uploads" },
  { label: "Query templates", value: "12", help: "Pre-built fundamental analysis queries" },
  { label: "Data isolation", value: "100%", help: "Per-user ChromaDB collections via OAuth" },
];

const WHY_CARDS = [
  {
    icon: Briefcase,
    title: "For financial analysts",
    body: "Stop copy-pasting numbers from PDFs. Upload a Screener.in Excel export or an SEBI annual report and ask plain-English questions. The AI fuses tables and narrative into a single grounded answer, with citations from the retrieved chunks.",
  },
  {
    icon: LineChart,
    title: "For retail investors",
    body: "The internet is full of stale data. FinTemporal RAG fetches live Yahoo Finance metrics at query time and ranks retrieved context by age, so you always see the most recent quarter first, not a 2019 filing buried in the index.",
  },
  {
    icon: GraduationCap,
    title: "For M.Tech / MBA research",
    body: "Need to benchmark operating margins, map dividend history, or identify risk factors across five years of reports? Use the 12 structured query templates as a research accelerator, each backed by an explicit extract → derive → refuse logic chain.",
  },
];

const CAPABILITIES = [
  { icon: Radio, title: "Chat with live market data", body: "Type any Nifty 500 ticker and ask earnings, valuation, or governance questions backed by real-time Yahoo Finance and GNews retrieval." },
  { icon: FolderLock, title: "Upload private documents", body: "Your PDFs and Excel sheets are ingested into your own isolated ChromaDB collection — no other user can see or query your files." },
  { icon: Shuffle, title: "Switch between Hybrid and BYOD modes", body: "Hybrid blends live data with your uploads; BYOD sandboxes the AI strictly to your documents only." },
  { icon: Clock, title: "Temporal re-ranking", body: "Every retrieved chunk carries a recency score so a Q4-2024 filing always outranks a Q2-2022 chunk, even if both are semantically similar." },
  { icon: MessageSquare, title: "Persistent chat history", body: "Your conversation survives page refreshes and browser restarts — log out, come back later, and pick up where you left off." },
  { icon: ListChecks, title: "12 structured query templates", body: "Pre-engineered prompts for PEG ratio, D/E ratio, ROE, FCF trend, segment revenue, dividend history, and more." },
];

export default function LandingPage() {
  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2">
            <TrendingUp size={20} className="text-foreground" strokeWidth={2} />
            <span className="text-base font-semibold text-foreground">FinTemporal RAG</span>
          </div>
          <form
            action={async () => {
              "use server";
              await signIn("google", { redirectTo: "/dashboard" });
            }}
          >
            <button
              type="submit"
              className="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-85"
            >
              Sign in
            </button>
          </form>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-16">
        <h1 className="mx-auto max-w-2xl text-center text-3xl font-semibold tracking-tight text-foreground">
          Your private, hallucination-guarded financial co-pilot
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-center text-base text-muted">
          Live NSE/BSE market data fused with your own annual reports, ranked by recency.
        </p>

        {/* ── Product preview — built from the exact same tokens/components as the
             real dashboard (Sidebar tabs, chat bubbles, pill input) so this is a
             genuine preview of the theme, not a mocked-up marketing screenshot. */}
        <div className="mt-12 overflow-hidden rounded-2xl border border-border shadow-sm">
          <div className="flex h-[420px]">
            <div className="hidden w-56 shrink-0 flex-col border-r border-border bg-sidebar p-4 sm:flex">
              <div className="flex gap-1">
                <div className="flex-1 rounded-lg bg-card px-3 py-1.5 text-center text-xs font-medium text-foreground shadow-sm">
                  Home
                </div>
                <div className="flex-1 rounded-lg px-3 py-1.5 text-center text-xs text-muted">
                  Sources
                </div>
              </div>
              <div className="mt-4 flex items-center justify-center gap-1.5 rounded-lg bg-foreground px-3 py-2 text-xs font-medium text-background">
                New chat
              </div>
              <div className="mt-3 space-y-1">
                <div className="rounded-lg bg-card px-2.5 py-1.5 text-xs font-medium text-foreground shadow-sm">
                  RELIANCE.NS — Debt-to-Equity ratio
                </div>
                <div className="rounded-lg px-2.5 py-1.5 text-xs text-muted">
                  TCS.NS — Q1 results summary
                </div>
                <div className="rounded-lg px-2.5 py-1.5 text-xs text-muted">
                  HDFCBANK.NS — Dividend history
                </div>
              </div>
            </div>
            <div className="flex flex-1 flex-col justify-between p-6">
              <div className="space-y-4">
                <div className="flex justify-end">
                  <div className="max-w-[75%] rounded-2xl bg-muted-soft px-4 py-2 text-sm text-foreground">
                    What is the Debt-to-Equity ratio?
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-foreground text-background">
                    <Landmark size={14} strokeWidth={2} />
                  </div>
                  <p className="max-w-[85%] pt-0.5 text-sm leading-relaxed text-foreground">
                    The Debt-to-Equity ratio for RELIANCE.NS is 0.41, based on the latest FY2025
                    balance sheet — extracted directly from your uploaded annual report.
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 rounded-full border border-border bg-card py-1.5 pr-1.5 pl-4 shadow-sm">
                <span className="flex-1 text-sm text-muted">
                  Ask a question about the selected stock…
                </span>
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background">
                  <ArrowUp size={16} strokeWidth={2.5} />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-16 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label} title={s.help} className="bg-card p-5">
              <p className="text-2xl font-semibold text-foreground">{s.value}</p>
              <p className="mt-1 text-xs text-muted">{s.label}</p>
            </div>
          ))}
        </div>

        <section className="mt-20">
          <h2 className="text-lg font-semibold text-foreground">Why FinTemporal RAG</h2>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {WHY_CARDS.map((c) => (
              <div key={c.title} className="rounded-xl border border-border p-5">
                <c.icon size={18} className="text-muted" strokeWidth={1.75} />
                <p className="mt-3 text-sm font-medium text-foreground">{c.title}</p>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{c.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-16">
          <h2 className="text-lg font-semibold text-foreground">What you can do once you sign in</h2>
          <div className="mt-6 grid gap-x-8 gap-y-6 sm:grid-cols-2">
            {CAPABILITIES.map((c) => (
              <div key={c.title} className="flex gap-3">
                <c.icon size={17} className="mt-0.5 shrink-0 text-muted" strokeWidth={1.75} />
                <div>
                  <p className="text-sm font-medium text-foreground">{c.title}</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-muted">{c.body}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <p className="mt-20 border-t border-border pt-6 text-center text-xs text-muted">
          Built with Next.js, FastAPI, ChromaDB &amp; Sentence-Transformers · Indian fiscal year
          aware ·
        </p>
      </main>
    </div>
  );
}
