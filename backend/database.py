import os
import uuid
import psycopg2
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from openai import OpenAI

COLLECTION_NAME = "memories"
VECTOR_SIZE = 1024

model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"))

qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST"),
    port=int(os.getenv("QDRANT_PORT"))
)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "gpt-5.4-nano")

def get_pg_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

def normalize_id(id: str) -> str:
    """Validate and normalize a memory id to canonical UUID string form.
    Raises ValueError (not a raw DB exception) if id isn't a valid UUID —
    fail fast, before ever reaching the database. Also fixes a real bug:
    Postgres always returns UUIDs in canonical lowercase-dashed form, so a
    validly-formatted but differently-cased input id would otherwise fail
    to match dict keys built from query results. See security-preventions.md."""
    return str(uuid.UUID(id))

CREATE_MEMORIES_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY,
    text TEXT NOT NULL,
    impact FLOAT DEFAULT 1.0,
    stability FLOAT DEFAULT 1.0,
    retrieval_count INT DEFAULT 0,
    use_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_reinforced_at TIMESTAMPTZ DEFAULT NOW(),
    memory_type VARCHAR(50) DEFAULT 'general'
);
"""

def insert_memory(id: str, text: str, impact: float, stability: float):
    id = normalize_id(id)
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memories (id, text, impact, stability) VALUES (%s, %s, %s, %s)",
                    (id, text, impact, stability)
                )
    finally:
        conn.close()

def get_memories_metadata(ids: list[str]) -> dict:
    """Fetch stability, use_count, last_reinforced_at, and impact for a set of
    memory IDs. Returns a dict keyed by id string for easy lookup. Plain read
    — no computation, no business logic; the caller (router) turns stability/
    use_count/last_reinforced_at into retrievability/frequency. impact is
    returned as-is (raw, not part of the ranking formula) purely for
    surfacing in API responses — see search_memories()."""
    ids = [normalize_id(id) for id in ids]
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, stability, use_count, last_reinforced_at, impact FROM memories WHERE id = ANY(%s::uuid[])",
                    (ids,)
                )
                rows = cur.fetchall()
    finally:
        conn.close()
    return {
        str(row[0]): {"stability": row[1], "use_count": row[2], "last_reinforced_at": row[3], "impact": row[4]}
        for row in rows
    }

def get_all_memories():
    """Fetch id, stability, last_reinforced_at, impact for every stored
    memory. Used by Consolidation to compute retrievability and decide what
    to prune. Plain read, no business logic."""
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, stability, last_reinforced_at, impact FROM memories")
                rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {"id": str(row[0]), "stability": row[1], "last_reinforced_at": row[2], "impact": row[3]}
        for row in rows
    ]

def delete_memories(ids: list[str]):
    """Delete memories from both Postgres and Qdrant together, so they can
    never drift out of sync with each other — same reasoning as
    scripts/clear.sh. Plain write, no business logic."""
    ids = [normalize_id(id) for id in ids]
    if not ids:
        return
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memories WHERE id = ANY(%s::uuid[])", (ids,))
    finally:
        conn.close()
    qdrant.delete(collection_name=COLLECTION_NAME, points_selector=ids)

def increment_retrieval_counts(ids: list[str]):
    """Bump retrieval_count for whatever search actually returns to a
    caller — shown, not necessarily used. Plain write, no business logic.
    Batched via ANY(%s::uuid[]) rather than one query per id."""
    ids = [normalize_id(id) for id in ids]
    if not ids:
        return
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE memories SET retrieval_count = retrieval_count + 1 WHERE id = ANY(%s::uuid[])",
                    (ids,)
                )
    finally:
        conn.close()

def update_memory_reinforcement(id: str, stability: float):
    """Apply reinforcement: write the new (already-computed) stability,
    increment use_count by 1, refresh last_reinforced_at to now. Plain write
    — no business logic; the caller already computed the new stability via
    compute_reinforced_stability. use_count increments in SQL itself
    (use_count + 1) rather than being passed in, so two concurrent
    reinforcements can't clobber each other's increment."""
    id = normalize_id(id)
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE memories SET stability = %s, use_count = use_count + 1, last_reinforced_at = NOW() WHERE id = %s::uuid",
                    (stability, id)
                )
    finally:
        conn.close()
