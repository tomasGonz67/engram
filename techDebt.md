# Tech Debt

## Open

- **No automated testing** — no unit or integration tests. Acceptable for a personal project at this stage.

- **Public repo exposes schema docs** — `dataModel.md` and `techStack.md` document internal DB structure. Acceptable for a dev/portfolio project with no real users. Revisit if this becomes a real product.

- **No `start.sh` script** — collection creation and any future startup logic runs inline on app start. If startup complexity grows (migrations, health checks, seed data), consolidate into a `start.sh` script.

- **Non-atomic dual-store writes/deletes** — `store()` (Qdrant then Postgres) and `delete_memories()` (Postgres then Qdrant) are each two sequential operations, not one atomic one. If the first succeeds and the second fails mid-request (network blip, one store briefly down), the result is a permanently orphaned record in whichever store didn't get the matching write. `search_memories()` already tolerates a Qdrant-only orphan by skipping it (no Postgres row to rank against), but nothing ever cleans it up — Consolidation's `get_all_memories()` only reads Postgres, so a Qdrant-only orphan is invisible to it forever, and a Postgres-deleted-but-Qdrant-still-has-it orphan is equally invisible. Real fix needs either a reconciliation job cross-checking both stores, or a retry/compensating-action pattern around the two writes. Low probability (requires one store to fail mid-request specifically), not worth the added complexity yet.

---

## Considered & Rejected

- **Difficulty parameter** (per-memory, affects how much reinforcement boosts stability) — rejected for now. FSRS-style Difficulty is only useful because it's learned from real outcome data (pass/fail review ratings); this system has no equivalent feedback signal, so it'd just be a stored number nothing meaningfully drives. Revisit if a real "was this memory actually useful" feedback loop gets built.
- **Confidence parameter** (how trustworthy the memory's content is, distinct from impact/importance) — genuinely useful idea, not redundant with `impact`, but deferred — not needed for v1's ranking to work. Would need its own term in the ranking formula, not routed through `stability` like impact is.
- **Separate importance / attention_quality / understanding / emotional_salience fields** — rejected. All collapse into the single `impact` field ("how significant/emotionally weighted is this to me"); no clear signal distinguishes them from each other or from impact, and several (attention_quality, understanding) have no natural input signal at all for a system storing text via an API call.
- **Variable reinforcement_gain** (`1.1 + 0.2 × (1 - retrievability)` — bigger stability boost for memories that had decayed further before being reinforced) — good future improvement, models the real spacing effect more accurately than a fixed multiplier. Deferred: the fixed `REINFORCEMENT_MULTIPLIER = 1.2` is simpler and good enough to start collecting real usage data before tuning something more elaborate.
- **Migrations** — not using, personal project.
- **ORM (SQLAlchemy)** — considered for Postgres interaction. Rejected — one table, simple queries (insert, update stability, delete where computed retrievability < threshold). Raw SQL with psycopg2 is cleaner and easier to reason about for this project size. Revisit if schema complexity grows significantly.

---

## Resolved

- **Double startup on uvicorn reload** — collection creation was running at module level, firing twice due to uvicorn's reloader process. Fixed by moving startup logic into FastAPI's lifespan context manager, which only runs in the server process.
- **No services layer** — resolved differently than originally proposed. Rather than extracting business logic into a separate services module, the decision was: routers own business logic (validation, clamping, computing derived values) directly, and `database.py` stays a plain data-access layer with no logic of its own. See the "Code Architecture (MVC)" section in `architecture.md`.
- **POST endpoint uses query param** — already resolved before this item was written; `store()` has always taken a Pydantic request body (`MemoryInput`), never a query param. Stale tech-debt entry, removed.
- **Consolidation could die permanently on one bad row** — `consolidate()`'s per-memory loop had no error handling; a row with `stability <= 0` or `impact == 0` (nothing in the schema prevents this — only app-level clamping at write time) would raise an uncaught exception that killed the entire background `asyncio` loop in `main.py`, silently disabling Consolidation for the rest of the process's life with no log or alert. Fixed: the per-row computation is now wrapped in `try/except (ValueError, ZeroDivisionError)`, logging and skipping the bad row instead of crashing the loop.
- **`/generate` could 500 on a malformed tool call** — a `reinforce_memory` tool call missing the `id` argument raised an uncaught `KeyError` (not a `ValueError`, so the existing except clause didn't catch it), crashing the whole request. Fixed: broadened the catch to `(ValueError, KeyError)`.
- **No validation on `limit`** — `SearchInput.limit`/`GenerateInput.limit` had no lower bound; a negative value (e.g. `-1`) made `ranked[:limit]` silently return all-but-the-last result instead of erroring. Fixed: `Field(default=5, ge=1)` on both.
- **`reinforced_memory_ids` echoed a non-canonical id** — `/generate`'s response appended the model's raw tool-call argument string rather than the normalized UUID actually written to Postgres; a differently-cased but validly-formatted id could look mismatched to a caller comparing against Postgres's canonical form. Fixed: `reinforce_memory()` now returns the normalized id, and `/generate` uses that instead of the raw argument.
