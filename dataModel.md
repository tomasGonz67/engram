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
| `impact` | float | How significant/emotionally weighted this memory is, 0.5–2.0 (clamped server-side regardless of client input), 1.0 = neutral. Set once at creation, used only to seed initial `stability` |
| `stability` | float | Resistance to decay. Seeded from `impact` at creation, multiplied by `REINFORCEMENT_MULTIPLIER` (capped at `MAX_STABILITY`) on each meaningful use. There is no stored "strength"/"retrievability" column — it's computed lazily from `stability` + time elapsed, never written to the DB |
| `retrieval_count` | int | Number of times this memory has been returned by search (shown, not necessarily used). Bookkeeping only — does not affect ranking or stability |
| `use_count` | int | Number of times this memory was *meaningfully used* (included in an answer, explicitly selected, referenced later) — distinct from `retrieval_count` to avoid a self-reinforcing popularity loop where mere exposure strengthens a memory. Only this counter drives stability growth and the `frequency` term in ranking |
| `created_at` | timestamptz | When the memory was first stored |
| `last_reinforced_at` | timestamptz | When the memory was last *meaningfully used* — not updated on every retrieval, only on reinforcement |
| `memory_type` | string | Category of memory (episodic, semantic, procedural). Defaults to `general`. Classification logic not yet implemented — either user-provided or auto-classified via LLM in the future. |

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
| `limit` | Max number of ranked results to return (optional, defaults to 5, must be >= 1) |

**Search response** `POST /memories/search` — full weighted ranking is implemented. Fetches a wide candidate pool from Qdrant, normalizes and semantic-threshold-filters it, discards any candidate with no matching Postgres row (can't compute retrievability/frequency without `stability`/`use_count`), computes all three ranking signals for what's left, and returns the top `limit` sorted by `final_score` descending:

| Field | Description |
|-------|-------------|
| `id` | UUID of the matched memory |
| `text` | Original text of the matched memory |
| `semantic` | Normalized Qdrant cosine similarity (`architecture.md`'s `normalize_qdrant_similarity`) |
| `retrievability` | `(1 + age_days / stability)^-0.5`, computed from this memory's `stability` and time since `last_reinforced_at` |
| `frequency` | `1 - exp(-use_count / 5)` |
| `final_score` | `0.75×semantic + 0.15×retrievability + 0.10×frequency` — what results are actually sorted by |
| `stability` | Raw value underlying `retrievability` — not itself part of `final_score`'s weighted sum (the computed `retrievability` is). Included for callers that want to show the underlying numbers, e.g. an analytics UI |
| `use_count` | Raw value underlying `frequency`, same reasoning — included for display, not used directly in ranking |
| `age_days` | Days since `last_reinforced_at`, computed server-side and fed into `retrievability` — included as-is since it's more directly readable than a raw timestamp |
| `impact` | The memory's `impact` value (0.5–2.0) from creation — plays no role in ranking at all (only seeds initial `stability`, see `architecture.md`'s "On creation" section), included purely for display |

This is a deliberately verbose response — kept as separate fields rather than collapsing to a single `score` so each signal can be inspected/verified independently. May collapse to just `{id, text, score}` later once the formula (particularly `SEMANTIC_THRESHOLD`, still an unvalidated placeholder — see `constants.py`) is trusted enough not to need per-request visibility into its components.

**If nothing survives filtering, the response is a different shape**: `{"message": "No valid memories found"}` instead of an array. A deliberate exception to "the response type should always be the same" — chosen so there's no need to fake a memory-shaped placeholder object (a fake `id` or an out-of-bounds `final_score` like `100`, both considered and rejected) just to keep the shape uniform. Any caller of this endpoint needs to handle both an array and this object.

`retrieval_count` bookkeeping — incrementing it for whatever `search_memories()` actually returns (not every candidate considered internally) — is implemented via `increment_retrieval_counts()` in `database.py`, called from `search_memories()` so both `/memories/search` and `/generate` correctly count as retrieval events. Batched in one query via `ANY(%s::uuid[])` rather than one update per id.

**Reinforce (mark as meaningfully used)** `reinforce_memory(id)` in `memory_operations.py` — implemented, but **not an HTTP endpoint** of its own. Called directly by `/generate` when the model calls the `reinforce_memory` tool on a memory it actually used to answer — see `architecture.md`'s "How Generation Works" section. That's the first real caller; still not wrapped in its own route since nothing outside the LLM tool-loop needs one yet. Increments `use_count`, bumps `stability` via `compute_reinforced_stability`, updates `last_reinforced_at`. Raises `ValueError` if the id doesn't exist.

Would become `POST /memories/{id}/use` (a thin route wrapping this same function) if an external caller — e.g. a future UI — ever needs one.

**Generate** `POST /generate` — the "AG" half of RAG. Retrieves relevant memories via `search_memories()` (same ranking logic `/memories/search` uses), sends them plus the query to the generation model (`gpt-5.4-nano`, see `techStack.md`) with `reinforce_memory` exposed as a tool. If the model calls it for a memory it actually relied on, that memory's `stability`/`use_count` are updated for real via `memory_operations.reinforce_memory` — not just acknowledged and dropped. See `architecture.md`'s "How Generation Works" section for the full flow.

**Generate request** `POST /generate`

| Field | Description |
|-------|--------------|
| `text` | The user's query (required) |
| `limit` | How many memories `search_memories()` should retrieve (default 5, must be >= 1) |
| `recent_turns` | Caller-supplied short-term conversation context (`{role, content}` list, `role` restricted to `"user"`/`"assistant"` — a plain unconstrained `str` used to let a caller inject a `"system"`-role message straight into the prompt sent to the model, see `security-preventions.md`'s Resolved section) — Engram has no session concept of its own, so the caller tracks and passes this in; see `architecture.md`'s statelessness note. No size limit enforced server-side (still true — see `security-preventions.md`'s "To Add"); the frontend caller currently caps this at the last 20 messages before sending — see `techStack.md`'s "React + Vite (Frontend)" section |

**Generate response** `POST /generate`

| Field | Description |
|-------|--------------|
| `answer` | The model's final natural-language answer |
| `reinforced_memory_ids` | IDs of memories the model actually called `reinforce_memory` on and that resulted in a real reinforcement — a subset of (or none of) `retrieved`. If the model calls the tool more than once for the same id in one turn, only the first counts; repeats are deduped, not double-reinforced (see `architecture.md`'s "How Generation Works") |
| `retrieved` | `search_memories()`'s raw return value — always an array, even if empty. Not the same as `/memories/search`'s HTTP response, which wraps an empty result in `{"message": "No valid memories found"}` instead; `/generate` has no equivalent wrapper. Included so the caller can see what was available even if the model didn't use all of it |

**Generate error response** — a `422` (malformed request, e.g. an invalid `recent_turns[].role`) follows FastAPI/Pydantic's standard validation-error shape. A `502` means the request itself was valid but the upstream OpenAI call failed (rate limit, timeout, outage) — see `security-preventions.md`'s Resolved section.
