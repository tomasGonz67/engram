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
- Decay-Based Forgetting reads `id`/`stability`/`last_reinforced_at`, computes eligibility in Python (`memory_operations.delete_decayed_memories()`), and deletes eligible Postgres rows in one transactional batch (`DELETE ... WHERE id = ANY(...)`) — the bulk read/delete pattern is still a natural fit for a relational store, not a document store
- ACID compliance — the Postgres batch delete itself is transactional, but the Qdrant deletion that follows is a separate operation; the complete dual-store deletion is not atomic (see `techDebt.md`'s "Non-atomic dual-store writes/deletes" entry)
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

#### slowapi
Rate limiting. IP-keyed since Masi Memory has no auth/session concept to key on instead — see `architecture.md`'s permanent no-auth decision. Keying goes through `backend/rate_limit.py`'s `get_rate_limit_key()`, not `slowapi`'s own `get_remote_address()` directly — `get_remote_address()` only ever reads the immediate TCP peer, which becomes wrong once a reverse proxy sits in front (see `prod.md`'s "Reverse proxy & trusted client IP"). `get_rate_limit_key()` instead calls `trusted_proxy.resolve_client_ip()`, which reads `X-Forwarded-For` only when the immediate peer is in an explicitly configured, fail-fast-validated trust set (`TRUSTED_PROXY_IPS`) — empty/unset by default, identical to `get_remote_address()`'s behavior until that's actually configured for a real deployment. In-memory storage (`slowapi`'s default), not Redis-backed — correct for the actual deployment shape (a single DigitalOcean droplet running one backend process, not multiple instances needing shared state — see `prod.md`).

One shared limit — `20 requests per 5 minutes` + `200 per day` — pooled across `store`, `search`, and `generate` via `limiter.shared_limit(..., scope="global_api")` in `backend/rate_limit.py`, rather than each route getting its own independent allowance. See `security-preventions.md`'s Resolved section for the full reasoning, including two real gotchas found while building this: `default_limits` on the `Limiter` constructor does nothing without an explicit decorator on each route, and a per-route `@limiter.limit(...)` decorator (rather than `shared_limit`) gives each route its own separate bucket instead of one pooled total.

#### torch (CPU-only)
PyTorch is a dependency of sentence-transformers. Using the CPU-only build (`--extra-index-url https://download.pytorch.org/whl/cpu`) keeps the Docker image at ~2.4GB vs ~14.5GB for the full CUDA build. No GPU acceleration in dev — acceptable since inference runs fast enough on CPU for a single-user project. Switch to full PyTorch if deploying on a GPU instance.

#### sentence-transformers
Loads and runs embedding models locally. Acts as the encoding layer — converts raw text into a vector, the form in which it's stored. Only a loose analogy to neural encoding, and only to the *encoding* step specifically — it does not implement biological encoding, and it's not consolidation either: consolidation is a separate, time-dependent stabilization/reorganization process (potentially involving longer-term hippocampal-neocortical reorganization), not the immediate act of forming a representation. Encoding and consolidation are different stages in the actual research; this is encoding only, and even that is a loose analogy, not a model.

**Model (dev):** `Qwen/Qwen3-Embedding-0.6B` — 64.33 MTEB score, ~1.5GB RAM, **1024 dimensions**
**Model (prod):** `Qwen3-Embedding-8B` via API (OpenRouter, $0.01/M tokens) — decided, not self-hosted. See `prod.md`'s "Embedding Model" section for the full comparison and reasoning.

**Why Qwen3-Embedding-0.6B for dev:**
- 8 points higher than all-MiniLM-L6-v2 (64 vs 56 MTEB) — meaningfully better retrieval quality
- Small enough to run comfortably in Docker on a dev machine

**Loaded once on startup and kept in memory.** The model is stateless during inference — weights do not change between requests. Since embedding is a core dependency in store and retrieve operations, the model is typically loaded once and kept resident in memory. This avoids model reload overhead, so each request only incurs inference compute cost plus standard system overhead such as tokenization, request scheduling, and I/O. This is standard practice for embedding services in production systems regardless of model size.

**Query instruction prefix**: Qwen3-Embedding is instruction-aware — its model card recommends prefixing *queries* (not documents) with a task instruction for retrieval, typically worth 1-5%. `search_memories()` (`routers/memories.py`) prepends `RETRIEVAL_QUERY_INSTRUCTION` (`constants.py`) to the query text before embedding; stored memory text stays bare, matching the model's own config (an empty prompt for "document," a real one for "query"). Applied via plain string concatenation rather than `sentence-transformers`' `prompt_name="query"` shortcut, deliberately — manual concatenation keeps query construction portable across the local and planned API paths without relying on `sentence-transformers`-specific prompt plumbing. That portability is about how the query text gets built, not a claim that retrieval behavior itself is identical across the two paths — prod swaps in a different model entirely (`Qwen3-Embedding-8B`, 4096 dimensions, via a remote provider) rather than just a different code path to the same 0.6B model, and provider-side tokenization/normalization/truncation could plausibly differ too. Empirically tested before adopting, not just applied on the model card's say-so — see `architecture.md`'s "How Retrieval Works" for the actual measured numbers (Recall@5, MRR, negative-query separation) and `security-preventions.md`'s Resolved section for the full experiment — but that testing was against the dev `Qwen3-Embedding-0.6B` model only. Retrieval behavior still needs to be re-evaluated against the production 8B provider before assuming the same results carry over.

---

## OpenAI API (Generation)
External LLM API. Handles the "AG" (generation) half of RAG — takes the query, whatever `search()` retrieves, and a small window of recent conversation turns, and produces the actual answer. No function calling is involved — `/generate` sends one plain completion request; a code-level guardrail decides reinforcement afterward, entirely outside the model (see `architecture.md`'s "How Generation Works").

**Model:** `gpt-5.4-nano`

**Why GPT-5.4 Nano:**
- Cheapest of the models evaluated — $0.20 / $1.25 per M tokens (input/output), vs GPT-5 mini's $0.25 / $2.00 and GPT-5.4 Mini's $0.75 / $4.50
- Current generation (released March 2026) — unlike Gemini 2.5 Flash Lite, which was ruled out for being scheduled for shutdown October 16, 2026
- Tool-calling reliability was originally part of this decision (Nano matched or beat the pricier GPT-5.4 Mini tier on MCP Atlas at the time) — no longer a live factor, since `/generate` stopped using function calling entirely (see `architecture.md`'s "Why there's no function calling"). The cost and currency reasons above still stand on their own regardless; nothing here forces revisiting the model choice, but if it were being made fresh today, tool-calling benchmarks wouldn't be part of the comparison.

**Why an API instead of self-hosting:**
- Usable generation quality needs GPU compute; DigitalOcean GPU droplets run ~$2.50–$6.74/hr even sitting idle, versus pay-per-token pricing — at this project's low, sporadic query volume, self-hosting would cost far more than it saves
- Unlike the embedding model (small, called on every store *and* search, cheap enough for CPU), generation runs far less often and needs a much bigger model to produce good output — the "already-paid-for idle CPU" argument that justifies self-hosting embeddings doesn't hold here

**Alternatives considered** (at the time of the original decision, when tool-calling capability was still a factor):
- Claude Haiku 4.5 — priciest candidate on both input and output, no offsetting reliability edge for this use case
- Llama 3.3 70B / Llama-3-Groq-70B-Tool-Use (Groq) — legitimate contender, strong published BFCL tool-calling score and cheap output pricing, but Nano beat it on cost without giving anything up
- Gemini 2.5 Flash Lite — cheapest raw pricing, but ruled out over the Oct 2026 shutdown
- GPT-5 mini (previous OpenAI generation) — superseded by GPT-5.4 Nano on cost regardless of tool-calling

**Statelessness:** like every LLM chat API, each call is independent — nothing is retained between requests. Masi Memory reconstructs the relevant context (system prompt + retrieved memories + a small bounded window of recent turns) and resends it in full on every generation call. This is exactly why the Qdrant/Postgres layer exists as a separate system — the LLM itself has no persistent memory to lean on.

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

**Analytics panel**: alongside the chat, each message gets its own card showing that query's real retrieval/generation data — every retrieved memory's `semantic`/`retrievability`/`frequency`/`final_score` plus the raw `stability`/`use_count`/`age_days`/`impact` values behind them, and a "reinforced" tag on whichever ones the reinforcement guardrail estimated were reflected in the answer (cross-referencing `reinforced_memory_ids` against `retrieved`). This is the actual reason those raw fields were added to `search_memories()`'s response (see `dataModel.md`) — no new endpoints needed, `/generate` already returned everything required. The same or similar query can still reinforce anywhere from 0 to all 5 retrieved memories across different runs — not because of tool-calling variance anymore (there's no tool calling), but because the model's answer wording genuinely varies between runs, and the guardrail checks that actual wording each time.

**Header info buttons** (About / Formulas / Neuroscience): static reference content — what Masi Memory is, the actual ranking/decay/reinforcement formulas, and plain-English explanations of each stat grounded in the same reasoning already documented in `architecture.md` (the testing effect, flashbulb memories, etc.). No backend calls, just hardcoded content mirrored from the docs.

