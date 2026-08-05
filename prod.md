# Production Considerations

## Architecture Overview

The full production plan, settled after comparing cost/quality/performance tradeoffs for each piece individually — not a first guess, a conclusion reached by actually pricing out the alternatives. Revised once already: an earlier version of this plan had frontend and backend co-located on one droplet specifically so the backend could stay fully internal — that's no longer the plan, see below for why.

**Status: backend live in prod. Frontend not yet deployed.** DigitalOcean droplet provisioned (Ubuntu 24.04, NYC1), Docker/firewall/certbot set up, the backend built and running there against real Neon (Postgres) and Qdrant Cloud accounts, embeddings via OpenRouter (`Qwen3-Embedding-8B`), generation via OpenAI, all reachable over a real, publicly-trusted HTTPS endpoint (`https://134-209-121-221.sslip.io`, no reverse proxy — see "TLS & Reverse Proxy" below) with no `curl -k` needed. Verified live end-to-end: stored a memory, retrieved it with real ranking scores, and generated an answer citing it, all through the public endpoint. Cloudflare Pages (frontend) is the one piece from this section not yet done — dev's frontend still points at `localhost:8000`. Read anything below still phrased as "the plan is to move to X" at face value for whatever hasn't shipped yet; sections describing what's actually live say so directly.

- **Frontend**: React + Vite, static build, hosted on **Cloudflare Pages** (free tier — unlimited bandwidth, commercial use allowed, free `*.pages.dev` subdomain with HTTPS included). Chosen over Vercel because this project's shape doesn't need what Vercel's actually good at — no SEO, no server-side rendering, no Route Handlers, since the backend already exists separately and the frontend just calls it. Cloudflare Pages wins instead on bandwidth (unlimited vs. Vercel's 100GB cap), commercial-use terms, and raw performance (~45ms global TTFB vs. Vercel's ~70ms). Also sets up naturally for adding Cloudflare's DDoS protection on the backend later, under the same account — see "Generation API" below.
- **Backend**: FastAPI on a **DigitalOcean droplet** — not a serverless platform, and not optional. Render's free tier spins down after 15 minutes of inactivity; at Masi Memory's low, sporadic traffic that would kill the Decay-Based Forgetting loop's persistent background process before it ever completed a full weekly cycle. Supabase's compute option (Edge Functions) is Deno/JavaScript, not Python, and is also stateless/serverless — same fundamental problem. A real, always-on process is a hard requirement here, not a preference, because of Decay-Based Forgetting specifically.
- **Repo structure**: one monorepo, `backend/` and `frontend/` as subdirectories (already the shape of this repo), each deployed independently — Cloudflare Pages points at `frontend/` as its build root, the droplet's Docker setup points at `backend/` (already the case today). Hosting two pieces in different places doesn't require splitting them into separate repos; both platforms support deploying from a subdirectory of a larger repo.
- **Domain/DNS**: no purchased domain. Frontend uses Cloudflare Pages' free `*.pages.dev` subdomain. Backend HTTPS: a free `sslip.io` hostname (e.g. `<droplet-ip-with-dashes>.sslip.io`) — a real DNS name that resolves to the droplet's own IP, so the standard, long-established 90-day Let's Encrypt certificate flow applies (certbot, no special ACME Profiles/`shortlived` support needed). Deliberately chosen over the bare-IP short-lived-certificate route (real as of January 2026, but only 160-hour/~6.67-day certs, needing renewal every 5-6 days instead of every ~60-90) — `sslip.io` gets the same "no domain purchase needed" outcome with a far more forgiving renewal cadence.
- **No reverse proxy — Uvicorn terminates TLS directly.** Originally planned around Traefik (for ACME cert automation and reverse-proxy trust-chain handling), reconsidered and dropped: with `sslip.io` making the plain 90-day certbot flow available, the main thing Traefik was buying was cert *automation*, not cert *capability* — and removing it also removes an entire category of deployment complexity for a single-droplet, low-traffic personal project. See "TLS & Reverse Proxy" below for the full account, including what this simplifies and what it costs.
- **Postgres**: Neon (managed, free tier). Not self-hosted on the droplet.
- **Vector DB**: Qdrant Cloud (managed, free tier). Not self-hosted on the droplet.
- **Generation**: OpenAI `gpt-5.4-nano`, API (see `techStack.md`).
- **Embedding**: `Qwen3-Embedding-8B`, API (via OpenRouter). Not self-hosted in prod — differs from dev, see "Embedding Model" below.

**A real consequence of splitting frontend and backend across platforms**: the backend can no longer stay fully internal the way co-locating it with the frontend would have allowed — Cloudflare Pages has no fixed outbound IPs to allowlist against, so the backend has to be publicly reachable for the frontend to call it at all. Accepted deliberately, specifically because rate limiting is already a required prerequisite regardless of this decision (see below) — it doesn't eliminate the added exposure, but it meaningfully narrows what that exposure actually costs.

With Postgres, Qdrant, and both AI models all external/managed under this plan, and the frontend hosted separately, the droplet — once it exists — would only need to run the backend process: no database, no vector store, no ML model resident in memory, no static files to serve either. That's what makes the cheapest viable droplet tier realistic instead of needing a 4GB+ instance just to hold an embedding model in RAM.

**Rate limiting on `store`, `search`, and `generate` is done, and stays correct with no further work under this architecture.** All three now carry real per-call cost once both API migrations happen (Postgres/Qdrant are flat-rate free tiers, not billed per-call, so they don't carry this same risk), and Masi Memory has no auth by design, so nothing else currently gates who can hit them. Implemented with `slowapi`, one shared `20/5minutes;200/day` limit pooled across all three routes rather than per-route — see `security-preventions.md`'s Resolved section. With no reverse proxy in front of Uvicorn (see "TLS & Reverse Proxy" below), `request.client.host` is always the real caller's direct TCP peer, so `get_rate_limit_key()`/`resolve_client_ip()` resolve correctly by default — no `TRUSTED_PROXY_IPS` configuration needed for this deployment. See "Embedding Model" and "Generation API" below for what else this migration still needs.

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

**Status: code done, account/key not yet set up.** `database.py`'s `_OpenRouterEmbedder` mirrors `SentenceTransformer`'s `.encode()` interface (returns the same numpy array shape, so every existing call site works unchanged), gated on `OPENROUTER_API_KEY` being set rather than on `ENVIRONMENT` directly — dev keeps self-hosting unless that var is present. `VECTOR_SIZE` now tracks which branch is active (1024/4096) automatically, so the collection gets created at the right dimension from the start. Verified by building the actual prod image and importing the module inside it with the real prod env var shape (dummy key values, no live API call needed to prove the import graph and branch selection are correct) — confirmed it selects `_OpenRouterEmbedder`, `VECTOR_SIZE=4096`, and never imports `sentence_transformers` at all (not installed in the prod image, would otherwise crash on startup). The "requires re-embedding every stored memory" consequence above doesn't apply to this specific deployment — the Qdrant Cloud collection doesn't exist yet, so it gets created at 4096 dimensions from scratch, not migrated from an existing 1024-dim one. Still needed: the actual OpenRouter account and API key.

---

## Postgres — Neon (managed)

Not self-hosted in prod — the plan is to move to Neon's free tier (0.5GB storage/project, up to 100 projects, scale-to-zero, $0 permanently; not yet migrated — see "Architecture Overview"'s status note above). Picked over Supabase specifically because Masi Memory only needs a plain `psycopg2` connection — Supabase bundles Auth/Storage/Realtime/Edge Functions that would sit entirely unused, adding complexity for no benefit. Supabase becomes the better pick only if Masi Memory ever actually uses `pgvector` to consolidate the metadata and vector stores into one database (a real, considered alternative — see "Vector DB" below — but a bigger rearchitecture than a hosting swap, not adopted here).

Migration is simple: `database.py` already reads all Postgres connection info from environment variables (`POSTGRES_HOST`, `POSTGRES_PORT`, etc.) — pointing at Neon instead of the local `postgres` container is just swapping those env var values, no code changes needed.

At Masi Memory's realistic scale (currently 980 canonical development-memory rows, with each metadata row still small), 500MB leaves ample room for growth and is not a meaningful constraint for this prototype.

Neon's scale-to-zero means a brief cold-start delay on the first query after a period of inactivity — a non-issue given Masi Memory's actual latency requirements (personal, sporadic usage, not a real-time system).

---

## Vector DB — Qdrant Cloud (managed)

Not self-hosted in prod — the plan is to move to Qdrant Cloud's free tier (0.5 vCPU, 1GB RAM, 4GB disk, $0 permanently; not yet migrated — see "Architecture Overview"'s status note above). This was actually the original plan from `techStack.md`'s own initial reasoning ("self-hostable with Docker locally, managed cloud for production... free tier covers this project"), written before any of this session's work — this decision just confirms and acts on it.

**RAM, not disk, is the binding constraint** for a vector DB specifically — search performance depends on keeping the HNSW index resident in memory, unlike a relational DB, which can page rows in from disk on demand for typical indexed lookups. At ~10-15KB/vector (1024-dim, current) this free tier holds roughly 70-100k vectors; at ~4096-dim (`Qwen3-Embedding-8B`, once that migration happens) roughly 25k. Either way, that remains well above the current 980-memory development corpus.

Requires an API key for access — unlike the current self-hosted Qdrant, which has no auth at all since it only lives on the private Docker network today. One more secret to manage, same pattern as `OPENAI_API_KEY` (env var, gitignored `.env`, never hardcoded in a committed compose file).

**Considered alternative, not adopted**: consolidating Postgres and Qdrant into one database via Supabase's `pgvector` extension — this would incidentally fix the non-atomic dual-store write/delete bug already logged in `techDebt.md`, since one transaction could cover both the vector and the metadata. Genuine benefit, but a real rearchitecture (touches `database.py`, `search_memories()`'s two-stage retrieval, and most of `architecture.md`/`dataModel.md`), not a hosting swap — logged here as a real option for later, not something decided against permanently.

---

## Generation API (OpenAI) — required for prod

The generation model (`gpt-5.4-nano`, see `techStack.md`) is an external paid API — every `/generate` call costs real money. Combined with the embedding model move above, **three routes** (`store`, `search`, `generate`) all carry real per-call cost once both API migrations are live, not just `/generate` alone — and by design (no auth, ever) all three are reachable by anyone who finds the URL.

**Before any public deployment:**
- ~~Rate limiting on all three routes~~ — done, and correct as-is under this architecture: no reverse proxy sits in front of Uvicorn (see "TLS & Reverse Proxy" above), so there's no forwarded-header trust chain to wire up — `request.client.host` is already the real caller.
- A spend cap/budget alert on both the OpenAI account and whichever provider hosts the embedding API — not just an app-level rate limit, the same reasoning as spend alerts on any cloud account, since the app-level limit is the only thing standing between a traffic spike and an unbounded bill. Still not confirmed set.

DDoS protection (e.g. proxying through Cloudflare's free tier) is a separate, additional layer worth adding eventually — rate limiting alone doesn't stop network-level flood attacks, since those can saturate the droplet's bandwidth before any application code even runs. Not yet decided on/built; noted here as a known gap, not solved by anything above. If this is ever adopted, it reintroduces exactly the reverse-proxy trust problem "TLS & Reverse Proxy" above describes avoiding — `TRUSTED_PROXY_IPS` would need a real value then (Cloudflare's published IP ranges), and the rate-limiting test matrix would need re-running through that proxy, same as the original Traefik plan would have required.

---

## TLS & Reverse Proxy — decided: no reverse proxy, Uvicorn terminates TLS directly

**Reversed from the original plan.** `prod.md` originally called for Traefik in front of Uvicorn, for two reasons: automated ACME certificate management, and resolving the real caller's IP for rate limiting once something sits between the caller and Uvicorn. Reconsidered once `sslip.io` was chosen for the domain (see "Architecture Overview" above) — a real hostname means the standard, well-supported certbot/Let's Encrypt flow is available directly, so a dedicated reverse proxy is no longer needed just to get automated HTTPS. Dropping it removes real complexity, not just a container: **there is no reverse proxy in this architecture, so there is no second hop for rate limiting to be fooled by** — `request.client.host` is always the actual TCP peer, so `backend/rate_limit.py`'s `get_rate_limit_key()` (via `trusted_proxy.resolve_client_ip()`) resolves correctly with the default, empty `TRUSTED_PROXY_IPS` — no configuration needed for this deployment, and the entire "keep two mechanisms from fighting over `request.client.host`" problem the original plan had to solve (Uvicorn's own `--proxy-headers` vs. `trusted_proxy.py`) doesn't exist when nothing is forwarding headers in the first place.

**`backend/trusted_proxy.py`/`TRUSTED_PROXY_IPS` stay in the codebase, unused by design, not removed.** Same pattern as `store_memory()`'s dormant backdating parameters (see `techDebt.md`'s Resolved section) — a real, tested capability with no current caller, kept because it's genuinely useful *if* a reverse proxy (e.g. Cloudflare, see the DDoS-protection note under "Generation API" below) ever does get added later, and ripping it out now would just mean rebuilding it then. `backend/test_trusted_proxy.py` still passes and still documents the algorithm; none of that testing was wasted, it's just not wired into this specific deployment's trust boundary because there's nothing between the caller and Uvicorn for it to account for.

**What this actually requires, deployment-time** (none of it built yet — no `docker-compose.yml` (prod — see `.gitignore`, never committed), no prod Dockerfile variant, no droplet):
1. **certbot in standalone mode**, run directly on the droplet host (not in a container competing for port 80) — temporarily binds port 80 to complete the HTTP-01 challenge against `<droplet-ip-with-dashes>.sslip.io`, obtains a normal 90-day cert under `/etc/letsencrypt/live/<hostname>/`.
2. **Uvicorn's production command binds directly to `443`** with `--ssl-keyfile`/`--ssl-certfile` pointed at those cert files, and drops `--reload` (see the existing "Dockerfile's `--reload` flag" section above — still applies regardless of this change). No `--proxy-headers`/`--forwarded-allow-ips` needed at all, since there's no proxy rewriting `request.client.host` to begin with. **Done, and hit a real gotcha along the way**: the first attempt bind-mounted only `/etc/letsencrypt/live/<domain>` into the container, which crashed Uvicorn on startup (`FileNotFoundError` loading the cert) — Let's Encrypt's `live/` files are relative symlinks into `../../archive/<domain>/...`, so mounting just `live/` breaks them inside the container (the symlink target doesn't exist there). Fixed by mounting the whole `/etc/letsencrypt` tree at the same absolute path instead (preserving the relative structure symlinks depend on), and moving the exact cert paths into `SSL_KEYFILE`/`SSL_CERTFILE` env vars (`docker-compose.yml`) rather than hardcoding them in the Dockerfile's `CMD`, via a shell-form `CMD` so those vars actually expand. Verified live: `https://134-209-121-221.sslip.io/docs` returns `200` with a fully trusted cert, no `-k` needed.
3. **A renewal hook restarts the backend after a successful certbot renewal** (`certbot renew --deploy-hook "..."`, or a systemd timer wrapping both steps) — Uvicorn doesn't hot-reload cert files, so a renewed cert only takes effect after a restart. A few seconds of dropped connections each renewal (roughly every 60 days, well inside the 90-day validity) is an accepted tradeoff for this project's traffic pattern, not something worth adding zero-downtime cert reloading to solve.
4. **Droplet firewall**: `22` (restricted), `80` (certbot's HTTP-01 challenge only — not serving app traffic), `443` (the actual API). No separate "backend port must never be published" rule needed the way the Traefik plan required — Uvicorn *is* the thing listening on the public port now, by design, not something to hide behind a proxy.
5. **The rate-limiting live test matrix** (20-request burst + `429` on the 21st, separate buckets per real client, admin bypass still working) should still be re-run once against the real deployed droplet, the same way any first deployment gets smoke-tested — not because the trust logic is in question (nothing forwards headers here), just to confirm the actual deployed Uvicorn/`slowapi` wiring behaves as expected outside the dev environment.

## ADMIN_BYPASS_TOKEN — required for prod

Lets `scripts/seed.py` (and anything else run by the project owner directly) skip rate limiting by sending it as the `X-Admin-Bypass-Token` header — see `security-preventions.md`'s Resolved section for the full mechanism and why it doesn't weaken the no-auth decision on the actual product routes. Same secret-handling pattern as `OPENAI_API_KEY`: env var, gitignored `.env` locally, never hardcoded in a committed compose file. Whichever compose file/env config ends up defining the prod deployment needs its own value for this — without it, the bypass check can never pass (safe default), but that also means seeding against prod would run into the normal rate limit like any other caller until this is actually set.

---

## ENVIRONMENT variable — required for prod

`scripts/clear.sh` (see `DEVELOPMENT.md`) destroys all Postgres and Qdrant data and refuses to run if `ENVIRONMENT` resolves to `production` — but it reads that value out of the compose file it's pointed at, not a host shell variable. There is no production deployment yet, but whichever compose file (or equivalent config) ends up defining the production environment **must** set `ENVIRONMENT: production` on the backend service. Without it, this guard is a no-op and the reset script could be run against production data.

Note: once Postgres and Qdrant move to Neon/Qdrant Cloud (see above), `clear.sh` as currently written won't apply to them at all — it only resets the local Docker volumes. Whatever replaces it for a managed-service world still needs the same production safety check, just implemented against Neon/Qdrant Cloud's own reset/branch-reset mechanisms instead of `docker volume rm`.
