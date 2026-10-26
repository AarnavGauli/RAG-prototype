import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Workspace } from "@/components/workspace";
import { ApiError } from "@/lib/api";
import type { Citation, Conversation, DocumentItem, Health, Message } from "@/lib/types";

const mocks = vi.hoisted(() => ({
  health: vi.fn(),
  listDocuments: vi.fn(),
  deleteDocument: vi.fn(),
  retryDocument: vi.fn(),
  uploadDocument: vi.fn(),
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  updateConversation: vi.fn(),
  deleteConversation: vi.fn(),
  listMessages: vi.fn(),
  ask: vi.fn(),
  getCitation: vi.fn(),
  pageImageUrl: vi.fn(() => "/page.png"),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: mocks }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

const health: Health = {
  status: "ok", version: "1", database: true, indexed_chunks: 3,
  embedding: { provider: "hash", model: "hash-512", ready: true, detail: null },
  llm: { provider: "anthropic", model: "m", ready: true, detail: null },
  limits: { max_upload_mb: 20, max_documents: 25, max_question_chars: 2000 },
};
const doc = (over: Partial<DocumentItem> = {}): DocumentItem => ({
  id: "doc_1", name: "report.pdf", size_bytes: 2048, page_count: 3, chunk_count: 7, status: "ready", stage: null,
  progress: null, error: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...over,
});
const citation: Citation = {
  id: "cit_1", label: "S1", document_id: "doc_1", document_name: "report.pdf", page_number: 2,
  excerpt: "The budget is 12 million euros.", quote_verified: true, score: 0.8,
};
const msg = (over: Partial<Message>): Message => ({
  id: "m1", role: "user", content: "q", status: "ok", created_at: "2026-01-01T00:00:00Z", citations: [], meta: null, ...over,
});
const conv = (over: Partial<Conversation> = {}): Conversation => ({
  id: "conv_1", title: "Budget questions", document_ids: [], created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...over,
});

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  mocks.pageImageUrl.mockReturnValue("/page.png");
  mocks.health.mockResolvedValue(health);
  mocks.listDocuments.mockResolvedValue([doc()]);
  mocks.listConversations.mockResolvedValue([]);
});

const composer = () => screen.getByLabelText("Ask a question about your documents");

describe("Workspace", () => {
  it("shows the initial empty state and disables questions until a document is indexed", async () => {
    mocks.listDocuments.mockResolvedValue([]);
    render(<Workspace />);
    expect(await screen.findByRole("heading", { name: "Start by adding a PDF" })).toBeInTheDocument();
    expect(await screen.findByText("No documents yet.")).toBeInTheDocument();
    expect(composer()).toBeDisabled();
    expect(await screen.findByTestId("no-conversations")).toBeInTheDocument();
  });

  it("shows real processing progress, never 'indexed' before the backend says so", async () => {
    mocks.listDocuments.mockResolvedValue([
      doc({ id: "a", name: "big.pdf", status: "processing", stage: "embedding", progress: { current: 3, total: 10 }, chunk_count: 0 }),
      doc({ id: "b", name: "wait.pdf", status: "queued", chunk_count: 0 }),
    ]);
    render(<Workspace />);
    expect(await screen.findByText(/Embedding passages 3\/10/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Indexing big.pdf" })).toHaveAttribute("aria-valuenow", "3");
    expect(screen.getByText(/Queued for indexing/)).toBeInTheDocument();
    expect(screen.queryByText(/Indexed ·/)).toBeNull();
    expect(composer()).toBeDisabled();
  });

  it("offers retry for retryable failures and not for permanent ones", async () => {
    mocks.listDocuments.mockResolvedValue([
      doc({ id: "a", name: "flaky.pdf", status: "failed", error: { code: "embedding_unavailable", message: "Embedding service down", retryable: true } }),
      doc({ id: "b", name: "scan.pdf", status: "failed", error: { code: "no_extractable_text", message: "No extractable text; OCR is not supported.", retryable: false } }),
    ]);
    mocks.retryDocument.mockResolvedValue(doc({ id: "a", status: "queued" }));
    render(<Workspace />);
    expect(await screen.findByText(/OCR is not supported/)).toBeInTheDocument();
    const retry = screen.getAllByRole("button", { name: /Retry indexing/ });
    expect(retry).toHaveLength(1);
    await userEvent.click(retry[0]!);
    expect(mocks.retryDocument).toHaveBeenCalledWith("a");
  });

  it("submits a question, shows a pending state, then the answer with a working citation", async () => {
    let resolveAsk: (v: unknown) => void = () => undefined;
    mocks.createConversation.mockResolvedValue(conv({ title: "New conversation" }));
    mocks.ask.mockReturnValue(new Promise((r) => (resolveAsk = r)));
    mocks.getCitation.mockResolvedValue({
      ...citation, chunk_text: "Operating budget. The budget is 12 million euros. Funded by the council.",
      char_start: 0, char_end: 70, page_image_url: "/api/v1/documents/doc_1/pages/2/image?citation=cit_1", message_id: "m2",
    });
    render(<Workspace />);
    await screen.findByText(/Indexed ·/);
    await userEvent.type(composer(), "What is the budget?{Enter}");

    expect(await screen.findByTestId("answer-pending")).toBeInTheDocument();
    expect(mocks.createConversation).toHaveBeenCalledWith({ document_ids: [] });
    expect(composer()).toHaveValue("");

    resolveAsk({
      user_message: msg({ id: "m1", content: "What is the budget?" }),
      assistant_message: msg({ id: "m2", role: "assistant", content: "The budget is 12 million euros [S1].", citations: [citation] }),
    });
    const answer = await screen.findByTestId("assistant-message");
    expect(within(answer).getByText(/The budget is 12 million euros/, { selector: "p" })).toBeInTheDocument();
    expect(screen.queryByTestId("answer-pending")).toBeNull();
    expect(mocks.ask).toHaveBeenCalledWith("conv_1", "What is the budget?");

    await userEvent.click(within(answer).getByRole("button", { name: /Open source S1/ }));
    const panel = await screen.findByRole("complementary", { name: "Source inspector" });
    const excerpt = await within(panel).findByTestId("source-excerpt");
    expect(excerpt).toHaveTextContent("The budget is 12 million euros.");
    expect(excerpt.querySelector("mark")).toHaveTextContent("The budget is 12 million euros.");
    expect(within(panel).getByText(/page 2/)).toBeInTheDocument();
    expect(within(panel).getByRole("img", { name: /Page 2 of report.pdf/ })).toHaveAttribute("src", expect.stringContaining("citation=cit_1"));
    await userEvent.click(within(panel).getByRole("button", { name: "Close source panel" }));
    expect(screen.queryByRole("complementary", { name: "Source inspector" })).toBeNull();
  });

  it("renders insufficient-evidence answers without citations", async () => {
    mocks.createConversation.mockResolvedValue(conv());
    mocks.ask.mockResolvedValue({
      user_message: msg({ content: "Who won?" }),
      assistant_message: msg({ id: "m2", role: "assistant", status: "insufficient_evidence", content: "I couldn't find enough evidence.", meta: { retrieved: 0, top_score: null, reason: "no_relevant_passages" } }),
    });
    render(<Workspace />);
    await screen.findByText(/Indexed ·/);
    await userEvent.type(composer(), "Who won?{Enter}");
    const answer = await screen.findByTestId("assistant-message");
    expect(answer).toHaveAttribute("data-status", "insufficient_evidence");
    expect(within(answer).getByText(/Insufficient evidence/)).toBeInTheDocument();
    expect(within(answer).queryByTestId("citations")).toBeNull();
  });

  it("reports network failures with a retry that resends the same question", async () => {
    mocks.createConversation.mockResolvedValue(conv());
    mocks.deleteConversation.mockResolvedValue(undefined);
    mocks.ask.mockRejectedValueOnce(new ApiError("Cannot reach the PDF Intelligence server.", "network_error", 0));
    render(<Workspace />);
    await screen.findByText(/Indexed ·/);
    await userEvent.type(composer(), "Will this fail?{Enter}");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Connection problem");
    expect(alert).toHaveTextContent("Will this fail?");
    expect(mocks.deleteConversation).toHaveBeenCalledWith("conv_1"); // no empty conversation left behind

    mocks.ask.mockResolvedValueOnce({
      user_message: msg({ content: "Will this fail?" }),
      assistant_message: msg({ id: "m2", role: "assistant", content: "Now it works [S1].", citations: [citation] }),
    });
    await userEvent.click(within(alert).getByRole("button", { name: /Retry/ }));
    expect(await screen.findByText(/Now it works/)).toBeInTheDocument();
    expect(mocks.ask).toHaveBeenLastCalledWith("conv_1", "Will this fail?");
  });

  it("shows provider configuration problems as actionable messages, with no retry button", async () => {
    mocks.health.mockResolvedValue({ ...health, llm: { provider: "anthropic", model: "m", ready: false, detail: "No Anthropic API key is configured. Set ANTHROPIC_API_KEY." } });
    mocks.createConversation.mockResolvedValue(conv());
    mocks.deleteConversation.mockResolvedValue(undefined);
    mocks.ask.mockRejectedValue(new ApiError("No Anthropic API key is configured. Set ANTHROPIC_API_KEY.", "llm_not_configured", 503));
    render(<Workspace />);
    expect(await screen.findByText("AI provider not configured")).toBeInTheDocument();
    await screen.findByText(/Indexed ·/);
    await userEvent.type(composer(), "Hello?{Enter}");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("ANTHROPIC_API_KEY");
    expect(within(alert).queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("lists previous conversations, loads history with citations, renames and deletes", async () => {
    mocks.listConversations.mockResolvedValue([conv()]);
    mocks.listMessages.mockResolvedValue({
      has_more: false,
      messages: [msg({ id: "m1", content: "What is the budget?" }), msg({ id: "m2", role: "assistant", content: "It is 12M [S1].", citations: [citation] })],
    });
    mocks.updateConversation.mockResolvedValue(conv({ title: "Finance" }));
    mocks.deleteConversation.mockResolvedValue(undefined);
    render(<Workspace />);

    await userEvent.click(await screen.findByRole("button", { name: /^Budget questions/ }));
    expect(await screen.findByText("What is the budget?")).toBeInTheDocument();
    expect(screen.getByTestId("citation-card")).toHaveTextContent("report.pdf");
    expect(mocks.listMessages).toHaveBeenCalledWith("conv_1");

    await userEvent.click(screen.getByRole("button", { name: "Rename Budget questions" }));
    const input = screen.getByLabelText("Conversation title");
    await userEvent.clear(input);
    await userEvent.type(input, "Finance{Enter}");
    await waitFor(() => expect(mocks.updateConversation).toHaveBeenCalledWith("conv_1", { title: "Finance" }));
    expect(await screen.findByRole("button", { name: /^Finance/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete Finance" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("permanently removed");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete conversation" }));
    await waitFor(() => expect(mocks.deleteConversation).toHaveBeenCalledWith("conv_1"));
    expect(await screen.findByTestId("no-conversations")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ask your documents anything" })).toBeInTheDocument();
  });

  it("starting a new conversation clears the previous one", async () => {
    mocks.listConversations.mockResolvedValue([conv()]);
    mocks.listMessages.mockResolvedValue({ has_more: false, messages: [msg({ content: "old question" })] });
    render(<Workspace />);
    await userEvent.click(await screen.findByRole("button", { name: /^Budget questions/ }));
    expect(await screen.findByText("old question")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /New conversation/ }));
    expect(screen.queryByText("old question")).toBeNull();
    expect(screen.getByRole("heading", { name: "Ask your documents anything" })).toBeInTheDocument();
  });

  it("deletes a document only after confirmation and removes it from the list", async () => {
    mocks.listDocuments.mockResolvedValueOnce([doc()]).mockResolvedValue([]);
    mocks.deleteDocument.mockResolvedValue(undefined);
    render(<Workspace />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete report.pdf" }));
    expect(mocks.deleteDocument).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(mocks.deleteDocument).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Delete report.pdf" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete document" }));
    await waitFor(() => expect(mocks.deleteDocument).toHaveBeenCalledWith("doc_1"));
    await waitFor(() => expect(screen.queryByTestId("document-row")).toBeNull());
    expect(await screen.findByText(/Deleted “report.pdf”/)).toBeInTheDocument();
  });

  it("shows an unavailable-source message when a citation's document no longer exists", async () => {
    mocks.listConversations.mockResolvedValue([conv()]);
    mocks.listMessages.mockResolvedValue({ has_more: false, messages: [msg({ id: "m2", role: "assistant", content: "Old answer [S1].", citations: [citation] })] });
    mocks.getCitation.mockRejectedValue(new ApiError("Citation not found.", "citation_not_found", 404));
    render(<Workspace />);
    await userEvent.click(await screen.findByRole("button", { name: /^Budget questions/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Open source S1/ }));
    expect(await screen.findByText("Source no longer available")).toBeInTheDocument();
  });

  it("shows the backend-unreachable banner and loading skeletons", async () => {
    mocks.health.mockRejectedValue(new ApiError("Cannot reach the server.", "network_error", 0));
    mocks.listDocuments.mockRejectedValue(new ApiError("Cannot reach the server.", "network_error", 0));
    render(<Workspace />);
    expect(await screen.findByText("Backend unreachable")).toBeInTheDocument();
    expect(await screen.findByText("Could not load documents")).toBeInTheDocument();
  });
});
