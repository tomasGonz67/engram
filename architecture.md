# Architecture

## How Retrieval Works

Memory retrieval is a two-stage process:

**Stage 1 — Semantic Search (Qdrant)**
The query is embedded into a vector using the same model used to store memories. Qdrant finds the top N most semantically similar vectors using cosine similarity. Fast, pure vector math.

**Stage 2 — Re-ranking (Postgres)**
The N candidate IDs from Qdrant are used to fetch metadata from Postgres — strength, stability, access count, timestamps. A weighted formula re-ranks the candidates:

```
final_score = semantic_similarity × strength × recency_weight × frequency_weight
```

The final top results are returned after re-ranking. This means a memory that is semantically similar but hasn't been accessed in months gets pushed down. A memory that is frequently accessed and has high strength gets pushed up — even if it's slightly less semantically similar.

N is intentionally larger than the number of results returned. Fetch top 20 from Qdrant, re-rank, return top 5. This gives the re-ranking enough candidates to work with.

---

## Code Architecture (MVC)

Layered architecture mapped to MVC:

- **Model** — split across two files:
  - `models.py` — data shapes. Defines what request/response data looks like using Pydantic. No logic, no DB, just structure.
  - `database.py` — data access. Holds the Qdrant client, embedding model, and constants. Reads all connection info from environment variables — no hardcoded credentials.
- **View** — none yet. Would be React if a frontend is added.
- **Controller** — `routers/` — handles requests, uses database.py to do the work, returns responses. Each file in routers is a resource (memories, etc.)
- **App entry point** — `main.py` — app setup, lifespan, router registration. No business logic.

Concerns are separated by responsibility. Structure expands as complexity justifies it — not prematurely.
