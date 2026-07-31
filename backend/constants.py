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

# STILL A PLACEHOLDER, but better calibrated than before — a genuine nonsense
# query ("asdkjf qwoeiru zzxcvbn blorp glorp nonsense gibberish") scored
# 0.716-0.768 against a 60-memory seeded dataset, all of it wrongly passing
# the old 0.7 threshold. Known-relevant matches have all scored 0.834+.
# 0.8 sits between those two ranges. Still not a large validated dataset —
# revisit once there's real usage data. See architecture.md.
SEMANTIC_THRESHOLD = 0.8
