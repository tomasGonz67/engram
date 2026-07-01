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
| `strength` | float | Current memory strength (0.0 - 1.0). Decays over time, increases on access |
| `stability` | float | Resistance to decay — increases as memory is repeatedly reinforced |
| `access_count` | int | Number of times this memory has been retrieved |
| `created_at` | timestamp | When the memory was first stored |
| `last_accessed_at` | timestamp | When the memory was last retrieved |
| `memory_type` | string | Category of memory (e.g. episodic, semantic) |

## How they connect

Qdrant handles semantic search — returns IDs of the most similar vectors. Postgres takes those IDs and returns the full engram record with all metadata. Together they form one complete memory.

## API (current)

| Field | Description |
|-------|-------------|
| `id` | UUID returned on store |
| `text` | Original text returned on store |

Response models will expand as Postgres is added.
