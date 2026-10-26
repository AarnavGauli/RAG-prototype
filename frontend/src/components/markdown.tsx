"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CITE_PREFIX, linkCitations } from "@/lib/citations";
import type { Citation } from "@/lib/types";

/**
 * Renders model output. Raw HTML in the Markdown is NOT interpreted (no rehype-raw), images are never loaded,
 * and react-markdown's URL transform removes javascript:/data: links.
 */
export function AnswerMarkdown({
  content,
  citations,
  onOpenCitation,
}: {
  content: string;
  citations: Citation[];
  onOpenCitation: (citation: Citation) => void;
}) {
  const byId = new Map(citations.map((c) => [c.id, c]));
  const components: Components = {
    a({ href, children }) {
      if (href?.startsWith(CITE_PREFIX)) {
        const citation = byId.get(href.slice(CITE_PREFIX.length));
        if (!citation) return null;
        return (
          <button
            type="button"
            onClick={() => onOpenCitation(citation)}
            aria-label={`Open source ${citation.label}: ${citation.document_name}, page ${citation.page_number}`}
            title={`${citation.document_name} · page ${citation.page_number}`}
            className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded bg-accent-soft px-1 align-baseline text-xs font-semibold text-accent no-underline hover:bg-accent hover:text-accent-ink"
          >
            {children}
          </button>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow">
          {children}
        </a>
      );
    },
    img: () => null,
  };
  return (
    <div className="prose-answer">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {linkCitations(content, citations)}
      </ReactMarkdown>
    </div>
  );
}
