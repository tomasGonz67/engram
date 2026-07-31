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

**Search response** `POST /memories/search` — full weighted ranking is implemented. Fetches a wide candidate pool from Qdrant, normalizes and semantic-threshold-filters it, discards any candidate with no matching Postgres row (can't compute retrievability/frequency without `stability`/`use_count`), computes all three ranking signals for what's left, and returns the top `limit` sorted by `final_score` descending:

| Field | Description |
|-------|-------------|
| `id` | UUID of the matched memory |
| `text` | Original text of the matched memory |
| `semantic` | Normalized Qdrant cosine similarity (`architecture.md`'s `normalize_qdrant_similarity`) |
| `retrievability` | `(1 + age_days / stability)^-0.5`, computed from this memory's `stability` and time since `last_reinforced_at` |
| `frequency` | `1 - exp(-use_count / 5)` |
| `final_score` | `0.75×semantic + 0.15×retrievability + 0.10×frequency` — what results are actually sorted by |

This is a deliberately verbose response — kept as separate fields rather than collapsing to a single `score` so each signal can be inspected/verified independently. May collapse to just `{id, text, score}` later once the formula (particularly `SEMANTIC_THRESHOLD`, still an unvalidated placeholder — see `constants.py`) is trusted enough not to need per-request visibility into its components.

**If nothing survives filtering, the response is a different shape**: `{"message": "No valid memories found"}` instead of an array. A deliberate exception to "the response type should always be the same" — chosen so there's no need to fake a memory-shaped placeholder object (a fake `id` or an out-of-bounds `final_score` like `100`, both considered and rejected) just to keep the shape uniform. Any caller of this endpoint needs to handle both an array and this object.

`retrieval_count` bookkeeping (incrementing it for whatever search returns) is **not yet implemented** — despite being conceptually part of search, not reinforcement.

**Reinforce (mark as meaningfully used)** `POST /memories/{id}/use` — not yet implemented

Called explicitly by whatever consumes search results, once a memory is confirmed actually used (not just returned). Increments `use_count`, bumps `stability`, updates `last_reinforced_at`. See `architecture.md` for the full formula.

Response models will expand as this is implemented.
