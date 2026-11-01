# ADR 0002: Retune the confidence decision (agreement depth, common-word OR matches, zero-BM25 floor)

Status: **proposed, BLOCKED**. 2026-10-31. Task 99-WW-RETUNE-ADR, step 1 of the CTO's confidence/abstain retune. This ADR and its pre-registration (`reports/W5-CONFIDENCE-RETUNE-PREREG.md`) are docs only: no code, label, fit or question is added by this PR.

**BLOCKER.** The retune needs a dev set of fresh labelled questions. Who writes them depends on Patrick's pending A/B/C author choice in `reports/W4-FRESH-BLIND-PREREG.md` §1. The author is **PENDING PATRICK**. Until Patrick ticks an option, no question is written, no code is changed and nothing in this ADR ships. If Patrick picks C (skip), the retune does not happen and the current rule stays.

Line numbers below hold on this PR's base tree (`git merge-base HEAD origin/main`). The two W5 reports are not on main; their line numbers hold at the head of their PR branches (`qa/w5-search-failure-probe`, PR #89; `qa/w5-demo-query-spotcheck`, PR #90).

## Context

The confidence level (`strong` / `weak` / `none` / `unrated`) comes from two signals in `src/preached/abstain.py`:

- **Agreement** (`compute_signals`, `src/preached/abstain.py:112-136`): some shown hit is in both the BM25 list and the dense list, each taken at `CANDIDATES` = 100 (`src/preached/abstain.py:60`, used at `:126` and `:129`; the test is `:135`).
- **Dense floor** (`decide`, `src/preached/abstain.py:153-168`): the top dense cosine against the floor in `search/abstain.toml` (Granite English R2: 0.8129, `search/abstain.toml:24` and `:34`), fitted by `fit_floor` (`src/preached/abstain.py:176-195`).

The BM25 query shape comes from `src/preached/fts.py`: a question with more than 4 content terms is ORed, 4 or fewer are ANDed (`src/preached/fts.py:151`); stopwords are removed first (`content_terms`, `src/preached/fts.py:132-140`); a `Book ch:v` reference uses `scripture_match` instead (`src/preached/fts.py:110-129`).

Two report-only probes found three failure modes. They are **regression illustrations only** (see "Evidence status"):

1. **OR queries make agreement nearly free.** An OR query fills its BM25 list to 100 rows, so a shared row in two 100-deep lists is almost automatic. Out-of-domain questions then get `weak` instead of `none`: the cookie recipe and Super Bowl queries in both probes (`reports/W5-SEARCH-FAILURE-PROBE.md:10`, `:218-232`; `reports/W5-DEMO-QUERY-SPOTCHECK.md:223`), and on-topic queries with bad results get `strong` (c3 and e6, `reports/W5-SEARCH-FAILURE-PROBE.md:10`).
2. **The agreement matches are made of common words** ("good", "year", "last", "won"), not of the question's distinctive words (`reports/W5-SEARCH-FAILURE-PROBE.md:224`, `:232`). Stopword removal is not the cause; stopwords are already dropped (`reports/W5-DEMO-QUERY-SPOTCHECK.md:223`).
3. **Zero BM25 rows caps the level at `weak`.** With no BM25 row there is no agreement, so a question is at best `weak` however high its cosine (`src/preached/abstain.py:162-165`). 11 of the 30 probe queries had 0 BM25 rows (`reports/W5-SEARCH-FAILURE-PROBE.md:9`), and the spot check graded three such `weak` banners as under-confident (`reports/W5-DEMO-QUERY-SPOTCHECK.md:25-26`, `:30`).

The probe's own recommendations 4 and 5 (`reports/W5-SEARCH-FAILURE-PROBE.md:345-346`) propose this direction and say any refit needs a pre-registered dev set disjoint from the frozen eval and from the probe queries.

## Decision (CTO's final scope)

**Change ONLY the confidence decision:** `compute_signals` and `decide` in `src/preached/abstain.py`, plus the floor in `search/abstain.toml`. Three changes, together, as one candidate rule:

1. **Shallow agreement depth.** Agreement is computed at a shallow pre-registered depth instead of 100. The depth is fixed at **20** in the pre-registration (§3.1) and is not tuned. `bm25_hits` stays the count at `CANDIDATES` (it is a reported signal, not part of the change).
2. **OR-mode agreement ignores common-word-only matches.** When the query is OR-shaped (`scripture_match(query) is None and len(content_terms(query)) > 4`, the same OR-shape rule as `reports/W4-FRESH-BLIND-PREREG.md` §3), a BM25 row counts toward agreement only if it contains at least one query content term that is **not** on the common-word list. The list is fixed **from document frequency** over the published Wesley chunks by a rule written in the pre-registration (§3.2). It is **not hand-picked**: no word is added or removed by hand.
3. **Zero-BM25 queries get their own cosine floor.** A query with 0 BM25 rows is decided by its top dense cosine against a separate floor, fitted on the dev split, instead of being capped at `weak` (§3.3). No new level: the result is still one of `strong`, `weak` or `none`.

The dense floor and the new zero-BM25 floor are fitted on the **dev split only**, by the rules fixed in the pre-registration. The frozen eval is a guard, never a fitting set.

### Out of scope

- **The AND→OR fallback** in `src/preached/fts.py` (probe recommendation 1). A later, separate task with its own review.
- **Quote boost** (probe recommendation 3).
- **New API levels** or a new level name (probe recommendation 5's "separate wording or level"). The level set stays `strong` / `weak` / `none` / `unrated`, and the note texts (`src/preached/abstain.py:70-74`) are unchanged.
- **Fusion weights and ranking.** `w = 1.0` stays (the `w = 0.5` HOLD, `reports/W3-CONFIRMATORY.md`); RRF, `rrf_k`, candidates, dedupe and `src/preached/rank.py` / `src/preached/search.py` are not touched. Because ranking is untouched, every result list is identical before and after; only the confidence fields may differ.
- `church_confidence` (`src/preached/abstain.py:139-150`): church libraries stay `unrated`.

## Pre-registration (summary; binding text in `reports/W5-CONFIDENCE-RETUNE-PREREG.md`)

- **Dev set:** NEW questions, disjoint from the frozen eval (`eval/questions.jsonl`, 93 questions), from the 41 PR #89 probe queries (30 plus 11 controls) and from the 25 PR #90 spot-check queries. The 41 and the 25 serve **only as regression illustrations**: no parameter, floor, list or threshold is read off them.
- **Author:** PENDING PATRICK, using the A/B/C definitions and exposure rules of `reports/W4-FRESH-BLIND-PREREG.md` §1, not new ones.
- **Label provenance disclosure:** who wrote each question, who graded it, whether author = grader, and that this design was drafted by an LLM agent (Claude) after reading the probe results.
- **Primary metrics** with exact formulas and decision thresholds: the false-abstain rate on answerable questions, the abstain rate on out-of-domain questions, and the share of `strong` banners on a bad top 3.
- **Held-out confirmation split**, assigned by a fixed seed before any retrieval and **scored once**.

## Guards (all must hold, or the retune does not ship)

1. **Frozen eval does not regress:** hit@10 on `eval/questions.jsonl` is unchanged (it must be identical, since ranking is untouched), and its abstain numbers (false-abstain rate on answerable, abstain recall on unanswerable) do not get worse.
2. **Response parity:** every `/api/search` response, with the confidence fields stripped (`abstain`, `confidence`, and the timing field `took_ms`), is byte-identical before and after.
3. **Fusion `w = 1.0`, no LLM, no PRC models** hold (AGENTS.md): no change to ranking code, models, dependencies or `uv.lock`.
4. **The citable W3 sentence is untouched** in `README.md`, `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md` and `reports/W3-CONFIRMATORY.md`. No accuracy, "improves" or "better" claim is made from this retune unless the pre-registration's claim rule allows it, and then only after CTO review.

## Evidence status

The PR #89 and #90 reports are one LLM reader's judgments on non-blind, hand-written queries (`reports/W5-SEARCH-FAILURE-PROBE.md`, "Method, limits and disclosure"; `reports/W5-DEMO-QUERY-SPOTCHECK.md:9`). They show the failure modes exist. They do not measure rates and they are not evidence that this candidate fixes anything. They are re-run before and after as illustrations and reported, but they gate nothing.

## Consequences

- If the candidate passes, `abstain.py` and `search/abstain.toml` change in one code PR; the module docstring (`src/preached/abstain.py:1-44`) is updated to describe the new rule and its dev-set provenance.
- If it fails any primary threshold or guard, the current rule stays and the result is reported as it is. No second candidate is tried on the same confirmation split.
- `search/abstain.toml` gains the zero-BM25 floor and the common-word list with their provenance (the open point O1 in the pre-registration covers the loader change this needs).
- Nothing here touches `app/server.py` or any file cited in `docs/DEPLOY.md`.

## Steps

1. This ADR and the pre-registration are reviewed by the CTO and merged.
2. Patrick ticks the author option. **(BLOCKED here.)**
3. Questions written, frozen and split (freeze PR); pool, blind sheet and labels (pre-registration §§4-5).
4. Code PR: the candidate rule, the DF list generator, the floor fits on the dev split, the scoring script and the guard tests. Reviewed before the confirmation split is scored.
5. Confirmation split scored once; report reviewed by the CTO before anything ships or is claimed.
