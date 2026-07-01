# Tech Stack

## Qdrant
Vector database. Stores and searches memory vectors by semantic similarity. Acts as the primary memory storage — every engram is indexed here as a vector.

**Why Qdrant:**
- Purpose-built for vector search — fast and accurate
- Self-hostable with Docker locally, managed cloud for production
- Free tier covers this project

**Limitations:**
- Not designed for complex structured queries
- No relational support
- Bulk updates are slow compared to SQL

---

## PostgreSQL
Relational database. Stores all engram metadata — strength, stability, timestamps, access count, memory type. Acts as the other half of every engram — Qdrant holds the meaning, Postgres holds the details. Together they form one complete memory.

**Why Postgres:**
- Schema is fixed — every engram has the same fields, no flexibility needed
- Scheduled jobs need aggregate SQL queries — `UPDATE WHERE strength < 0.2` is natural SQL
- ACID compliance — transaction guarantees when decay updates thousands of records at once
- Better for relational data — if users are added later, foreign keys handle it cleanly

**Why both Qdrant and Postgres:**
They do different jobs. Qdrant finds similar memories by vector. Postgres holds the full engram record and handles scheduled jobs. They connect by ID — Qdrant returns IDs, Postgres returns the full record.

---

## Python + FastAPI
Backend framework. Handles API routes, background jobs, and orchestrates communication between Qdrant and Postgres.

**Why FastAPI:**
- Async support — important for background jobs running alongside API calls
- Auto-generates API docs at `/docs`
- Standard for Python AI/ML projects

### Libraries

#### sentence-transformers
Loads and runs embedding models locally. Acts as the encoding layer — converts raw text into a vector, the form in which it's stored. Similar to how the brain encodes an experience into a neural representation that is consolidated into a memory.

**Model (dev):** `Qwen/Qwen3-Embedding-0.6B` — 64.33 MTEB score, ~1.5GB RAM, **1024 dimensions**
**Model (prod):** TBD — evaluating open source (Qwen3-Embedding-4B/8B) vs API options based on scale and cost

**Why Qwen3-Embedding-0.6B for dev:**
- 8 points higher than all-MiniLM-L6-v2 (64 vs 56 MTEB) — meaningfully better retrieval quality
- Small enough to run comfortably in Docker on a dev machine

**Loaded once on startup and kept in memory.** The model is stateless during inference — weights do not change between requests. Since embedding is a core dependency in store and retrieve operations, the model is typically loaded once and kept resident in memory. This avoids model reload overhead, so each request only incurs inference compute cost plus standard system overhead such as tokenization, request scheduling, and I/O. This is standard practice for embedding services in production systems regardless of model size.

