# Tech Stack

## Qdrant
Vector database. Stores and searches memory vectors by semantic similarity. Acts as the primary memory storage — every engram is indexed here as a vector.

**Why Qdrant:**
- Purpose-built for vector search — fast and accurate
- Self-hostable with Docker locally, managed cloud for production
- Free tier covers this project

**Limitations:**
- Not designed for complex structured queries
- No relational support
- Bulk updates are slow compared to SQL

---

## PostgreSQL
Relational database. Stores all engram metadata — `impact`, `stability`, `retrieval_count`/`use_count`, timestamps, memory type. There is no stored "strength" column; retrievability is computed lazily from `stability` and elapsed time, never written to the DB — see `architecture.md`. Acts as the other half of every engram — Qdrant holds the meaning, Postgres holds the details. Together they form one complete memory.

**Why Postgres:**
- Schema is fixed — every engram has the same fields, no flexibility needed
- Consolidation (pruning weak memories) reads `stability`/`last_reinforced_at`/`impact` for every row and issues one batched `DELETE ... WHERE id = ANY(...)` for whatever's prune-eligible — the threshold math itself runs in Python (`memory_operations.consolidate()`), not SQL, but the bulk read/delete pattern is still a natural fit for a relational store, not a document store
- ACID compliance — transaction guarantees when Consolidation updates many records at once
- Better for relational data — if users are added later, foreign keys handle it cleanly

**Why both Qdrant and Postgres:**
They do different jobs. Qdrant finds similar memories by vector. Postgres holds the full engram record and handles scheduled jobs. They connect by ID — Qdrant returns IDs, Postgres returns the full record.

---

## Python + FastAPI
Backend framework. Handles API routes, background jobs, and orchestrates communication between Qdrant and Postgres.

**Why FastAPI:**
- Async support — important for background jobs running alongside API calls
- Auto-generates API docs at `/docs`
- Standard for Python AI/ML projects

### Libraries

#### psycopg2-binary
PostgreSQL driver for Python. Used to connect to Postgres, create tables on startup, and execute queries.

#### torch (CPU-only)
PyTorch is a dependency of sentence-transformers. Using the CPU-only build (`--extra-index-url https://download.pytorch.org/whl/cpu`) keeps the Docker image at ~2.4GB vs ~14.5GB for the full CUDA build. No GPU acceleration in dev — acceptable since inference runs fast enough on CPU for a single-user project. Switch to full PyTorch if deploying on a GPU instance.

#### sentence-transformers
Loads and runs embedding models locally. Acts as the encoding layer — converts raw text into a vector, the form in which it's stored. Similar to how the brain encodes an experience into a neural representation that is consolidated into a memory.

**Model (dev):** `Qwen/Qwen3-Embedding-0.6B` — 64.33 MTEB score, ~1.5GB RAM, **1024 dimensions**
**Model (prod):** `Qwen3-Embedding-8B` via API (OpenRouter, $0.01/M tokens) — decided, not self-hosted. See `prod.md`'s "Embedding Model" section for the full comparison and reasoning.

**Why Qwen3-Embedding-0.6B for dev:**
- 8 points higher than all-MiniLM-L6-v2 (64 vs 56 MTEB) — meaningfully better retrieval quality
- Small enough to run comfortably in Docker on a dev machine

**Loaded once on startup and kept in memory.** The model is stateless during inference — weights do not change between requests. Since embedding is a core dependency in store and retrieve operations, the model is typically loaded once and kept resident in memory. This avoids model reload overhead, so each request only incurs inference compute cost plus standard system overhead such as tokenization, request scheduling, and I/O. This is standard practice for embedding services in production systems regardless of model size.

---

## OpenAI API (Generation)
External LLM API. Handles the "AG" (generation) half of RAG — takes the query, whatever `search()` retrieves, and a small window of recent conversation turns, and produces the actual answer. Also the tool-calling boundary: exposes `reinforce_memory` as a callable tool so the model can mark a memory as meaningfully used, per `architecture.md`'s "On meaningful use" distinction.

**Model:** `gpt-5.4-nano`

**Why GPT-5.4 Nano:**
- Cheapest of the models evaluated — $0.20 / $1.25 per M tokens (input/output), vs GPT-5 mini's $0.25 / $2.00 and GPT-5.4 Mini's $0.75 / $4.50
- Tool-calling reliability matches or beats the pricier GPT-5.4 Mini tier (57.7% vs 56.1% on MCP Atlas) — the only capability that actually matters here, since `reinforce_memory` is the sole tool exposed
- GPT-5.4 Mini's edge over Nano is computer-use and tool search, neither relevant to a single-tool workflow
- Current generation (released March 2026) — unlike Gemini 2.5 Flash Lite, which was ruled out for being scheduled for shutdown October 16, 2026

**Why an API instead of self-hosting:**
- Usable generation quality needs GPU compute; DigitalOcean GPU droplets run ~$2.50–$6.74/hr even sitting idle, versus pay-per-token pricing — at this project's low, sporadic query volume, self-hosting would cost far more than it saves
- Unlike the embedding model (small, called on every store *and* search, cheap enough for CPU), generation runs far less often and needs a much bigger model to produce good output — the "already-paid-for idle CPU" argument that justifies self-hosting embeddings doesn't hold here

**Alternatives considered:**
- Claude Haiku 4.5 — priciest candidate on both input and output, no offsetting reliability edge for this use case
- Llama 3.3 70B / Llama-3-Groq-70B-Tool-Use (Groq) — legitimate contender, strong published BFCL tool-calling score and cheap output pricing, but Nano beat it on cost without giving anything up
- Gemini 2.5 Flash Lite — cheapest raw pricing, but ruled out over the Oct 2026 shutdown
- GPT-5 mini (previous OpenAI generation) — superseded by GPT-5.4 Nano on both cost and tool-calling

**Statelessness:** like every LLM chat API, each call is independent — nothing is retained between requests. Engram reconstructs the relevant context (system prompt + retrieved memories + a small bounded window of recent turns) and resends it in full on every generation call. This is exactly why the Qdrant/Postgres layer exists as a separate system — the LLM itself has no persistent memory to lean on.

---

## React + Vite (Frontend)
Single-page chat interface in `frontend/`. Calls `/generate` directly — no server-side rendering, no backend logic of its own, since the actual backend already exists separately.

**Why React + Vite, not Next.js:**
- No SEO needs — a personal chat tool, not public marketing content
- No server-side rendering needs — just a UI hitting an existing API
- No Route Handlers needed — all backend logic already lives in the separate FastAPI backend; the frontend only ever calls it
- Builds to pure static files with no framework-specific adapter needed for Cloudflare Pages (see `prod.md`) — Next.js would've needed `@cloudflare/next-on-pages`, which has real compatibility gaps (e.g. `firebase-admin` doesn't work on Cloudflare Workers at all)

**CORS**: the backend's `CORSMiddleware` (see `security-preventions.md`) is what makes cross-origin calls from the frontend possible at all — configurable via `ALLOWED_ORIGINS`, defaults to the Vite dev server (`http://localhost:5173`).

**Sliding window for `recent_turns`**: the frontend caps what it sends to `/generate` at the last 20 messages (`RECENT_TURNS_LIMIT` in `App.tsx`), not the full conversation history. Not primarily a cost decision — at this project's usage scale a full 20-message conversation costs about $0.0015, negligible either way. The real reasons: avoiding "lost in the middle" quality degradation on unusually long conversations, and staying nowhere near GPT-5.4 Nano's 400K token context ceiling. 20 was chosen because it roughly matches typical conversation length, so it rarely triggers for normal use — it's a ceiling for the runaway case, not a constraint on typical usage.

**Analytics panel**: alongside the chat, each message gets its own card showing that query's real retrieval/generation data — every retrieved memory's `semantic`/`retrievability`/`frequency`/`final_score` plus the raw `stability`/`use_count`/`age_days`/`impact` values behind them, and a "reinforced" tag on whichever ones the model actually cited (cross-referencing `reinforced_memory_ids` against `retrieved`). This is the actual reason those raw fields were added to `search_memories()`'s response (see `dataModel.md`) — no new endpoints needed, `/generate` already returned everything required. Observed in practice that the model's tool-calling isn't perfectly consistent — the same or similar query can reinforce 0, 1, or all 5 retrieved memories across different runs, a real, visible instance of the tool-calling reliability tradeoff already documented under "Why GPT-5.4 Nano" above.

**Header info buttons** (About / Formulas / Neuroscience): static reference content — what Engram is, the actual ranking/decay/reinforcement formulas, and plain-English explanations of each stat grounded in the same reasoning already documented in `architecture.md` (the testing effect, flashbulb memories, etc.). No backend calls, just hardcoded content mirrored from the docs.

