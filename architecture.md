# Architecture

## How Retrieval Works

Memory retrieval is a two-stage process:

**Stage 1 — Semantic Search (Qdrant)**
The query is embedded into a vector using the same model used to store memories. Qdrant finds the top N most semantically similar vectors using cosine similarity. Fast, pure vector math.

**Stage 2 — Re-ranking (Postgres)** — *target design; not yet implemented. `search()` currently fetches the wide candidate pool and joins raw metadata but doesn't compute or apply this formula yet — see `dataModel.md`'s API section for what it actually returns today.*
The N candidate IDs from Qdrant are used to fetch metadata from Postgres — `stability`, `use_count`, `last_reinforced_at`. A weighted formula re-ranks the candidates:

```
semantic = normalize_qdrant_similarity(raw_similarity)
retrievability = (1 + age_days / stability)^(-0.5)      // age_days = days since last_reinforced_at
frequency = 1 - exp(-use_count / 5)

discard candidates where semantic < semantic_threshold   // hard floor, calibrated against the embedding model
final_score = 0.75×semantic + 0.15×retrievability + 0.10×frequency
```

This is a weighted **sum**, not a product — deliberately, so that a weak signal on one term (e.g. a brand-new memory with `use_count = 0`) can't zero out the whole score the way a product would. Semantic similarity dominates (75%) so an irrelevant memory can't win purely by being old or heavily used; the semantic threshold is an additional hard floor on top of that weighting, applied before re-ranking.

N is intentionally larger than the number of results returned. Fetch top 50 from Qdrant, filter by the semantic threshold, re-rank, return top 5. This gives the re-ranking enough candidates to work with.

---

## Memory Lifecycle (Decay, Reinforcement, Consolidation)

**Constants**
```
BASE_STABILITY = 1.0
REINFORCEMENT_MULTIPLIER = 1.2
MAX_STABILITY = 3650.0        (days, ~10 years — a safety rail, not meant to be reached)
MIN_IMPACT = 0.5
MAX_IMPACT = 2.0
```

**On creation**
```
impact = clamp(provided_impact ?? 1.0, MIN_IMPACT, MAX_IMPACT)
stability = BASE_STABILITY × impact
use_count = 0
retrieval_count = 0
last_reinforced_at = now()
```
`impact` only ever matters once, at creation — it seeds `stability`. There is no separate "importance"/"attention"/"emotional_salience" field; those all collapse into `impact`, which is the one explicit signal available at write time (unlike e.g. difficulty, which would need real outcome/feedback data this system doesn't have).

**Retrievability — computed lazily, never stored**
```
retrievability = (1 + age_days / stability)^(-0.5)
```
Important: `stability` is **not** a half-life. At `age_days = stability`, retrievability is ~70.7%, not 50%. The actual half-life is `3 × stability`. Computing this on the fly (rather than a stored, periodically-updated `strength` column) means it's always exact and needs no background decay job.

**On search — a memory is returned as a result**
```
retrieval_count += 1
```
Does **not** touch `stability`. Being shown is not reinforcement — see below for why.

**On meaningful use — explicit signal only (`POST /memories/{id}/use`, not automatic)**
```
stability = min(stability × REINFORCEMENT_MULTIPLIER, MAX_STABILITY)
use_count += 1
last_reinforced_at = now()
```
Reinforcing on every search *return* (rather than confirmed use) creates a self-reinforcing popularity loop: a memory ranks well → gets shown more → gets reinforced just from exposure → ranks even better. Splitting `retrieval_count` (shown) from `use_count` (actually used) avoids that — only genuine use should make a memory more durable.

The `MAX_STABILITY` cap exists because reinforcement is multiplicative and otherwise unbounded — without it, a heavily-used memory's `age_days / stability` ratio would trend to ~0 for any realistic elapsed time, making retrievability permanently ~100% even after years of neglect. That defeats the entire point of decay for exactly the memories that were reinforced the most.

**Deferred, not built**: a Difficulty parameter, a Confidence parameter, and a variable reinforcement gain (bigger stability boost for memories that had decayed further before being reinforced) are all documented as considered-and-deferred in `techDebt.md` — none has a real signal driving it yet, or isn't needed for a working v1.

---

## Code Architecture (MVC)

Layered architecture mapped to MVC:

- **Model** — split across two files:
  - `models.py` — data shapes. Defines what request/response data looks like using Pydantic. No logic, no DB, just structure.
  - `database.py` — data access. Holds the Qdrant client, embedding model, and the Postgres connection helper. Plain functions that take already-finished values and read/write them — no business logic, no clamping, no derived-value computation. Reads all connection info from environment variables — no hardcoded credentials.
- **View** — none yet. Would be React if a frontend is added.
- **Controller** — `routers/` — owns business logic (validation, clamping incoming values, computing derived values like `stability`), then calls `database.py` purely for reads/writes with the values it already computed. Returns responses. Each file in routers is a resource (memories, etc.)
- **App entry point** — `main.py` — app setup, lifespan, router registration. No business logic.
- **Constants** — `constants.py` — shared, tunable memory-lifecycle values (see below), imported by whichever business logic in `routers/` needs them. Not part of the MVC split itself, just a single source of truth so tuning values live in one place instead of scattered across route handlers.

Concerns are separated by responsibility. Structure expands as complexity justifies it — not prematurely.
