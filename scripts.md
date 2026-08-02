# Scripts

Utility scripts for local development. See `DEVELOPMENT.md` for general dev environment setup.

## `scripts/clear.sh` — reset Postgres and Qdrant

No migrations are in use (see `techDebt.md`), so schema changes require a fresh database rather than an in-place migration. Since a memory's vector (Qdrant) and metadata (Postgres) are linked by id, resetting only one of the two leaves orphaned records in the other — a Qdrant vector with no matching Postgres row, or vice versa.

```bash
./scripts/clear.sh
```

This stops the dev containers, removes both the `postgres_data` and `qdrant_data` volumes (leaving `hf_cache` alone, so the embedding model doesn't need to re-download), and brings everything back up fresh so both stores start from zero together. Refuses to run if `ENVIRONMENT` resolves to `production` in the compose file being used — see `prod.md`.

## `scripts/seed.py` — populate with mock data

Seeds the running API with a realistic-scale set of mock memories (currently 75, across pets/work/food-hobbies/games-entertainment/misc categories) for testing search and ranking beyond a handful of manually-stored memories. Talks to the real HTTP API (`POST /memories`) — same code path a real client would use, not a shortcut around the system.

```bash
python3 scripts/seed.py
```

Requires the dev environment to already be running. Each memory gets a random `impact` within the valid range, so seeded data exercises impact/stability variation alongside semantic relevance and threshold filtering. Every seeded memory starts unreinforced (`use_count=0`) — reinforcement only happens through real use (`reinforce_memory()` or a `/generate` call that actually cites a memory), not from seeding itself.

## `scripts/backdate.sh` — spread seeded memories across realistic ages

Everything `seed.py` creates gets `created_at`/`last_reinforced_at` set to the moment it was inserted, so right after seeding, every memory looks equally "just created." Run this afterward to backdate all of them to a random point in the last 3 years instead — makes retrievability decay, Consolidation eligibility, and `/generate`'s dynamic `[time ago]` prompt marker (see `architecture.md`'s "How Generation Works") actually visible across a realistic spread, rather than everything sitting at `age_days ≈ 0`.

```bash
./scripts/backdate.sh
```

Runs a single SQL `UPDATE` directly against the dev Postgres container (`docker compose exec postgres psql`) — computes one random offset per row and applies it to both `created_at` and `last_reinforced_at` identically, matching how a never-reinforced memory's two timestamps are already equal by default. No Python or new dependencies involved; this deliberately doesn't use `store_memory()`/`insert_memory()`'s optional backdating parameters (see `techDebt.md`) since raw SQL against already-seeded rows is simpler than switching `seed.py` itself to call those functions in-process. Same dev-only `ENVIRONMENT` guard as `clear.sh`, plus it's structurally unable to reach prod regardless — prod Postgres will be Neon (see `prod.md`), not a local container, so there's no `postgres` service for this to `exec` into outside of dev.
