"""
Reproduces the analysis behind MIN_RETRIEVABILITY = 0.01 (constants.py).

Two parts:
1. A table of expected deletion ages across representative stability/impact/
   reinforcement combinations, at a few candidate threshold values.
2. A check against the live dev database: for each candidate threshold,
   what fraction of memories currently in Postgres would already be
   eligible for deletion, and how that compares to the old (impact-divided)
   formula on the same data.

Dev-only, read-only (never calls delete_memories) — safe to run anytime
against the dev stack. The backend container only mounts ./backend (not
the repo root), so this can't run in place — copy it in, then exec it,
same as scripts.md documents:

    docker cp scripts/forgetting_threshold_analysis.py \\
        <backend-container>:/app/forgetting_threshold_analysis.py
    docker compose -f docker-compose-dev.yml exec backend \\
        python3 /app/forgetting_threshold_analysis.py

BASE_STABILITY/REINFORCEMENT_MULTIPLIER/MAX_STABILITY/MIN_RETRIEVABILITY
are imported from constants.py rather than hardcoded here, specifically
so this stays reproducible: if any of those change, this analysis
reflects the new values automatically instead of silently evaluating a
stale model.
"""

import sys

sys.path.insert(0, "/app")

from database import get_pg_conn
from formulas import compute_age_days, compute_retrievability
from constants import BASE_STABILITY, REINFORCEMENT_MULTIPLIER, MAX_STABILITY, MIN_RETRIEVABILITY

# Historical candidates from the MIN_RETRIEVABILITY decision (see
# techDebt.md/architecture.md), plus whatever the current production value
# actually is — deduplicated and sorted so the current value always shows
# up and gets labeled below, even if it's later changed to something
# outside this historical set.
CANDIDATE_THRESHOLDS = sorted({0.05, 0.03, 0.02, 0.015, MIN_RETRIEVABILITY}, reverse=True)


def deletion_age_days(stability: float, threshold: float) -> float:
    """Solve (1 + age/stability)^-0.5 < threshold for age."""
    return stability * (1 / threshold**2 - 1)


def print_lifetime_table():
    print("=== Expected deletion ages (never-reinforced unless noted) ===")
    for threshold in CANDIDATE_THRESHOLDS:
        current = " (current production MIN_RETRIEVABILITY)" if threshold == MIN_RETRIEVABILITY else ""
        print(f"\n--- threshold = {threshold}{current} ---")
        print(f"{'impact':>7} {'reinforcements':>15} {'stability':>10} {'deletion age (days)':>20} {'~time':>10}")
        for impact in (0.5, 1.0, 2.0):
            for n in (0, 1, 3, 5, 10):
                stability = min(BASE_STABILITY * impact * (REINFORCEMENT_MULTIPLIER**n), MAX_STABILITY)
                age = deletion_age_days(stability, threshold)
                years = age / 365.25
                label = f"{years:.2f} yr" if years >= 1 else f"{age:.0f} d"
                print(f"{impact:>7.1f} {n:>15} {stability:>10.3f} {age:>20.1f} {label:>10}")


def print_live_data_check():
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, stability, impact, use_count, last_reinforced_at FROM memories")
        rows = cur.fetchall()
    finally:
        conn.close()

    data = []
    for _id, stability, impact, use_count, last_reinforced_at in rows:
        try:
            age_days = compute_age_days(last_reinforced_at)
            retrievability = compute_retrievability(stability, age_days)
        except ValueError:
            continue
        data.append((retrievability, stability, impact, use_count))

    total = len(data)
    print(f"\n=== Live dev database: {total} memories ===")
    if total == 0:
        print("0 memories; live eligibility check skipped.")
        return
    print(f"{'threshold':>10} {'flat model':>18} {'old (÷impact) model':>22}")
    for threshold in CANDIDATE_THRESHOLDS:
        flat_eligible = sum(1 for r, s, i, u in data if r < threshold)
        old_eligible = sum(1 for r, s, i, u in data if r < threshold / i)
        current = "  <- current production" if threshold == MIN_RETRIEVABILITY else ""
        print(
            f"{threshold:>10} {flat_eligible:>10}/{total} ({100*flat_eligible/total:4.0f}%) "
            f"{old_eligible:>10}/{total} ({100*old_eligible/total:4.0f}%){current}"
        )


if __name__ == "__main__":
    print_lifetime_table()
    print_live_data_check()
