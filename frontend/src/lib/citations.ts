import type { Citation } from "./types";

export const CITE_PREFIX = "#cite:";

/**
 * Turns `[S1]` markers in an answer into Markdown links to the *validated* citations of that message.
 * Markers that do not correspond to a stored citation are dropped, so the UI can never show a link
 * that is not backed by retrieved evidence.
 */
export function linkCitations(content: string, citations: Citation[]): string {
  const byLabel = new Map(citations.map((c) => [c.label, c]));
  return content.replace(/([ \t]*)\[(S\d+)\]/g, (_, space: string, label: string) => {
    const c = byLabel.get(label);
    return c ? `${space}[${label}](${CITE_PREFIX}${c.id})` : "";
  });
}

/** Splits `chunk` into [before, match, after] around the excerpt so the supporting text can be highlighted. */
export function splitAroundExcerpt(chunk: string, excerpt: string): [string, string, string] | null {
  const core = excerpt.replace(/^…/, "").replace(/…$/, "").trim();
  if (core.length < 8) return null;
  const i = chunk.indexOf(core);
  if (i === -1) return null;
  return [chunk.slice(0, i), core, chunk.slice(i + core.length)];
}
