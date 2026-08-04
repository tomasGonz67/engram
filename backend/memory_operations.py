"""
Controller-layer logic that isn't wired to an HTTP route — see
architecture.md's "Code Architecture (MVC)" section. Same role as
routers/memories.py (orchestration: fetch, compute, write), just for
operations with no current external caller. Trivial to wrap in a route
later if one's ever needed (see dataModel.md).
"""

from database import update_memory_reinforcement, normalize_id, get_all_memories, delete_memories
from formulas import compute_age_days, compute_retrievability
from constants import REINFORCEMENT_MULTIPLIER, MAX_STABILITY, MIN_RETRIEVABILITY


def reinforce_memory(id: str):
    """Reinforce a memory following an estimated meaningful use — e.g.
    /generate's reinforcement guardrail estimating, via embedding
    similarity, that a retrieved memory was reflected in the model's
    answer, or a person selecting it from search results. NOT called
    automatically by search(). See architecture.md's "On meaningful use"
    section for why that distinction matters, and techDebt.md for the
    guardrail's measured false-positive rate on this estimate.

    The actual stability computation (min(stability * REINFORCEMENT_MULTIPLIER,
    MAX_STABILITY)) happens inside update_memory_reinforcement()'s single
    atomic UPDATE, not here — no separate read-then-compute step, since that
    previously let two concurrent reinforcements lose one increment's worth
    of stability growth to each other. See database.py and
    security-preventions.md's Resolved section."""
    id = normalize_id(id)
    found = update_memory_reinforcement(id, REINFORCEMENT_MULTIPLIER, MAX_STABILITY)
    if not found:
        raise ValueError(f"No memory found with id {id}")
    return id


def delete_decayed_memories(dry_run: bool = False):
    """Approximates forgetting by permanently deleting memories whose
    modeled retrievability has fallen below MIN_RETRIEVABILITY, a flat
    threshold — impact affects initial stability only, not this threshold
    (see constants.py). See architecture.md's Decay-Based Forgetting
    section.

    dry_run=True computes and logs what would be deleted without actually
    deleting it — meant for validating a new MIN_RETRIEVABILITY value
    against real data before trusting it with irreversible deletes. See
    FORGETTING_DRY_RUN in main.py.

    Not an HTTP route — Masi Memory has no auth by design, and this is
    destructive, so it only runs from the background loop in main.py's
    lifespan. Returns the list of (would-be-)deleted ids either way."""
    memories = get_all_memories()
    to_delete = []
    for m in memories:
        try:
            age_days = compute_age_days(m["last_reinforced_at"])
            retrievability = compute_retrievability(m["stability"], age_days)
        except ValueError as e:
            # A malformed row (stability <= 0 — nothing in the schema
            # prevents this, only app-level clamping at write time) must
            # not kill the loop for every other memory. Skip and move on
            # rather than letting one bad row silently disable forgetting
            # for the rest of the process's lifetime.
            print(f"Forgetting: skipping malformed memory {m['id']}: {e}")
            continue
        if retrievability < MIN_RETRIEVABILITY:
            to_delete.append(m["id"])

    if to_delete and not dry_run:
        delete_memories(to_delete)
    return to_delete
