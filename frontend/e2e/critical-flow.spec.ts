import { expect, test } from "@playwright/test";
import path from "node:path";

const SAMPLE = path.resolve(__dirname, "../../backend/app/evaluation/data/meridian_bikeshare_handbook.pdf");

test.describe.configure({ mode: "serial" });

test("upload → index → cited answer → inspect source → abstain → delete", async ({ page }) => {
  await page.goto("/");

  // 1. initial empty state
  await expect(page.getByRole("heading", { name: "Start by adding a PDF" })).toBeVisible();
  await expect(page.getByLabel("Ask a question about your documents")).toBeDisabled();

  // 2. client-side rejection of a non-PDF
  await page.locator('input[type="file"]').setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await expect(page.getByRole("alert").filter({ hasText: "is not a PDF" })).toBeVisible();
  await page.getByRole("button", { name: /Dismiss error for notes.txt/ }).click();

  // 3. upload the sample PDF and wait until the backend reports it as indexed
  await page.locator('input[type="file"]').setInputFiles(SAMPLE);
  const row = page.getByTestId("document-row");
  await expect(row).toContainText("meridian_bikeshare_handbook.pdf");
  await expect(row).toHaveAttribute("data-status", "ready");
  await expect(row).toContainText("6 pages");

  // 4. ask a question with a known answer
  await expect(page.getByRole("heading", { name: "Ask your documents anything" })).toBeVisible();
  await page.getByLabel("Ask a question about your documents").fill("How many stations are in operation today?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByTestId("answer-pending")).toBeVisible();

  // 5. the answer carries a validated citation to page 1
  const answer = page.getByTestId("assistant-message").first();
  await expect(answer).toContainText("112 stations");
  await expect(answer).toHaveAttribute("data-status", "ok");
  const card = answer.getByTestId("citation-card").first();
  await expect(card).toContainText("meridian_bikeshare_handbook.pdf");
  await expect(card).toContainText("p. 1");

  // 6. open the citation → source panel shows excerpt and the rendered page
  await answer.getByRole("button", { name: /Open source S1/ }).first().click();
  const panel = page.getByRole("complementary", { name: "Source inspector" });
  await expect(panel.getByTestId("source-excerpt")).toContainText("112 stations");
  await expect(panel).toContainText("page 1");
  const img = panel.getByRole("img", { name: /Page 1 of meridian_bikeshare_handbook.pdf/ });
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(100);
  await panel.getByRole("button", { name: "Close source panel" }).click();
  await expect(panel).toBeHidden();

  // 7/8. an unanswerable question yields the insufficient-evidence state and no citations
  await page.getByLabel("Ask a question about your documents").fill("What is the recipe for sourdough bread?");
  await page.keyboard.press("Enter");
  const second = page.getByTestId("assistant-message").nth(1);
  await expect(second).toHaveAttribute("data-status", "insufficient_evidence");
  await expect(second).toContainText("Insufficient evidence");
  await expect(second.getByTestId("citation-card")).toHaveCount(0);

  // conversation history is listed and survives a reload
  await expect(page.getByRole("button", { name: /^How many stations/ })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: /^How many stations/ }).first().click();
  await expect(page.getByTestId("assistant-message")).toHaveCount(2);
  await expect(page.getByTestId("assistant-message").first().getByTestId("citation-card")).toHaveCount(1);

  // 9. delete the document (with confirmation) and verify it is gone
  await page.getByRole("button", { name: /Delete meridian_bikeshare_handbook.pdf/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("permanently removed");
  await dialog.getByRole("button", { name: "Delete document" }).click();
  await expect(page.getByTestId("document-row")).toHaveCount(0);
  await expect(page.getByText("No documents yet.")).toBeVisible();
  const res = await page.request.get("/api/v1/documents");
  expect(await res.json()).toEqual([]);
});

test("conversation rename and delete", async ({ page }) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SAMPLE);
  await expect(page.getByTestId("document-row")).toHaveAttribute("data-status", "ready");
  await page.getByLabel("Ask a question about your documents").fill("How much does a monthly membership cost?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("assistant-message")).toContainText("$24");

  await page.getByRole("button", { name: /^Rename How much/ }).click();
  const input = page.getByLabel("Conversation title");
  await input.fill("Pricing questions");
  await input.press("Enter");
  await expect(page.getByRole("button", { name: /^Pricing questions/ }).first()).toBeVisible();

  await page.getByRole("button", { name: "Delete Pricing questions" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete conversation" }).click();
  await expect(page.getByTestId("no-conversations")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ask your documents anything" })).toBeVisible();
});

test("mobile layout uses a drawer for the library", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 800 } });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:3100/");
  await expect(page.getByRole("navigation", { name: "Library" })).toHaveCount(0);
  await page.getByRole("button", { name: "Open library" }).click();
  await expect(page.getByRole("dialog", { name: "Library" })).toBeVisible();
  await expect(page.getByText("Upload PDFs")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  await context.close();
});
