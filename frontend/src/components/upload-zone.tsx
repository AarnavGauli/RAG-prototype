"use client";

import { useCallback, useId, useRef, useState } from "react";
import { FileUp, Loader2, X } from "lucide-react";
import { api, describeError } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { validateFile } from "@/lib/validate";
import { cn } from "@/lib/cn";
import type { DocumentItem } from "@/lib/types";

interface UploadEntry {
  id: number;
  file: File;
  state: "uploading" | "error";
  progress: number;
  error?: string;
}

let counter = 0;

export function UploadZone({
  maxMb,
  disabled,
  disabledReason,
  onUploaded,
}: {
  maxMb: number;
  disabled?: boolean;
  disabledReason?: string;
  onUploaded: (doc: DocumentItem) => void;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [entries, setEntries] = useState<UploadEntry[]>([]);

  const patch = useCallback((id: number, update: Partial<UploadEntry>) => {
    setEntries((list) => list.map((e) => (e.id === id ? { ...e, ...update } : e)));
  }, []);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const id = ++counter;
        const check = validateFile(file, maxMb);
        if (!check.ok) {
          setEntries((l) => [...l, { id, file, state: "error", progress: 0, error: check.error }]);
          continue;
        }
        setEntries((l) => [...l, { id, file, state: "uploading", progress: 0 }]);
        try {
          const doc = await api.uploadDocument(file, (p) => patch(id, { progress: p }));
          setEntries((l) => l.filter((e) => e.id !== id));
          onUploaded(doc);
        } catch (err) {
          patch(id, { state: "error", error: describeError(err).message });
        }
      }
    },
    [maxMb, onUploaded, patch],
  );

  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          if (disabled) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled && e.dataTransfer.files.length) void handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-1 rounded-xl border border-dashed px-3 py-4 text-center text-sm transition-colors focus-within:outline-2 focus-within:outline-accent",
          dragging ? "border-accent bg-accent-soft" : "border-line bg-surface hover:bg-surface-2",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <FileUp className="h-5 w-5 text-accent" aria-hidden />
        <span className="font-medium">{dragging ? "Drop PDF to upload" : "Upload PDFs"}</span>
        <span className="text-xs text-muted">
          {disabled ? disabledReason : `Drag & drop or click · up to ${maxMb} MB each`}
        </span>
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          disabled={disabled}
          className="sr-only"
          onChange={(e) => {
            if (e.target.files?.length) void handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </label>

      {entries.length > 0 && (
        <ul className="mt-2 space-y-1.5" aria-label="Uploads in progress">
          {entries.map((e) => (
            <li key={e.id} className="rounded-lg border border-line bg-surface px-3 py-2 text-xs">
              <div className="flex items-center gap-2">
                {e.state === "uploading" ? (
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" aria-hidden />
                ) : (
                  <X className="h-3.5 w-3.5 shrink-0 text-danger" aria-hidden />
                )}
                <span className="min-w-0 flex-1 truncate font-medium">{e.file.name}</span>
                <span className="text-muted">{formatBytes(e.file.size)}</span>
                {e.state === "error" && (
                  <button
                    type="button"
                    aria-label={`Dismiss error for ${e.file.name}`}
                    className="rounded p-0.5 text-muted hover:text-ink"
                    onClick={() => setEntries((l) => l.filter((x) => x.id !== e.id))}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              {e.state === "uploading" ? (
                <div
                  role="progressbar"
                  aria-label={`Uploading ${e.file.name}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(e.progress * 100)}
                  className="mt-1.5 h-1 overflow-hidden rounded bg-surface-2"
                >
                  <div className="h-full bg-accent transition-all" style={{ width: `${Math.round(e.progress * 100)}%` }} />
                </div>
              ) : (
                <p role="alert" className="mt-1 text-danger">
                  {e.error}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
