# Seed Dataset — Cast & Timeline

Reference doc for the 10,000-memory synthetic seed dataset (`seed_data.json`) —
the single source of truth for character names, relationships, and timeline
anchors, so consistency doesn't drift across many separate generation passes.
Check every new batch of memories against this file before adding them.

## Cast

| Role | Name |
|---|---|
| Protagonist | Masi |
| Brother | Lio |
| Sister | Chloe |
| Dad | William |
| Mom | April |
| Dog | Bugzy (puppy, ~1 year old — acquired ~2025) |
| Daughter (mother: Madeline, only child) | Bailey |
| Good friend (since childhood) | Tiger |
| Good friend (met at Sigma University, ~2004) | Cruz |
| Wife (girlfriend 2005–2010, married ~2010, still married now) | Madeline |
| Ex (high school girlfriend, 2002–2004) | Veronica |
| High school | Gigachad High School |
| College | Sigma University — major: Money Making, minor: Cryptocurrency. Took classes like Copywriting and Dropshipping. |
| Career | Professional Hustler — kept intentionally vague/generic in memory text ("closed a deal," "grinding," no concrete specifics). The Money Making major/hustle-adjacent coursework is the direct lead-in to this career, unlike the career itself, these college specifics (major/minor/class names) ARE fine to reference concretely in memory text. |
| Home | 67 Banana Lane, Warner, Ohio |

## Timeline anchors

Anchored to "now" = 2026. Masi born ~1986.

| Year | Age | Event |
|---|---|---|
| ~1990s | childhood | Becomes close friends with Tiger |
| ~2000 | 14 | Starts Gigachad High School |
| ~2002 | 16 | Starts dating Veronica |
| ~2004 | 18 | Breaks up with Veronica; graduates high school; starts Sigma University (Money Making major, Crypto minor); meets Cruz there |
| ~2005 | 19 | Meets Madeline (during college) |
| ~2008 | 22 | Graduates Sigma University |
| 2005–2010 | 19–24 | Dates Madeline (spans the last ~3 years of college and the first ~2 years after) |
| 2009-05-16 | 23 | Proposes to Madeline |
| 2010-03-14 | 24 | Marries Madeline |
| 2010-09-15 | 24 | Finds out Madeline is pregnant |
| 2011-05-11 | 24-25 | Bailey born (only child) — corrected from the original loose "~2010" estimate once the pregnancy timeline was checked for realism (conception ~Aug 2010, ~9 months to birth); this pushes Bailey's current age to 15, not 16 as first estimated |
| ~2025 | 39 | Gets Bugzy as a puppy |
| 2026 | 40 | Now — still married to Madeline, Bailey is 15 (turns 16 in May 2027), Bugzy is ~1, Tiger still a close friend |

Relationship status as of "now": **married to Madeline**, no breakup/reconciliation arc — treat "who is Masi's partner" as a stable fact across the whole dataset, not a contradiction-bucket case. Veronica is unambiguously in the past (high school only, ended 2004) — safe material for "ex"/history-themed memories, not current-state ones. Bailey is an only child — no siblings to invent.

## Resolved — no more open questions

Cast and timeline are locked. Ready to generate memories against this reference.
