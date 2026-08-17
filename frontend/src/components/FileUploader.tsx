"use client";

import { useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Upload, X } from "lucide-react";

// Ports app.py's st.file_uploader for PDF/TXT/Excel, wired to a real
// POST /api/backend/ingest/document call (see dashboard/page.tsx for the
// handler that calls ingestDocuments() and updates diagnostics/detected
// company from the response).

const ACCEPTED = ".pdf,.txt,.xlsx,.xls";

type FileStatus = "uploading" | "done" | "error";

const STATUS_ICON: Record<FileStatus, React.ReactNode> = {
  uploading: <Loader2 size={13} className="animate-spin text-muted" />,
  done: <CheckCircle2 size={13} className="text-success" />,
  error: <AlertCircle size={13} className="text-danger" />,
};

export default function FileUploader({
  disabled,
  onFilesSelected,
  onAllRemoved,
}: {
  disabled: boolean;
  onFilesSelected: (files: File[]) => Promise<void>;
  onAllRemoved: () => void;
}) {
  const [entries, setEntries] = useState<{ file: File; status: FileStatus }[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function addFiles(list: FileList | null) {
    if (!list || list.length === 0 || disabled) return;
    const newFiles = Array.from(list);
    setEntries((prev) => [...prev, ...newFiles.map((file) => ({ file, status: "uploading" as const }))]);

    try {
      await onFilesSelected(newFiles);
      setEntries((prev) =>
        prev.map((e) => (newFiles.includes(e.file) ? { ...e, status: "done" as const } : e)),
      );
    } catch {
      setEntries((prev) =>
        prev.map((e) => (newFiles.includes(e.file) ? { ...e, status: "error" as const } : e)),
      );
    }
  }

  function removeFile(file: File) {
    setEntries((prev) => {
      const next = prev.filter((e) => e.file !== file);
      if (next.length === 0) onAllRemoved();
      return next;
    });
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold tracking-wide text-muted uppercase">Knowledge base</p>
      <div
        onClick={() => !disabled && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          addFiles(e.dataTransfer.files);
        }}
        className={`flex flex-col items-center gap-1.5 rounded-lg border border-dashed px-3 py-5 text-center text-xs transition-colors ${
          disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"
        } ${
          dragOver ? "border-foreground/40 bg-muted-soft" : "border-border text-muted hover:border-foreground/25"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED}
          disabled={disabled}
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
        <Upload size={16} className="text-muted" />
        <span>PDF, TXT, or Excel — drag &amp; drop or click to browse</span>
      </div>

      {entries.length > 0 && (
        <ul className="space-y-1">
          {entries.map(({ file, status }) => (
            <li
              key={file.name}
              className="flex items-center justify-between rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs text-foreground"
            >
              <span className="flex min-w-0 items-center gap-1.5">
                {STATUS_ICON[status]}
                <span className="truncate">{file.name}</span>
              </span>
              <button
                type="button"
                onClick={() => removeFile(file)}
                className="ml-2 shrink-0 text-muted hover:text-danger"
                aria-label={`Remove ${file.name}`}
              >
                <X size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
