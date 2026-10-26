import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AnswerMarkdown } from "@/components/markdown";
import type { Citation } from "@/lib/types";

const citation: Citation = {
  id: "cit_1", label: "S1", document_id: "doc_1", document_name: "report.pdf", page_number: 4, excerpt: "e", quote_verified: true, score: 0.8,
};

describe("AnswerMarkdown", () => {
  it("renders validated citation markers as buttons that open the source", async () => {
    const onOpen = vi.fn();
    render(<AnswerMarkdown content="The budget is 12M [S1]." citations={[citation]} onOpenCitation={onOpen} />);
    const btn = screen.getByRole("button", { name: /Open source S1: report.pdf, page 4/ });
    await userEvent.click(btn);
    expect(onOpen).toHaveBeenCalledWith(citation);
  });

  it("drops markers that have no stored citation", () => {
    render(<AnswerMarkdown content="Claim [S7]." citations={[citation]} onOpenCitation={() => undefined} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Claim.")).toBeInTheDocument();
  });

  it("does not execute or render raw HTML, images or script URLs", () => {
    const { container } = render(
      <AnswerMarkdown
        content={'<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>\n\n![tracker](https://evil.example/p.png)\n\n[click](javascript:alert(1))'}
        citations={[]}
        onOpenCitation={() => undefined}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    const link = screen.getByText("click").closest("a");
    expect(link?.getAttribute("href") ?? "").not.toMatch(/^javascript:/i);
  });

  it("renders Markdown structure and opens external links safely", () => {
    render(<AnswerMarkdown content={"- one\n- two\n\n[docs](https://example.com)"} citations={[]} onOpenCitation={() => undefined} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
});
