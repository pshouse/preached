# ADR 0002: Retune the confidence decision (agreement depth, common-word OR matches, zero-BM25 floor)

Status: **proposed, BLOCKED**. 2026-10-31. Task 99-WW-RETUNE-ADR, step 1 of the CTO's confidence/abstain retune. This ADR and its pre-registration (`reports/W5-CONFIDENCE-RETUNE-PREREG.md`) are docs only: no code, label, fit or question is added by this PR. r2 addresses the CTO's r1 CONDITIONAL (MF1-MF6 and the should-fixes). The candidate's values (agreement depth 20, τ = 0.05, thresholds 0.10 / 0.80 / 0.15, ≥ 20 strong banners, minimum n 50 / 40, the ~200-question brief, seeds 520261031 / 520261032) were chosen after viewing the PR #89 and #90 probe results; those 66 probe queries are excluded from all fitting, choosing and scoring.

**Freeze.** These values freeze at this PR's merge commit. A change is allowed only through an amendment merged before any fresh question is written. The freeze PR records the pre-registration's sha256 and this PR's merge sha. A dev-check failure is terminal (pre-registration §6.5).

**BLOCKER.** The retune needs a dev set of fresh labelled questions. Who writes them depends on Patrick's pending A/B/C author choice in `reports/W4-FRESH-BLIND-PREREG.md` §1. The author is **PENDING PATRICK**. Until Patrick ticks an option, no question is written, no code is changed and nothing in this ADR ships. If Patrick picks C (skip), the retune does not happen and the current rule stays.

Line numbers below hold on this PR's base tree (`git merge-base HEAD origin/main`). The two W5 reports are not on main; their line numbers hold at the head of their PR branches (`qa/w5-search-failure-probe`, PR #89; `qa/w5-demo-query-spotcheck`, PR #90).

## Context

The confidence level (`strong` / `weak` / `none` / `unrated`) comes from two signals in `src/preached/abstain.py`:

- **Agreement** (`compute_signals`, `src/preached/abstain.py:112-136`): some shown hit is in both the BM25 list and the dense list, each taken at `CANDIDATES` = 100 (`src/preached/abstain.py:60`, used at `:126` and `:129`; the test is `:135`).
- **Dense floor** (`decide`, `src/preached/abstain.py:153-168`): the top dense cosine against the floor in `search/abstain.toml` (Granite English R2: 0.8129, `search/abstain.toml:24` and `:34`), fitted by `fit_floor` (`src/preached/abstain.py:176-195`).

The BM25 query shape comes from `src/preached/fts.py`: a question with more than 4 content terms is ORed, 4 or fewer are ANDed (`src/preached/fts.py:151`); stopwords are removed first (`content_terms`, `src/preached/fts.py:132-140`); a `Book ch:v` reference uses `scripture_match` instead (`src/preached/fts.py:110-129`).

Two report-only probes, on LLM-written queries, found three failure modes. They are **regression illustrations only** (see "Evidence status"):

1. **OR queries make agreement nearly free.** An OR query fills its BM25 list to 100 rows, so a shared row in two 100-deep lists is almost automatic. Out-of-domain questions then get `weak` instead of `none`: the cookie recipe and Super Bowl queries in both probes (`reports/W5-SEARCH-FAILURE-PROBE.md:10`, `:218-232`; `reports/W5-DEMO-QUERY-SPOTCHECK.md:223`), and on-topic queries with bad results get `strong` (c3 and e6, `reports/W5-SEARCH-FAILURE-PROBE.md:10`).
2. **The agreement matches are made of common words** ("good", "year", "last", "won"), not of the question's distinctive words (`reports/W5-SEARCH-FAILURE-PROBE.md:224`, `:232`). Stopword removal is not the cause; stopwords are already dropped (`reports/W5-DEMO-QUERY-SPOTCHECK.md:223`).
3. **Zero BM25 rows caps the level at `weak`.** With no BM25 row there is no agreement, so a question is at best `weak` however high its cosine (`src/preached/abstain.py:162-165`). 11 of the 30 probe queries had 0 BM25 rows (`reports/W5-SEARCH-FAILURE-PROBE.md:9`), and the spot check graded three such `weak` banners as under-confident (`reports/W5-DEMO-QUERY-SPOTCHECK.md:25-26`, `:30`).

The probe's own recommendations 4 and 5 (`reports/W5-SEARCH-FAILURE-PROBE.md:345-346`) propose this direction and say any refit needs a pre-registered dev set disjoint from the frozen eval and from the probe queries.

## Decision (CTO's final scope)

**Change ONLY the confidence decision:** `compute_signals` and `decide` in `src/preached/abstain.py`, plus the floor in `search/abstain.toml`, and the plumbing that carries them to every caller (listed under "Plumbing" below). Three changes, together, as one candidate rule:

1. **Shallow agreement depth.** Agreement is computed at a shallow pre-registered depth instead of 100. The depth is fixed at **20** in the pre-registration (§3.1) and is not tuned. `bm25_hits` stays the count at `CANDIDATES` (it is a reported signal, not part of the change).
2. **OR-mode agreement ignores common-word-only matches.** When the query is OR-shaped (`scripture_match(query) is None and len(content_terms(query)) > 4`, the same OR-shape rule as `reports/W4-FRESH-BLIND-PREREG.md` §3), a BM25 row counts toward agreement only if it contains at least one query content term that is **not** on the common-word list. The list is fixed **from document frequency** (τ = 0.05, DF counted over chunk rows as stored, overlaps included) by a rule written in the pre-registration (§3.2). It is **not hand-picked**: no word is added or removed by hand. It is **not stored in `search/abstain.toml`**: it is computed from the served index at first use, cached per `index_version` (the index's `chunks_sha256`), and its size and sha256 are pinned in a test, with the index sha they hold for; index drift fails that pin until a re-pin PR. At τ = 0.05 doctrinal stems (`god`, `love`, `spirit`, `sin`, `christ`, `faith`, `holi`, `grace`) are expected to be common; that subgroup is reported.
3. **Zero-BM25 queries get their own cosine floor.** A query with 0 BM25 rows is decided by its top dense cosine against a separate floor, fitted on the dev split, instead of being capped at `weak` (§3.3). With fewer than 5 bad zero-BM25 dev cases there is no `zero_floor`, and zero-BM25 stays capped at `weak`. No new level: the result is still one of `strong`, `weak` or `none`.

The dense floor and the new zero-BM25 floor are fitted on the **dev split only**, by the rules fixed in the pre-registration, for Granite English R2 ONNX fp32 (scored) and torch fp32 (refit, gating nothing). The `embeddinggemma-2` calibration is dropped, not refit (that model never abstains). The frozen eval is a guard, never a fitting set.

### Plumbing (every function and file touched outside `compute_signals` / `decide`)

- `floor_for` (`src/preached/abstain.py:250-300`) returns a `Floors(dense, zero)` value; `load_calibrations` and `calibration_toml` (`:215-240`, `:315-339`) read and write `zero_floor` only.
- `search_with_confidence` (`:342-353`) passes `Floors` to `decide`. **How `zero_floor` reaches `decide`:** `decide` accepts `Floors`, a bare float (dense floor only) or None, and reads `zero` from `Floors`. `Confidence.as_dict` is unchanged.
- The church path at `app/server.py:1587` calls `compute_signals` (signature unchanged), so it follows the new agreement with its own index's list and stays `unrated`.
- The CLI follows the new rule: `search/query.py:394-404` and `:523-528` (`compute_signals`, `floor_for`, `decide`).
- Bench follows the new rule: `search_with_confidence` at `search/bench.py:643` and `:654`; `decide` at `:702-708` and `:859` gets the stored `zero_floor` (bench never fits it, and `--write` keeps it).
- `app/` needs no change under this plumbing (`app/server.py:1407`, `:1796-1809`, `:1351` pass the floor value through). If the code PR must change `app/`, it says so, G3 drops "empty `app/` diff" for "no new API fields", and the DEPLOY-cite re-pin rule applies.

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
- **Size (CTO ruling):** a ~200-question brief, 120 in-domain and 80 out-of-domain. Confirmation minimums: 50 answerable, 40 out-of-domain and ≥ 20 `strong` banners, because at 20 / 15 a bad rule passes 17-21% of the time. The author choice is still PENDING PATRICK. If Patrick picks A and wants fewer, the only allowed fallback is 20 / 15 with the thresholds labelled "screening rules" plus their false-pass rates, by amendment before any question is written. That fallback is conditional and is not adopted now.
- **Held-out confirmation split**, assigned by a fixed seed before any retrieval and **scored once**. Its levels, signals and labels are sealed: the pool run records no level or signal, the grading KEY holds none, and the confirmation verdicts are kept outside the repo (sha256 committed) until the single scoring run.
- **Dev check is terminal:** a dev failure is reported as a negative result; any retry needs a new pre-registration with a new confirmation set. §6.1-6.2 and §6.6 of the pre-registration cannot be amended once any dev data exists.

## Guards (all must hold, or the retune does not ship)

1. **Frozen eval does not regress:** hit@10 on `eval/questions.jsonl` is unchanged (it must be identical, since ranking is untouched), and its abstain numbers (false-abstain rate on answerable, abstain recall on unanswerable) do not get worse.
2. **Response parity:** every `/api/search` response, with the confidence fields stripped (`abstain`, `confidence`, and the timing field `took_ms`), is byte-identical before and after. Parity runs never log levels or signals.
3. **Fusion `w = 1.0`, no LLM, no PRC models** hold (AGENTS.md): no change to ranking code, models, dependencies or `uv.lock`; empty `app/` diff (or, if `app/` must change, no new API fields).
4. **The citable W3 sentence is untouched** in `README.md`, `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md` and `reports/W3-CONFIRMATORY.md`. No accuracy, "improves" or "better" claim is made from this retune unless the pre-registration's claim rule allows it, and then only after CTO review.

## Evidence status

The PR #89 and #90 reports are one LLM reader's judgments on non-blind, LLM-written queries (`reports/W5-SEARCH-FAILURE-PROBE.md`, "Method, limits and disclosure"; `reports/W5-DEMO-QUERY-SPOTCHECK.md:9`). They show the failure modes exist. They do not measure rates and they are not evidence that this candidate fixes anything. They are re-run before and after as illustrations and reported, but they gate nothing.

## Consequences

- If the candidate passes, `abstain.py` and `search/abstain.toml` change in one code PR; the module docstring (`src/preached/abstain.py:1-44`) is updated to describe the new rule and its dev-set provenance.
- If it fails any primary threshold or guard, on the dev check or the confirmation split, the current rule stays and the result is reported as a negative result. No second candidate is tried on the same set; a retry needs a new pre-registration and a new confirmation set.
- `search/abstain.toml` gains the zero-BM25 floor with its provenance and loses the `embeddinggemma-2` entry. The common-word list is not stored there (see Decision 2).
- This PR touches no code. The planned code PR is not expected to touch `app/server.py` or any file cited in `docs/DEPLOY.md`; if it does, it re-pins those cites in the same PR.

## Steps

1. This ADR and the pre-registration are reviewed by the CTO and merged.
2. Patrick ticks the author option. **(BLOCKED here.)**
3. Questions written, frozen and split (freeze PR); pool, blind sheet and labels (pre-registration §§4-5).
4. Code PR: the candidate rule and its plumbing, the DF list function and its pin test, the floor fits on the dev split, the scoring script and the guard tests. Reviewed before the dev check.
5. Dev check (a failure is terminal); on a pass, confirmation split scored once; report reviewed by the CTO before anything ships or is claimed.
