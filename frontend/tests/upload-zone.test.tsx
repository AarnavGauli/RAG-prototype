import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UploadZone } from "@/components/upload-zone";
import { ApiError } from "@/lib/api";
import type { DocumentItem } from "@/lib/types";

const upload = vi.fn();
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: { uploadDocument: (...a: unknown[]) => upload(...a) } }));

const doc = { id: "doc_1", name: "a.pdf" } as DocumentItem;
const input = () => document.querySelector('input[type="file"]') as HTMLInputElement;
const pdf = (name = "a.pdf", size = 1000) => new File([new Uint8Array(size)], name, { type: "application/pdf" });

describe("UploadZone", () => {
  beforeEach(() => {
    upload.mockReset();
  });

  it("uploads a valid PDF and reports the new document", async () => {
    upload.mockResolvedValue(doc);
    const onUploaded = vi.fn();
    render(<UploadZone maxMb={20} onUploaded={onUploaded} />);
    await userEvent.upload(input(), pdf());
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(doc));
    expect(upload).toHaveBeenCalledTimes(1);
  });

  it("rejects non-PDF and oversized files without calling the API", async () => {
    render(<UploadZone maxMb={1} onUploaded={vi.fn()} />);
    fireEvent.change(input(), { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });
    expect(await screen.findByText(/not a PDF/)).toBeInTheDocument();
    fireEvent.change(input(), { target: { files: [pdf("big.pdf", 2 * 1024 * 1024)] } });
    expect(await screen.findByText(/limit is 1 MB/)).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
  });

  it("shows real upload progress while uploading", async () => {
    let report: (f: number) => void = () => undefined;
    upload.mockImplementation((_f: File, cb: (f: number) => void) => {
      report = cb;
      return new Promise(() => undefined);
    });
    render(<UploadZone maxMb={20} onUploaded={vi.fn()} />);
    await userEvent.upload(input(), pdf());
    report(0.42);
    const bar = await screen.findByRole("progressbar", { name: /Uploading a.pdf/ });
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "42"));
  });

  it("shows server-side rejections and lets the user dismiss them", async () => {
    upload.mockRejectedValue(new ApiError("The PDF is malformed or unreadable.", "malformed_pdf", 422));
    render(<UploadZone maxMb={20} onUploaded={vi.fn()} />);
    await userEvent.upload(input(), pdf());
    expect(await screen.findByRole("alert")).toHaveTextContent("malformed or unreadable");
    await userEvent.click(screen.getByRole("button", { name: /Dismiss error/ }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the drag-over state and disables upload when at the limit", () => {
    const { rerender } = render(<UploadZone maxMb={20} onUploaded={vi.fn()} />);
    fireEvent.dragOver(screen.getByText("Upload PDFs").closest("label")!);
    expect(screen.getByText("Drop PDF to upload")).toBeInTheDocument();
    rerender(<UploadZone maxMb={20} disabled disabledReason="Document limit reached (25)." onUploaded={vi.fn()} />);
    expect(input()).toBeDisabled();
    expect(screen.getByText(/Document limit reached/)).toBeInTheDocument();
  });
});
