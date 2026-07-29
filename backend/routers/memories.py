import uuid
from fastapi import APIRouter
from qdrant_client.models import PointStruct
from models import MemoryInput, SearchInput
from database import model, qdrant, COLLECTION_NAME, insert_memory, get_memories_metadata
from constants import BASE_STABILITY, MIN_IMPACT, MAX_IMPACT, CANDIDATE_POOL_SIZE

router = APIRouter()

@router.post("/memories")
def store(body: MemoryInput):
    id = str(uuid.uuid4())
    vector = model.encode(body.text).tolist()

    # Store vector in Qdrant
    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[PointStruct(id=id, vector=vector, payload={"text": body.text})]
    )

    # Business logic: clamp impact, compute initial stability
    impact = max(MIN_IMPACT, min(body.impact, MAX_IMPACT))
    stability = BASE_STABILITY * impact

    # Store metadata in Postgres
    insert_memory(id, body.text, impact, stability)

    return {"id": id, "text": body.text}

@router.post("/memories/search")
def search(body: SearchInput):
    vector = model.encode(body.text).tolist()
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=CANDIDATE_POOL_SIZE
    ).points

    ids = [str(r.id) for r in results]
    metadata = get_memories_metadata(ids)

    # Temporary: re-ranking (retrievability, frequency, weighted score) isn't
    # implemented yet — this just proves the metadata is being fetched correctly.
    # Still returns only body.limit results, but from a much wider candidate pool.
    return [
        {
            "id": r.id,
            "text": r.payload["text"],
            "semantic_score": r.score,
            "metadata": metadata.get(str(r.id))
        }
        for r in results[:body.limit]
    ]
