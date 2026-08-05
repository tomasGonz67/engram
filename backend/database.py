import os
import uuid
from datetime import datetime, timezone
import psycopg2
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from openai import OpenAI

COLLECTION_NAME = "memories"
VECTOR_SIZE = 1024

model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"))

# Dev: self-hosted Qdrant on the private Docker network, no auth, plain HTTP
# (QDRANT_HOST/QDRANT_PORT). Prod: Qdrant Cloud, which requires HTTPS + an
# API key — QdrantClient(host=, port=) has no way to express either, so
# Qdrant Cloud is selected via QDRANT_URL instead (its full https:// URL,
# as given in the Qdrant Cloud dashboard), gated on whether that var is set
# rather than on ENVIRONMENT directly, so dev keeps working unchanged.
if os.getenv("QDRANT_URL"):
    qdrant = QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY"),
    )
else:
    qdrant = QdrantClient(
        host=os.getenv("QDRANT_HOST"),
        port=int(os.getenv("QDRANT_PORT"))
    )

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "gpt-5.4-nano")

def get_pg_conn():
    # Neon (prod) requires sslmode=require; dev's self-hosted Postgres
    # container has no SSL configured at all, so "prefer" (negotiate SSL if
    # offered, otherwise plain) is the safe default that works unchanged for
    # both without needing an env var set in dev specifically.
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        sslmode=os.getenv("POSTGRES_SSLMODE", "prefer")
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
    last_reinforced_at TIMESTAMPTZ DEFAULT NOW()
);
"""

def insert_memory(id: str, text: str, impact: float, stability: float, created_at: datetime = None, last_reinforced_at: datetime = None):
    """created_at/last_reinforced_at are dev-only backdating hooks — None
    (the default) means "now" for both, identical to the old DEFAULT NOW()
    behavior. Only ever passed a real value by scripts/backdate.sh (direct
    SQL, not through this function) or its predecessor use case; never
    exposed through MemoryInput or the public /memories route. See
    dataModel.md and security-preventions.md."""
    id = normalize_id(id)
    now = datetime.now(timezone.utc)
    created_at = created_at or now
    last_reinforced_at = last_reinforced_at or now
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memories (id, text, impact, stability, created_at, last_reinforced_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (id, text, impact, stability, created_at, last_reinforced_at)
                )
    finally:
        conn.close()

def get_memories_metadata(ids: list[str]) -> dict:
    """Fetch stability, use_count, last_reinforced_at, impact, and created_at
    for a set of memory IDs. Returns a dict keyed by id string for easy
    lookup. Plain read — no computation, no business logic; the caller
    (router) turns stability/use_count/last_reinforced_at into
    retrievability/frequency. impact and created_at are both returned as-is
    (raw, not part of the ranking formula) purely for surfacing in API
    responses — see search_memories(). created_at specifically feeds
    generate.py's prompt (via formulas.humanize_age) so the model can reason
    about accurate elapsed time; it plays no role in ranking or decay."""
    ids = [normalize_id(id) for id in ids]
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, stability, use_count, last_reinforced_at, impact, created_at FROM memories WHERE id = ANY(%s::uuid[])",
                    (ids,)
                )
                rows = cur.fetchall()
    finally:
        conn.close()
    return {
        str(row[0]): {
            "stability": row[1],
            "use_count": row[2],
            "last_reinforced_at": row[3],
            "impact": row[4],
            "created_at": row[5],
        }
        for row in rows
    }

def get_all_memories():
    """Fetch id, stability, last_reinforced_at for every stored memory.
    Used by Decay-Based Forgetting to compute retrievability and decide
    what to delete. Plain read, no business logic.

    Deliberately does not select impact: the flat MIN_RETRIEVABILITY
    threshold no longer depends on it (see constants.py) — see
    delete_decayed_memories(), which never reads it."""
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, stability, last_reinforced_at FROM memories")
                rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {"id": str(row[0]), "stability": row[1], "last_reinforced_at": row[2]}
        for row in rows
    ]

def delete_memories(ids: list[str]):
    """Delete memories from both Postgres and Qdrant, reducing the risk of
    drift between them — same reasoning as scripts/clear.sh. Not atomic:
    these are two sequential operations, so a failure between them can
    still leave an orphan in whichever store didn't get the second call —
    see techDebt.md's "Non-atomic dual-store writes/deletes" entry. Plain
    write, no business logic."""
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

def update_memory_reinforcement(id: str, multiplier: float, max_stability: float) -> bool:
    """Apply reinforcement atomically in one UPDATE: stability = min(current
    stability * multiplier, max_stability), use_count + 1, last_reinforced_at
    = NOW(). Deliberately NOT a read-then-compute-then-write — an earlier
    version read stability in Python, multiplied it there, and wrote the
    result back, which let two concurrent reinforcements both read the same
    starting stability and each write stability * multiplier once, silently
    losing one increment's worth of growth (use_count was already safe,
    since `use_count + 1` runs in SQL). Postgres serializes concurrent
    UPDATEs against the same row, so computing LEAST(stability * %s, %s)
    inside the UPDATE itself always operates on whatever stability is
    truly current at that moment, not a value read earlier in a separate
    round-trip. See security-preventions.md's Resolved section. Returns
    False if no row matched id, so the caller can raise a clear error
    without needing its own separate existence check beforehand."""
    id = normalize_id(id)
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE memories SET stability = LEAST(stability * %s, %s), use_count = use_count + 1, last_reinforced_at = NOW() WHERE id = %s::uuid",
                    (multiplier, max_stability, id)
                )
                return cur.rowcount > 0
    finally:
        conn.close()
