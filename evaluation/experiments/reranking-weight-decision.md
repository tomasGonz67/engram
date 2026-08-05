# Re-ranking Weight Decision Record

Authoritative record for the `SEMANTIC_WEIGHT`/`RETRIEVABILITY_WEIGHT`/`FREQUENCY_WEIGHT` change made in `backend/constants.py`. `architecture.md`, `security-preventions.md`, and `techDebt.md` summarize this and link back here — this file is the one place the full hypothesis, predeclared rule, results, and reasoning live, so the numbers can't drift across four separate documents telling slightly different versions of the same story.

## Status

**MVP decision, evidence-backed, not neuroscientifically optimal or universally validated.** Chosen from a hand-built 23-query fixture against one live database snapshot (this session's reinforcement-skewed dev data). Re-evaluate on a broader, frozen dataset before treating these as final — see `techDebt.md`'s corresponding entry.

**Also now stale in a second way**: that 23-query fixture (`evaluation/retrieval_cases.json`) was written against the former ~181-memory corpus. The seed dataset has since been fully rewritten to 980 memories with entirely different content, so none of this fixture's labels resolve against the current data — see `evaluation/README.md`'s Fixture section and `techDebt.md`. The results below remain valid evidence for *why* `0.95/0.00/0.05` beat the former weights on the corpus that existed at the time; they are not a current-state claim about the live 980-memory dataset.

## Hypothesis

Retrieval originally re-ranked candidates using `final_score = 0.75×semantic + 0.15×retrievability + 0.10×frequency`. An empirical evaluation (see round 1 below) showed this formula measurably displacing genuinely relevant memories out of the top 5 in favor of heavily-reinforced-but-irrelevant ones. Signal ablation implicated `retrievability` as the dominant driver of the damage, with `frequency` costing comparatively little. Hypothesis going into the focused round: some small, nonzero `retrievability` weight might retain most of the recall benefit of removing it while still contributing a meaningful "proven useful" signal — worth testing directly rather than assuming either "keep it as-is" or "remove it entirely" without evidence.

## Predeclared decision rule (stated before round 2 ran)

> If 0.01–0.02 retains nearly all semantic recall while producing meaningful, *desirable* rank changes (checked per-query, not just in aggregate), keep a small retrievability signal. If even 0.01 causes meaningful relevance loss, choose `0.90/0.00/0.10` and state honestly that decay/retrievability governs pruning but not retrieval ranking.

## Round 1 — coarse exploratory grid

Raw output: `reranking-weights-20260803-212801.txt` (uses the fixture *before* the audit fixes in round 2 — preserved unchanged as evidence, not updated).

Ablation (instructed queries):

| variant | Hit@5 | Recall@5 | MRR |
|---|---|---|---|
| semantic only | 100.0% | 81.0% | 0.891 |
| semantic + retrievability | 43.5% | 26.7% | 0.394 |
| semantic + frequency | 100.0% | 74.4% | 0.891 |
| production (0.75/0.15/0.10) | 39.1% | 23.0% | 0.340 |

`semantic + retrievability` alone caused far more damage than `semantic + frequency` alone — first evidence implicating `retrievability` specifically, not just "re-ranking in general."

7-point coarse weight grid (not predeclared, chosen after seeing the ablation) confirmed the damage is steep and front-loaded: recall dropped from 74.4% (`retr=0.00`) to 59.7% (`retr=0.05`) to 23.0% (`retr=0.15`, production) — most of the loss happens early, not gradually across the full range.

## Fixture audit, between rounds

Before round 2, the known missing "weightlifting" label was fixed, and all 22 other positive cases were audited against their top-10 semantic candidates for other obviously-missing labels. Found and fixed real gaps in 9 of 23 cases — mostly paraphrased/duplicate seed memories the original fixture only partially caught (e.g. two separate memories both describing finishing last at the first cross country practice). Re-audited after fixing; no further obvious gaps remained. This changed the fixture's absolute numbers between rounds (more complete ground truth), which is why round 1 and round 2 numbers for the same weights aren't identical — see the controlled comparison below for a number that isolates the weight change specifically.

## Round 2 — focused, predeclared grid (post-fixture-audit)

Raw output: `reranking-weights-round2-focused-20260803-214347.txt`. All 7 points predeclared before running, weights sum to 1.0 for interpretability, all variants share one frozen candidate set per query (fetched once, reused across every ranking variant — no re-embedding or re-querying between comparisons).

| semantic | retrievability | frequency | Hit@5 | Recall@5 | MRR |
|---|---|---|---|---|---|
| 1.00 | 0.00 | 0.00 | 100.0% | 82.0% | 0.978 |
| 0.95 | 0.00 | 0.05 | 100.0% | **82.0%** | **1.000** |
| 0.90 | 0.00 | 0.10 | 100.0% | 75.2% | 0.949 |
| 0.89 | 0.01 | 0.10 | 100.0% | 74.7% | 0.938 |
| 0.88 | 0.02 | 0.10 | 100.0% | 74.7% | 0.906 |
| 0.87 | 0.03 | 0.10 | 100.0% | 68.3% | 0.849 |
| 0.85 | 0.05 | 0.10 | 95.7% | 63.5% | 0.788 |

`0.95/0.00/0.05` is the strongest point tested — both highest Recall@5 (tied with pure semantic) and highest MRR of anything in the grid, including pure semantic alone.

### Per-query check (not just aggregate) — did any query actually benefit from a small retrievability weight?

Systematically compared every one of the 23 queries between `retr=0.00`, `retr=0.01`, and `retr=0.02` (holding `frequency=0.10` fixed, matching the grid's own held-frequency design):

- **0.00 → 0.01**: 3 of 23 queries got measurably worse (Eleutheria, running times, dog Chloe). 0 improved.
- **0.00 → 0.02**: 4 of 23 queries got measurably worse (the same 3, plus "tell me about college"). 0 improved.

Concrete example: "was I ever stressed about money?" — at `retr=0.00`/`0.01`/`0.02`, the correct answer ("Lay awake at night stressed about money") ranks #1. At `retr=0.03`, it's demoted to rank 4, behind three heavily-reinforced but topically unrelated Madeline/surgery memories — `rr` drops from `1.00` to `0.25`. Not a neutral reshuffle; a real quality regression, and a case outside the systematic 0.00-vs-0.02 comparison above that shows the damage continuing past that range too.

**No query, at any tested nonzero retrievability weight, showed an improvement.** This directly answers the predeclared rule's second branch: even 0.01 causes measurable, real relevance loss, with nothing anywhere offsetting it.

## Controlled production-vs-MVP comparison

Both numbers below use the *same*, corrected, post-audit fixture and the same frozen candidate set — genuinely apples-to-apples, unlike comparing round 1 to round 2 directly:

| | Hit@5 | Recall@5 | MRR |
|---|---|---|---|
| Production (0.75/0.15/0.10) | 39.1% | 22.1% | 0.341 |
| MVP (0.95/0.00/0.05) | 100.0% | 82.0% | 1.000 |

(Note: production's number here, 22.1%, is nearly identical to round 1's 23.0% measured on the pre-audit fixture — confirming the fixture corrections didn't materially change how production weights perform, even though the exact figure differs slightly.)

## Decision

**Adopted `SEMANTIC_WEIGHT=0.95`, `RETRIEVABILITY_WEIGHT=0.00`, `FREQUENCY_WEIGHT=0.05`** — the strongest point in the predeclared, focused grid, and the only one with zero measured query regressions anywhere in the per-query check.

`retrievability` is removed from ranking, not from the system — it continues to govern Consolidation's pruning threshold (`MIN_RETRIEVABILITY / impact`) unchanged. The separation is deliberate: decay/accessibility still shapes which memories eventually get pruned, it just no longer shapes which memories rank highest for a given query, since at this dataset's current reinforcement state, giving it that role actively hurt relevance with no measured benefit.

> **Correction (2026-08-03), appended — the sentence above is left unedited above as the historical record, but is no longer accurate.** Two later, separate decisions changed what it describes: (1) the pruning mechanism was renamed from "Consolidation" to "Decay-Based Forgetting" — that name was itself misleading, borrowed from a neuroscience term for memory *stabilization* to describe a feature that does the opposite (deletion); and (2) its threshold changed from `MIN_RETRIEVABILITY / impact` to a flat `MIN_RETRIEVABILITY` — `impact` no longer divides into the deletion threshold, it only seeds initial `stability` at creation. `retrievability` still governs that threshold exactly as this record's core finding describes (removed from ranking, not from the system) — only the threshold's own formula and name changed, not the ranking decision this file documents. See `techDebt.md`'s `MIN_RETRIEVABILITY` entry and `architecture.md`'s Decay-Based Forgetting section for the current, authoritative description of that separate decision.

## Limitations — read before treating this as final

- **23 hand-built queries, one person's dataset.** Not a large or independently-sourced benchmark. A different user's memories, a different reinforcement history, or more ambiguous/adversarial queries could show a different pattern.
- **One live database snapshot, not a frozen/reproducible one.** This dataset's current reinforcement skew (a session's worth of testing concentrated on a handful of memories) makes it a genuine stress test, but also means re-running this exact comparison next month, after more organic usage, could produce different numbers even with identical code — see `techDebt.md`'s snapshot-mode entry.
- **`frequency` at 0.05 isn't fully vindicated, just not measured as harmful here.** The same heavily-reinforced Madeline/surgery memories that dominated under high `retrievability` still intrude into some unrelated queries' top-5 results purely from `frequency`, even at `retrievability=0.00` — it just didn't move Recall@5/MRR enough on this fixture to register as a regression. Worth more scrutiny before assuming 0.05 is safe at a larger scale.
- **"Biologically inspired," not biologically validated.** This is an engineering decision made with real evidence, not a claim about how human memory retrieval actually works. Framing it as "MVP defaults, re-evaluate before production" throughout the docs is deliberate, not hedging.

> **Clarification (2026-08-04), appended, not a change to the finding above**: "re-evaluate before production" reads as if it blocks starting deployment/infra work, which was never the intent — it's about not treating these specific weight values as mature, validated-at-scale defaults, not a gate on infrastructure work that doesn't depend on them being final. Production deployment work began without a broader re-evaluation having happened first; that's consistent with this record, not a contradiction of it. What this still means: resolve the broader evaluation before *public launch* specifically (same category of open item as `prod.md`'s `ADMIN_BYPASS_TOKEN`/`ENVIRONMENT` — required before real users, not before starting to build). See `constants.py`'s `SEMANTIC_WEIGHT` comment and `techDebt.md`'s corresponding entry for the current framing.
