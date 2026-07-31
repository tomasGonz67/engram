# Tunable constants for memory lifecycle and search. See architecture.md for the
# full formulas and reasoning. Single source of truth: business logic (in routers/)
# imports these rather than redefining them wherever they're used.

# Memory lifecycle
BASE_STABILITY = 1.0
REINFORCEMENT_MULTIPLIER = 1.2
MAX_STABILITY = 3650.0  # ~10 years, a safety rail against unbounded growth
MIN_IMPACT = 0.5
MAX_IMPACT = 2.0

# Search / ranking
CANDIDATE_POOL_SIZE = 50  # candidates fetched from Qdrant before re-ranking down to the caller's limit
SEMANTIC_WEIGHT = 0.75
RETRIEVABILITY_WEIGHT = 0.15
FREQUENCY_WEIGHT = 0.10

# UNVALIDATED PLACEHOLDER — a working hypothesis based on exactly two manual
# test examples (one relevant match normalizing to 0.834, one irrelevant
# match normalizing to 0.614), not a calibrated value. Revisit once there's
# real usage data to check it against. See architecture.md.
SEMANTIC_THRESHOLD = 0.7
