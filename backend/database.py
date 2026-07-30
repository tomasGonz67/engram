import os
import psycopg2
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient

COLLECTION_NAME = "memories"
VECTOR_SIZE = 1024

model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"))

qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST"),
    port=int(os.getenv("QDRANT_PORT"))
)

def get_pg_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

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
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO memories (id, text, impact, stability) VALUES (%s, %s, %s, %s)",
        (id, text, impact, stability)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_memories_metadata(ids: list[str]) -> dict:
    """Fetch stability, use_count, and last_reinforced_at for a set of memory IDs.
    Returns a dict keyed by id string for easy lookup. Plain read — no computation,
    no business logic; the caller (router) turns these into retrievability/frequency."""
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, stability, use_count, last_reinforced_at FROM memories WHERE id = ANY(%s::uuid[])",
        (ids,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {
        str(row[0]): {"stability": row[1], "use_count": row[2], "last_reinforced_at": row[3]}
        for row in rows
    }
