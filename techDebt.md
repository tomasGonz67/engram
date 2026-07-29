# Tech Debt

## Open

- **No automated testing** — no unit or integration tests. Acceptable for a personal project at this stage.

- **Public repo exposes schema docs** — `dataModel.md` and `techStack.md` document internal DB structure. Acceptable for a dev/portfolio project with no real users. Revisit if this becomes a real product.

- **No `start.sh` script** — collection creation and any future startup logic runs inline on app start. If startup complexity grows (migrations, health checks, seed data), consolidate into a `start.sh` script.

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
