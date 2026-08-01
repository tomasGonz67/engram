"""
Controller-layer logic that isn't wired to an HTTP route — see
architecture.md's "Code Architecture (MVC)" section. Same role as
routers/memories.py (orchestration: fetch, compute, write), just for
operations with no current external caller. Trivial to wrap in a route
later if one's ever needed (see dataModel.md).
"""

from database import get_memories_metadata, update_memory_reinforcement, normalize_id, get_all_memories, delete_memories
from formulas import compute_reinforced_stability, compute_age_days, compute_retrievability, compute_consolidation_threshold


def reinforce_memory(id: str):
    """Reinforce a memory following a confirmed, meaningful use — e.g. an
    LLM's tool call citing it, or a person selecting it from search results.
    NOT called automatically by search(). See architecture.md's "On
    meaningful use" section for why that distinction matters."""
    id = normalize_id(id)
    metadata = get_memories_metadata([id])
    meta = metadata.get(id)
    if meta is None:
        raise ValueError(f"No memory found with id {id}")

    new_stability = compute_reinforced_stability(meta["stability"])
    update_memory_reinforcement(id, new_stability)
    return id


def consolidate():
    """Prune memories that have decayed past recovery. The prune threshold
    scales with impact — high-impact memories must decay further before
    they're eligible, modeling flashbulb-memory-style enhanced durability
    rather than treating every memory's decay uniformly. See
    architecture.md's Consolidation section.

    Not an HTTP route — Engram has no auth by design, and this is
    destructive, so it only runs from the background loop in main.py's
    lifespan. Returns the list of deleted ids."""
    memories = get_all_memories()
    to_delete = []
    for m in memories:
        try:
            age_days = compute_age_days(m["last_reinforced_at"])
            retrievability = compute_retrievability(m["stability"], age_days)
            threshold = compute_consolidation_threshold(m["impact"])
        except (ValueError, ZeroDivisionError) as e:
            # A malformed row (stability <= 0, impact == 0 — nothing in the
            # schema prevents this, only app-level clamping at write time)
            # must not kill the loop for every other memory. Skip and move
            # on rather than letting one bad row silently disable
            # Consolidation for the rest of the process's lifetime.
            print(f"Consolidation: skipping malformed memory {m['id']}: {e}")
            continue
        if retrievability < threshold:
            to_delete.append(m["id"])

    if to_delete:
        delete_memories(to_delete)
    return to_delete
