# PDF Intelligence

Upload PDFs, ask questions, and get answers **grounded in your documents** with **clickable page-level citations**. If the documents don't contain the answer, the app says so instead of guessing.

> A **local, single-user** app. It has no user accounts, so don't expose it publicly without putting authentication in front of it.

![Answer with source](docs/screenshots/02-answer-with-source.png)

## How it works

1. **Upload** a PDF. It is validated, split page by page, cut into overlapping chunks, embedded, and stored (SQLite + a FAISS vector index).
2. **Ask** a question. The most relevant chunks are retrieved, filtered by a relevance threshold, and sent to an LLM.
3. **Verify.** The LLM must cite the passages it used. Every citation is checked against what was actually retrieved; invented or unsupported citations are dropped, and an answer without valid citations becomes "insufficient evidence".
4. **Inspect.** Click a citation to see the excerpt and the real PDF page with the passage highlighted.

```mermaid
flowchart LR
  UI[Next.js UI] -->|/api proxy| API[FastAPI]
  API --> IDX[Extract, chunk, embed] --> DB[(SQLite)]
  IDX --> VS[(FAISS)]
  API --> RET[Retrieve + validate] --> LLM[[LLM]]
  RET --> VS
```

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run it

You need Python 3.12+ and Node 20+.

```bash
# Terminal 1: backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env            # then add your ANTHROPIC_API_KEY
python -m uvicorn app.main:app_factory --factory --port 8000

# Terminal 2: frontend
cd frontend
npm ci
npm run dev                        # open http://localhost:3000
```

Or with Docker: `cp .env.example .env` (add your key), then `docker compose up --build` and open http://localhost:3000.

The first upload downloads a small local embedding model (~65 MB). To avoid that, set `PDFI_EMBEDDING_PROVIDER=hash` (works offline, but retrieval is much weaker).

**Try it:** upload `backend/app/evaluation/data/meridian_bikeshare_handbook.pdf` (a fictional sample), then ask:
- "How many stations are in operation today?" → cited answer
- "What is the recipe for sourdough bread?" → "insufficient evidence"

## Choose an AI provider

Uploading and indexing work without any key. **Answering needs an LLM**; without one the app shows a clear message (it never fakes an answer). Set these in `backend/.env`:

| Provider | Settings |
|---|---|
| Anthropic (default) | `ANTHROPIC_API_KEY=...` |
| Google Gemini | `PDFI_LLM_PROVIDER=gemini`, `GEMINI_API_KEY=...` (optional `PDFI_LLM_MODEL`, default `gemini-2.5-flash`) |
| OpenAI | `PDFI_LLM_PROVIDER=openai`, `PDFI_LLM_API_KEY=...`, `PDFI_LLM_MODEL=gpt-4o-mini` |
| Local (Ollama etc.) | `PDFI_LLM_PROVIDER=openai`, `PDFI_LLM_BASE_URL=http://localhost:11434/v1`, `PDFI_LLM_MODEL=<model>` |

## Common settings

All optional; see [.env.example](.env.example) for the full list.

| Variable | Default | Meaning |
|---|---|---|
| `PDFI_DATA_DIR` | `./data` | Where the database, uploads and index live |
| `PDFI_MAX_UPLOAD_MB` | 20 | Max size per PDF |
| `PDFI_MAX_DOCUMENTS` | 25 | Max documents per browser session |
| `PDFI_EMBEDDING_PROVIDER` | fastembed | `fastembed`, `hash` or `openai` |
| `PDFI_CHUNK_SIZE_TOKENS` / `PDFI_CHUNK_OVERLAP_TOKENS` | 350 / 60 | Chunking |
| `PDFI_RETRIEVAL_TOP_K` | 6 | Passages sent to the LLM |
| `PDFI_RETRIEVAL_MIN_SCORE` | by provider | Relevance floor (0.5 for the default model) |

Database migrations run automatically at startup (manual: `cd backend && alembic upgrade head`).

## Tests and evaluation

```bash
cd backend && pytest && ruff check .                     # backend
cd frontend && npm run typecheck && npm run lint && npm test
cd frontend && npx playwright install chromium && npm run test:e2e   # full browser flow
cd backend && python -m app.evaluation.cli --output report.json      # RAG evaluation
```

No test calls a paid API. The evaluation runs offline by default using a simple stand-in for the LLM, so it checks retrieval, citation validity and abstention, not real LLM quality. Add `--live` for real LLM answers (costs money) and `--judge` for LLM-judged scores (not objective ground truth). The evaluation is also available in the UI at `/evaluation`.

## Deploying

- Mount a **persistent volume** at `PDFI_DATA_DIR` (database, uploads, index). Container disks are temporary.
- Run **one** backend process (SQLite and the index are in-process).
- Put HTTPS and **authentication** in front, and set `PDFI_COOKIE_SECURE=true`.
- Set `BACKEND_URL` when building the frontend (it is baked in).
- Health check: `GET /api/v1/health`. API docs: `/docs`.

This repo has not been deployed anywhere.

## Privacy and security

- Browsers are separated by a random session cookie. That isolates data but is **not authentication**.
- Uploads are untrusted: type, size and structure are checked, files are stored under generated names, and PDF content is never executed.
- Document text is delimited as untrusted data in the prompt, and answers are validated afterwards. This reduces prompt-injection risk but can't eliminate it.
- **Document text is sent to your LLM provider** when you ask a question. Use a local model if that is a problem.
- Secrets and document contents are not logged. Model Markdown is rendered without raw HTML or images.

## Known limitations

- No OCR: scanned PDFs are detected and rejected with an explanation.
- Text only: tables, multi-column layouts and figures are not well understood.
- The real Anthropic/OpenAI APIs were not exercised during development (no key available); the adapters are tested against fake servers.
- The relevance threshold was tuned on a tiny sample; re-check it on your documents.
- Single process, in-process rate limiting, answers are not streamed.

## Ideas for later

OCR, reranking, hybrid keyword + vector search, streaming answers, real multi-user auth, a server-side vector database.
