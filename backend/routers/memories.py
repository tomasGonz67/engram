import uuid
from fastapi import APIRouter
from qdrant_client.models import PointStruct
from models import MemoryInput, SearchInput
from database import model, qdrant, COLLECTION_NAME, insert_memory, get_memories_metadata, increment_retrieval_counts
from constants import CANDIDATE_POOL_SIZE, SEMANTIC_THRESHOLD
from formulas import (
    clamp_impact,
    compute_initial_stability,
    normalize_qdrant_similarity,
    compute_age_days,
    compute_retrievability,
    compute_frequency,
    compute_final_score,
)

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
    impact = clamp_impact(body.impact)
    stability = compute_initial_stability(impact)

    # Store metadata in Postgres
    insert_memory(id, body.text, impact, stability)

    return {"id": id, "text": body.text}

def search_memories(text: str, limit: int):
    """Embed text, retrieve and rank candidate memories. Returns a ranked
    list (possibly empty) — shared by /memories/search (raw results, no LLM
    involved — used for debugging/calibrating ranking, e.g. the
    SEMANTIC_THRESHOLD tuning in architecture.md) and /generate (feeds the
    results into the generation prompt). One implementation so ranking logic
    can't drift between callers — same reasoning as formulas.py. See
    architecture.md's Controller section."""
    vector = model.encode(text).tolist()
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=CANDIDATE_POOL_SIZE
    ).points

    ids = [str(r.id) for r in results]
    metadata = get_memories_metadata(ids)

    # Normalize semantic scores, then discard anything below the (currently
    # unvalidated) semantic threshold before it ever reaches ranking — see
    # constants.py and architecture.md.
    candidates = [
        {"result": r, "semantic": normalize_qdrant_similarity(r.score)}
        for r in results
    ]
    candidates = [c for c in candidates if c["semantic"] >= SEMANTIC_THRESHOLD]

    # Only candidates with a matching Postgres row can be ranked — there's no
    # stability/use_count/last_reinforced_at to compute retrievability or
    # frequency from otherwise (an orphaned Qdrant vector, e.g. from a
    # partial write failure — see architecture.md).
    ranked = []
    for c in candidates:
        meta = metadata.get(str(c["result"].id))
        if meta is None:
            continue
        age_days = compute_age_days(meta["last_reinforced_at"])
        retrievability = compute_retrievability(meta["stability"], age_days)
        frequency = compute_frequency(meta["use_count"])
        final_score = compute_final_score(c["semantic"], retrievability, frequency)
        ranked.append({
            "id": c["result"].id,
            "text": c["result"].payload["text"],
            "semantic": c["semantic"],
            "retrievability": retrievability,
            "frequency": frequency,
            "final_score": final_score,
        })

    ranked.sort(key=lambda r: r["final_score"], reverse=True)
    top = ranked[:limit]
    increment_retrieval_counts([str(r["id"]) for r in top])
    return top

@router.post("/memories/search")
def search(body: SearchInput):
    ranked = search_memories(body.text, body.limit)
    if not ranked:
        return {"message": "No valid memories found"}
    return ranked
