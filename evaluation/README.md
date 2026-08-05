# Retrieval Evaluation

A read-only harness for measuring retrieval/ranking quality against the live dev Qdrant/Postgres data, instead of relying on one-off manual spot checks. Built as the shared foundation for two things: validating the Qwen query-instruction change, and (going forward) evaluating re-ranking weight changes on the same labeled benchmark instead of inventing a new ad-hoc test each time.

## Running it

Requires the dev environment already running (see `../DEVELOPMENT.md`) and the same Python dependencies as `backend/` (it imports directly from there — `sentence-transformers`, `qdrant-client`, `psycopg2`, etc.), so it needs to run inside the backend container, not on the host. The container only mounts `./backend`, not the repo root, so this directory isn't reachable at a fixed in-container path by default. From the repo root:

```bash
CID=$(docker compose -f docker-compose-dev.yml ps -q backend)
docker exec "$CID" mkdir -p /evalroot
docker exec "$CID" ln -sf /app /evalroot/backend      # only needed once per container lifetime
docker cp evaluation "$CID":/evalroot/evaluation       # re-run this line after editing the script/fixture
docker exec "$CID" python3 /evalroot/evaluation/evaluate_retrieval.py [flags]
```

The symlink makes `/evalroot/backend` resolve the same way `evaluation/`'s real sibling `backend/` does on the host, so the script's own `Path(__file__).resolve().parent.parent / "backend"` import logic works unmodified inside the container. If this ends up getting run often enough that this is annoying, the cleaner long-term fix would be a permanent read-only volume mount for `./evaluation` in `docker-compose-dev.yml` — not done here, since this is a one-off dev tool, not something that needed a runtime config change to build.

Flags:
- `--bare-vs-instructed` — compares `RETRIEVAL_QUERY_INSTRUCTION` on vs. off, at both the semantic-only and full production-formula ranking level, plus negative-control score separation. Default mode if no flags are given.
- `--signal-comparison` — semantic-only / semantic+retrievability / semantic+frequency / semantic+retrievability+frequency, each at fixed experimental weights declared in the script (deliberately not `constants.py`'s current prototype weights — see `run_signal_comparison`'s docstring for why: pinning this to the deployed defaults would silently stop comparing a signal the moment its weight hit `0.0`, which is exactly what happened to the retrievability variant before this was fixed), plus the prototype's actual weights as a separately labeled row via `compute_final_score()`. Isolates which signal helps or hurts, at a weight actually large enough to show an effect.
- `--weight-grid` — a small, coarse grid of `(semantic, retrievability, frequency)` weight combinations, not an exhaustive search. Useful for a quick "is the current split even in a reasonable neighborhood" sanity check, not for finding an optimal weighting.
- `--detail` — print per-query results (which memories ranked top-5, hit/recall/reciprocal-rank for that query) instead of just the aggregate table.
- `--all` — run every mode in one pass.

## What it does NOT do

- **Never calls `search_memories()` or `/memories/search`.** It re-implements the same read-only steps directly (`qdrant.query_points`, `get_memories_metadata`), skipping the one side-effecting step (`increment_retrieval_counts()`) entirely — running this repeatedly cannot change `retrieval_count` or anything else in the database.
- **Never writes anything.** No memory creation, no reinforcement, no deletion. Pure reads.
- **Never changes runtime ranking weights.** `SEMANTIC_WEIGHT`/`RETRIEVABILITY_WEIGHT`/`FREQUENCY_WEIGHT` are read from `constants.py`, never modified — the weight-grid mode only affects *this script's own* ranking calculations, not the live app.

## Why it reuses production code instead of reimplementing the math

`normalize_qdrant_similarity`, `compute_retrievability`, `compute_frequency`, `RETRIEVAL_QUERY_INSTRUCTION`, and the actual weight constants are all imported directly from `backend/formulas.py` and `backend/constants.py`. Importantly, so is `compute_final_score()` itself — the "production" ranking variant in every comparison mode (`rank_by_final_score()`) calls it directly rather than reimplementing its formula, so if `compute_final_score()` ever becomes more than a weighted sum (clamping, interactions, normalization), the production baseline here changes with it automatically instead of silently diverging. The only reimplemented piece is `weighted_score()`, a parameterized weighted sum used exclusively for signal-comparison/weight-grid *experimental* variants, which need custom weight combinations `compute_final_score()` has no way to accept — it's never used for the production baseline itself.

## Fixture (`retrieval_cases.json`) — currently stale, do not trust results until rebuilt

**As of the 1,000-memory seed dataset rewrite, this fixture no longer matches `scripts/seed_data.json` at all.** All 86 unique `relevant_memory_texts` across its 23 positive cases were written against the former ~181-memory corpus (different fictional content entirely — e.g. `"Met my girlfriend Madeline playing Toontown"`, a surgery/medical-bill storyline) and none of them exist in the current seed data. `validate_fixture()` will fail fatally against a freshly reseeded dev DB (see below) until the fixture itself is rebuilt against the current dataset. Tracked in `techDebt.md` — not fixed here.

23 positive cases (a query plus the exact text of every memory that genuinely answers it) and 4 negative controls (queries with no genuine answer anywhere in this dataset — gibberish, or topics unrelated to anyone's personal life). Labels are stored as **exact memory text**, not UUIDs — ids are regenerated on every reseed, but the seeded text content is normally stable across an ordinary reseed of the *same* `seed_data.json`, so the fixture is designed to survive a `clear.sh` + reseed without needing to be hand-updated. That design assumption doesn't hold when `seed_data.json`'s actual content is replaced wholesale, as it was here — the fixture needs rebuilding whenever the canonical dataset itself changes, not just reseeded. The script resolves text to whatever id it currently has via a fresh Postgres lookup on every run.

Validation is **fatal**, not a warning: `validate_fixture()` exits with status 1, before running any evaluation, if any labeled memory text can't be found in the live database, if any positive case has no relevant-memory labels or a duplicate label within itself, if either case list is empty, or if any query string is empty. A silent warning-and-continue would let a stale or incomplete fixture look like a ranking regression instead of what it actually is — a data problem. Re-check the fixture or re-seed the dev DB if this fires.

This fixture was constructed fresh for this evaluation harness — it is not a byte-for-byte reproduction of whatever query set an earlier review session used (that raw data wasn't available to build from), but it covers comparable topics/breadth across the same seeded dataset (relationships, work history, pets, sports, childhood, college, side projects, financial stress), including the specific categories mentioned in that earlier report (surgery, Eleutheria, this project itself, Cadooga, William, Bailey's death, money stress, weightlifting, degree).

## Metric definitions

All metrics are evaluated at **K=5**, matching `/generate`'s default `limit`.

- **Hit@5** — did *at least one* genuinely relevant memory land in the top 5? Binary per query (1 or 0), averaged across all positive queries into a percentage.
- **Recall@5** — of *all* the memories genuinely relevant to this query, what fraction made it into the top 5? Per query: `(relevant memories in top 5) / (total relevant memories for this query)`. Macro-averaged across queries (each query weighted equally, regardless of how many relevant memories it has).
- **MRR (Mean Reciprocal Rank)** — how high does the *first* relevant memory rank, across the full retrieved candidate pool (not capped at 5)? Per query: `1 / (rank of the first relevant memory found)` — e.g. `1/3` if the first genuine match is 3rd. Macro-averaged. Higher is better; a query where the best match is always #1 scores `1.0`.
- **Negative-control scores** — for queries with no genuine answer, the highest semantic similarity any real memory reaches. Reported as the mean and max across all 4 negative queries. Lower is better here — it means real content isn't leaking toward looking relevant for a query it doesn't actually answer.

Recall@5 and MRR are measuring different things and can disagree: MRR cares only about whether the *single best* match is ranked first; Recall@5 cares about how much of the *full relevant set* survives into the top 5. A query with 5+ genuinely relevant memories can have perfect MRR (the best one is #1) while still having mediocre Recall@5 (the other 4 didn't make the cut) — both numbers are reported because either one alone would miss part of the picture.

## What was established about re-ranking vs. semantic search under the *former* production weights (0.75/0.15/0.10) — historical, not current status

**This section describes the investigation that led to the reranking-weight decision — it is not a benchmark of the current 1,000-memory corpus.** Current prototype weights are `SEMANTIC_WEIGHT=0.95`/`RETRIEVABILITY_WEIGHT=0.00`/`FREQUENCY_WEIGHT=0.05` (`constants.py`), adopted because they fixed the measured regressions on the former corpus. See "Adopted prototype weights" below; the rest of this section is preserved as decision history.

Running this harness against the dev database at the time (after a full session's worth of manual testing, which repeatedly reinforced a narrow subset of memories — mostly Madeline/surgery/work-raise-related, via dozens of live `/generate` calls), **under the then-production weights of `0.75/0.15/0.10`**, produced final-ranking numbers well below the semantic-only numbers, in that same run, on the exact same frozen candidate set per query. That comparison was controlled — same fixture, same database snapshot-in-time, same queries, only the ranking strategy differed — so the conclusion **"final ranking under those weights performed worse than semantic-only search on this database"** was directly supported by the data, not inferred.

What was also directly confirmed, not inferred, under those former weights: inspecting the actual top-5 for a query like "tell me about weightlifting" showed heavily-reinforced Madeline/surgery memories (`retrievability≈0.998`, `frequency≈0.75`) with zero topical connection to weightlifting displacing the genuinely relevant, never-manually-reinforced weightlifting memories out of the top 5 entirely. And the signal-comparison mode, also controlled (same frozen candidates, only the weighting differs), showed `semantic + retrievability` alone dropping Recall@5 much further than `semantic + frequency` alone — implicating `retrievability` as the larger contributor of the two, on this dataset, in its state at the time.

### Adopted prototype weights — historical evaluation

**These numbers predate the 1,000-memory seed dataset rewrite and the fixture staleness noted above — they describe the former ~181-memory corpus, not the current one, and haven't been re-measured since.** Treat the table below as historical evidence for why `0.95/0.00/0.05` was chosen over the former weights, not as a current-state guarantee about the live dataset. Re-running this harness against the current corpus requires rebuilding the fixture first (see above).

Adopted weights (`0.95/0.00/0.05`) were re-measured against the same corrected fixture and frozen candidate set as the former production weights, for a genuine apples-to-apples comparison — full record in `evaluation/experiments/reranking-weight-decision.md`:

| | Hit@5 | Recall@5 | MRR |
|---|---|---|---|
| Former production (0.75/0.15/0.10) | 39.1% | 22.1% | 0.341 |
| Semantic-only (1.00/0.00/0.00) | 100.0% | 82.0% | 0.978 |
| **Adopted prototype weights (0.95/0.00/0.05)** | **100.0%** | **82.0%** | **1.000** |

On the historical 181-memory evaluation, the adopted prototype ranking tied semantic-only on Recall@5 and beat it on MRR; unlike the former weights, it did not perform worse than semantic-only search on that snapshot. The MVP-not-neuroscientifically-derived caveat still applies (see `reranking-weight-decision.md`'s Limitations section and `techDebt.md`'s corresponding entry), and the stale fixture means this is not a current-corpus result.

**What is not established, and shouldn't be claimed**: an earlier evaluation (different query fixture, run against the database at an earlier, less-skewed reinforcement state) reported a considerably higher final-ranking Recall@5 than this harness currently measures. It's tempting to attribute that entire numerical gap to reinforcement accumulating in the meantime — but two things changed between that evaluation and this one: the database's reinforcement state, *and* the query/label fixture itself. With two variables changed at once, the size of the gap can't be attributed to either one alone. Treat the direction (more skew plausibly means worse final-ranking) as a reasonable hypothesis consistent with the controlled evidence above — not as a precisely-quantified before/after measurement, which this comparison isn't.

This does mean **final-ranking results are not stable over time on a live, actively-used database** — the same fixture run today versus after another month of organic usage could produce different final-ranking numbers, purely from reinforcement accumulating unevenly across topics. Semantic-only numbers don't have this problem (raw semantic similarity doesn't depend on `stability`/`use_count` at all). A genuinely controlled before/after comparison — e.g. for evaluating a ranking-weight change — needs either a frozen metadata snapshot evaluated identically both times, or a deterministic, reproducible seed/backdate/reinforcement scenario, rather than comparing two runs against a live, continuously-changing database. Not yet built here — see the fixture's own limitations noted above.
