# Architecture

## How Retrieval Works

Memory retrieval is a two-stage process:

**Stage 1 — Semantic Search (Qdrant)**
The query is embedded into a vector using the same model used to store memories. Qdrant finds the top N most semantically similar vectors using cosine similarity. Fast, pure vector math.

**Stage 2 — Re-ranking (Postgres)** — *implemented. See `dataModel.md`'s API section for the exact current response shape (kept as separate `semantic`/`retrievability`/`frequency`/`final_score` fields rather than collapsed to one `score`, for now).*
The N candidate IDs from Qdrant are used to fetch metadata from Postgres — `stability`, `use_count`, `last_reinforced_at`. A weighted formula re-ranks the candidates:

```
semantic = normalize_qdrant_similarity(raw_similarity)
retrievability = (1 + age_days / stability)^(-0.5)      // age_days = days since last_reinforced_at
frequency = 1 - exp(-use_count / 5)

discard candidates where semantic < semantic_threshold   // hard floor, calibrated against the embedding model
final_score = 0.75×semantic + 0.15×retrievability + 0.10×frequency
```

`normalize_qdrant_similarity(raw_similarity)` is `(raw_similarity + 1) / 2` — cosine similarity is mathematically bounded to `[-1, 1]`, not `[0, 1]`, but `final_score`'s weighting assumes all three terms share the same `[0, 1]` scale (which `retrievability` and `frequency` already do, by construction). Without this rescale, a negative raw score would pull `final_score` down in a way the other two terms never do, breaking the intended proportions.

This is a weighted **sum**, not a product — deliberately, so that a weak signal on one term (e.g. a brand-new memory with `use_count = 0`) can't zero out the whole score the way a product would. Semantic similarity dominates (75%) so an irrelevant memory can't win purely by being old or heavily used; the semantic threshold is an additional hard floor on top of that weighting, applied before re-ranking. `SEMANTIC_THRESHOLD` (`constants.py`) is currently **0.75** — still a placeholder, not a fully validated value. History: a genuine nonsense query ("asdkjf qwoeiru zzxcvbn blorp glorp nonsense gibberish") tested against a 60-memory seeded dataset scored `0.716`–`0.768`, all of which wrongly passed the original `0.7` threshold, so it was raised to `0.8`. Then a real, clearly relevant query ("do I have a girlfriend?" against 15 seeded girlfriend-related memories) scored `0.767` and was wrongly filtered out entirely at `0.8`, so it was lowered to `0.75`. Caveat: `0.75` sits below the nonsense query's high end (`0.768`), so some of the false-positive risk the `0.7`→`0.8` move was meant to close is back — confirmed, not just theoretical: re-running the same nonsense query through `/generate` against the 75-memory seeded dataset leaked 3 irrelevant memories past `0.75` (scores `0.757`–`0.768`). See "How Generation Works" below for why that didn't produce a bad answer anyway. Known-relevant matches have scored `0.834`+. Still worth real calibration once there's larger, more systematic usage data — see `constants.py`.

N is intentionally larger than the number of results returned. Fetch top 50 from Qdrant, filter by the semantic threshold, re-rank, return top 5. This gives the re-ranking enough candidates to work with.

If nothing survives filtering, `search()` returns `{"message": "No valid memories found"}` instead of an empty array — a deliberate exception to keeping the response type uniform, chosen over faking a memory-shaped placeholder object (a fake `id`, an out-of-bounds `final_score` like `100`) just to preserve a single type. See `dataModel.md`'s API section for the exact shape.

---

## How Generation Works

`/generate` is the "AG" half of RAG, built on top of retrieval:

1. **Retrieve** — `search_memories()` (shared with `/memories/search`, see Controller section below) runs the query through the same embed → search → rank pipeline as Stage 1/2 above, returning the top `limit` ranked memories.
2. **Assemble the prompt** — system prompt + retrieved memories (as plain `(id) text` lines) + the caller-supplied `recent_turns` + the new query, all as one `messages` list sent to the generation model (`gpt-5.4-nano`, see `techStack.md`).
3. **Call the model with `reinforce_memory` exposed as a tool** — the model can call it, by id, for any memory it actually used to answer. The system prompt explicitly tells it not to call the tool for memories that were merely shown but not relied on.
4. **Execute any tool calls** — for each `reinforce_memory` call, invoke the real function from `memory_operations.py`, which updates `stability`/`use_count` in Postgres and returns the normalized id (used in the response's `reinforced_memory_ids` instead of the model's raw, possibly differently-cased argument). A hallucinated/nonexistent id or malformed arguments (`ValueError`) and a tool call missing the `id` field entirely (`KeyError`) are both caught and skipped rather than failing the whole request.
5. **Second completion call** — the first response often has no text content when tool calls are present, so a second call (with the tool results appended to the message list) gets the model's final natural-language answer.

The response returns the answer, which memory IDs actually got reinforced, and the full `retrieved` list — so a caller can see what was available even if the model didn't use all of it.

**A second defense layer against retrieval noise, observed in practice**: `SEMANTIC_THRESHOLD` is an imperfect filter (see above) — a nonsense query at `0.75` let 3 irrelevant memories through to `/generate`. But the system prompt's instruction to ignore irrelevant retrieved memories meant the model still recognized the input as gibberish, didn't fabricate an answer from that irrelevant context, and called `reinforce_memory` on none of them. Retrieval and generation aren't a single point of failure — a bad retrieval result doesn't automatically become a bad answer or a bad reinforcement, as long as the model actually follows the "ignore what's not relevant" instruction.

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

`compute_retrievability` raises `ValueError` if `stability <= 0` rather than letting the calculation proceed — Python's `**` on a negative base with a fractional exponent silently returns a complex number instead of erroring, which would otherwise corrupt `final_score` without any visible failure at the point something actually went wrong. `compute_initial_stability` also clamps its own input internally now, so it can't produce an invalid `stability` regardless of whether the caller already validated `impact`.

**On search — a memory is returned as a result**
```
retrieval_count += 1
```
Does **not** touch `stability`. Being shown is not reinforcement — see below for why.

**On meaningful use — explicit signal only, not automatic**
```
stability = min(stability × REINFORCEMENT_MULTIPLIER, MAX_STABILITY)
use_count += 1
last_reinforced_at = now()
```
Reinforcing on every search *return* (rather than confirmed use) creates a self-reinforcing popularity loop: a memory ranks well → gets shown more → gets reinforced just from exposure → ranks even better. Splitting `retrieval_count` (shown) from `use_count` (actually used) avoids that — only genuine use should make a memory more durable.

The `MAX_STABILITY` cap exists because reinforcement is multiplicative and otherwise unbounded — without it, a heavily-used memory's `age_days / stability` ratio would trend to ~0 for any realistic elapsed time, making retrievability permanently ~100% even after years of neglect. That defeats the entire point of decay for exactly the memories that were reinforced the most.

**Deferred, not built**: a Difficulty parameter, a Confidence parameter, and a variable reinforcement gain (bigger stability boost for memories that had decayed further before being reinforced) are all documented as considered-and-deferred in `techDebt.md` — none has a real signal driving it yet, or isn't needed for a working v1.

**Consolidation — implemented.** Prunes memories that have decayed past any realistic chance of being retrieved again, deleting them from Postgres and Qdrant together so the two stores can't drift out of sync — same reasoning as `scripts/clear.sh`.

```
threshold = MIN_RETRIEVABILITY / impact
prune if retrievability < threshold
```

The threshold scales with `impact` rather than treating every memory's decay uniformly — grounded in **flashbulb memory** research (Neisser & Harsch's Challenger disaster study is the key citation): sufficiently significant/emotional events get a real, measurable consolidation boost at encoding (amygdala-mediated enhancement of hippocampal LTP via noradrenergic arousal signals), so they persist longer without reinforcement — but that boost is *not* permanent immunity. Flashbulb memories still decay in accuracy over time, despite people's confidence in them staying artificially high; they just start stronger and fade slower. A hard exemption for high-impact memories would overshoot what the research actually supports, so the threshold is scaled, not waived.

`MIN_RETRIEVABILITY = 0.05` was validated against the decay math before being picked, not guessed: a never-reinforced memory at min impact (0.5) becomes prune-eligible after ~7 weeks; baseline impact (1.0) after ~13 months; max impact (2.0) after ~8.75 years; anything genuinely reinforced (`stability` near the `MAX_STABILITY` cap) is effectively never pruned. Verified directly: a test memory backdated to a year old with min impact was correctly deleted from both Postgres and Qdrant, while 75 freshly-seeded memories in the same run were correctly left untouched.

Each memory's retrievability/threshold computation is wrapped in its own `try/except (ValueError, ZeroDivisionError)` — a single malformed row (`stability <= 0` or `impact == 0`; nothing in the schema prevents either, only app-level clamping at write time) is logged and skipped rather than raising uncaught and killing the entire weekly loop for every other memory. See `techDebt.md`'s Resolved section for the failure mode this replaced.

**Runs on a weekly `asyncio` loop inside the app, not a manual script or an HTTP route.** Three deliberate choices here:

1. **Automated, not manual** — unlike `scripts/seed.py`/`scripts/clear.sh` (both hand-triggered), Consolidation runs on its own for as long as the app is up. The backend is already a long-running process, so a loop started in `main.py`'s `lifespan` (`asyncio.create_task`, cancelled on shutdown) costs nothing extra to add — no new dependency (no APScheduler), no OS-level cron needed.
2. **Weekly, not daily** — chosen for the actual timescale of decay, not performance. Each run is cheap regardless of interval (a small table scan, pure-Python math, a batched delete — no external API calls, unlike `/generate`), so interval doesn't meaningfully affect cost. But retrievability moves on a scale of weeks-to-months (see the numbers above), so checking daily would just re-scan a table that's barely changed since yesterday. Weekly matches the data; daily would be busywork.
3. **No HTTP route** — this is destructive (real deletions), and Engram has no auth by design (see the project decision to never add it). A public `POST /consolidate` would let anyone on the internet trigger mass deletion. Keeping it as an internal-only background loop means there's no route to protect in the first place.

**Why a real thread (`asyncio.to_thread`), not just `async`/`await`.** These solve different problems and get confused easily. Plain `async`/`await` is cooperative concurrency on a *single* thread — coroutines only yield control at `await` points, so a blocking call with no `await` in it (like a synchronous `psycopg2` query) hogs that one thread completely, stalling every other request (`/generate`, `/memories/search`, everything) until it finishes. Wrapping the blocking DB work in `asyncio.to_thread()` instead hands it to a real, separate OS thread from a shared pool — the event loop stays free to keep serving requests while that thread does its own work in parallel, and `await` just means "resume this coroutine once that thread's result is ready." This is the same mechanism FastAPI already uses under the hood for every plain-`def` route (`run_in_threadpool`) — Consolidation's loop just applies the identical pattern explicitly, rather than introducing a new one. One caveat worth naming: Python's GIL means threads don't buy true CPU-parallelism — two threads can't execute Python bytecode at the same instant — but the GIL releases during I/O waits (a network round-trip to Postgres or Qdrant), which is exactly what this workload is, so the threading genuinely helps here despite the GIL.

---

## Code Architecture (MVC)

Layered architecture mapped to MVC:

- **Model** — split across two files:
  - `models.py` — data shapes. Defines what request/response data looks like using Pydantic. No logic, no DB, just structure.
  - `database.py` — data access. Holds the Qdrant client, embedding model, and the Postgres connection helper. Plain functions that take already-finished values and read/write them — no business logic, no clamping, no derived-value computation. Reads all connection info from environment variables — no hardcoded credentials.
- **View** — none yet. Would be React if a frontend is added.
- **Controller** — split across two places, same role (orchestration: fetch, compute, write), split by whether it's wired to an HTTP route:
  - `routers/` — actual HTTP routes. Each file is a resource (memories, generate). Owns business logic, calls `formulas.py` for calculations and `database.py` purely for reads/writes, returns responses. Retrieval is a plain function, `search_memories()` in `routers/memories.py`, shared by `/memories/search` (returns ranked results directly, no LLM involved — used for debugging/calibrating ranking, e.g. the `SEMANTIC_THRESHOLD` tuning above) and `/generate` (feeds the results into the generation prompt). One implementation so ranking logic can't drift between callers — same reasoning as `formulas.py`.
  - `memory_operations.py` — orchestration with no dedicated HTTP route of its own (e.g. `reinforce_memory`). Now has a real caller: `/generate` invokes it directly when the LLM calls the `reinforce_memory` tool after actually using a retrieved memory in its answer. Same internal shape as a router function, just not wrapped in its own route — could still get one later (e.g. `POST /memories/{id}/use`) if a caller other than the LLM tool-loop needs it.
- **App entry point** — `main.py` — app setup, lifespan, router registration. No business logic.
- **Formulas** — `formulas.py` — every calculation from this doc (impact clamping, stability, retrievability, frequency, semantic normalization, final score) as pure, independently testable functions. Not part of the MVC split itself — routers call into it rather than computing things inline, so the same math can't drift between call sites (e.g. Consolidation reuses `compute_retrievability` too, via `memory_operations.py`).
- **Constants** — `constants.py` — shared, tunable values (see below). Imported by `formulas.py` (most of them) and directly by `routers/` for the few that are orchestration parameters rather than formula inputs (e.g. `CANDIDATE_POOL_SIZE`). Not part of the MVC split itself, just a single source of truth so tuning values live in one place instead of scattered across the codebase.

Concerns are separated by responsibility. Structure expands as complexity justifies it — not prematurely.
