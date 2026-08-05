# Scripts

Utility scripts for local development. See `DEVELOPMENT.md` for general dev environment setup.

## `scripts/clear.sh` — reset Postgres and Qdrant

No migrations are in use (see `techDebt.md`), so schema changes require a fresh database rather than an in-place migration. Since a memory's vector (Qdrant) and metadata (Postgres) are linked by id, resetting only one of the two leaves orphaned records in the other — a Qdrant vector with no matching Postgres row, or vice versa.

```bash
./scripts/clear.sh
```

This stops the dev containers, removes both the `postgres_data` and `qdrant_data` volumes (leaving `hf_cache` alone, so the embedding model doesn't need to re-download), and brings everything back up fresh so both stores start from zero together. Refuses to run if `ENVIRONMENT` resolves to `production` in the compose file being used — see `prod.md`.

## `scripts/seed_data.json` — the canonical seed dataset

The current file contains 980 synthetic autobiographical memories. This is the canonical development corpus; the retrieval fixture under `evaluation/` still targets the former 181-memory corpus and is explicitly marked stale there.

A flat JSON array of `{text, impact, created_at}` objects — the single source of truth both `seed.py` and `backdate.sh` read from, so they can never drift apart (one script's `text`/`impact` and the other script's `text`/`created_at` always describe the same memory). `impact` and `created_at` are hand-assigned per memory, not randomly generated: `impact` reflects that specific memory's actual content (a significant event scores higher than a mundane one), and `created_at` reflects a real, internally consistent timeline — causal/narrative dependencies between related memories (e.g. a pet's acquisition predating its death) are respected by construction, not left to chance. This replaces an earlier design where `impact` was randomly rolled per memory and `created_at` was a random offset within a coarse category range (`childhood`/`teen`/`young_adult`) — see `techDebt.md`'s Resolved section (the `backdate.sh`/`memory_type` entries) for the full history and why that changed. No `memory_type` field exists anymore; nothing in the system reads it after this refactor (it never affected ranking, decay, or the prompt to begin with).

## `scripts/seed.py` — populate with mock data

Reads `seed_data.json` and POSTs each entry's `text`/`impact` to the real `POST /memories` HTTP endpoint — same code path a real client would use, not a shortcut around the system. `created_at` is deliberately *not* sent here (see below for why) — `backdate.sh` applies it afterward as a separate step.

```bash
python3 scripts/seed.py
```

Requires the dev environment to already be running. Every seeded memory starts unreinforced (`use_count=0`) and lands at `created_at = NOW()` — reinforcement only happens through real use (`reinforce_memory()` or a `/generate` call that actually cites a memory), not from seeding itself; and `created_at` only gets its real, intended value once `backdate.sh` runs afterward.

Since it POSTs through the real `/memories` route, a large seed run runs into that route's rate limit (see `security-preventions.md`) same as any other caller — unless `ADMIN_BYPASS_TOKEN` is set, in which case every request includes it as the `X-Admin-Bypass-Token` header and skips the limit entirely. Reads the token from an already-exported shell env var first, falling back to parsing the repo root's `.env` directly (this script runs on the host, not inside the backend container, so Docker Compose's own `.env` substitution doesn't reach it). Not required — without it, every request past the first 20 in a 5-minute window gets a `429`, which the script catches and logs as failed (no retry).

## `scripts/backdate.sh` — apply each memory's hand-assigned `created_at`

`MemoryInput` (the public `POST /memories` request body) deliberately never exposes `created_at`/`last_reinforced_at` — by design, a real caller should never be able to backdate their own memories (see `dataModel.md`, `security-preventions.md`). So `seed.py` can't set these fields even for its own seeded data. This script bypasses that the same way its predecessor did: direct SQL against Postgres, not through the app — but instead of computing a random offset per row, it reads the exact `created_at` already decided for each memory in `seed_data.json` and applies it, matched by `text` (not `id`, since ids are server-generated and change on every reseed — same reasoning `evaluation/`'s fixture already relies on for its own text-based labels).

```bash
./scripts/backdate.sh
```

Builds one `UPDATE ... FROM (VALUES ...)` statement covering every memory in a single round trip (not one `UPDATE` per row), with memory text properly SQL-escaped (single quotes doubled) since real memory text legitimately contains apostrophes. Sets `created_at` and `last_reinforced_at` to the same value per row, matching how a never-reinforced memory's two timestamps are already equal by default. Same dev-only `ENVIRONMENT` guard as `clear.sh`, plus it's structurally unable to reach prod regardless — prod Postgres will be Neon (see `prod.md`), not a local container, so there's no `postgres` service for this to `exec` into outside of dev.

Supersedes an earlier version that backdated by `memory_type` category (`childhood`/`teen`/`young_adult`) to a random offset within a coarse range — that version had no awareness of causal/narrative dependencies between related memories, and this actually caused real ordering bugs in the seeded dataset (see `techDebt.md`'s Resolved section). Hand-assigning each memory's exact date in `seed_data.json` — rather than generating any date at backdate-time — closes that gap by construction: the same person who's writing/reviewing the dataset already knows which memories causally depend on which, so the dependency gets encoded once, correctly, instead of risked on every reseed.

## `scripts/forgetting_threshold_analysis.py` — reproduce the MIN_RETRIEVABILITY decision

Read-only, dev-only script backing the `MIN_RETRIEVABILITY = 0.01` decision in `constants.py`. Prints two things: expected deletion ages across representative stability/impact/reinforcement combinations at several candidate thresholds, and — against whatever's actually in the live dev database — what fraction of real memories would be eligible for deletion at each candidate threshold, comparing the flat model to the old impact-divided one. Never calls `delete_memories()`.

```bash
docker cp scripts/forgetting_threshold_analysis.py <backend-container>:/app/forgetting_threshold_analysis.py
docker compose -f docker-compose-dev.yml exec backend python3 /app/forgetting_threshold_analysis.py
```

Uses `docker cp` rather than running in-place because, same as the `evaluation/` harness (see `evaluation/README.md`), the backend container only mounts `./backend`, not the repo root where this script lives.
