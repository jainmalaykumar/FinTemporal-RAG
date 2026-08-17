export type SearchScope = "all" | "youtube" | "docs";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  context?: string[];
}

export interface ChatSessionSummary {
  id: string;
  label: string;
  created: string;
}

export interface StatusMessage {
  type: "success" | "warning" | "error";
  text: string;
}

export const CUSTOM_STOCK_SENTINEL = "CUSTOM / OTHER (Enter Custom Ticker)";
