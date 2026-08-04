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

# MVP retrieval-ranking weights, selected through the controlled evaluation
# in evaluation/experiments/reranking-weight-decision.md (the authoritative
# record — architecture.md/security-preventions.md/techDebt.md summarize
# and link to it rather than duplicating the full analysis). Semantic
# relevance remains dominant.
#
# Frequency provides a small reinforcement bias without reducing measured
# Recall@5 on the current 23-query fixture. Retrievability is intentionally
# excluded from ranking because even a 0.01 weight caused relevance
# regressions on 3 of 23 test queries, with zero queries improved at any
# nonzero value tested. Retrievability still governs decay-based
# forgetting (the flat MIN_RETRIEVABILITY deletion threshold below,
# unchanged) — this only removes its role in ranking, not from the system.
#
# These are prototype defaults, not universal or neuroscientifically
# derived parameters. Chosen from one hand-built 23-query fixture against
# one live, reinforcement-skewed database snapshot — re-evaluate against
# broader, frozen datasets before production. See techDebt.md.
SEMANTIC_WEIGHT = 0.95
RETRIEVABILITY_WEIGHT = 0.00
FREQUENCY_WEIGHT = 0.05

# Qwen3-Embedding is instruction-aware — its model card recommends prefixing
# *queries* (not documents) with a task instruction for retrieval, typically
# worth 1-5%. Only applied to the query side of search_memories(); memories
# are stored/embedded bare, matching the model's own config, which defines
# an empty prompt for "document" and only a non-empty one for "query".
# Empirically tested (not just applied on the model card's say-so) against
# 23 labeled positive queries + 4 negative controls across all 181 live
# memories, comparing bare vs. this exact instruction: final-ranking
# Recall@5 rose from 67.0% to 78.9% (+11.9 pts), final-ranking Hit@5 rose
# from 91.3% to 95.7%, and negative-query separation improved (mean highest
# irrelevant-query similarity dropped from 0.762 to 0.683). Tradeoff: MRR
# dropped slightly (0.525 -> 0.512 on final ranking) — the single best match
# lands in the #1 spot marginally less often, in exchange for more
# genuinely relevant memories surviving into the top 5 overall. Judged
# worth it here specifically because /generate hands the model all 5
# retrieved memories, not just the top one — breadth matters more than
# strict top-1 precision for how this system actually uses the results.
# Does NOT eliminate score overlap between relevant and irrelevant content
# — confirmed still overlapping even with this instruction (lowest
# genuine-match score 0.702, highest irrelevant-query score 0.748) — so
# this doesn't change the "no hard threshold" decision in "How Retrieval
# Works", it only narrows the overlap. Deliberately NOT applied to the
# reinforcement guardrail's sentence/memory comparisons in generate.py —
# those are symmetric similarity checks (does this answer reflect this
# memory), not asymmetric query-to-document retrieval, so this instruction
# doesn't conceptually apply there. See security-preventions.md's Resolved
# section for the full experiment.
RETRIEVAL_QUERY_INSTRUCTION = (
    "Instruct: Retrieve autobiographical memories relevant to the user's question\n"
    "Query: "
)

# How many recent turns get folded into the text actually embedded for
# retrieval (not to be confused with the frontend's RECENT_TURNS_LIMIT,
# which controls how much conversation history reaches the generation
# prompt itself — a much larger, separate concern). Retrieval used to
# embed only the new message alone, with zero conversation context, so a
# context-dependent follow-up ("tell me more details", "why?") searched
# with no idea what it was following up on. Small on purpose: unlike the
# generation prompt (which benefits from more context), folding in many
# turns here risks diluting the retrieval embedding with irrelevant
# earlier conversation the same way a long /generate answer was found to
# dilute the reinforcement guardrail's embedding — see
# security-preventions.md's Resolved section. Not empirically tuned.
RETRIEVAL_CONTEXT_TURNS = 2

# There used to be a SEMANTIC_THRESHOLD constant here — a hard floor on
# retrieval's semantic score, discarding any candidate below it before
# ranking. Removed: measured to be unreliable for this embedding model and
# dataset, not just untuned. History: 0.7 -> 0.8 -> 0.75, each move chasing
# a real failure the previous value caused (nonsense queries leaking noise
# past 0.7/0.75, a genuinely relevant query — "do I have a girlfriend?" —
# getting wrongly filtered out at 0.8). The value that finally killed the
# whole approach: the single best real match in a 181-memory dataset for
# that girlfriend query scored 0.71, while real (non-nonsense) content
# scored as high as 0.79 against a totally unrelated nonsense query — the
# two distributions genuinely overlap, so no single cutoff can separate
# them. See architecture.md and security-preventions.md's Resolved section.
# Retrieval now returns every candidate in the pool, ranked but unfiltered;
# relevance is judged downstream instead — by the model for what shows up
# in /generate's answer, and by the constant below for what's allowed to
# actually persist to the DB.

# Answers a different question than the old retrieval threshold did —
# not "does this memory match the query" but "does this memory match the
# model's actual written answer," used by /generate's reinforcement
# guardrail (see architecture.md's "How Generation Works" and
# security-preventions.md's Resolved section) to decide whether a
# retrieved memory is actually grounded in the real answer text or not —
# checked for every retrieved memory directly, no function calling
# involved (see security-preventions.md for why that changed). 0.75
# (the old retrieval value) was tried here first and measured to let
# short/generic replies ("You're welcome.", "Congrats on that!") through
# against memories they have no real connection to. Empirically tested
# against ~15 generic/filler answers and ~11 answers that genuinely cited a
# memory, across several different memory texts: filler topped out at
# 0.837, genuine citations started at 0.879 — a clean, non-overlapping gap
# at the whole-sentence level.
#
# Set to 0.8, not 0.85 — a deliberate, known-imperfect tradeoff, not a
# cleaner calibration. A genuine citation buried in a parenthetical clause
# ("...she's been my girlfriend for a while (we originally met playing
# Toontown)...") was measured to score only 0.81-0.83 even at the finest
# chunk granularity tried, while a filler phrase from the original set
# ("That's a fun childhood memory to have.") scored 0.837 — higher than
# that genuine citation. Genuine and filler measurably overlap at this fine
# a grain, so 0.8 is known to let some filler back through in exchange for
# catching more real citations like the one above — accepted deliberately
# rather than fixed, since the alternative (a hybrid embedding + literal-
# word-overlap check) was discussed but not built. See security-preventions.md's
# Resolved section.
REINFORCEMENT_GUARDRAIL_THRESHOLD = 0.8

# Decay-Based Forgetting
# Flat deletion threshold: a memory is deleted once retrievability <
# MIN_RETRIEVABILITY. impact affects only initial stability (see
# compute_initial_stability) — it is deliberately NOT used again here.
# Using it twice (seeding stability AND dividing the deletion threshold)
# was the original design, but was rejected: it double-counts impact's
# influence and gives high-impact memories a disproportionately compounding
# advantage. See architecture.md's Decay-Based Forgetting section.
#
# Set to 0.01, not the previously-considered 0.02, after checking both
# against this project's own live seeded dataset (181 memories spanning
# decades, per scripts/backdate.sh): 0.02 still made 54% of that dataset
# immediately eligible for deletion, including many never-reinforced but
# genuine autobiographical memories, which was judged too aggressive for
# an autobiographical-memory prototype. 0.01 was chosen instead — never-
# reinforced lifetimes: min impact (0.5) ~13.7 years, baseline impact (1.0)
# ~27.4 years, max impact (2.0) ~54.8 years; anything genuinely reinforced
# (stability near MAX_STABILITY) is effectively never deleted. Reproducible
# via scripts/forgetting_threshold_analysis.py.
#
# This is an MVP default, not a biologically established value — no
# claim that these specific lifetimes match real human forgetting curves,
# only that they're no longer obviously wrong for this dataset. Because
# this permanently deletes data, the first forgetting run under any new
# threshold should go through dry-run mode first — see FORGETTING_DRY_RUN
# in main.py.
MIN_RETRIEVABILITY = 0.01
FORGETTING_INTERVAL_SECONDS = 7 * 86400  # weekly — decay now moves on a scale of years-to-decades (see MIN_RETRIEVABILITY above), so weekly is a conservative check, not a tight one; kept weekly anyway since each run is cheap regardless of interval (see architecture.md's Decay-Based Forgetting section)
