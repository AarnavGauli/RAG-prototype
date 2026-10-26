import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

// End-to-end tests run the real stack: Next.js (production build) -> FastAPI -> SQLite/FAISS, with the OpenAI-compatible
// adapter pointed at a deterministic local fake LLM server, so no paid API or network model is involved.
const backendDir = path.resolve(__dirname, "../backend");
const python = path.join(backendDir, ".venv/bin/python");
const E2E_DATA = path.join(backendDir, ".e2e-data");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    { command: `${python} ${backendDir}/tests/e2e_support/fake_llm_server.py 9911`, url: "http://127.0.0.1:9911/x", reuseExistingServer: false, ignoreHTTPSErrors: true, timeout: 20_000, stdout: "ignore", gracefulShutdown: { signal: "SIGTERM", timeout: 1000 } },
    {
      command: `rm -rf ${E2E_DATA} && ${python} -m uvicorn app.main:app_factory --factory --port 8100`,
      cwd: backendDir,
      url: "http://127.0.0.1:8100/api/v1/health",
      timeout: 60_000,
      env: {
        PDFI_DATA_DIR: E2E_DATA,
        PDFI_EMBEDDING_PROVIDER: "hash",
        PDFI_LLM_PROVIDER: "openai",
        PDFI_LLM_BASE_URL: "http://127.0.0.1:9911/v1",
        PDFI_LLM_API_KEY: "e2e-not-a-real-key",
        PDFI_CORS_ORIGINS: '["http://127.0.0.1:3100"]',
        PDFI_RATE_LIMIT_PER_MINUTE: "0",
      },
    },
    {
      command: "npx next build && npx next start -p 3100 -H 127.0.0.1",
      url: "http://127.0.0.1:3100",
      timeout: 180_000,
      env: { BACKEND_URL: "http://127.0.0.1:8100", NEXT_DIST_DIR: ".next-e2e" },
    },
  ],
});
