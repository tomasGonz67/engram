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
