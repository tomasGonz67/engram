import math
from datetime import datetime, timezone

from constants import (
    BASE_STABILITY,
    REINFORCEMENT_MULTIPLIER,
    MAX_STABILITY,
    MIN_IMPACT,
    MAX_IMPACT,
    SEMANTIC_WEIGHT,
    RETRIEVABILITY_WEIGHT,
    FREQUENCY_WEIGHT,
)


def clamp_impact(impact: float) -> float:
    """Clamp incoming impact to [MIN_IMPACT, MAX_IMPACT]. See architecture.md's
    "On creation" section — never trust a client-provided value unclamped."""
    return max(MIN_IMPACT, min(impact, MAX_IMPACT))


def compute_initial_stability(impact: float) -> float:
    """BASE_STABILITY * impact. See architecture.md's "On creation" section.
    Clamps impact itself rather than trusting the caller already did — this
    function should never be able to produce an invalid stability."""
    return BASE_STABILITY * clamp_impact(impact)


def compute_reinforced_stability(stability: float) -> float:
    """min(stability * REINFORCEMENT_MULTIPLIER, MAX_STABILITY). See
    architecture.md's "On meaningful use" section — only called on confirmed
    use, never on a memory merely being returned by search."""
    return min(stability * REINFORCEMENT_MULTIPLIER, MAX_STABILITY)


def compute_age_days(last_reinforced_at: datetime) -> float:
    """Days elapsed since a memory was last reinforced. Feeds into
    compute_retrievability — see architecture.md's Retrievability section."""
    now = datetime.now(timezone.utc)
    if last_reinforced_at.tzinfo is None:
        last_reinforced_at = last_reinforced_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - last_reinforced_at).total_seconds() / 86400)


def compute_retrievability(stability: float, age_days: float) -> float:
    """(1 + age_days / stability)^-0.5. See architecture.md's Retrievability
    section. Not a half-life: at age_days == stability, retrievability is
    ~70.7%, not 50%. Actual half-life is 3 * stability. Computed lazily —
    never stored.

    Raises if stability isn't positive rather than silently propagating a
    complex number (Python's ** on a negative base with a fractional
    exponent returns one instead of erroring)."""
    if stability <= 0:
        raise ValueError(f"stability must be positive, got {stability}")
    return (1 + age_days / stability) ** -0.5


def compute_frequency(use_count: int) -> float:
    """1 - exp(-use_count / 5). See architecture.md's "How Retrieval Works"
    section. use_count only reflects confirmed meaningful use, not every
    time a memory is returned by search."""
    return 1 - math.exp(-use_count / 5)


def normalize_qdrant_similarity(raw_similarity: float) -> float:
    """Rescale cosine similarity from its mathematical range [-1, 1] to
    [0, 1], so it's on the same scale as retrievability and frequency going
    into compute_final_score's weighted sum. See architecture.md's "How
    Retrieval Works" section."""
    return (raw_similarity + 1) / 2


def compute_final_score(semantic: float, retrievability: float, frequency: float) -> float:
    """Weighted SUM (not product) of the three ranking signals. See
    architecture.md for why a sum is used — a weak signal on one term (e.g.
    a brand-new memory with frequency == 0) can't zero out the whole score
    the way a product would."""
    return (
        SEMANTIC_WEIGHT * semantic
        + RETRIEVABILITY_WEIGHT * retrievability
        + FREQUENCY_WEIGHT * frequency
    )
