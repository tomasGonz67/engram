# Production Considerations

## Architecture Overview

The full production plan, settled after comparing cost/quality/performance tradeoffs for each piece individually — not a first guess, a conclusion reached by actually pricing out the alternatives. Revised once already: an earlier version of this plan had frontend and backend co-located on one droplet specifically so the backend could stay fully internal — that's no longer the plan, see below for why.

- **Frontend**: React + Vite, static build, hosted on **Cloudflare Pages** (free tier — unlimited bandwidth, commercial use allowed, free `*.pages.dev` subdomain with HTTPS included). Chosen over Vercel because this project's shape doesn't need what Vercel's actually good at — no SEO, no server-side rendering, no Route Handlers, since the backend already exists separately and the frontend just calls it. Cloudflare Pages wins instead on bandwidth (unlimited vs. Vercel's 100GB cap), commercial-use terms, and raw performance (~45ms global TTFB vs. Vercel's ~70ms). Also sets up naturally for adding Cloudflare's DDoS protection on the backend later, under the same account — see "Generation API" below.
- **Backend**: FastAPI on a **DigitalOcean droplet** — not a serverless platform, and not optional. Render's free tier spins down after 15 minutes of inactivity; at Masi Memory's low, sporadic traffic that would kill Consolidation's persistent background loop before it ever completed a full weekly cycle. Supabase's compute option (Edge Functions) is Deno/JavaScript, not Python, and is also stateless/serverless — same fundamental problem. A real, always-on process is a hard requirement here, not a preference, because of Consolidation specifically.
- **Repo structure**: one monorepo, `backend/` and `frontend/` as subdirectories (already the shape of this repo), each deployed independently — Cloudflare Pages points at `frontend/` as its build root, the droplet's Docker setup points at `backend/` (already the case today). Hosting two pieces in different places doesn't require splitting them into separate repos; both platforms support deploying from a subdirectory of a larger repo.
- **Domain/DNS**: no purchased domain. Frontend uses Cloudflare Pages' free `*.pages.dev` subdomain. Backend HTTPS: **try a direct Let's Encrypt IP certificate first.** Let's Encrypt has issued real, trusted certificates for bare IPv4/IPv6 addresses since general availability on January 15, 2026 — no hostname needed at all, not even `sslip.io`. Two catches: these certs are only valid for 160 hours (~6.67 days) instead of the usual 90, so renewal has to succeed roughly every 5-6 days instead of every ~60 — much less buffer before a renewal hiccup becomes an actual outage. They also require an ACME client with "ACME Profiles" support and explicit selection of the `shortlived` profile — a genuinely new (mid-2026-era) capability with visible early friction in other tooling (e.g. an open Caddy GitHub issue hitting exactly this). Since this is a personal project, the actual cost of a renewal failure is low (brief downtime until manually noticed and fixed, not a real business cost), so it's worth just trying this directly with Traefik. **Fallback if Traefik doesn't handle ACME Profiles/`shortlived` cleanly**: a free `sslip.io` hostname (e.g. `<droplet-ip-with-dashes>.sslip.io`) instead of the bare IP — rides the long-established, reliably-automated 90-day certificate flow Traefik already supports, same pattern already used for Eleutheria.
- **Postgres**: Neon (managed, free tier). Not self-hosted on the droplet.
- **Vector DB**: Qdrant Cloud (managed, free tier). Not self-hosted on the droplet.
- **Generation**: OpenAI `gpt-5.4-nano`, API (see `techStack.md`).
- **Embedding**: `Qwen3-Embedding-8B`, API (via OpenRouter). Not self-hosted in prod — differs from dev, see "Embedding Model" below.

**A real consequence of splitting frontend and backend across platforms**: the backend can no longer stay fully internal the way co-locating it with the frontend would have allowed — Cloudflare Pages has no fixed outbound IPs to allowlist against, so the backend has to be publicly reachable for the frontend to call it at all. Accepted deliberately, specifically because rate limiting is already a required prerequisite regardless of this decision (see below) — it doesn't eliminate the added exposure, but it meaningfully narrows what that exposure actually costs.

With Postgres, Qdrant, and both AI models all external/managed, and the frontend hosted separately, the droplet itself only runs the backend process — no database, no vector store, no ML model resident in memory, no static files to serve either. That's what makes the cheapest viable droplet tier realistic instead of needing a 4GB+ instance just to hold an embedding model in RAM.

**Rate limiting on `store`, `search`, and `generate` is done** — all three now carry real per-call cost once both API migrations happen (Postgres/Qdrant are flat-rate free tiers, not billed per-call, so they don't carry this same risk), and Masi Memory has no auth by design, so nothing else currently gates who can hit them. Implemented with `slowapi`, one shared `20/5minutes;200/day` limit pooled across all three routes rather than per-route — see `security-preventions.md`'s Resolved section. See "Embedding Model" and "Generation API" below for what else this migration still needs.

---

## PyTorch — dev only

Currently using CPU-only PyTorch to keep the Docker image small (~2.4GB vs ~14.5GB with full PyTorch). This only matters for **dev**, where the embedding model still runs self-hosted (see below) — prod no longer runs any local embedding inference at all once the migration happens, so the prod image wouldn't need `torch`/`sentence-transformers` as dependencies.

**Why CPU is acceptable for dev:**
- Single-user, low throughput — one request at a time
- ~50-200ms per embedding on CPU is imperceptible at this scale

---

## Dockerfile's `--reload` flag — dev-only, must not ship to prod

The single `backend/Dockerfile` bakes `--reload` into its `CMD` (`uvicorn main:app --host 0.0.0.0 --port 8000 --reload`), and there's no separate prod Dockerfile. `--reload` runs a file-watcher process that continuously monitors the app directory and restarts the server on any change — meant for the dev workflow of "restart fast when I save a file," not for a production image that's never supposed to change while running. Three concrete costs of leaving it in prod:

- **Wasted resources** watching for file changes that should never happen against an immutable production deployment.
- **A real failure surface, not just a theoretical one** — `--reload` works by running the app in a separate subprocess while a parent process watches and manages restarts. This project has already been bitten by exactly that dual-process behavior once: see `techDebt.md`'s "Double startup on uvicorn reload," where Qdrant collection creation fired twice because of it. That happened in dev, where the stakes were low; the same class of bug in production would matter more.
- **Fights against how production should scale** — real deployments typically want multiple worker processes for concurrency/resilience, and `--reload` mode is fundamentally single-process, built around the dev restart-on-save loop, not production traffic.

Whichever compose file or deployment config ends up building this image for production needs to either override the `CMD` to drop `--reload`, or use a separate prod-specific Dockerfile — not build the current one as-is.

---

## Embedding Model

**Dev**: self-hosted `Qwen3-Embedding-0.6B` (1024 dimensions, ~1.5GB RAM) — see `techStack.md`.

**Prod**: `Qwen3-Embedding-8B` via API (OpenRouter, $0.01/M tokens) — not self-hosted. Decision history, in order:

1. First compared self-hosted 0.6B against OpenAI's `text-embedding-3-small` API. Self-hosted won outright — 64.33 MTEB vs 62.3, and *smaller* (1024 vs 1536 dimensions). Switching to that specific API would've been a downgrade on quality and storage both, for no benefit besides droplet RAM. Rejected.
2. Then compared against the bigger Qwen3 variants. `Qwen3-Embedding-8B` scores 70.58 MTEB — a real jump over the current 64.33 — but self-hosting an 8B-parameter model isn't realistic on a budget droplet (~13x more parameters than 0.6B; would need a GPU instance, likely $500-1000+/mo). Via API, though, it's $0.01/M tokens — cheaper than the OpenAI option already rejected, and better quality than what's currently self-hosted. At Masi Memory's actual usage volume this costs pennies a month regardless, so there's no real cost tradeoff to weigh — just better model, no new infra spend.

**Consequence**: vector dimensions change from 1024 (current) to 4096 (`Qwen3-Embedding-8B`). Vector dimensions are fixed at collection creation time in Qdrant — this requires creating a new collection and re-embedding every stored memory, not a config toggle. It also reduces how many vectors fit in Qdrant Cloud's free tier from roughly ~100k down to ~25k — still vastly more than this project needs, but worth knowing since it's a real, measurable tradeoff of the switch.

**Prerequisite, done**: rate limiting on `store`/`search` — both become tied to an external API bill once this migration ships, and Masi Memory has no auth to gate them. See `security-preventions.md`'s Resolved section.

---

## Postgres — Neon (managed)

Not self-hosted in prod — moved to Neon's free tier (0.5GB storage/project, up to 100 projects, scale-to-zero, $0 permanently). Picked over Supabase specifically because Masi Memory only needs a plain `psycopg2` connection — Supabase bundles Auth/Storage/Realtime/Edge Functions that would sit entirely unused, adding complexity for no benefit. Supabase becomes the better pick only if Masi Memory ever actually uses `pgvector` to consolidate the metadata and vector stores into one database (a real, considered alternative — see "Vector DB" below — but a bigger rearchitecture than a hosting swap, not adopted here).

Migration is simple: `database.py` already reads all Postgres connection info from environment variables (`POSTGRES_HOST`, `POSTGRES_PORT`, etc.) — pointing at Neon instead of the local `postgres` container is just swapping those env var values, no code changes needed.

At Masi Memory's realistic scale (currently ~100 memory rows, ~200-500 bytes/row), 500MB comfortably holds somewhere between 1-2.5 million rows — not a real constraint at any scale this project is likely to reach as a personal tool.

Neon's scale-to-zero means a brief cold-start delay on the first query after a period of inactivity — a non-issue given Masi Memory's actual latency requirements (personal, sporadic usage, not a real-time system).

---

## Vector DB — Qdrant Cloud (managed)

Not self-hosted in prod — moved to Qdrant Cloud's free tier (0.5 vCPU, 1GB RAM, 4GB disk, $0 permanently). This was actually the original plan from `techStack.md`'s own initial reasoning ("self-hostable with Docker locally, managed cloud for production... free tier covers this project"), written before any of this session's work — this decision just confirms and acts on it.

**RAM, not disk, is the binding constraint** for a vector DB specifically — search performance depends on keeping the HNSW index resident in memory, unlike a relational DB, which can page rows in from disk on demand for typical indexed lookups. At ~10-15KB/vector (1024-dim, current) this free tier holds roughly 70-100k vectors; at ~4096-dim (`Qwen3-Embedding-8B`, once that migration happens) roughly 25k. Either way, vastly more than Masi Memory's current scale (~100 memories) will realistically need.

Requires an API key for access — unlike the current self-hosted Qdrant, which has no auth at all since it only lives on the private Docker network today. One more secret to manage, same pattern as `OPENAI_API_KEY` (env var, gitignored `.env`, never hardcoded in a committed compose file).

**Considered alternative, not adopted**: consolidating Postgres and Qdrant into one database via Supabase's `pgvector` extension — this would incidentally fix the non-atomic dual-store write/delete bug already logged in `techDebt.md`, since one transaction could cover both the vector and the metadata. Genuine benefit, but a real rearchitecture (touches `database.py`, `search_memories()`'s two-stage retrieval, and most of `architecture.md`/`dataModel.md`), not a hosting swap — logged here as a real option for later, not something decided against permanently.

---

## Generation API (OpenAI) — required for prod

The generation model (`gpt-5.4-nano`, see `techStack.md`) is an external paid API — every `/generate` call costs real money. Combined with the embedding model move above, **three routes** (`store`, `search`, `generate`) all carry real per-call cost once both API migrations are live, not just `/generate` alone — and by design (no auth, ever) all three are reachable by anyone who finds the URL.

**Before any public deployment:**
- ~~Rate limiting on all three routes~~ — done, see `security-preventions.md`'s Resolved section.
- A spend cap/budget alert on both the OpenAI account and whichever provider hosts the embedding API — not just an app-level rate limit, the same reasoning as spend alerts on any cloud account, since the app-level limit is the only thing standing between a traffic spike and an unbounded bill. Still not confirmed set.

DDoS protection (e.g. proxying through Cloudflare's free tier) is a separate, additional layer worth adding eventually — rate limiting alone doesn't stop network-level flood attacks, since those can saturate the droplet's bandwidth before any application code even runs. Not yet decided on/built; noted here as a known gap, not solved by anything above.

---

## ENVIRONMENT variable — required for prod

`scripts/clear.sh` (see `DEVELOPMENT.md`) destroys all Postgres and Qdrant data and refuses to run if `ENVIRONMENT` resolves to `production` — but it reads that value out of the compose file it's pointed at, not a host shell variable. There is no production deployment yet, but whichever compose file (or equivalent config) ends up defining the production environment **must** set `ENVIRONMENT: production` on the backend service. Without it, this guard is a no-op and the reset script could be run against production data.

Note: once Postgres and Qdrant move to Neon/Qdrant Cloud (see above), `clear.sh` as currently written won't apply to them at all — it only resets the local Docker volumes. Whatever replaces it for a managed-service world still needs the same production safety check, just implemented against Neon/Qdrant Cloud's own reset/branch-reset mechanisms instead of `docker volume rm`.
