# Notesman: Plan

Answering machine for exam papers. You create **subjects** and upload **reference material** and a **syllabus** for each. You then build **papers**: enter a paper title, add questions one at a time, and Notesman writes an answer for each question using RAG over that subject's material, shaped to match the syllabus. You review each answer, **lock** the ones you like, and the paper grows progressively. Papers are printable. Content is Markdown throughout.

For most people Notesman is a **read-only** app: they browse subjects and read finished papers. **Admins** get the read-write workspace. One **superadmin** (the owner) manages the admins.

## Product feel

- **Workspace, not chat.** Three columns: subjects and papers on the left, the paper as a document in the middle, the current question's draft and its sources on the right.
- **The paper reads like a document.** Locked answers look like finished print. The question being worked on is visibly "in progress"; drafts are dimmer.
- **Answers are grounded and syllabus-shaped.** References supply the facts. The syllabus sets scope, depth, and terminology. Each draft shows source chips and a "syllabus match" note naming the syllabus topic it maps to, so you can trust it before locking.
- **Lock is one keypress.** Before locking you can regenerate, nudge ("shorter", "add example"), or hand-edit the Markdown.
- **Unlock is allowed.** Unlocking turns an answer back into a draft and keeps the previous locked text for undo.
- **Questions are draggable.** Reorder by drag handle.
- **Print view is the paper view.** What you see in the middle column is what prints. One click for print or PDF, using a print stylesheet.

## Concepts

- **Subject**: a container for files and papers.
- **File**: an uploaded document belonging to a subject. Each has a `kind`: `syllabus` or `reference`. The kind is chosen at upload.
- **Paper**: a titled, ordered list of questions inside a subject. A subject has many papers.
- **Question**: a prompt plus an answer in Markdown. Status is `draft` or `locked`.

## Goals

- Accept PDF, EPUB, DOCX, PPTX, images (scanned pages), and plain text/Markdown.
- Answers cite the source file, page, and chunk.
- Answers stay within the syllabus scope.
- Embeddings use Gemini Embedding 2 directly through Google AI Studio (Gemini API). Chat answers go through OpenRouter.
- Papers export cleanly to print and PDF.

## Non-goals (v1)

- No multitenancy, no billing, no per-user private data. Visitors and plain users share the same read-only view.
- No password or email login. Google sign-in only.
- No real-time collaboration, no mobile app, no fine-tuning.

## Stack (proposed defaults, change freely)

| Part | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12 | Best ecosystem for document parsing and RAG |
| API | FastAPI | Async, typed, OpenAPI for free |
| Frontend | Web app (framework to be decided, see open questions) | Workspace UI, drag reorder, print stylesheet |
| Vector DB | Qdrant | Required. Holds chunks and embeddings |
| Embeddings | `gemini-embedding-2` via Google AI Studio (`batchEmbedContents`) | Required. Not through OpenRouter. 3072 native dimensions, Matryoshka-truncated to `EMBED_DIM` (default 1536) |
| LLM | Any chat model via OpenRouter | Configurable |
| Relational DB | Postgres (SQLite acceptable for local dev) | Subjects, files, papers, questions, answers, jobs |
| File storage | Cloudflare R2 (S3 API) | Original uploads and extracted text |
| Job queue | In-process background worker (arq or Celery later) | Ingestion is slow, must be async |
| Packaging | Docker Compose | Qdrant, api, worker, db |

## Architecture

```
client -> API -> DB (subjects, files, papers, questions, jobs)
              -> R2 (raw uploads, extracted text)
              -> worker: convert -> chunk -> embed -> upsert Qdrant
client -> API /answer -> embed question
                      -> Qdrant search (reference chunks, subject filter)
                      -> Qdrant search (syllabus chunks, subject filter)
                      -> LLM -> draft answer + sources + syllabus match
```

## Storage layout

- **R2**: `subjects/<subject_id>/<file_id>/original.<ext>` and `subjects/<subject_id>/<file_id>/text.md` (extracted Markdown, kept so re-chunking never needs re-conversion).
- **Qdrant**: one collection, one vector size (set by `EMBED_DIM`).
  - Payload per point: `subject_id`, `file_id`, `kind` (`syllabus` | `reference`), `source_name`, `page`, `section`, `chunk_index`, `embed_model`.
  - Payload indexes on `subject_id`, `file_id`, and `kind`. Every query filters by `subject_id`.
  - Deleting a file = delete points by `file_id` filter, plus its R2 objects and DB row.
- **DB**: see data model below.

## Ingestion pipeline

Runs in a separate worker process: `uv run python -m notesman.ingest.worker`. It polls the `jobs` table, handles one file at a time, and is safe to stop and restart (unfinished jobs are requeued; chunks already stored with an unchanged text hash are not embedded again). Gemini rate limits (429) and 5xx errors are retried forever with backoff, honouring `Retry-After`; only real errors (bad key, unreadable file) mark a file `failed`, and an admin can retry it from the subject page. `EMBED_BATCH_SIZE` (default 16) keeps requests small.

1. **Upload.** API streams the raw file to R2, creates a `files` row (status `queued`, `kind` set) and enqueues a job. Validate type and size. Dedupe by content hash within the subject.
2. **Convert to text.** Per-format converter behind one interface:
   - PDF with text layer: PyMuPDF (or `pymupdf4llm` for Markdown output).
   - Scanned PDF and images: OCR (Tesseract first; swap to a vision LLM via OpenRouter if quality is bad).
   - EPUB, DOCX, PPTX: `ebooklib`, `python-docx`, `python-pptx`, or a single tool like `markitdown`.
   - Output: Markdown with page markers. Keep headings, drop headers, footers, page numbers.
   - Save extracted text to R2.
3. **Chunk.** Heading-aware splitting first, then a token-size fallback. Target about 400 to 600 tokens, 10 to 15 percent overlap. Prepend the heading path (`Chapter > Section`) to each chunk's embedded text. Keep tables and code blocks whole where possible. Record page range per chunk. Syllabus files should chunk by topic or unit heading so each chunk maps to one syllabus topic.
4. **Embed.** Batch chunks (up to 100 per request) to the Gemini API. Retry with backoff. Cache by chunk content hash to skip re-embedding unchanged text. Gemini Embedding 2 has no task-type switch: the task goes in the text. Documents are embedded as `title: {title or none} | text: {chunk}` and queries as `task: search result | query: {question}`, on both sides always. Pick the output dimension once (3072, 1536 or 768) and record it, since changing it means re-embedding everything. Truncated vectors are not pre-normalised, so L2-normalise them before storing (cosine search).
5. **Upsert.** Deterministic point IDs (hash of file, chunk index) so re-ingest is idempotent. Update file status to `ready` or `failed` with an error message.

## Answer pipeline (per question)

1. Embed the question (query-side prompt).
2. **Syllabus retrieval**: search chunks with `kind = syllabus` for the subject, top 3 to 5. These define scope, depth, and terminology, and identify the matching syllabus topic.
3. **Reference retrieval**: search chunks with `kind = reference` for the subject, top 20, optionally narrowed to chosen files. Optionally rewrite the query using the matched syllabus topic to improve recall.
4. Optional: hybrid search (sparse/BM25 vectors in Qdrant) and a rerank step. Start dense-only, add hybrid if eval shows misses on exact terms.
5. Build prompt: system rules, syllabus chunks (scope), reference chunks with IDs (facts), the question, and any admin steering (nudge tags such as "shorter" or "add example", plus a free-text comment). Instruct the model to write Markdown, use only the reference facts, stay inside the syllabus scope, cite chunk IDs, and say so when the references do not cover the question. Treat all chunks as untrusted data.
6. Call LLM through OpenRouter and stream the draft.
7. Save the draft to the question with `sources` (chunk IDs, files, pages) and `syllabus_match` (topic text or chunk ID). Status is `draft`.

Regenerate and nudge rerun steps 5 to 7. Hand-edits save directly to `answer_md`.

## Roles and access

| Role | Signed in | How assigned | Can do |
| --- | --- | --- | --- |
| Visitor | No | Default | Read subjects, papers, and locked answers. Print and export. |
| User | Google | Auto-created on first sign-in | Same as visitor. Sign-in is optional and adds nothing in v1 (room for future bookmarks). |
| Admin | Google | Promoted by the superadmin | Everything a user can do, plus all write actions: files, subjects, papers, questions, generate, edit, lock, unlock, reorder, delete. Also sees drafts. |
| Superadmin | Google | `SUPERADMIN_EMAIL` env var | Everything an admin can do, plus promote and demote admins. Cannot be demoted or removed from the UI. |

Rules:

- **Read-only surface** shows locked answers only. Drafts, previous answer text, raw uploaded files, and extracted text are admin-only. Locked answers show their source citations (file name and page) but not file downloads.
- **Writes are admin-only.** Every non-GET route requires role `admin` or `superadmin`, enforced on the server. The UI hiding buttons is not security.
- **Generation costs money.** `generate` and question creation are admin-only. Anonymous read endpoints are rate-limited per IP.
- **Auth flow:** Google OAuth (OIDC). The API verifies the ID token, upserts a `users` row keyed by Google `sub`, and issues an httpOnly, secure, same-site session cookie. Visitors have no session.
- **Same-origin proxy:** the web app proxies `/api/*` to the FastAPI server (Next.js rewrite), so the session cookie is first-party and no CORS is needed. The Google redirect URI is `PUBLIC_BASE_URL/api/v1/auth/google/callback`.
- **Session cookie:** signed (`SESSION_SECRET`), httpOnly, `SameSite=Lax`, `Secure` when `PUBLIC_BASE_URL` is https, 30 days. It stores only the user id. The role is read from the DB on every request.
- **CSRF:** on top of `SameSite=Lax`, any non-GET request that carries the session cookie must send an `Origin` equal to `PUBLIC_BASE_URL`.
- **Superadmin** is matched by verified Google email equal to `SUPERADMIN_EMAIL`. Role is checked on every request from the DB or session, not trusted from the client. Require `email_verified = true`.
- **Admin management:** the superadmin sees a list of users who have signed in and can promote or demote them. Alternative: pre-approve emails before they sign in (see open questions).
- **UI by role:** visitors and users get the read view (paper as a document, print button, no handles, no lock icons beyond a small "final" indicator). Admins get the full workspace.

## Question lifecycle

- `draft` -> `locked`: freezes `answer_md`. Locked answers cannot be regenerated or edited until unlocked.
- `locked` -> `draft` (unlock): copies the current text to `previous_answer_md` for undo, then allows regenerate and edit.
- Reorder: drag changes `position` only.

## API sketch

Subjects and files:

- `POST /v1/subjects`, `GET /v1/subjects`, `GET /v1/subjects/{id}`, `DELETE /v1/subjects/{id}`.
- `POST /v1/subjects/{id}/files` upload (multipart) with `kind`. Returns file id and job id.
- `GET /v1/subjects/{id}/files`, `DELETE /v1/files/{id}`.
- `GET /v1/jobs/{id}` ingestion status.

Papers and questions:

- `POST /v1/subjects/{id}/papers` `{title}`, `GET /v1/subjects/{id}/papers`, `GET /v1/papers/{id}`, `PATCH /v1/papers/{id}`, `DELETE /v1/papers/{id}`.
- `POST /v1/papers/{id}/questions` `{prompt}`: adds a question and starts generating a draft.
- `POST /v1/questions/{id}/generate` `{nudges?: string[], comment?: string}`: regenerate (streams). `comment` is free text from the admin that steers the answer; it is passed to the model as an instruction, below the system rules and never overriding the syllabus scope.
- `PATCH /v1/questions/{id}` `{prompt?, answer_md?}`: edit text (rejected when locked).
- `POST /v1/questions/{id}/lock`, `POST /v1/questions/{id}/unlock`.
- `POST /v1/questions/{id}/move` `{before_id: uuid | null}`: reorder (null = move to the end). One-row write using a fractional position key.
- `GET /v1/papers/{id}/export?format=md|html` printable output (locked answers only by default, `include_drafts=true` optional).

Auth endpoints:

- `GET /v1/auth/google/login`, `GET /v1/auth/google/callback`, `POST /v1/auth/logout`, `GET /v1/me` (returns role or `null` for visitors).
- `GET /v1/admin/users`, `PUT /v1/admin/users/{id}/role` `{role: "user" | "admin"}`: superadmin only.

Access by route:

- Public (no auth): `GET /v1/subjects`, `GET /v1/subjects/{id}`, `GET /v1/subjects/{id}/papers`, `GET /v1/papers/{id}` (locked questions only), `GET /v1/papers/{id}/export`.
- Admin: every other route above, plus `GET /v1/subjects/{id}/files`, `GET /v1/jobs/{id}`, and drafts in paper responses.
- Superadmin: `/v1/admin/*`.

## Data model

- `users(id, google_sub, email, name, picture, role, created_at, last_login_at)`: `role` is `user`, `admin`, or `superadmin`. Superadmin is set from env at sign-in.
- `subjects(id, name, created_at, created_by)`
- `files(id, subject_id, kind, filename, mime, sha256, r2_key, text_r2_key, status, error, pages, chunk_count, created_at)`
- `papers(id, subject_id, title, created_at, updated_at)`
- `questions(id, paper_id, position, prompt, answer_md, previous_answer_md, status, sources, syllabus_match, model, created_at, updated_at, locked_at)`
  - `position`: fractional index (string or float) so a drag is a single-row write.
  - `sources`: JSON list of `{chunk_id, file_id, page, snippet}`.
- `jobs(id, file_id, stage, attempts, started_at, finished_at, error)`

## Repo layout

```
notesman/
  plan.md
  docker-compose.yml
  pyproject.toml
  .env.example
  src/notesman/
    api/            # FastAPI routers (subjects, files, papers, questions), auth, schemas
    core/           # config, logging, db, r2 client
    ingest/         # converters/, chunker.py, pipeline.py, worker.py
    retrieval/      # qdrant.py, search.py, rerank.py
    llm/            # openrouter.py (embed + chat client)
    rag/            # prompt.py, answer.py (syllabus-aware)
    export/         # md and html rendering for print
  web/              # frontend: workspace UI, drag reorder, print stylesheet
  tests/
  evals/            # question/answer sets and scoring script
```

## Config (env)

`GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `EMBED_MODEL`, `EMBED_DIM`, `CHAT_MODEL`, `QDRANT_COLLECTION`, `QDRANT_URL`, `QDRANT_API_KEY`, `DATABASE_URL`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `GOOGLE_AUTH_CLIENT_ID`, `GOOGLE_AUTH_CLIENT_SECRET`, `SESSION_SECRET`, `SUPERADMIN_EMAIL`, `PUBLIC_BASE_URL`.

## Milestones

1. **M0 Skeleton.** Repo, Docker Compose (Qdrant, DB), config, R2 client, health endpoint.
2. **M0.5 Auth.** Google sign-in, session cookie, `users` table, role middleware, superadmin from env, admin promote and demote.
3. **M1 Ingestion happy path.** Create a subject, upload a text-layer PDF as `syllabus` and another as `reference`, convert, chunk, embed, upsert. Verify with curl.
4. **M2 Answer happy path.** Add a question to a paper, get a syllabus-shaped draft with sources. Lock and unlock. API only.
5. **M3 Frontend core.** Subject list, file upload with kind, paper view, add question, regenerate and nudge, edit, lock and unlock, drag reorder.
6. **M4 Print and export.** Print stylesheet, PDF, Markdown export.
7. **M5 More formats.** EPUB, DOCX, PPTX, OCR for scans. Status and error reporting.
8. **M6 Quality.** Eval set, tune chunk size and top-k, hybrid search and reranking if evals justify it.
9. **M7 Hardening.** Rate limits, retries, idempotency, deletion flows, structured logs, usage tracking.

## Evaluation

- Build a small gold set per sample subject: 30 to 50 questions with expected source pages and expected syllabus topic.
- Metrics: retrieval hit@k (is the right page in top k), syllabus-topic match accuracy, answer faithfulness (judged against retrieved context), scope adherence (no content outside the syllabus), and "correctly refuses when not in the material".
- Run on every change to chunking, embedding model, or prompt. Store results in `evals/results/`.

## Risks and mitigations

- **Bad OCR or conversion on textbooks (math, tables, figures).** Spot-check early on real books. Consider a vision LLM for hard pages. Math may need LaTeX-aware extraction.
- **Syllabus is hard to chunk** (tables, nested units, marks schemes). Chunk by unit heading and check by hand on real syllabi.
- **Answers drift outside the syllabus.** Pass syllabus chunks as explicit scope in the prompt, and add a scope-adherence eval.
- **Embedding model change.** Store `embed_model` and `embed_dim` per point. Re-embedding needs the saved extracted text, which is why we keep it in R2.
- **Gemini and OpenRouter rate limits and cost.** Batch embeddings, cache by content hash, track token usage. AI Studio free-tier limits may be too low for large textbooks.
- **Prompt injection from documents.** Treat chunks as untrusted data in the prompt. Never give the LLM tools in v1.
- **Draft or file leakage to read-only users.** Public routes must filter to `status = locked` in the query, not in the UI. Cover this with a test per public route.
- **Privilege escalation.** Role checks run server-side on every write route. Test that visitor and user tokens get 401 or 403 on each one.
- **Superadmin lockout or takeover.** Superadmin comes only from `SUPERADMIN_EMAIL` plus a verified Google email. Never settable through the API.
- **Cross-subject leakage.** Every Qdrant query must filter by `subject_id`. Cover this with a test.

## Open questions

- Admin onboarding: promote after first sign-in (current plan), or pre-approve emails so they become admin on first sign-in?
- Are all admins equal on all subjects, or does each admin own their own subjects? Current plan: all admins share everything.
- Should some subjects or papers be hidden from the public (unlisted or admin-only)?
- Does a signed-in plain user get anything extra in v1 (bookmarks, last-read)? Current plan: no.

- Frontend framework (Next.js is my suggestion), and whether to keep the Python backend separate from it.
- Confirm `gemini-embedding-2` is available on the AI Studio key (GA ID; `gemini-embedding-2-preview` is the older ID) and that 1536 dimensions retrieves well on real syllabi.
- Which LLM to default to for answers (cost versus quality)?
- Per-question length or marks hint (for example "5 marks" means a short answer)? It would improve syllabus matching.
- Are answers allowed to use world knowledge when the material lacks the answer, or strictly material-only?
- Postgres or SQLite for the relational DB?
- Deployment target (local machine, single VPS with Compose)?


## Answer generation (built)

`POST /v1/questions/{id}/generate` runs `notesman.answer`:

1. **Rewrite** the question into up to 3 search queries (fast model). The original question is always query 1 and counts double.
2. **Hybrid search**, per query, in syllabus and references separately: dense (Gemini) + BM25 sparse (built locally, IDF applied by Qdrant), fused with RRF inside Qdrant, then fused across queries. Always filtered by `subject_id`.
3. **Rerank** 20 reference and 5 syllabus candidates with one listwise LLM call each (scores 0-3, keep >= 2). If nothing is relevant the endpoint returns 422 instead of guessing.
4. **Small-to-big**: the 6 best chunks are expanded with their neighbours in the same section and merged into continuous passages.
5. **Generate** from only those passages. The syllabus is context for scope, terminology and depth, not citable. Steer nudges, the admin comment and the current draft (including manual edits) are included on regenerate. Sources are fenced as untrusted data.
6. **Ground check**: a second call lists claims the sources do not support; if any, one repair pass removes them (`GROUNDING_CHECK=false` turns it off).
7. **Citations** are validated and renumbered 1..k; only cited sources are stored. `syllabus_match` is the section of the best-matching syllabus chunk.

Existing collections need a one-off `uv run python -m notesman.retrieval.migrate` (stop the worker first) to gain the BM25 vector.
