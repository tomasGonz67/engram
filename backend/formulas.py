import math
import re
from datetime import datetime, timezone

from constants import (
    BASE_STABILITY,
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


def compute_age_days(last_reinforced_at: datetime) -> float:
    """Days elapsed since a memory was last reinforced. Feeds into
    compute_retrievability — see architecture.md's Retrievability section."""
    now = datetime.now(timezone.utc)
    if last_reinforced_at.tzinfo is None:
        last_reinforced_at = last_reinforced_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - last_reinforced_at).total_seconds() / 86400)


def humanize_age(created_at: datetime) -> str:
    """Converts elapsed time since created_at into a natural-language string
    ("3 years ago", "2 days ago", "just now") for generate.py's prompt —
    computed fresh on every request, so it's always accurate regardless of
    how much real time has passed since the memory was stored, instead of a
    relative-time phrase frozen into the memory's text at creation. Distinct
    from compute_age_days: that returns a raw float for the ranking formula
    and is driven by last_reinforced_at, not something meant for a language
    model to read directly, and not the same field as this function uses.
    created_at plays no role in ranking or decay — see database.py."""
    age_days = compute_age_days(created_at)

    if age_days < 1:
        hours = round(age_days * 24)
        if hours < 1:
            return "just now"
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    if age_days < 7:
        days = round(age_days)
        return f"{days} day{'s' if days != 1 else ''} ago"

    if age_days < 30:
        weeks = round(age_days / 7)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"

    if age_days < 365:
        months = round(age_days / 30)
        return f"{months} month{'s' if months != 1 else ''} ago"

    years = round(age_days / 365)
    return f"{years} year{'s' if years != 1 else ''} ago"


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
    section. use_count only reflects estimated meaningful use (see
    reinforce_memory()'s docstring for what "estimated" means here), not
    every time a memory is returned by search."""
    return 1 - math.exp(-use_count / 5)


def normalize_qdrant_similarity(raw_similarity: float) -> float:
    """Rescale cosine similarity from its mathematical range [-1, 1] to
    [0, 1], so it's on the same scale as retrievability and frequency going
    into compute_final_score's weighted sum. See architecture.md's "How
    Retrieval Works" section."""
    return (raw_similarity + 1) / 2


def compute_cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """Plain-Python cosine similarity between two embedding vectors, in
    [-1, 1] — pass through normalize_qdrant_similarity for the same [0, 1]
    scale Qdrant's own scores use. Used by /generate's reinforcement
    guardrail to compare a candidate memory's vector against an embedding of
    the model's actual final answer, entirely locally (no OpenAI call,
    same embedding model already used for storage/retrieval) — see
    architecture.md's "How Generation Works"."""
    dot = sum(a * b for a, b in zip(vector_a, vector_b))
    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))
    return dot / (norm_a * norm_b)


def split_into_sentences(text: str) -> list[str]:
    """Splits on blank lines/bullets first, then sentence-ending punctuation
    within each. Used by /generate's reinforcement guardrail so a long,
    multi-topic answer gets compared sentence-by-sentence against each
    proposed memory instead of as one embedded block — a long answer's
    generic wrapper text (greetings, transition phrases, closing questions)
    was measured to dilute the whole-answer embedding enough to drag a
    genuinely-cited memory's similarity score below threshold, even though
    one specific sentence in it was a near-exact paraphrase. See
    security-preventions.md's Resolved section. Not linguistically precise
    (doesn't handle abbreviations, decimals, etc.) — fine here since the
    output only ever feeds a similarity comparison, not anything requiring
    grammatical correctness."""
    lines = re.split(r"\n+", text)
    sentences = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        sentences.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip())
    return sentences


# Function words plus a small set of generic, low-information nouns/verbs
# (time, day, way, thing, moment, life, lot, bit — words common enough to
# appear in almost any autobiographical sentence regardless of actual
# subject matter) — see shares_significant_word()'s docstring for why the
# generic-noun additions are there specifically, not just standard
# stopwords.
_GUARDRAIL_STOPWORDS = frozenset("""
a an the is was were be been being am are i you he she it we they me him her us them
my your his its our their mine yours hers ours theirs
and or but if then so because as while although
to of in on at for with about against between into through during before after above below from
up down off over under again further once
this that these those
do does did doing have has had having
will would could should can may might must shall
not no nor yes
get got getting really just very also still even
more most some any all both each few other such
there here when where why how what which who whom
time times day days year years way ways thing things moment moments life lives lot bit
""".split()) | frozenset("""
i've i'm i'd i'll you've you're you'd don't didn't wasn't weren't isn't aren't
couldn't wouldn't shouldn't it's that's there's he's she's we've they've let's
can't won't
""".split())


def _significant_words(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    return {t for t in tokens if t not in _GUARDRAIL_STOPWORDS and len(t) > 1}


def shares_significant_word(memory_text: str, sentence: str) -> bool:
    """True if the memory text and the answer sentence share at least one
    word outside a stopword/generic-word list. Used by /generate's
    reinforcement guardrail as a second, independent condition alongside
    REINFORCEMENT_GUARDRAIL_THRESHOLD — a memory only gets reinforced if
    BOTH the embedding similarity clears the threshold AND this returns
    True, not either alone.

    Exists specifically to catch a failure mode embedding similarity alone
    doesn't: two sentences can share a narrative *shape* ("tried X, had a
    bad reaction, gave up on X") with high cosine similarity despite
    describing completely different things, if X differs. Confirmed live:
    "Tried kombucha for the first time and could not get past the taste"
    scored 0.82 (above the 0.8 threshold) against an answer sentence about
    giving up on gas station sushi — zero shared subject matter, just a
    shared sentence pattern. Requiring literal word overlap rejects that
    case (no shared words) while still passing genuine citations, since
    those reliably share specific words with the answer even under
    paraphrasing (verified against the parenthetical-clause case in
    security-preventions.md's Resolved section: "we originally met playing
    Toontown" shares "Toontown" with its memory) and still reject known
    filler (verified against the original ~15-phrase calibration set: none
    of it shares specific words with any real memory, having none to share
    to begin with).

    Known, accepted limitation, not silently ignored: a genuine citation
    paraphrased heavily enough to share zero literal words with its memory
    (e.g. "kombucha" rephrased as "a fermented tea drink") would now be
    incorrectly rejected — a new false negative traded for fixing the false
    positive above. Same category of tradeoff as REINFORCEMENT_GUARDRAIL_THRESHOLD
    itself: accepted because the failure mode it fixes (confidently wrong
    reinforcement onto an unrelated memory) is worse than the one it risks
    (an occasional real citation phrased so differently it isn't caught),
    not because it's free."""
    return bool(_significant_words(memory_text) & _significant_words(sentence))


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
