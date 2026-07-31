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

# STILL A PLACEHOLDER. History: 0.7 -> 0.8 -> 0.75.
# A genuine nonsense query ("asdkjf qwoeiru zzxcvbn blorp glorp nonsense
# gibberish") scored 0.716-0.768 against a 60-memory seeded dataset, all of
# it wrongly passing the old 0.7 threshold — moved to 0.8 to fix that.
# Then a real, clearly relevant query ("do I have a girlfriend?" against 15
# seeded girlfriend-related memories) scored 0.767 and got wrongly filtered
# out entirely at 0.8 — moved down to 0.75 to let it through.
#
# The predicted tradeoff of 0.75 showed up immediately: the same nonsense
# query, re-run through /generate against the 75-memory seeded dataset,
# leaked 3 irrelevant memories past the threshold (0.757-0.768) — "Played a
# new Roblox game", "My parrot said its first word", "Baked a loaf of
# sourdough bread". Retrieval let noise through as expected. Generation
# didn't: the model recognized the input as gibberish, didn't fabricate an
# answer from the irrelevant memories, and reinforced none of them — see
# architecture.md's "How Generation Works" section for that second defense
# layer. Known-relevant matches have scored 0.834+. Not a validated value —
# revisit with a larger, more systematic dataset. See architecture.md.
SEMANTIC_THRESHOLD = 0.75
