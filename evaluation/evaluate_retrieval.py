#!/usr/bin/env python3
"""
Read-only retrieval evaluation harness against the live dev Qdrant/Postgres
data. Never calls search_memories() or increment_retrieval_counts() — it
re-implements the same read-only retrieve-and-score steps directly (Qdrant
query_points, get_memories_metadata, formulas.py's actual functions), so
running this repeatedly cannot change retrieval_count or anything else in
the database. See README.md in this directory for metric definitions and
usage.

Reuses backend/formulas.py and backend/constants.py directly for every
signal computation (normalize_qdrant_similarity, compute_retrievability,
compute_frequency) AND for the production baseline's actual ranking
formula (compute_final_score() itself, called directly — not
reimplemented) and the exact RETRIEVAL_QUERY_INSTRUCTION string. This
matters beyond just avoiding typos: if compute_final_score() ever changes
to something more than a weighted sum (clamping, interactions,
normalization), the "production" baseline here changes with it
automatically, rather than silently diverging from what actually runs.
The only thing that IS reimplemented here is weighted_score() — a
parameterized weighted sum used exclusively for signal-comparison/
weight-grid EXPERIMENTAL variants, which need custom weight combinations
compute_final_score() has no way to accept. The "production" variant in
every comparison mode uses compute_final_score() directly, never
weighted_score().

Does not change runtime ranking weights — SEMANTIC_WEIGHT/
RETRIEVABILITY_WEIGHT/FREQUENCY_WEIGHT in constants.py are read for the
production baseline and for detecting an accidental collision with a
fixed experimental variant (see run_signal_comparison), never written.
run_signal_comparison's own experimental variants use fixed weights
declared in that function, deliberately not these constants — see its
docstring for why.

Fixture validation is FATAL (nonzero exit), not a warning-and-continue —
a decision-making harness that silently proceeds on a stale/incomplete
fixture can make a data problem look like a ranking regression.

Within a single comparison mode (bare-vs-instructed, signal-comparison,
or weight-grid), every ranking variant is evaluated against the exact
same, once-fetched candidate set per query — not independently
re-fetched per variant. Re-fetching per variant would re-embed, re-query
Qdrant, and recompute age_days from a fresh clock read each time, which
could subtly change results between variants for reasons having nothing
to do with the ranking strategy being compared.
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from database import model, qdrant, COLLECTION_NAME, get_pg_conn, get_memories_metadata  # noqa: E402
from constants import (  # noqa: E402
    CANDIDATE_POOL_SIZE,
    RETRIEVAL_QUERY_INSTRUCTION,
    SEMANTIC_WEIGHT,
    RETRIEVABILITY_WEIGHT,
    FREQUENCY_WEIGHT,
)
from formulas import (  # noqa: E402
    normalize_qdrant_similarity,
    compute_age_days,
    compute_retrievability,
    compute_frequency,
    compute_final_score,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "retrieval_cases.json"
K = 5  # evaluated at top-K, matching the app's default /generate limit


def load_cases():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def text_to_id_map():
    """Read-only SELECT against Postgres — resolves the fixture's stable
    memory-text labels to whatever ids they currently have, so the fixture
    survives a reseed (new UUIDs) without needing to be hand-updated."""
    conn = get_pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, text FROM memories")
                rows = cur.fetchall()
    finally:
        conn.close()
    return {text: str(id) for id, text in rows}


def embed_query(text: str, use_instruction: bool) -> list[float]:
    """Read-only — no DB writes, no retrieval_count changes. Mirrors
    search_memories()'s own query-embedding step exactly, including the
    instruction prefix when enabled."""
    full_text = f"{RETRIEVAL_QUERY_INSTRUCTION}{text}" if use_instruction else text
    return model.encode(full_text).tolist()


def fetch_candidates(query_text: str, use_instruction: bool, pool_size: int = CANDIDATE_POOL_SIZE):
    """Read-only: same Qdrant query_points + get_memories_metadata calls
    search_memories() makes, but WITHOUT the increment_retrieval_counts()
    call at the end — that's the one side-effecting step this deliberately
    skips. Returns every candidate with all three raw signals computed
    (semantic, retrievability, frequency), unsorted — callers decide how
    to combine/rank them."""
    vector = embed_query(query_text, use_instruction)
    results = qdrant.query_points(collection_name=COLLECTION_NAME, query=vector, limit=pool_size).points
    ids = [str(r.id) for r in results]
    metadata = get_memories_metadata(ids)

    candidates = []
    for r in results:
        meta = metadata.get(str(r.id))
        if meta is None:
            continue
        semantic = normalize_qdrant_similarity(r.score)
        age_days = compute_age_days(meta["last_reinforced_at"])
        retrievability = compute_retrievability(meta["stability"], age_days)
        frequency = compute_frequency(meta["use_count"])
        candidates.append({
            "id": str(r.id),
            "text": r.payload.get("text", ""),
            "semantic": semantic,
            "retrievability": retrievability,
            "frequency": frequency,
        })
    return candidates


def weighted_score(c: dict, w_sem: float, w_retr: float, w_freq: float) -> float:
    """Parameterized weighted sum — for EXPERIMENTAL signal-comparison/
    weight-grid variants only, which need custom weight combinations
    compute_final_score() has no way to accept. Never used for the
    "production" baseline itself — see rank_by_final_score()."""
    return w_sem * c["semantic"] + w_retr * c["retrievability"] + w_freq * c["frequency"]


def rank_by_semantic(candidates):
    return sorted(candidates, key=lambda c: c["semantic"], reverse=True)


def rank_by_final_score(candidates):
    """The actual production ranking — calls formulas.compute_final_score()
    directly rather than reimplementing its formula, so this baseline can't
    silently diverge if compute_final_score() ever becomes more than a
    weighted sum (clamping, interactions, normalization)."""
    return sorted(candidates, key=lambda c: compute_final_score(c["semantic"], c["retrievability"], c["frequency"]), reverse=True)


def rank_by_weights(candidates, w_sem, w_retr, w_freq):
    return sorted(candidates, key=lambda c: weighted_score(c, w_sem, w_retr, w_freq), reverse=True)


def hit_at_k(ranked_texts, relevant_texts, k):
    return 1.0 if any(t in relevant_texts for t in ranked_texts[:k]) else 0.0


def recall_at_k(ranked_texts, relevant_texts, k):
    """Set intersection, not a list scan — if a reseed without a prior
    clear ever left duplicate memories with identical text, counting every
    ranked occurrence separately against one relevance label could push
    recall above 100%. Intersecting as sets caps it at the label count
    regardless of how many duplicate rows rank in the top K."""
    if not relevant_texts:
        return None
    found = len(set(ranked_texts[:k]) & set(relevant_texts))
    return found / len(relevant_texts)


def reciprocal_rank(ranked_texts, relevant_texts):
    for i, t in enumerate(ranked_texts, start=1):
        if t in relevant_texts:
            return 1.0 / i
    return 0.0


def fetch_candidates_for_cases(cases, use_instruction):
    """Fetches every positive query's candidates ONCE, keyed by query text —
    the single frozen candidate set every ranking variant in one comparison
    mode reuses. Re-fetching per variant would re-embed, re-query Qdrant,
    and recompute age_days from a fresh clock read each time, which could
    subtly change results between variants for reasons unrelated to the
    ranking strategy actually being compared."""
    return {case["query"]: fetch_candidates(case["query"], use_instruction) for case in cases["positive_cases"]}


def evaluate_ranking(cases, candidates_by_query, rank_fn, detail=False, label=""):
    """Runs every positive case through rank_fn (a function of candidates ->
    sorted candidates) against the pre-fetched, frozen candidate set for
    that query, computes Hit@K/Recall@K/MRR per query, and returns the
    macro-averaged aggregate plus per-query rows for --detail."""
    rows = []
    for case in cases["positive_cases"]:
        candidates = candidates_by_query[case["query"]]
        ranked = rank_fn(candidates)
        ranked_texts = [c["text"] for c in ranked]
        relevant_texts = set(case["relevant_memory_texts"])
        rows.append({
            "query": case["query"],
            "hit": hit_at_k(ranked_texts, relevant_texts, K),
            "recall": recall_at_k(ranked_texts, relevant_texts, K),
            "rr": reciprocal_rank(ranked_texts, relevant_texts),
            "top_k": ranked_texts[:K],
        })

    n = len(rows)
    agg = {
        "label": label,
        "hit_at_k": sum(r["hit"] for r in rows) / n,
        "recall_at_k": sum(r["recall"] for r in rows if r["recall"] is not None) / n,
        "mrr": sum(r["rr"] for r in rows) / n,
    }

    if detail:
        print(f"--- {label}: per-query detail ---")
        for r in rows:
            print(f"  hit={int(r['hit'])} recall={r['recall']:.2f} rr={r['rr']:.2f}  {r['query']!r}")
            for t in r["top_k"]:
                print(f"      {t!r}")
        print()

    return agg, rows


def evaluate_negatives(cases, use_instruction, detail=False, label=""):
    """Negative-control score distribution — highest semantic similarity
    any real memory reaches against a query with no genuine answer in the
    dataset. Lower is better (less noise leaking toward relevance)."""
    highest_scores = []
    for case in cases["negative_cases"]:
        candidates = fetch_candidates(case["query"], use_instruction)
        ranked = rank_by_semantic(candidates)
        top_score = ranked[0]["semantic"] if ranked else 0.0
        highest_scores.append(top_score)
        if detail:
            print(f"  {label}: highest={top_score:.4f}  {case['query']!r} -> {ranked[0]['text']!r}")

    return {
        "label": label,
        "mean_highest": sum(highest_scores) / len(highest_scores),
        "max_highest": max(highest_scores),
    }


def print_aggregate_table(rows):
    print(f"{'label':<28} {'Hit@5':>8} {'Recall@5':>10} {'MRR':>8}")
    for r in rows:
        print(f"{r['label']:<28} {r['hit_at_k']*100:7.1f}% {r['recall_at_k']*100:9.1f}% {r['mrr']:8.3f}")
    print()


def run_bare_vs_instructed(cases, detail):
    print("=== Bare vs. instructed query embedding (production ranking formula) ===\n")
    aggs = []
    for use_instruction, label in [(False, "bare"), (True, "instructed")]:
        candidates_by_query = fetch_candidates_for_cases(cases, use_instruction)
        agg, _ = evaluate_ranking(cases, candidates_by_query, rank_by_final_score, detail=detail, label=f"final-ranking ({label})")
        aggs.append(agg)
        agg_sem, _ = evaluate_ranking(cases, candidates_by_query, rank_by_semantic, detail=False, label=f"semantic-only ({label})")
        aggs.append(agg_sem)
    print_aggregate_table(aggs)

    for use_instruction, label in [(False, "bare"), (True, "instructed")]:
        neg = evaluate_negatives(cases, use_instruction, detail=detail, label=label)
        print(f"negative controls ({label}): mean_highest={neg['mean_highest']:.4f}  max_highest={neg['max_highest']:.4f}")
    print()


def run_signal_comparison(cases, detail):
    """Compares how much each ranking signal contributes in isolation and
    combination. Deliberately uses fixed weights declared here, NOT
    SEMANTIC_WEIGHT/RETRIEVABILITY_WEIGHT/FREQUENCY_WEIGHT from
    constants.py — those are production's *current* choice, which has
    changed before (RETRIEVABILITY_WEIGHT went from 0.15 to 0.00 — see
    evaluation/experiments/reranking-weight-decision.md) and could again.
    Pinning this comparison to whatever they happen to be right now would
    silently stop comparing the retrievability/frequency signals at all
    the moment either weight hit zero, without this function's code
    changing or its name saying so — which is exactly what happened here
    before this fix. The actual production ranking still gets its own
    honest, separately-labeled row via compute_final_score() directly."""
    print("=== Signal comparison (instructed queries, all variants share one frozen candidate set) ===\n")
    candidates_by_query = fetch_candidates_for_cases(cases, use_instruction=True)
    experimental_variants = [
        ("semantic only", 1.00, 0.00, 0.00),
        ("semantic + retrievability", 0.90, 0.10, 0.00),
        ("semantic + frequency", 0.90, 0.00, 0.10),
        ("semantic + retrievability + frequency", 0.80, 0.10, 0.10),
    ]
    aggs = []
    for name, w_sem, w_retr, w_freq in experimental_variants:
        label = f"{name} ({w_sem:.2f}/{w_retr:.2f}/{w_freq:.2f})"
        # Guards against this experimental combination coincidentally
        # matching whatever production's weights are right now — if it
        # ever does, say so instead of silently printing what would look
        # like an unlabeled duplicate of the production row below.
        if (w_sem, w_retr, w_freq) == (SEMANTIC_WEIGHT, RETRIEVABILITY_WEIGHT, FREQUENCY_WEIGHT):
            label += " — matches current production weights"
        rank_fn = lambda c, ws=w_sem, wr=w_retr, wf=w_freq: rank_by_weights(c, ws, wr, wf)
        agg, _ = evaluate_ranking(cases, candidates_by_query, rank_fn, detail=detail, label=label)
        aggs.append(agg)
    production_label = f"production, current constants ({SEMANTIC_WEIGHT:.2f}/{RETRIEVABILITY_WEIGHT:.2f}/{FREQUENCY_WEIGHT:.2f})"
    agg, _ = evaluate_ranking(cases, candidates_by_query, rank_by_final_score, detail=detail, label=production_label)
    aggs.append(agg)
    print_aggregate_table(aggs)


def run_weight_grid(cases, detail):
    print("=== Focused weight grid — round 2 (instructed queries, all variants share one frozen candidate set) ===\n")
    print("Predeclared before running, not chosen after seeing results. Round 1 (a coarser 7-point sweep,")
    print("preserved unchanged in evaluation/experiments/ as evidence that 0.15 retrievability fails under")
    print("today's reinforcement skew) established that damage is steep and front-loaded, not gradual. This")
    print("round brackets the low end specifically: does a small nonzero retrievability signal (0.01-0.02)")
    print("survive mostly intact, or does even that much already cost meaningful recall? All weight triples")
    print("sum to 1.0 for interpretability — ranking only depends on ratios, so this isn't mathematically")
    print("required, but it keeps 'sem=0.90' meaning a literal 90% share rather than a ratio among a")
    print("differently-scaled total.\n")
    print("Decision rule (stated in advance): if 0.01-0.02 retains nearly all semantic recall while still")
    print("producing meaningful, sensible rank movement in --detail, keep a small retrievability signal.")
    print("If even 0.01 causes meaningful relevance loss, 0.90/0.00/0.10 is the better prototype choice —")
    print("decay would then govern pruning but not retrieval ranking, stated honestly as a real scope")
    print("limitation, not hidden.\n")
    print("Exploratory only: scored against the same 23-query fixture used everywhere else in this harness —")
    print("picking a 'winning' combination here is evidence for this dataset's current, reinforcement-skewed")
    print("state, not proof the combination generalizes universally. See README.md.\n")
    candidates_by_query = fetch_candidates_for_cases(cases, use_instruction=True)
    grid = [
        (1.00, 0.00, 0.00),
        (0.95, 0.00, 0.05),
        (0.90, 0.00, 0.10),
        (0.89, 0.01, 0.10),
        (0.88, 0.02, 0.10),
        (0.87, 0.03, 0.10),
        (0.85, 0.05, 0.10),
    ]
    aggs = []
    for w_sem, w_retr, w_freq in grid:
        label = f"sem={w_sem:.2f} retr={w_retr:.2f} freq={w_freq:.2f}"
        is_production_weights = (w_sem, w_retr, w_freq) == (SEMANTIC_WEIGHT, RETRIEVABILITY_WEIGHT, FREQUENCY_WEIGHT)
        # Use the real compute_final_score() for the production point in the
        # grid specifically, same reasoning as rank_by_final_score() — every
        # other grid point is genuinely experimental and has no production
        # function to call, so those still go through weighted_score().
        rank_fn = rank_by_final_score if is_production_weights else (lambda c, ws=w_sem, wr=w_retr, wf=w_freq: rank_by_weights(c, ws, wr, wf))
        if is_production_weights:
            label += " (production)"
        agg, _ = evaluate_ranking(cases, candidates_by_query, rank_fn, detail=detail, label=label)
        aggs.append(agg)
    print_aggregate_table(aggs)


def validate_fixture(cases):
    """Fatal validation (exits nonzero on any failure), not a warning — a
    decision-making harness that silently proceeds on a stale or malformed
    fixture can make a data problem look like a ranking regression instead
    of what it actually is."""
    errors = []

    positives = cases.get("positive_cases", [])
    negatives = cases.get("negative_cases", [])
    if not positives:
        errors.append("no positive_cases in fixture")
    if not negatives:
        errors.append("no negative_cases in fixture")

    for i, case in enumerate(positives):
        query = case.get("query", "")
        if not query.strip():
            errors.append(f"positive_cases[{i}]: empty query string")
        labels = case.get("relevant_memory_texts", [])
        if not labels:
            errors.append(f"positive_cases[{i}] ({query!r}): no relevant_memory_texts")
        if len(labels) != len(set(labels)):
            errors.append(f"positive_cases[{i}] ({query!r}): duplicate label within this case")

    for i, case in enumerate(negatives):
        if not case.get("query", "").strip():
            errors.append(f"negative_cases[{i}]: empty query string")

    # Every labeled memory text must actually exist right now — a stale
    # label (renamed/deleted memory, wrong text, DB reseeded since the
    # fixture was written) would otherwise silently understate Hit/Recall
    # for that query instead of surfacing as the data problem it is.
    id_map = text_to_id_map()
    missing = set()
    for case in positives:
        for t in case.get("relevant_memory_texts", []):
            if t not in id_map:
                missing.add(t)
    if missing:
        errors.append(f"{len(missing)} labeled memory text(s) not found in the live database: {sorted(missing)}")

    if errors:
        print("FATAL: fixture validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bare-vs-instructed", action="store_true", help="compare RETRIEVAL_QUERY_INSTRUCTION on/off")
    parser.add_argument("--signal-comparison", action="store_true", help="semantic-only / +retrievability / +frequency / +both, using fixed experimental weights, plus production as its own labeled row")
    parser.add_argument("--weight-grid", action="store_true", help="coarse grid search over ranking weights")
    parser.add_argument("--detail", action="store_true", help="print per-query results, not just aggregates")
    parser.add_argument("--all", action="store_true", help="run every mode")
    args = parser.parse_args()

    if not any([args.bare_vs_instructed, args.signal_comparison, args.weight_grid, args.all]):
        args.bare_vs_instructed = True  # default: cheapest, most commonly-needed mode

    cases = load_cases()
    validate_fixture(cases)  # fatal on any problem — see docstring

    if args.bare_vs_instructed or args.all:
        run_bare_vs_instructed(cases, args.detail)
    if args.signal_comparison or args.all:
        run_signal_comparison(cases, args.detail)
    if args.weight_grid or args.all:
        run_weight_grid(cases, args.detail)


if __name__ == "__main__":
    main()
