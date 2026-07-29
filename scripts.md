# Scripts

Utility scripts for local development. See `DEVELOPMENT.md` for general dev environment setup.

## `scripts/clear.sh` — reset Postgres and Qdrant

No migrations are in use (see `techDebt.md`), so schema changes require a fresh database rather than an in-place migration. Since a memory's vector (Qdrant) and metadata (Postgres) are linked by id, resetting only one of the two leaves orphaned records in the other — a Qdrant vector with no matching Postgres row, or vice versa.

```bash
./scripts/clear.sh
```

This stops the dev containers, removes both the `postgres_data` and `qdrant_data` volumes (leaving `hf_cache` alone, so the embedding model doesn't need to re-download), and brings everything back up fresh so both stores start from zero together. Refuses to run if `ENVIRONMENT` resolves to `production` in the compose file being used — see `prod.md`.
