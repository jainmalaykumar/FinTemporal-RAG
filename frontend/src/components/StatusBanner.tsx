"use client";

import { AlertTriangle, CheckCircle2, X, XCircle } from "lucide-react";
import type { StatusMessage } from "@/lib/types";

const STYLES: Record<StatusMessage["type"], string> = {
  success: "bg-success-soft border-success/20 text-success",
  warning: "bg-warning-soft border-warning/20 text-warning",
  error: "bg-danger-soft border-danger/20 text-danger",
};

const ICONS: Record<StatusMessage["type"], typeof CheckCircle2> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
};

export default function StatusBanner({
  message,
  onDismiss,
}: {
  message: StatusMessage;
  onDismiss: () => void;
}) {
  const Icon = ICONS[message.type];
  return (
    <div
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${STYLES[message.type]}`}
    >
      <Icon size={15} className="mt-0.5 shrink-0" />
      <span className="flex-1 text-foreground">{message.text}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 text-muted opacity-60 hover:opacity-100"
      >
        <X size={14} />
      </button>
    </div>
  );
}
