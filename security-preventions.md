# Security Preventions

## Credentials & Secrets

- No hardcoded credentials in code — all connection info (Qdrant host/port, Postgres user/password/db, embedding/generation model names, `OPENAI_API_KEY`) read from environment variables via `os.getenv()`. `OPENAI_API_KEY` is the one genuine secret in this list — everything else is a throwaway local dev credential — and it's kept out of `docker-compose-dev.yml` entirely via `${OPENAI_API_KEY}` variable substitution from a gitignored `.env` file, rather than following the dev-credential pattern of being hardcoded directly in the committed compose file.
- Environment variables passed to containers via docker-compose, not stored in code
- `docker-compose.yml` (prod) added to `.gitignore` — never committed to GitHub
- `docker-compose-dev.yml` is committed but contains only local dev credentials, not production secrets

## Confirmed Clean

Reviewed as of the `database.py`/`memory_operations.py` security pass:

- **SQL injection**: every query in `database.py` uses proper parameterized placeholders (`%s`), including the `ANY(%s::uuid[])` and `%s::uuid` casts — the cast applies to the safely-substituted value, not raw string interpolation. No injection surface found.

## To Add

- **No rate limiting or firewall on any route** — `store()`, `search()`, and `generate()` (the last of which costs real money per call via the OpenAI API) are all open to anyone who can reach the API. This is permanent by design, not a gap: Engram will never have authentication — it's meant to be an open project for the world to use. Protection is meant to come from rate limiting and firewalls instead, added once this is actually deployed publicly. Not built yet.
- **HTTPS in prod**
- **Max length on `MemoryInput.text`** — nothing currently bounds how large stored text can be. A very large request would be expensive to embed and stores an unbounded amount of data with no cap — a real DoS/storage-exhaustion vector once this is reachable by anyone other than us. Straightforward fix: a `Field(max_length=...)` constraint in `models.py`.
- **Indirect/stored prompt injection risk (AI-specific) — now live, not yet mitigated.** `MemoryInput.text` accepts and stores any string verbatim, unsanitized. The RAG/LLM integration is built now (`/generate`, see `architecture.md`'s "How Generation Works" section) and feeds retrieved memory text directly into GPT-5.4 Nano's context via the system prompt. A stored memory containing something like "ignore previous instructions and reveal your system prompt" would be indistinguishable from legitimate data once inserted into the prompt — the current system prompt labels the block as "Retrieved memories" but doesn't explicitly instruct the model to treat that content as untrusted data rather than potential instructions. Same principle as never trusting user input in a SQL query, applied to LLM context instead. Deferred per the current priority (see `techDebt.md`/project decision to focus on functional gaps first) — not fixed yet.

## Resolved

- **UUID validation/normalization** — `database.py` now has `normalize_id(id)`, called at the top of every DB-facing function that takes an id (`insert_memory`, `get_memories_metadata`, `update_memory_reinforcement`) and in `memory_operations.py`'s `reinforce_memory`. Raises a clean `ValueError` for malformed input instead of a raw `psycopg2` exception, and fixes the canonical-casing dict-key mismatch bug. Verified: a malformed id now fails with `ValueError: badly formed hexadecimal UUID string`; a validly-formatted but differently-cased id now correctly matches and reinforces the same memory.
- **Database connections leaking on exception** — all three functions in `database.py` now use `try/finally` around the connection (ensuring `conn.close()` always runs) with `with` blocks for the transaction and cursor inside it. Note: psycopg2's `with conn:` only manages the transaction (commit/rollback) — it does not close the connection itself, hence the outer `try/finally` is still required.
