"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ShieldCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { api, ApiError, describeError } from "@/lib/api";
import { splitAroundExcerpt } from "@/lib/citations";
import type { CitationDetail, DocumentItem, SourceSelection } from "@/lib/types";

function PageImage({ src, alt }: { src: string; alt: string }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  return (
    <div className="relative min-h-40 overflow-hidden rounded-lg border border-line bg-surface-2">
      {state === "loading" && <div className="skeleton absolute inset-0 h-full w-full" aria-hidden />}
      {state === "error" ? (
        <p role="alert" className="p-4 text-sm text-danger">
          The page image could not be loaded.
        </p>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- dynamic, same-origin, cookie-authenticated image
        <img
          key={src}
          src={src}
          alt={alt}
          className="relative block w-full"
          onLoad={() => setState("ready")}
          onError={() => setState("error")}
        />
      )}
    </div>
  );
}

export function SourcePanel({
  selection,
  documents,
  onClose,
}: {
  selection: SourceSelection;
  documents: DocumentItem[];
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<CitationDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [page, setPage] = useState<number | null>(null); // manual page override while inspecting

  useEffect(() => {
    if (selection.kind !== "citation") return;
    let cancelled = false;
    api
      .getCitation(selection.citationId)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(e));
    return () => {
      cancelled = true;
    };
  }, [selection]);

  const documentId = selection.kind === "citation" ? detail?.document_id : selection.documentId;
  const doc = documents.find((d) => d.id === documentId);
  const basePage = selection.kind === "citation" ? detail?.page_number : selection.page;
  const currentPage = page ?? basePage ?? 1;
  const pageCount = doc?.page_count ?? basePage ?? 1;
  const onCitedPage = selection.kind === "citation" && detail && currentPage === detail.page_number;

  const missing = error instanceof ApiError && error.status === 404;

  return (
    <aside aria-label="Source inspector" className="flex h-full min-h-0 flex-col bg-paper">
      <header className="flex items-center gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-serif text-base font-semibold">Source</h2>
          <p className="truncate text-xs text-muted">
            {detail ? detail.document_name : doc?.name ?? (error ? "Unavailable" : "Loading…")}
            {basePage ? ` · page ${currentPage}` : ""}
          </p>
        </div>
        <Button variant="ghost" size="icon" aria-label="Close source panel" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {Boolean(error) && (
          <Notice tone={missing ? "warn" : "error"} title={missing ? "Source no longer available" : describeError(error).title}>
            {missing
              ? "This passage can't be shown because the document was deleted or re-indexed."
              : describeError(error).message}
          </Notice>
        )}

        {selection.kind === "citation" && !detail && !error && (
          <div className="space-y-2" aria-label="Loading source">
            <div className="skeleton h-4 w-2/3" />
            <div className="skeleton h-24 w-full" />
            <div className="skeleton h-64 w-full" />
          </div>
        )}

        {detail && (
          <section aria-label="Supporting excerpt">
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
              <ShieldCheck className="h-3.5 w-3.5 text-ok" aria-hidden />
              Retrieved passage ({detail.label}) · {detail.quote_verified ? "quote verified in text" : "model quote not verified; showing passage start"}
            </p>
            <blockquote className="rounded-lg border border-line bg-surface p-3 text-sm leading-relaxed" data-testid="source-excerpt">
              {(() => {
                const parts = detail.quote_verified ? splitAroundExcerpt(detail.chunk_text, detail.excerpt) : null;
                return parts ? (
                  <>
                    {parts[0]}
                    <mark className="rounded bg-[var(--mark)] px-0.5 text-ink">{parts[1]}</mark>
                    {parts[2]}
                  </>
                ) : (
                  detail.chunk_text
                );
              })()}
            </blockquote>
          </section>
        )}

        {documentId && basePage && (
          <section aria-label="Page preview">
            <div className="mb-1.5 flex items-center justify-between">
              <p className="text-xs font-medium text-muted">
                Page {currentPage} of {pageCount}
                {onCitedPage ? " · highlighted" : ""}
              </p>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" aria-label="Previous page" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" aria-label="Next page" disabled={currentPage >= pageCount} onClick={() => setPage(currentPage + 1)}>
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <PageImage
              src={
                onCitedPage && detail
                  ? detail.page_image_url
                  : api.pageImageUrl(documentId, currentPage)
              }
              alt={`Page ${currentPage} of ${detail?.document_name ?? doc?.name ?? "document"}`}
            />
          </section>
        )}
      </div>
    </aside>
  );
}
