import { expect, test } from "@playwright/test";
import path from "node:path";

// Regenerates the README screenshots: CAPTURE=1 npx playwright test e2e/screenshots.spec.ts
const SAMPLE = path.resolve(__dirname, "../../backend/app/evaluation/data/meridian_bikeshare_handbook.pdf");
const OUT = path.resolve(__dirname, "../../docs/screenshots");

test.skip(!process.env.CAPTURE, "set CAPTURE=1 to regenerate screenshots");

test("capture screenshots", async ({ page, browser }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Start by adding a PDF" })).toBeVisible();
  await page.screenshot({ path: `${OUT}/01-empty.png` });

  await page.locator('input[type="file"]').setInputFiles(SAMPLE);
  await expect(page.getByTestId("document-row")).toHaveAttribute("data-status", "ready");
  await page.getByLabel("Ask a question about your documents").fill("What is the replacement fee if a bicycle is not returned within 72 hours?");
  await page.keyboard.press("Enter");
  const answer = page.getByTestId("assistant-message").first();
  await expect(answer).toContainText("$1,200");
  await answer.getByRole("button", { name: /Open source S1/ }).first().click();
  await expect(page.getByTestId("source-excerpt")).toBeVisible();
  await expect(page.getByRole("img", { name: /Page 6/ })).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/02-answer-with-source.png` });

  await page.getByRole("button", { name: "Close source panel" }).click();
  await page.getByLabel("Ask a question about your documents").fill("What is the recipe for sourdough bread?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("assistant-message").nth(1)).toHaveAttribute("data-status", "insufficient_evidence");
  await page.screenshot({ path: `${OUT}/03-insufficient-evidence.png` });

  const mobile = await browser.newContext({ viewport: { width: 390, height: 800 }, deviceScaleFactor: 2 });
  const m = await mobile.newPage();
  await m.goto("http://127.0.0.1:3100/");
  await m.getByRole("button", { name: "Open library" }).click();
  await m.locator('input[type="file"]').setInputFiles(SAMPLE);
  await expect(m.getByTestId("document-row")).toHaveAttribute("data-status", "ready");
  await m.screenshot({ path: `${OUT}/04-mobile-library.png` });
  await m.keyboard.press("Escape");
  await m.getByLabel("Ask a question about your documents").fill("How often is each bicycle inspected by a technician?");
  await m.keyboard.press("Enter");
  await expect(m.getByTestId("assistant-message")).toContainText("14 days");
  await m.screenshot({ path: `${OUT}/05-mobile-answer.png` });
  await mobile.close();
});
