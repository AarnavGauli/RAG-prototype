import { describe, expect, it } from "vitest";
import { linkCitations, splitAroundExcerpt } from "@/lib/citations";
import { describeError, ApiError } from "@/lib/api";
import { formatBytes, relativeTime } from "@/lib/format";
import { validateFile } from "@/lib/validate";
import type { Citation } from "@/lib/types";

const file = (name: string, size: number, type = "application/pdf") => new File([new Uint8Array(size)], name, { type });
const cit = (label: string, id: string): Citation => ({
  id, label, document_id: "d", document_name: "a.pdf", page_number: 2, excerpt: "x", quote_verified: true, score: 0.9,
});

describe("validateFile", () => {
  it("accepts a normal PDF", () => expect(validateFile(file("a.pdf", 100), 20).ok).toBe(true));
  it("rejects non-PDF files", () => {
    const r = validateFile(file("a.txt", 100, "text/plain"), 20);
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/not a PDF/);
  });
  it("rejects empty and oversized files", () => {
    expect(validateFile(file("a.pdf", 0), 20).error).toMatch(/empty/);
    expect(validateFile(file("big.pdf", 3 * 1024 * 1024), 2).error).toMatch(/limit is 2 MB/);
  });
  it("accepts a .pdf name even with a generic mime type", () => {
    expect(validateFile(file("scan.PDF", 10, "application/octet-stream"), 20).ok).toBe(true);
  });
});

describe("linkCitations", () => {
  it("links known markers and drops unknown ones without touching other text", () => {
    const out = linkCitations("Use an .edu address [S1] and more [S9].", [cit("S1", "cit_1")]);
    expect(out).toBe("Use an .edu address [S1](#cite:cit_1) and more.");
  });
});

describe("splitAroundExcerpt", () => {
  it("splits around the excerpt, ignoring ellipses", () => {
    expect(splitAroundExcerpt("before the quote here after", "…the quote here…")).toEqual(["before ", "the quote here", " after"]);
  });
  it("returns null when the excerpt is not in the chunk or too short", () => {
    expect(splitAroundExcerpt("abc def", "missing text here")).toBeNull();
    expect(splitAroundExcerpt("abc def", "abc")).toBeNull();
  });
});

describe("formatting and error messages", () => {
  it("formats sizes and times", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("2 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(relativeTime(new Date(Date.now() - 2 * 3600 * 1000).toISOString())).toBe("2h ago");
  });
  it("maps API errors to actionable titles", () => {
    expect(describeError(new ApiError("down", "network_error", 0))).toMatchObject({ title: "Connection problem", retryable: true });
    expect(describeError(new ApiError("set key", "llm_not_configured", 503))).toMatchObject({ title: "AI provider not configured", retryable: false });
    expect(describeError(new Error("boom")).retryable).toBe(true);
  });
});
