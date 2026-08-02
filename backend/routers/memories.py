import uuid
from datetime import datetime
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

def store_memory(text: str, impact: float, created_at: datetime = None, last_reinforced_at: datetime = None) -> dict:
    """Embed and store a memory in both Qdrant and Postgres. Shared by the
    /memories route below and by scripts/seed.py, which calls this directly
    (in-process, no HTTP) instead of duplicating this logic — same reasoning
    as search_memories() below: one implementation so it can't drift between
    callers. created_at/last_reinforced_at are dev-only backdating hooks —
    None (the default) preserves normal NOW() behavior; only seed.py ever
    passes real values, never exposed through MemoryInput/the public route.
    See dataModel.md and security-preventions.md."""
    id = str(uuid.uuid4())
    vector = model.encode(text).tolist()

    # Store vector in Qdrant
    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[PointStruct(id=id, vector=vector, payload={"text": text})]
    )

    # Business logic: clamp impact, compute initial stability
    impact = clamp_impact(impact)
    stability = compute_initial_stability(impact)

    # Store metadata in Postgres
    insert_memory(id, text, impact, stability, created_at=created_at, last_reinforced_at=last_reinforced_at)

    return {"id": id, "text": text}

@router.post("/memories")
def store(body: MemoryInput):
    return store_memory(body.text, body.impact)

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
            # Raw values below aren't part of final_score's weighted sum
            # (retrievability/frequency, the computed values above, are what
            # actually feed it) — included purely so callers (e.g. an
            # analytics UI) can show the underlying numbers, not just the
            # derived scores. created_at specifically also feeds /generate's
            # prompt (see generate.py) so the model can reason about
            # accurate elapsed time — it plays no role in ranking either.
            "stability": meta["stability"],
            "use_count": meta["use_count"],
            "age_days": age_days,
            "impact": meta["impact"],
            "created_at": meta["created_at"],
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
