"use client";

import { AlertCircle, CheckCircle2, Eye, FileText, Loader2, RotateCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import type { DocumentItem } from "@/lib/types";

const STAGE_LABEL: Record<string, string> = {
  extracting: "Extracting text…",
  embedding: "Embedding passages",
  indexing: "Writing to index…",
};

export function statusLabel(doc: DocumentItem): string {
  switch (doc.status) {
    case "queued":
      return "Queued for indexing";
    case "processing": {
      const base = STAGE_LABEL[doc.stage ?? ""] ?? "Processing…";
      return doc.stage === "embedding" && doc.progress ? `${base} ${doc.progress.current}/${doc.progress.total}` : base;
    }
    case "ready":
      return `Indexed · ${doc.page_count} page${doc.page_count === 1 ? "" : "s"} · ${doc.chunk_count} passages`;
    case "failed":
      return "Indexing failed";
  }
}

export function DocumentRow({
  doc,
  onPreview,
  onDelete,
  onRetry,
  retrying,
}: {
  doc: DocumentItem;
  onPreview: (doc: DocumentItem) => void;
  onDelete: (doc: DocumentItem) => void;
  onRetry: (doc: DocumentItem) => void;
  retrying?: boolean;
}) {
  const inFlight = doc.status === "queued" || doc.status === "processing";
  return (
    <li className="rounded-lg border border-line bg-surface p-2.5" data-testid="document-row" data-status={doc.status}>
      <div className="flex items-start gap-2">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={doc.name}>
            {doc.name}
          </p>
          <p className="mt-0.5 text-xs text-muted" aria-live="polite">
            {inFlight && <Loader2 className="mr-1 inline h-3 w-3 animate-spin align-[-2px]" aria-hidden />}
            {doc.status === "ready" && <CheckCircle2 className="mr-1 inline h-3 w-3 align-[-2px] text-ok" aria-hidden />}
            {doc.status === "failed" && <AlertCircle className="mr-1 inline h-3 w-3 align-[-2px] text-danger" aria-hidden />}
            {statusLabel(doc)} · {formatBytes(doc.size_bytes)}
          </p>
        </div>
        <div className="flex shrink-0 gap-0.5">
          {doc.status === "ready" && (
            <Button variant="ghost" size="icon" aria-label={`Preview ${doc.name}`} title="Preview" onClick={() => onPreview(doc)}>
              <Eye className="h-4 w-4" />
            </Button>
          )}
          <Button variant="ghost" size="icon" aria-label={`Delete ${doc.name}`} title="Delete" onClick={() => onDelete(doc)}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
      {doc.status === "processing" && doc.stage === "embedding" && doc.progress && doc.progress.total > 0 && (
        <div
          role="progressbar"
          aria-label={`Indexing ${doc.name}`}
          aria-valuemin={0}
          aria-valuemax={doc.progress.total}
          aria-valuenow={doc.progress.current}
          className="mt-2 h-1 overflow-hidden rounded bg-surface-2"
        >
          <div className="h-full bg-accent transition-all" style={{ width: `${(doc.progress.current / doc.progress.total) * 100}%` }} />
        </div>
      )}
      {doc.status === "failed" && doc.error && (
        <div className="mt-2 rounded-md bg-danger-soft p-2 text-xs" role="alert">
          <p className="break-words">{doc.error.message}</p>
          {doc.error.retryable && (
            <Button size="sm" className="mt-2" onClick={() => onRetry(doc)} disabled={retrying}>
              <RotateCw className={retrying ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} aria-hidden />
              Retry indexing
            </Button>
          )}
        </div>
      )}
    </li>
  );
}
