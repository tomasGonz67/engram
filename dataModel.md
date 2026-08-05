# Data Model

Every engram is split across two databases, connected by a UUID.

## Qdrant (vector storage)

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier — shared with Postgres |
| `vector` | float[1024] | Embedding of the memory text |
| `payload.text` | string | Original text of the memory |

## Postgres (metadata)

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier — shared with Qdrant |
| `text` | string | Original text of the memory |
| `impact` | float | How significant/emotionally weighted this memory is, 0.5–2.0 (clamped server-side regardless of client input), 1.0 = neutral. Set once at creation, used only to seed initial `stability` — deliberately not used again by Decay-Based Forgetting's deletion threshold, which is a flat `MIN_RETRIEVABILITY` independent of `impact`. See `architecture.md`'s "On creation" and Decay-Based Forgetting sections |
| `stability` | float | Resistance to decay. Seeded from `impact` at creation, multiplied by `REINFORCEMENT_MULTIPLIER` (capped at `MAX_STABILITY`) on each estimated meaningful use. There is no stored "strength"/"retrievability" column — it's computed lazily from `stability` + time elapsed, never written to the DB |
| `retrieval_count` | int | Number of times this memory has been returned by search (shown, not necessarily used). Bookkeeping only — does not affect ranking or stability |
| `use_count` | int | Number of answers in which this memory was *estimated to be reflected* — via the reinforcement guardrail's embedding-similarity check (see `architecture.md`'s "How Generation Works"), or a direct `reinforce_memory()` call (e.g. a person explicitly selecting it from search results). Distinct from `retrieval_count` to avoid a self-reinforcing popularity loop where mere exposure strengthens a memory. This is a similarity-based estimate with a measured false-positive rate (see `techDebt.md`), not proof of meaningful use, conscious retrieval, or causal influence on the answer. Only this counter drives stability growth and the `frequency` term in ranking |
| `created_at` | timestamptz | When the memory was first stored. Plays no role in ranking or decay (that's `last_reinforced_at`'s job) — its one use is feeding `/generate`'s prompt with an accurate, freshly-computed "time ago" marker via `formulas.humanize_age()`, see `architecture.md`'s "How Generation Works" |
| `last_reinforced_at` | timestamptz | Time of the most recent accepted similarity-based reinforcement — not updated on every retrieval, only when a check like the one above passes |

## How they connect

Qdrant handles semantic search — returns IDs of the most similar vectors. Postgres takes those IDs and returns the full engram record with all metadata. Together they form one complete memory.

## API (current)

**Store request** `POST /memories`

| Field | Description |
|-------|-------------|
| `text` | Memory text to embed and store (required) |
| `impact` | How significant this memory is, 0.5–2.0 (optional, defaults to 1.0). Clamped server-side regardless of what's sent. Seeds initial `stability` — see `architecture.md` |

**Store response** `POST /memories`

| Field | Description |
|-------|-------------|
| `id` | UUID of the stored memory |
| `text` | Original text |

**Search request** `POST /memories/search`

| Field | Description |
|-------|--------------|
| `text` | Query text to embed and search against (required) |
| `limit` | Requested number of ranked results (optional, defaults to 5, must be >= 1). There is currently no API-level upper bound, but retrieval fetches at most the fixed 50-candidate pool, so values above 50 still return at most 50 results. See `techDebt.md`. |

**Search response** `POST /memories/search` — full weighted ranking is implemented. Fetches a wide candidate pool from Qdrant, normalizes its scores, discards any candidate with no matching Postgres row (can't compute retrievability/frequency without `stability`/`use_count`), computes semantic similarity, retrievability, and frequency for what's left (`final_score`, what ranking actually sorts by, uses only semantic similarity and frequency — retrievability is computed and returned for display but deliberately excluded from ranking, see below), and returns the top `limit` sorted by `final_score` descending — no absolute-score filtering step; see `architecture.md`'s "How Retrieval Works" for why that was removed:

| Field | Description |
|-------|-------------|
| `id` | UUID of the matched memory |
| `text` | Original text of the matched memory |
| `semantic` | Normalized Qdrant cosine similarity (`architecture.md`'s `normalize_qdrant_similarity`) |
| `retrievability` | `(1 + age_days / stability)^-0.5`, computed from this memory's `stability` and time since `last_reinforced_at`. Still computed and returned for display, but no longer part of `final_score` — see below |
| `frequency` | `1 - exp(-use_count / 5)` |
| `final_score` | `0.95×semantic + 0.05×frequency` — what results are actually sorted by. `retrievability` deliberately isn't a ranking term (see `architecture.md`'s "How Retrieval Works" and `evaluation/experiments/reranking-weight-decision.md`) — it still governs Decay-Based Forgetting's deletion threshold, just not retrieval ranking |
| `stability` | Raw value underlying `retrievability` — not itself part of `final_score`'s weighted sum (neither is the computed `retrievability`, as of the ranking-weight decision above). Included for callers that want to show the underlying numbers, e.g. an analytics UI |
| `use_count` | Raw value underlying `frequency`, same reasoning — included for display, not used directly in ranking |
| `age_days` | Days since `last_reinforced_at`, computed server-side and fed into `retrievability` — included as-is since it's more directly readable than a raw timestamp |
| `impact` | The memory's `impact` value (0.5–2.0) from creation — plays no role in *ranking* (`final_score`'s weighted sum never includes it directly) and no role in Decay-Based Forgetting's deletion threshold either; its only effect is seeding initial `stability` at creation — see `architecture.md`'s "On creation" and Decay-Based Forgetting sections. Included here purely for display |
| `created_at` | When the memory was first stored — raw timestamp, included for display. Plays no role in ranking; `/generate` separately converts it to a human-readable "time ago" string for the model's prompt, see `architecture.md`'s "How Generation Works" |

This is a deliberately verbose response — kept as separate fields rather than collapsing to a single `score` so each signal can be inspected/verified independently. May collapse to just `{id, text, score}` later once the underlying formula is trusted enough not to need per-request visibility into its components.

**If nothing comes back, the response is a different shape**: `{"message": "No valid memories found"}` instead of an array. A deliberate exception to "the response type should always be the same" — chosen so there's no need to fake a memory-shaped placeholder object (a fake `id` or an out-of-bounds `final_score` like `100`, both considered and rejected) just to keep the shape uniform. Any caller of this endpoint needs to handle both an array and this object. This is now a rare case (an empty Qdrant collection, or candidates with no matching Postgres row) rather than a common outcome — retrieval no longer filters by an absolute score, so it basically always returns the closest `limit` candidates regardless of how weak the match is, see `architecture.md`'s "How Retrieval Works."

`retrieval_count` bookkeeping — incrementing it for whatever `search_memories()` actually returns (not every candidate considered internally) — is implemented via `increment_retrieval_counts()` in `database.py`, called from `search_memories()` so both `/memories/search` and `/generate` correctly count as retrieval events. Batched in one query via `ANY(%s::uuid[])` rather than one update per id.

**Reinforce (mark as meaningfully used)** `reinforce_memory(id)` in `memory_operations.py` — implemented, but **not an HTTP endpoint** of its own. Called directly by `/generate`'s reinforcement guardrail for any retrieved memory whose text is estimated, via local embedding similarity *and* literal word overlap with the best-matching answer sentence (`formulas.shares_significant_word()` — both conditions required), to be reflected in the model's answer — an estimate with a measured false-positive rate, not a certain determination, see `architecture.md`'s "How Generation Works" section and `techDebt.md`'s corresponding entry. That's the first real caller; still not wrapped in its own route since nothing outside `/generate` needs one yet. Increments `use_count`, updates `last_reinforced_at`, and multiplies+caps `stability` — all inside `update_memory_reinforcement()`'s single atomic SQL `UPDATE` in `database.py` (`stability = LEAST(stability * multiplier, max_stability)`), not computed in Python beforehand, so concurrent reinforcements of the same memory can't lose stability growth to each other. See `security-preventions.md`'s Resolved section. Raises `ValueError` if the id doesn't exist.

Would become `POST /memories/{id}/use` (a thin route wrapping this same function) if an external caller — e.g. a future UI — ever needs one.

**Generate** `POST /generate` — the "AG" half of RAG. Retrieves ranked candidate memories via `search_memories()` (same ranking logic `/memories/search` uses), sends them plus the query to the generation model (`gpt-5.4-nano`, see `techStack.md`) to write an answer — no function calling involved. A code-level guardrail then checks every retrieved memory against that answer via embedding similarity *and* literal word overlap; whichever ones clear both `REINFORCEMENT_GUARDRAIL_THRESHOLD` and `formulas.shares_significant_word()` get `stability`/`use_count` updated via `memory_operations.reinforce_memory`. “Candidate” is deliberate: retrieval has no hard relevance cutoff and can return weak matches. See `architecture.md` for the full flow and its measured limitations.

**Generate request** `POST /generate`

| Field | Description |
|-------|--------------|
| `text` | The user's query (required) |
| `limit` | Requested number of memories (default 5, must be >= 1). There is currently no API-level upper bound; the fixed candidate pool means at most 50 can be returned. See `techDebt.md`. |
| `recent_turns` | Caller-supplied short-term conversation context (`{role, content}` list). `role` is `Literal["user", "assistant"]`, not a plain `str` — it used to be unconstrained, which let a caller inject a `"system"`-role message straight into the prompt sent to the model; that's fixed now, see `security-preventions.md`'s Resolved section for the original bug. Masi Memory has no session concept of its own, so the caller tracks and passes this in; see `architecture.md`'s statelessness note. No size limit enforced server-side (still true — see `security-preventions.md`'s "To Add"); the frontend caller currently caps this at the last 20 messages before sending — see `techStack.md`'s "React + Vite (Frontend)" section |

**Generate response** `POST /generate`

| Field | Description |
|-------|--------------|
| `answer` | The model's final natural-language answer |
| `reinforced_memory_ids` | IDs of memories whose best answer-sentence similarity cleared `REINFORCEMENT_GUARDRAIL_THRESHOLD` **and** whose best-matching sentence shared at least one non-generic literal word via `shares_significant_word()`, resulting in a real reinforcement. This is an estimate that the answer reflected the memory, not proof of causal use. It is a subset of (or none of) `retrieved`; every retrieved memory is checked once. |
| `retrieved` | `search_memories()`'s raw return value — always an array, even if empty. Not the same as `/memories/search`'s HTTP response, which wraps an empty result in `{"message": "No valid memories found"}` instead; `/generate` has no equivalent wrapper. Included so the caller can see what was available even if the model didn't use all of it |

**Generate error response** — a `422` (malformed request, e.g. an invalid `recent_turns[].role`) follows FastAPI/Pydantic's standard validation-error shape. A `502` means the request itself was valid but the upstream OpenAI call failed (rate limit, timeout, outage) — see `security-preventions.md`'s Resolved section.
