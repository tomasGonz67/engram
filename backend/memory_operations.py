"""
Controller-layer logic that isn't wired to an HTTP route — see
architecture.md's "Code Architecture (MVC)" section. Same role as
routers/memories.py (orchestration: fetch, compute, write), just for
operations with no current external caller. Trivial to wrap in a route
later if one's ever needed (see dataModel.md).
"""

from database import get_memories_metadata, update_memory_reinforcement, normalize_id
from formulas import compute_reinforced_stability


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
