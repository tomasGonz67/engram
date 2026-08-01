# Production Considerations

## PyTorch

Currently using CPU-only PyTorch to keep the Docker image small (~2.4GB vs ~14.5GB with full PyTorch). If deploying on a GPU instance (e.g. EC2 GPU), switch back to full PyTorch to take advantage of hardware acceleration — remove the `--extra-index-url` and `torch` lines from `requirements.txt` and let sentence-transformers pull the default full version.

**Why CPU is acceptable now:**
- Single-user, low throughput — one request at a time
- ~50-200ms per embedding on CPU is imperceptible at this scale

**When to switch to GPU:**
- High throughput — bulk imports, real-time feeds, multiple concurrent users
- CPU becomes the bottleneck fast when embedding thousands of texts per second
- GPU inference is ~10-40x faster (~2-5ms per embedding)

---

## Embedding Model

Vector dimensions are fixed at collection creation time in Qdrant. Switching models in prod requires creating a new collection and re-embedding all stored memories.

| Model | Dimensions |
|-------|-----------|
| Qwen3-Embedding-0.6B (dev) | 1024 |
| Qwen3-Embedding-4B | 2560 |
| Qwen3-Embedding-8B | 4096 |
| OpenAI text-embedding-3-small | 1536 |
| OpenAI text-embedding-3-large | 3072 |

---

## Generation API (OpenAI) — required for prod

Unlike the embedding model (self-hosted, see above), the generation model (`gpt-5.4-nano`, see `techStack.md`) is an external paid API — every `/generate` call costs real money, with no rate limiting yet (see `security-preventions.md`). This is the only route in Engram with a per-request dollar cost, and by design (no auth, ever) it's reachable by anyone who finds the URL.

**Before any public deployment:**
- Rate limiting on `/generate` specifically — highest priority, since it's the only route where an open API translates directly into an open bill
- A spend cap/budget alert on the OpenAI account itself, not just an app-level rate limit — the same reasoning as spend alerts on any cloud account, since the app-level limit is the only thing standing between a traffic spike and an unbounded bill

---

## ENVIRONMENT variable — required for prod

`scripts/clear.sh` (see `DEVELOPMENT.md`) destroys all Postgres and Qdrant data and refuses to run if `ENVIRONMENT` resolves to `production` — but it reads that value out of the compose file it's pointed at, not a host shell variable. There is no production deployment yet, but whichever compose file (or equivalent config) ends up defining the production environment **must** set `ENVIRONMENT: production` on the backend service. Without it, this guard is a no-op and the reset script could be run against production data.
