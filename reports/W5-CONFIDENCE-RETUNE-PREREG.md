# W5-CONFIDENCE-RETUNE-PREREG: pre-registration for the confidence/abstain retune (DRAFT)

Branch `docs/w5-confidence-retune-adr`, from origin/main. Date: 2026-10-31. Status: **DRAFT r1 for CTO review. BLOCKED: the author option is PENDING PATRICK.** Decision record: `docs/adr/0002-confidence-retune.md`.

**This note has no questions and no results.** It changes no code, index, `eval/` file, label, floor or weight. No question has been written and no retrieval has been run for it. Line numbers hold on this PR's base tree (`git merge-base HEAD origin/main`); the two W5 reports are cited at the head of their PR branches (`qa/w5-search-failure-probe`, PR #89; `qa/w5-demo-query-spotcheck`, PR #90).

## 0. Order of steps (nothing skips ahead)

1. The ADR and this pre-registration are merged after CTO review.
2. **Patrick records the author option (§1). BLOCKED here.**
3. Questions are written to the brief (§2).
4. **Freeze PR** (§4): the question file, its sha256, the split and the drop list. CTO review. **No retrieval of any kind runs on the set until it is merged.**
5. **Pool and blind sheet** (§5): one retrieval run, then Patrick grades blind. Verdicts committed unchanged, then labels applied in their own commit.
6. **Code PR** (§3, §7): the candidate rule, the common-word list generator, the floor fits on the **dev split only**, the scoring script and the guard tests. CTO review. The confirmation split is not scored in this PR.
7. **Dev check** (§6.5), then **confirmation split scored once** (§6). The CTO reviews the report before anything ships or is claimed.

## 1. Author: PENDING PATRICK

The author options, their definitions, the exposure rules and the list of who may not author are those of `reports/W4-FRESH-BLIND-PREREG.md` §1, **reused unchanged**, not redefined here. That section's A/B/C choice is itself still pending.

> **PENDING PATRICK: tick exactly one of A, B or C for this dev set and date it. Until one is ticked, nothing below step 2 happens.**
>
> - [ ] **A.** Patrick writes the questions (W4 §1 (A), with its exposure rules).
> - [ ] **B.** A fresh non-PRC LLM session writes them (W4 §1 (B), all of its conditions).
> - [ ] **C.** Skip. No dev set is written, the retune does not happen, and the current rule and floor stay.
>
> Chosen: ____ Date and time (ET): ____

Applied to this set:

- **A:** W4 §1's exposure rules apply as written. The "any W3 or W4 report" item is read as including the W5 reports, in particular `reports/W5-SEARCH-FAILURE-PROBE.md` and `reports/W5-DEMO-QUERY-SPOTCHECK.md` (open point O3). Author = grader is disclosed (§5.4). Patrick has seen the PR #89 and #90 queries and this document; that is disclosed, not prevented.
- **B:** a **new** session, separate from any session used for the W4 fresh set, with the same model rules, the brief in §2 verbatim as the whole first message, and the same freeze-PR records (model, version, provider, visible settings, date and time, brief, full raw reply).
- **Who may NOT author** is W4 §1's list unchanged. It includes Claude in any session, so the agent that drafted this note writes, suggests, seeds or picks no question.

## 2. Brief (fixed and verbatim)

Under A, Patrick writes to this brief. Under B, this is the whole first message, character for character:

```
Write 100 questions, one per line, in your own words. Questions 1 to 60 are what a churchgoer or student might type into a search box to find a John Wesley sermon passage: 20 about a named topic or doctrine, then 20 everyday plain-language questions, then 20 that paraphrase an idea without its usual keywords. Questions 61 to 100 are what someone might type into the same search box that have nothing to do with John Wesley, Christianity or religion. Do not quote Wesley.
```

- **Tags:** `topic` (1-20), `everyday` (21-40), `paraphrase` (41-60), `ood` (61-100). Under A, Patrick tags while writing. Under B, the tag is the reply's own grouping if it gives one, otherwise the position in the raw reply before any drop; the freeze PR says which rule applied. `topic`, `everyday` and `paraphrase` together are "in-domain".
- **Drops (before freeze only):** W4 §2's reasons (duplicate; not a question someone would type into this search box; quotes Wesley; unreadable), plus "an `ood` question that is about Wesley, Christianity or religion", plus the near-duplicate drop in §4. Each drop is listed with its text and a one-line reason. Under B, Patrick may only drop: no rewording, merging, splitting, reordering or spelling fixes.
- **Minimum after drops: 50 in-domain and 32 `ood`.** Below either, the set is not frozen, the failed set is still committed for the record, and **one** replacement pass of a complete new 100 under the same option is allowed. If that also fails, option C applies. No top-up, no mixing of sets, no third pass.
- More than 100 lines: the first 100 non-empty question lines are kept. Fewer: taken as they are; the minimums still apply.

## 3. The candidate rule (fixed now, before any dev data)

Only `compute_signals` and `decide` in `src/preached/abstain.py` (`:112-136`, `:153-168`) and the floors in `search/abstain.toml` change. Ranking does not change, so the shown hits are identical in both arms.

### 3.1 Agreement depth: **20**

`AGREE_DEPTH = 20`. Let `L20` be the first 20 rowids of the publish-gated BM25 list (`searcher._lexical(query, CANDIDATES, where)`, `src/preached/abstain.py:126`) and `D20` the first 20 of the publish-gated dense list (`:129`). Today both are 100 deep (`CANDIDATES`, `:60`). `bm25_hits` stays `len` of the 100-deep BM25 list and `dense_top` stays the top dense cosine; only agreement uses depth 20. **20 is not tuned:** no other depth is run on the dev or confirmation split.

### 3.2 OR-mode agreement ignores common-word-only matches

- **OR-shaped query:** `scripture_match(query) is None and len(content_terms(query)) > 4` (`src/preached/fts.py:110`, `:132`, `:151`; the same rule as `reports/W4-FRESH-BLIND-PREREG.md` §3).
- **Common-word list, from document frequency:** `N` = the number of published Wesley chunk rows in the FTS table; `df(t)` = the number of those rows in which index term `t` occurs (in any column BM25 matches), read from the index itself (an FTS5 `fts5vocab` table or the equivalent count). `COMMON = { t : df(t) >= 0.05 * N }`. **τ = 0.05 is fixed now** (open point O4). The list is generated by a script in the code PR from the pinned index, written to `search/abstain.toml` with `N`, τ and the index sha256, and **never edited by hand**: no word is added, removed or exempted.
- **Term matching** uses the index's own tokenizer on both sides (query content terms and index terms), so case and punctuation follow FTS5, not a hand rule.
- **Rule:** for an OR-shaped query, `L20' = { r in L20 : row r contains at least one content term of the query that is not in COMMON }`. If every content term is in COMMON, `L20'` is empty. For AND-shaped and scripture queries, `L20' = L20`.
- **Agreement** = some shown hit is in `L20' ∩ D20`.

### 3.3 Zero-BM25 queries: their own floor

`decide` for a calibrated model with dense evidence (`dense_top` not None, `dense_floor` not None):

| condition | level |
| --- | --- |
| `bm25_hits == 0` and `zero_floor` is set and `dense_top > zero_floor` | `strong` |
| `bm25_hits == 0`, otherwise, and `dense_top > dense_floor` | `weak` |
| `bm25_hits == 0`, otherwise | `none` |
| `bm25_hits > 0` | today's rule (`src/preached/abstain.py:161-167`) with the §3.1-3.2 agreement |

Unchanged: no results is `none`; no dense signal is `unrated`; an uncalibrated model (`dense_floor` None) never abstains and a zero-BM25 list is `weak`; `zero_floor` None leaves zero-BM25 capped at `weak`, as today; `church_confidence` stays `unrated`.

### 3.4 Floor fits (dev split only)

Classes come from the labels (§5.3). The fits read only dev-split rows, with signals from the candidate `compute_signals`, on each (model, backend, variant) entry that is refit (open point O2).

- **`dense_floor`:** `fit_floor` unchanged (`src/preached/abstain.py:176-195`), with `answerable` = answerable-in-pool and the negatives = `ood` questions with no verdict-2 chunk in their pool. In-domain questions with no verdict-2 chunk are **not** used in this fit (they may be retrieval misses on answerable questions); they are reported.
- **`zero_floor`:** let `Z_bad` be the dev questions with `bm25_hits == 0`, a `dense_top`, and no verdict-2 chunk in their hybrid top 3 (any class). `zero_floor = max(round_up(max dense_top over Z_bad), dense_floor)`, using `round_up` (`src/preached/abstain.py:171-173`). If `Z_bad` is empty, `zero_floor` is None. Rationale, stated before data: a zero-BM25 `strong` is said only when the cosine beats every known bad zero-BM25 case. A floor set too high only leaves answers at `weak` (today's behaviour), so there is no answerable-question guard here as there is in `fit_floor`.

## 4. Freeze, near-duplicates and split (before retrieval)

A **separate PR** adds `eval/confidence_questions.jsonl`: one object per kept question with `id` (`c-001`..), `query` exactly as written, `tag`, `provenance` (`person-written:patrick` or `llm-written:<model>`), `split` and `relevant: []`. Its PR body or a committed report records the sha256, the author option, author, date and time, the brief, the drop list with reasons, and for B the W4 §1 (B) records; for A, Patrick's statement that he used no Preached search, index, corpus or results while writing.

- **Disjointness / near-duplicate review (CTO, in the freeze PR).** Every question is checked against the 93 frozen eval questions (`eval/questions.jsonl`, sha256 `5f8d0918888747c2a281d31c95c56ca7edbff659373ab2fcccfe309baad12c53` on the base tree), the 41 PR #89 probe queries (`reports/W5-SEARCH-FAILURE-PROBE.md`, "How to run it" `queries.json`), the 25 PR #90 spot-check queries (`reports/W5-DEMO-QUERY-SPOTCHECK.md:15-41`), and additionally (open point O3) the 12 `PROBES` in `search/bench.py:610-623`, the 18 questions in `eval/nl-questions-w3polish.jsonl` and `eval/fresh_questions.jsonl` if it exists. A near-duplicate is dropped as **"echoes an existing question"**, and the drop counts toward the §2 minimums.
- **Split seed `520261031`** ("5" for W5 and today's date; differs from the W4 sheet seed `420261031`, the W3 sheet seed `20261031` and the bootstrap seed `20261030`). Within each tag, the kept questions are sorted by `id`, shuffled with `random.Random(520261031)` (one generator, tags in the order `topic`, `everyday`, `paraphrase`, `ood`), and the first `floor(n/2)` go to `dev`, the rest to `confirm`. The split is written into the file in the freeze PR, before any retrieval. **It cannot be tuned:** it is fixed before any question exists and depends only on ids and tags.
- After the merge, no question is added, dropped, edited or moved between splits. The sha256 is checked before every later step.

## 5. Pool, grading and label provenance

### 5.1 One retrieval run

Because the retune does not change ranking, one pool serves both arms. On the base tree's code, Granite English R2 on the ONNX fp32 query embedder (the demo default), the Wesley index, the API path (`api_search`, k = 10), for every frozen question: the hybrid, dense and BM25 top 10. **Pool** = the union per question. The run also records each question's signals and level under the current rule (that is the baseline arm's input, not a score). Per CTO rule 5 it reads only a read-only copy of the index in a temp dir, never `/cache` directly; the copy's sha256 is recorded before and after and must match. An empty result list for any question in hybrid or dense mode, a sha mismatch or a crash stops the run for the CTO; nothing is retried without a ruling.

### 5.2 Blind sheet

The W4 sheet flow (`reports/W4-FRESH-BLIND-PREREG.md` §5, "Sheet"): columns `row id, question id, question, chunk id, chunk text, verdict, notes`; rows shuffled with **sheet seed `520261032`**; opaque ids. Tag, split, provenance, real chunk ids, titles, ranks, rankers, levels, signals and banners appear only in the KEY, which Patrick does not open until verdicts are committed. Pointing the generator at this pool is part of the code PR or its own PR, with the W3 sheet, KEY and KEY-source pins kept byte-for-byte as W4 §5 requires.

### 5.3 Verdicts, labels and classes

- **Grader:** Patrick, blind, `found_by: human:patrick-blind-w5`, verdicts 0, 1 or 2 with the W3 sheet meanings. Dev and confirmation rows are on one sheet, graded before any fitting.
- Verdicts are committed unchanged (CSV plus sha256), then labels in their own commit, whose hash is recorded before any fit. No label changes after it. Verdict 2 = relevant; verdict 1 counts only in the sensitivity analysis (§6.4). Quote anchors follow W4 §5 (c1, c2, c3).
- **Classes (from labels, not from tags):** *answerable* = at least one verdict-2 chunk in the pool. *Out-of-domain (OOD)* = tag `ood` and no verdict-2 chunk in the pool. *In-domain-unanswerable* = in-domain tag and no verdict-2 chunk; reported descriptively, in no primary metric except P3. An `ood`-tagged question with a verdict-2 chunk is counted as answerable and listed by id.
- **Bad top 3** = no verdict-2 chunk among the hybrid API top 3. Every top-3 chunk is in the pool, so every top 3 is fully graded.

### 5.4 Label provenance disclosure (goes into every report)

- Question author and option (A or B), with `provenance` per question; under B, the model and that its output is LLM-written.
- Grader: Patrick, blind. **Under A, author = grader**, stated in the sheet PR and every report.
- The candidate rule, τ, the depth, the fitting rules and the thresholds were drafted by an LLM agent (Claude Code, claude-opus-5-5) **after** it read the PR #89 and #90 queries and outcomes (§9).
- The frozen eval's labels are LLM-proposed and partly unconfirmed by a human (`eval/README.md:37`); they are used only for the G1 guard.

## 6. Primary metrics, thresholds and the single confirmation scoring

Both arms are scored on the same questions. **Baseline** = the current rule with the shipped Granite ONNX fp32 floor 0.8129 (`search/abstain.toml:24`). **Candidate** = §3 with the dev-fitted floors. Levels are those `search_with_confidence` returns in hybrid mode, k = 10 (the `GET /api/search` path).

### 6.1 Formulas (per split; the decision uses `confirm` only)

- **P1 false-abstain rate** `FAR = |{q answerable : level(q) = none}| / |{q answerable}|`.
- **P2 OOD abstain rate** `OAR = |{q OOD : level(q) = none}| / |{q OOD}|`.
- **P3 strong-on-bad share** `SB = |{q : level(q) = strong and top 3 bad}| / |{q : level(q) = strong}|`, over all scored questions (answerable, OOD and in-domain-unanswerable).

Each is reported with its numerator, denominator and a 95% bootstrap CI (`preached.stats.bootstrap_ci`, 10,000 resamples, seed `20261030`). Paired differences, candidate minus baseline, use `preached.stats.paired_bootstrap` (same resamples and seed) on per-question indicators: for P1 `[level = none]` over answerable, for P2 `[level = none]` over OOD, for P3 `[level = strong and top 3 bad]` over all questions (a rate per question, since the SB denominator differs between arms). W/T/L is reported for each.

### 6.2 Decision thresholds (confirmation split)

The candidate passes only if **all** hold:

- **P1:** `FAR_cand <= FAR_base` and `FAR_cand <= 0.10`.
- **P2:** `OAR_cand >= OAR_base` and `OAR_cand >= 0.80`.
- **P3:** `SB_cand <= SB_base` and `SB_cand <= 0.15`, with at least 5 `strong` banners in the candidate arm (a rule that almost never says `strong` fails P3).
- **Not a no-op:** at least one of P1-P3 is strictly better than baseline in point estimate.
- **Minimum n:** at least 20 answerable and 15 OOD questions in `confirm`. Below either, the result is **inconclusive**: every number is still reported, and nothing ships.
- **Every guard in §7 holds.**

### 6.3 Scored once

The confirmation split is scored **once**, by the scoring script merged in the code PR, after the dev check. There is no re-scoring after a fix, no second candidate, no change to τ, depth, fitting rules or thresholds, no label edit and no re-split. A failure is reported as a failure, and the current rule stays.

### 6.4 Reported alongside, gating nothing

Per tag with n; the in-domain-unanswerable questions' levels; `weak` rate on answerable; the zero-BM25 subset's level shift; the sensitivity "verdict 1 counted as relevant" (affects the classes and bad top 3); the torch fp32 entry, if refit (O2).

### 6.5 Dev check (before confirmation)

The candidate with its fitted floors is scored on `dev` (in-sample, labelled as such). If it fails P1-P3 there, the confirmation split is **not** scored, and the dev result is reported. Any change to the rule after that is a new amendment, reviewed by the CTO, that discloses the dev results that prompted it; the confirmation split stays unscored until then.

### 6.6 Claims

The retune makes no accuracy, "improves" or "better" claim by default. A metric may be described as improved only if its paired-difference 95% CI excludes zero in the favourable direction on `confirm`, stated with n and the §5.4 disclosure, and only after CTO review. The W3 sentence stays the only retrieval-quality sentence (this retune does not change retrieval).

## 7. Guards (all must hold; checked in the code PR and in the confirmation report)

- **G1 frozen eval.** On `eval/questions.jsonl` (sha256 above), candidate versus baseline on the API path: per-question hit@10 identical; false-abstain rate on its 86 answerable questions not higher; abstain recall on its 7 unanswerable questions not lower. The candidate's floors are the dev-fitted ones, not refit on this file. (`search/bench.py --abstain` refits floors in-sample and leave-one-out, `search/bench.py:696-720`, so the scoring script evaluates fixed floors; O5.) Disclosed: the baseline floor was fitted on an earlier 40-question version of this file (`search/abstain.toml:27`).
- **G2 response parity.** For every question in the frozen eval, the confidence set, the 41 PR #89 queries, the 25 PR #90 queries and `search/bench.py` `PROBES`, in `hybrid`, `dense` and `bm25` modes, k = 10, `library=wesley`: the `/api/search` JSON with `took_ms`, `abstain` and `confidence` removed (the fields set at `app/server.py:1413`, `:1420-1421`) is identical before and after, compared as canonical JSON (sorted keys). Shipped as a test in the code PR plus a recorded run.
- **G3 fusion `w = 1.0`, no LLM, no PRC models.** `git diff <base>..<code PR head> -- src/preached/rank.py src/preached/search.py src/preached/fts.py search/models.toml app/ uv.lock pyproject.toml` is empty. No model or dependency is added.
- **G4 the citable W3 sentence is untouched.** It occurs verbatim, unchanged, in `README.md:52`, `docs/DEMO-SCRIPT.md:107`, `docs/SUBMISSION-DRAFT.md:33` and `reports/W3-CONFIRMATORY.md:180`, and none of those files is in the code PR's diff.

## 8. Regression illustrations (PR #89 and #90; gating nothing)

The 41 probe queries and 25 spot-check queries are re-run under both arms and reported as a before/after level table. They are **not** used to fit, choose or check any parameter, floor, list or threshold, are not re-graded, and pass or fail nothing. Cases worth reading in that table, named for the failure mode they show, with no prediction of their outcome: zero-BM25 `weak` on good results (probe a1, a2, b1, b2, b4; spot check 9, 10, 14); OR-mode agreement on out-of-domain queries (probe d1, d2; spot check 22, 23); `strong` on a bad top 3 (probe c3, e6; spot check 6, 12); false abstains (probe b6; spot check 13).

## 9. Disclosure: what the drafting agent saw

Drafted by Claude Code (claude-opus-5-5). It read `src/preached/abstain.py`, `search/abstain.toml`, `src/preached/fts.py`, `src/preached/stats.py` (signatures), the `--abstain` section of `search/bench.py`, the `/api/search` handler in `app/server.py`, `eval/README.md`, `reports/W4-FRESH-BLIND-PREREG.md`, and both W5 reports in full, including all 66 queries and their outcomes. It counted the frozen eval's groups and took its sha256. It ran no search, read no corpus text, and did not open `/cache`. Depth 20 is the CTO's example value. τ = 0.05, the dev-set size and the thresholds 0.10 / 0.80 / 0.15 are the agent's, chosen with the probe figures in view (out-of-domain abstains 4 of 6 and 2 of 4; strong-on-bad 2 of 15 in the probe; false abstains 1 of 30 and 1 of 21). They were not computed from those figures, but they are not blind to them. The CTO may change any of them **before the freeze PR**; after it, they are fixed.

## 10. Open points for the CTO

- **O1 loader scope.** Storing `zero_floor` and the common-word list in `search/abstain.toml` needs the loader and writer (`load_calibrations`, `floor_for`, `calibration_toml`, `src/preached/abstain.py:215-339`) to read and write new keys. That is outside `compute_signals`/`decide`. Proposed: treat it as part of "the abstain.toml floor".
- **O2 other entries.** The new agreement changes what the floors mean for every entry. Proposed: refit the Granite torch fp32 entry by §3.4 (gating nothing), and drop the `embeddinggemma-2` entry (`search/abstain.toml:10-18`) unless it is refit by the same rules, which leaves that model uncalibrated (never abstains).
- **O3 additions to the CTO scope.** Disjointness from the bench `PROBES`, `eval/nl-questions-w3polish.jsonl` and the W4 fresh set, and reading W4's exposure list as covering W5 reports. Strike any you do not want.
- **O4 τ and thresholds** (§9).
- **O5 scoring script.** G1 and §6 need a script that scores fixed floors (bench refits). It is in the code PR and reviewed before the confirmation split is scored.

## 11. What this does not do

- It writes, suggests or paraphrases no question, runs no retrieval and reads no corpus text.
- It changes no code, floor, label, weight, OR-shape rule or the AND→OR behaviour. The AND→OR fallback, quote boost, new API levels, fusion weights and ranking are out of scope (ADR 0002).
- It does not decide the author option. That is Patrick's call (§1).
- It makes no accuracy claim and does not touch the W3 sentence.

## 12. Checklist

Patrick:

- [ ] Author option ticked in §1, with date and time.
- [ ] Questions written per W4 §1 for that option; drops only, with reasons; minimums met (else one replacement pass, then C).
- [ ] KEY not opened until verdicts are committed; sheet graded blind as `human:patrick-blind-w5`.

CTO:

- [ ] ADR 0002 and this note reviewed: depth 20, τ, the zero-floor and dense-floor fitting rules, the thresholds, seeds `520261031` (split) and `520261032` (sheet), O1-O5.
- [ ] Freeze PR reviewed: disjointness and near-duplicates, split written, sha256 recorded; merged before any retrieval.
- [ ] Pool run: read-only temp copy, sha unchanged, no empty list or crash.
- [ ] Verdicts committed unchanged; label commit hash recorded.
- [ ] Code PR reviewed: scope (`abstain.py`, `abstain.toml`, generator, scoring script, tests), G1-G4 tests, floors fitted on dev only.
- [ ] Dev check reported; confirmation split scored once; every §6 number with its CI; claim wording (if any) approved before it appears anywhere.
