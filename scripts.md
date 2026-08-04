# Scripts

Utility scripts for local development. See `DEVELOPMENT.md` for general dev environment setup.

## `scripts/clear.sh` — reset Postgres and Qdrant

No migrations are in use (see `techDebt.md`), so schema changes require a fresh database rather than an in-place migration. Since a memory's vector (Qdrant) and metadata (Postgres) are linked by id, resetting only one of the two leaves orphaned records in the other — a Qdrant vector with no matching Postgres row, or vice versa.

```bash
./scripts/clear.sh
```

This stops the dev containers, removes both the `postgres_data` and `qdrant_data` volumes (leaving `hf_cache` alone, so the embedding model doesn't need to re-download), and brings everything back up fresh so both stores start from zero together. Refuses to run if `ENVIRONMENT` resolves to `production` in the compose file being used — see `prod.md`.

## `scripts/seed.py` — populate with mock data

Seeds the running API with a realistic-scale set of mock memories (currently 162, split across three life-stage categories — `childhood`, `teen`, `young_adult`) for testing search and ranking beyond a handful of manually-stored memories. `MEMORIES` is a dict keyed by `memory_type` rather than a flat list — each category gets tagged accordingly via `MemoryInput.memory_type` when POSTed, so `backdate.sh` can later backdate each to a different, life-stage-appropriate age range. Talks to the real HTTP API (`POST /memories`) — same code path a real client would use, not a shortcut around the system.

```bash
python3 scripts/seed.py
```

Requires the dev environment to already be running. Each memory gets a random `impact` within the valid range, so seeded data exercises impact/stability variation alongside semantic relevance (retrieval has no threshold filtering anymore — see `architecture.md`'s "How Retrieval Works"). Every seeded memory starts unreinforced (`use_count=0`) — reinforcement only happens through real use (`reinforce_memory()` or a `/generate` call that actually cites a memory), not from seeding itself. Everything lands at `created_at = NOW()` regardless of category until `backdate.sh` runs afterward.

Since it POSTs 150+ requests in quick succession through the real `/memories` route, it now runs into that route's rate limit (see `security-preventions.md`) same as any other caller — unless `ADMIN_BYPASS_TOKEN` is set, in which case every request includes it as the `X-Admin-Bypass-Token` header and skips the limit entirely. Reads the token from an already-exported shell env var first, falling back to parsing the repo root's `.env` directly (this script runs on the host, not inside the backend container, so Docker Compose's own `.env` substitution doesn't reach it). Not required — without it, every request past the first 20 in a 5-minute window gets a `429`, which the script catches and logs as failed (no retry), so most of a full seed run would end up in the `failed` count rather than `succeeded` instead of actually populating the data.

## `scripts/backdate.sh` — spread seeded memories across life-stage-appropriate ages

Everything `seed.py` creates gets `created_at`/`last_reinforced_at` set to the moment it was inserted, so right after seeding, every memory looks equally "just created." Run this afterward to backdate each memory based on its `memory_type` instead — `childhood` to 20-30 years ago, `teen` to 10-20 years ago, `young_adult` (and any other/unrecognized value) to 0-10 years ago. Makes retrievability decay, Decay-Based Forgetting eligibility, and `/generate`'s dynamic `[time ago]` prompt marker (see `architecture.md`'s "How Generation Works") actually visible across a realistic, life-stage-correct spread, rather than everything sitting at `age_days ≈ 0` or all landing in one uniform range regardless of what era the memory is actually from.

```bash
./scripts/backdate.sh
```

Runs a single SQL `UPDATE` directly against the dev Postgres container (`docker compose exec postgres psql`) — a `CASE` on `memory_type` picks the correct day range per row, then computes one random offset within that range and applies it to both `created_at` and `last_reinforced_at` identically, matching how a never-reinforced memory's two timestamps are already equal by default. No Python or new dependencies involved; this deliberately doesn't use `store_memory()`/`insert_memory()`'s optional backdating parameters (see `techDebt.md`) since raw SQL against already-seeded rows is simpler than switching `seed.py` itself to call those functions in-process. Same dev-only `ENVIRONMENT` guard as `clear.sh`, plus it's structurally unable to reach prod regardless — prod Postgres will be Neon (see `prod.md`), not a local container, so there's no `postgres` service for this to `exec` into outside of dev.

**Note**: this only assigns *independent* random timestamps per row — it has no awareness of causal/narrative dependencies between related memories (e.g. an "acquired a pet" memory needing to land before that same pet's "passed away" memory). Two memories in the same category with a real dependency between them can land in the wrong order purely by chance — this has actually happened (see `techDebt.md`). No automated guard against this exists; verify manually after backdating if the dataset has narrative sequences that matter.

## `scripts/forgetting_threshold_analysis.py` — reproduce the MIN_RETRIEVABILITY decision

Read-only, dev-only script backing the `MIN_RETRIEVABILITY = 0.01` decision in `constants.py`. Prints two things: expected deletion ages across representative stability/impact/reinforcement combinations at several candidate thresholds, and — against whatever's actually in the live dev database — what fraction of real memories would be eligible for deletion at each candidate threshold, comparing the flat model to the old impact-divided one. Never calls `delete_memories()`.

```bash
docker cp scripts/forgetting_threshold_analysis.py <backend-container>:/app/forgetting_threshold_analysis.py
docker compose -f docker-compose-dev.yml exec backend python3 /app/forgetting_threshold_analysis.py
```

Uses `docker cp` rather than running in-place because, same as the `evaluation/` harness (see `evaluation/README.md`), the backend container only mounts `./backend`, not the repo root where this script lives.
