# W5-CONFIDENCE-RETUNE-PREREG: pre-registration for the confidence/abstain retune (DRAFT)

Branch `docs/w5-confidence-retune-adr`, from origin/main. Date: 2026-10-31. Status: **DRAFT r3 for CTO review (r2 addressed the CTO's r1 CONDITIONAL on PR #93: MF1-MF6 and the should-fixes; r3 addresses the r2 CONDITIONAL: MF-R2-1 to MF-R2-8 and the 90-OOD brief, §13). BLOCKED: the author option is PENDING PATRICK.** Decision record: `docs/adr/0002-confidence-retune.md`.

**This note has no questions and no results.** It changes no code, index, `eval/` file, label, floor or weight. No question has been written and no retrieval has been run for it. Line numbers hold on this PR's base tree (`git merge-base HEAD origin/main`), including the two W5 reports (`reports/W5-SEARCH-FAILURE-PROBE.md`, PR #89, and `reports/W5-DEMO-QUERY-SPOTCHECK.md`, PR #90), which are now on main. The candidate's values (agreement depth 20, τ = 0.05, thresholds 0.10 / 0.80 / 0.15, ≥ 20 strong banners, minimum n 50 / 40, the ~210-question brief, seeds 520261031 / 520261032) were chosen after viewing the PR #89 and #90 probe results; those 66 probe queries are excluded from all fitting, choosing and scoring. The PR #89 and #90 queries are LLM-written, not hand-written.

**Freeze.** Every value in this note freezes at **this PR's merge commit**. A change is allowed only through an amendment PR, reviewed by the CTO and merged **before any fresh question is written**; after that, nothing here changes. The freeze PR (§4) records this file's sha256 and this PR's merge sha. §6.1, §6.2 and §6.6 can never be amended once any dev data exists (any retrieval output on the set, from the §5.1 pool run on).

## 0. Order of steps (nothing skips ahead)

1. The ADR and this pre-registration are merged after CTO review. Every value freezes at that merge commit; an amendment is possible only before step 3.
2. **Patrick records the author option (§1). BLOCKED here.**
3. Questions are written to the brief (§2).
4. **Freeze PR** (§4): the question file, its sha256, the split, the drop list, this note's sha256 and the merge sha of the PR that merged it. CTO review. **No retrieval of any kind runs on the set until it is merged.**
5. **Pool and blind sheet** (§5): one retrieval run that records no level and no signal, then Patrick grades blind. Dev verdicts committed unchanged, then dev labels applied in their own commit; confirmation verdicts sealed (§5.3).
6. **Code PR** (§3, §7): the candidate rule, the common-word list generator, the floor fits on the **dev split only**, the scoring script and the guard tests. CTO review. The confirmation split is not scored in this PR.
7. **Dev check** (§6.5). A dev-check failure is **terminal**: it is reported as a negative result and the confirmation split is never scored under this note. On a pass, the **confirmation split is scored once** (§6). The CTO reviews the report before anything ships or is claimed.

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

- **A:** W4 §1's exposure rules apply as written. The "any W3 or W4 report" item is read as including the W5 reports, in particular `reports/W5-SEARCH-FAILURE-PROBE.md` and `reports/W5-DEMO-QUERY-SPOTCHECK.md` (O3, adopted). Author = grader is disclosed (§5.4). Patrick has seen the PR #89 and #90 queries (LLM-written) and this document; that is disclosed, not prevented.
- **B:** a **new** session, separate from any session used for the W4 fresh set, with the same model rules, the brief in §2 verbatim as the whole first message, and the same freeze-PR records (model, version, provider, visible settings, date and time, brief, full raw reply).
- **Who may NOT author** is W4 §1's list unchanged. It includes Claude in any session, so the agent that drafted this note writes, suggests, seeds or picks no question.

## 2. Brief (fixed and verbatim)

Under A, Patrick writes to this brief. Under B, this is the whole first message, character for character:

```
Write 210 questions, one per line, in your own words. Questions 1 to 120 are what a churchgoer or student might type into a search box to find a John Wesley sermon passage: 40 about a named topic or doctrine, then 40 everyday plain-language questions, then 40 that paraphrase an idea without its usual keywords. Questions 121 to 210 are what someone might type into the same search box that have nothing to do with John Wesley, Christianity or religion. Do not quote Wesley.
```

- **Size (CTO ruling, MF4; OOD raised to 90 in the r2 review).** About 210 questions: 120 in-domain and 90 out-of-domain. The size is set by the §6.2 confirmation minimums (50 answerable, 40 OOD, at least 20 `strong` banners), because at the earlier 20 / 15 a bad rule passes 17-21% of the time. With nothing dropped, the §4 split gives `confirm` 60 in-domain and 45 `ood` questions: a 5-question `ood` margin over the 40 minimum, shared between drops and `ood` questions graded answerable. The author choice is still **PENDING PATRICK** (§1); writing 210 is a real cost under A.
- **Tags:** `topic` (1-40), `everyday` (41-80), `paraphrase` (81-120), `ood` (121-210). Under A, Patrick tags while writing. Under B, the tag is the reply's own grouping if it gives one, otherwise the position in the raw reply before any drop; the freeze PR says which rule applied. `topic`, `everyday` and `paraphrase` together are "in-domain".
- **Drops (before freeze only):** W4 §2's reasons (duplicate; not a question someone would type into this search box; quotes Wesley; unreadable), plus "an `ood` question that is about Wesley, Christianity or religion", plus the near-duplicate drop in §4. Each drop is listed with its text and a one-line reason. Under B, Patrick may only drop: no rewording, merging, splitting, reordering or spelling fixes.
- **Binding minimum (CTO ruling, MF4):** `confirm` must hold **≥ 50 answerable** and **≥ 40 OOD** questions (classes from labels, §5.3), and the candidate arm **≥ 20 `strong` banners** (§6.2); below any, the result is inconclusive and nothing ships. **Drop rule, pre-stated:** drops are made only before the freeze PR, only for the reasons above and the §4 near-duplicate rule, each listed with its text and reason, and never after the freeze. Freeze feasibility check, derived from those minimums and not a power calculation: after drops, the §4 split must give `confirm` at least 50 in-domain-tagged and 40 `ood`-tagged questions (at least 100 in-domain and 79 `ood` kept, since `confirm` takes ⌈n/2⌉ per tag); otherwise one replacement pass, then C. The check is necessary, not sufficient: answerable and OOD are label classes, which can only be fewer than the tags. If the check fails, the set is not frozen, the failed set is still committed for the record, and the **one** replacement pass is a complete new 210 under the same option. If that also fails, option C applies. No top-up, no mixing of sets, no third pass.
- More than 210 lines: the first 210 non-empty question lines are kept. Fewer: taken as they are; the minimums still apply.

## 3. The candidate rule (fixed now, before any dev data)

The rule lives in `compute_signals` and `decide` in `src/preached/abstain.py` (`:112-136`, `:153-168`) and the floors in `search/abstain.toml`. The plumbing that carries it to every caller is named in full in §3.5. Ranking does not change, so the shown hits are identical in both arms.

### 3.1 Agreement depth: **20**

`AGREE_DEPTH = 20`. Let `L20` be the first 20 rowids of the publish-gated BM25 list (`searcher._lexical(query, CANDIDATES, where)`, `src/preached/abstain.py:126`) and `D20` the first 20 of the publish-gated dense list (`:129`). Today both are 100 deep (`CANDIDATES`, `:60`). `bm25_hits` stays `len` of the 100-deep BM25 list and `dense_top` stays the top dense cosine; only agreement uses depth 20. **20 is not tuned:** no other depth is run on the dev or confirmation split.

### 3.2 OR-mode agreement ignores common-word-only matches

- **OR-shaped query:** `scripture_match(query) is None and len(content_terms(query)) > 4` (`src/preached/fts.py:110`, `:132`, `:151`; the same rule as `reports/W4-FRESH-BLIND-PREREG.md` §3).
- **Common-word list, from document frequency:** `N` = the number of published chunk rows in the FTS table of the served index; `df(t)` = the number of those rows in which index term `t` occurs (in any column BM25 matches), read from the index itself (an FTS5 `fts5vocab` table or the equivalent count). `COMMON = { t : df(t) >= 0.05 * N }`. **τ = 0.05 is fixed now.** DF counts chunk rows as stored: chunks overlap, so a term in an overlap is counted once per row it sits in, and no de-overlapping is done.
- **Where the list lives (MF5).** The list is **not** stored in `search/abstain.toml`. It is computed from the served index at first use (first `compute_signals` call on that searcher's connection), through the publish gate (`searcher._where()`), and cached in memory per `index_version` (the index's `meta` `chunks_sha256`, the value `/healthz` reports, `app/server.py:1311-1321`). A reload onto a different index computes a new list; a church index gets its own list by the same rule. The list is **never edited by hand**: no word is added, removed or exempted.
- **Pin and index drift.** The code PR records, for the Wesley index the dev and confirmation splits are scored on: its `chunks_sha256`, `N`, the list's size, the sha256 of the sorted, newline-joined list and the sha256 of the index file. The pin test makes its own temporary copy with `scripts/bundle_manifest.copy_index` (`scripts/bundle_manifest.py:53`; read-only source, rule 5) from the configured Wesley index (`$PREACHED_CACHE/index/wesley.sqlite`, never `/cache` directly), checks the copy and the source sha256 before and after, and **skips cleanly** (`skipTest`, with the path) when no index is present. CI runs a second test on a synthetic fixture index with its own pinned N, size and list sha256. The pinned real-index values are `index_version` (`chunks_sha256`), N, the list size, the list sha256 and **the sha256 of the source index file**. If the served index's `chunks_sha256` differs from the pinned one (a rebuild or a newly published sermon), the rule still applies as written, but the served list is no longer the scored list: the pin test fails until a re-pin PR records the new size and sha256 and the words added and removed, and every confirmation number is stated as holding for the pinned `chunks_sha256` only.
- **All-common subgroup, reported.** The subgroup of OR-shaped questions (all tags) whose every content term is in COMMON, so that `L20'` is empty, is reported per split with n and levels in both arms (§6.4), gating nothing. No hand-picked word list defines any subgroup. τ is not changed for it. (CTO r1 measured on a scratch build of the Wesley index: at τ = 0.05, |COMMON| = 321 of 8992 stems, including god, love, spirit, sin, christ, faith, holi, heaven, grace and salvat; the code PR's pin records the actual list.)
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

Classes come from the labels (§5.3). The fits read only dev-split rows, with signals from the candidate `compute_signals`, on each (model, backend, variant) entry that is refit: Granite English R2 ONNX fp32 (the scored entry) and Granite torch fp32 (refit by the same rules, gating nothing). The `embeddinggemma-2` entry (`search/abstain.toml:10-18`) is **dropped**, not refit: that model becomes uncalibrated and never abstains. The drop is recorded in the `search/abstain.toml` header comment (model, date, reason: not refit under ADR 0002).

- **`dense_floor`:** `fit_floor` unchanged (`src/preached/abstain.py:176-195`), with `answerable` = answerable-in-pool and the negatives = `ood` questions with no verdict-2 chunk in their pool. In-domain questions with no verdict-2 chunk are **not** used in this fit (they may be retrieval misses on answerable questions); they are reported.
- **`zero_floor`:** let `Z_bad` be the dev questions with `bm25_hits == 0`, a `dense_top`, and no verdict-2 chunk in their hybrid top 3 (any class). `zero_floor = max(round_up(max dense_top over Z_bad), dense_floor)`, using `round_up` (`src/preached/abstain.py:171-173`). If `Z_bad` has **fewer than 5** questions, `zero_floor` is None (there is no zero-BM25 floor, and zero-BM25 stays capped at `weak`); `|Z_bad|` is reported. Rationale, stated before data: a zero-BM25 `strong` is said only when the cosine beats every known bad zero-BM25 case. A floor set too high only leaves answers at `weak` (today's behaviour), so there is no answerable-question guard here as there is in `fit_floor`.

### 3.5 Plumbing outside `compute_signals` / `decide` (MF5; all of it, cited on this PR's base tree)

- **`floor_for`** (`src/preached/abstain.py:250-300`) returns a `Floors(dense, zero)` value instead of a bare float (None, as now, when the entry is missing or bad). `load_calibrations` and `calibration_toml` (`:215-240`, `:315-339`) read and write one new key, `zero_floor`; its provenance is written into the entry's existing `fitted_on` and `results` strings, and no other key is added to any entry; a bad `zero_floor` is ignored (zero-BM25 stays capped at `weak`) without disabling the dense floor.
- **`search_with_confidence`** (`:342-353`) passes the `Floors` value to `decide`. **How `zero_floor` reaches `decide`:** `decide(signals, floor, has_results=True)` accepts `Floors`, a bare float (dense floor only, `zero` None: existing tests and callers) or None; it reads `zero` from the `Floors`. `Confidence.floor` keeps the dense floor, and `Confidence.as_dict` is unchanged.
- **Pinned bare-float test.** The existing bare-float `decide` tests (`tests/test_abstain.py:36-63`, the `DecideTests` class) stay unchanged and pass. The code PR adds a test that `decide(signals, x)` with a bare float `x` returns, for every row of a fixed signal table, the same level, `calibrated`, `floor` and `as_dict()` as `decide(signals, Floors(dense=x, zero=None))`.
- **`compute_signals`** takes the cached common-word list (§3.2) and the depth from module state; its signature is unchanged, so the **church path** at `app/server.py:1589` (`compute_signals` then `church_confidence`) follows the new agreement with the church index's own list and stays `unrated`.
- **CLI (`search/query.py`).** `:394-404` (the main path: `compute_signals`, `floor_for`, `decide`) and `:523-528` (the side-by-side path: `floor_for`, `decide(compute_signals(...))`) follow the new rule unchanged in text, because `floor_for` now returns `Floors` and `decide` reads it.
- **Bench (`search/bench.py`).** Its `search_with_confidence` calls (`:643`, `:654`) follow the new agreement. `abstain_eval` (`:702-708`) and the probe levels (`:859`) call `decide` with its own refit dense floor; they pass the stored `zero_floor` from `search/abstain.toml` and never fit it. `--abstain --write` keeps a stored `zero_floor` and refuses to overwrite an entry whose `fitted_on` string says it was fitted on this dev split.
- **`app/`.** Under this plumbing `app/server.py` needs no change: it passes `self.floor` through (`:1409`), loads it with `floor_for` (`:1798-1811`), and `/healthz`'s `abstain_calibrated` is `self.floor is not None` (`:1353`), which still holds. If the code PR finds it must change `app/`, it says so, G3 replaces "empty `app/` diff" with "no new API fields", and AGENTS.md's DEPLOY-cite re-pin rule applies.

## 4. Freeze, near-duplicates and split (before retrieval)

A **separate PR** adds `eval/confidence_questions.jsonl`: one object per kept question with `id` (`c-001`..), `query` exactly as written, `tag`, `provenance` (`person-written:patrick` or `llm-written:<model>`), `split` and `relevant: []`. Its PR body or a committed report records the question file's sha256, this note's sha256 and the merge sha of the PR that merged it (§0 freeze), the author option, author, date and time, the brief, the drop list with reasons, and for B the W4 §1 (B) records; for A, Patrick's statement that he used no Preached search, index, corpus or results while writing.

- **Disjointness / near-duplicate review (CTO, in the freeze PR).** Every question is checked against the 93 frozen eval questions (`eval/questions.jsonl`, sha256 `5f8d0918888747c2a281d31c95c56ca7edbff659373ab2fcccfe309baad12c53` on the base tree), the 41 LLM-written PR #89 probe queries (`reports/W5-SEARCH-FAILURE-PROBE.md`, "How to run it" `queries.json`), the 25 LLM-written PR #90 spot-check queries (`reports/W5-DEMO-QUERY-SPOTCHECK.md:15-41`), and additionally (O3, adopted) the 12 `PROBES` in `search/bench.py:610-623`, the 18 questions in `eval/nl-questions-w3polish.jsonl` and `eval/fresh_questions.jsonl` if it exists. A near-duplicate is dropped as **"echoes an existing question"**, and the drop counts toward the §2 minimums.
- **Split seed `520261031`** ("5" for W5 and today's date; differs from the W4 sheet seed `420261031`, the W3 sheet seed `20261031` and the bootstrap seed `20261030`). Within each tag, the kept questions are sorted by `id`, shuffled with `random.Random(520261031)` (one generator, tags in the order `topic`, `everyday`, `paraphrase`, `ood`), and the first `floor(n/2)` go to `dev`, the rest to `confirm`. The split is written into the file in the freeze PR, before any retrieval. **It cannot be tuned:** it is fixed before any question exists and depends only on ids and tags.
- After the merge, no question is added, dropped, edited or moved between splits. The sha256 is checked before every later step.

## 5. Pool, grading and label provenance

### 5.1 One retrieval run

Because the retune does not change ranking, one pool serves both arms. On the base tree's code, Granite English R2 on the ONNX fp32 query embedder (the demo default), the Wesley index, the API path (`api_search`, k = 10), for every frozen question: the hybrid, dense and BM25 top 10. **Pool** = the union per question. **The run records no level, no signal (`bm25_hits`, `dense_top`, agreement) and no banner for any question**, and its output keeps only the rowids and chunk ids of the pool; the `confidence` and `abstain` fields are dropped before anything is written or logged. Levels and signals of both arms are first computed in the dev check (dev rows) and the single scoring run (confirmation rows). Per CTO rule 5 it reads only a read-only copy of the index in a temp dir, never `/cache` directly; the copy's sha256 is recorded before and after and must match. An empty result list for any question in hybrid or dense mode, a sha mismatch or a crash stops the run for the CTO; nothing is retried without a ruling.

### 5.2 Blind sheet

The W4 sheet flow (`reports/W4-FRESH-BLIND-PREREG.md` §5, "Sheet"): columns `row id, question id, question, chunk id, chunk text, verdict, notes`; rows shuffled with **sheet seed `520261032`**; opaque ids. Tag, split, provenance, real chunk ids, titles, ranks and rankers appear only in the KEY, which Patrick does not open until verdicts are committed. The KEY holds **no** level, signal or banner for any row (the pool run never produced them). Pointing the generator at this pool is part of the code PR or its own PR, with the W3 sheet, KEY and KEY-source pins kept byte-for-byte as W4 §5 requires.

### 5.3 Verdicts, labels and classes

- **Grader:** Patrick, blind, `found_by: human:patrick-blind-w5`, verdicts 0, 1 or 2 with the W3 sheet meanings. Dev and confirmation rows are on one sheet, graded before any fitting.
- **Dev rows:** verdicts are committed unchanged (CSV plus sha256), then labels in their own commit, whose hash is recorded before any fit. No label changes after it.
- **Confirmation rows are sealed (MF3).** A script splits the graded sheet by the KEY's split column without printing any verdict or count. The confirmation verdicts go to a sealed CSV that Patrick keeps outside the repo and outside every agent's reach; only its sha256 is committed, with the dev verdicts and before the dev labels are applied (the one step and the ordering below). Its labels, classes, levels and signals are not computed, committed, logged or shown to anyone before the single scoring run, which receives the file, checks its sha256, and commits it byte-identical with the scoring report. A sha mismatch stops the scoring run for the CTO. Verdict 2 = relevant; verdict 1 counts only in the sensitivity analysis (§6.4). Quote anchors follow W4 §5 (c1, c2, c3).

> **Patrick, one step (after grading, before anything is committed):** in the repo root on your own machine, run `uv run python scripts/seal_confirm.py <graded-sheet.csv>`. It writes `eval/confidence_dev_verdicts.csv` (dev rows only) and `W5-confirm-verdicts.csv` in a local sealed location (confirmation rows only, outside the repo), prints only the confirmation file's sha256, and deletes nothing else. Patrick stores the sealed file in a 1Password vault that no agent, bot, service account or CLI integration can read (or on offline media), and deletes the local copy after the sha is printed. Then commit `eval/confidence_dev_verdicts.csv` plus `eval/confidence_confirm_verdicts.sha256` (the printed sha). Do not commit the graded sheet; keep it with the sealed file.

- **Ordering.** The sealed file's sha256 is committed **before** the dev labels are applied and before any dev run. No tuner, Claude or any other agent reads the sealed file, or any copy of it, before the dev-check result is committed. The only reader is the single scoring run (§6.3), to which Patrick supplies the file then.
- **The seal script.** `scripts/seal_confirm.py` is the CTO's proposed name; the code PR or the sheet PR may name it otherwise. It must be written and reviewed before grading.

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
- **P3:** `SB_cand <= SB_base` and `SB_cand <= 0.15`, with **at least 20** `strong` banners in the candidate arm (a rule that almost never says `strong` fails P3).
- **Not a no-op:** at least one of P1-P3 is strictly better than baseline in point estimate.
- **Minimum n (CTO ruling, MF4):** at least **50 answerable** and **40 OOD** questions in `confirm`. Below either, the result is **inconclusive**: every number is still reported, and nothing ships. Reason: at the earlier 20 answerable / 15 OOD, a bad rule passes these thresholds 17-21% of the time.
- **Conditional fallback, not adopted.** The author choice is still PENDING PATRICK. *If* Patrick picks option A and wants to write fewer than ~210 questions, the **only** allowed fallback is: minimum n 20 answerable / 15 OOD, with the §6.2 thresholds relabelled **"screening rules"** and every report stating their false-pass rates next to them (and no claim under §6.6 from a screening-rule pass). It is made only by an amendment merged **before any question is written**. Until such an amendment merges, the 50 / 40 / 20 minimums above apply.
- **Every guard in §7 holds.**

### 6.3 Scored once

The confirmation split is scored **once**, by the scoring script merged in the code PR, after the dev check. There is no re-scoring after a fix, no second candidate, no change to τ, depth, fitting rules or thresholds, no label edit and no re-split. A failure is reported as a failure, and the current rule stays. Before this run, no confirmation row's level, signal or label exists anywhere (§5.1-5.3).

### 6.4 Reported alongside, gating nothing

Per tag with n; the in-domain-unanswerable questions' levels; `weak` rate on answerable; the zero-BM25 subset's level shift and `|Z_bad|` (§3.4); the all-common OR subgroup (§3.2) with n and levels in both arms; the common-word list's size and the pinned `chunks_sha256`; the sensitivity "verdict 1 counted as relevant" (affects the classes and bad top 3); the Granite torch fp32 entry's refit (§3.4).

### 6.5 Dev check (before confirmation)

The candidate with its fitted floors is scored on `dev` (in-sample, labelled as such), with the §6.1 formulas and the §6.2 P1-P3 thresholds (minimum n does not apply to `dev`). **A dev-check failure is terminal (CTO option i, MF3).** It is reported as a negative result; the confirmation split is never scored under this pre-registration and its sealed verdicts (§5.3) stay sealed. There is no amendment and no second candidate on this set: any retry needs a **new** pre-registration with a **new** confirmation set of freshly written questions. §6.1, §6.2 and §6.6 cannot be amended once any dev data exists.

### 6.6 Claims

The retune makes no accuracy, "improves" or "better" claim by default. A metric may be described as improved only if its paired-difference 95% CI excludes zero in the favourable direction on `confirm`, stated with n and the §5.4 disclosure, and only after CTO review. The W3 sentence stays the only retrieval-quality sentence (this retune does not change retrieval).

## 7. Guards (all must hold; checked in the code PR and in the confirmation report)

- **G1 frozen eval.** On `eval/questions.jsonl` (sha256 above), candidate versus baseline on the API path: per-question hit@10 identical; false-abstain rate on its 86 answerable questions not higher; abstain recall on its 7 unanswerable questions not lower. The candidate's floors are the dev-fitted ones, not refit on this file. (`search/bench.py --abstain` refits floors in-sample and leave-one-out, `search/bench.py:696-720`, so the scoring script, merged and reviewed in the code PR, evaluates fixed floors; O5.) Disclosed: the baseline floor was fitted on an earlier 40-question version of this file (`search/abstain.toml:27`).
- **G2 response parity.** For every question in the frozen eval, the confidence set, the 41 PR #89 queries, the 25 PR #90 queries and `search/bench.py` `PROBES`, in `hybrid`, `dense` and `bm25` modes, k = 10, `library=wesley`: the `/api/search` JSON with `took_ms`, `abstain` and `confidence` removed (the fields set at `app/server.py:1415`, `:1422-1423`) is identical before and after, compared as canonical JSON (sorted keys). Shipped as a test in the code PR plus a recorded run. **The parity test and run never log, print or write levels or signals**: the fields are stripped before comparison and only the stripped JSON (or its sha256) and pass/fail are recorded, so G2 cannot expose a confirmation row's level or signals before the scoring run. **HTTP parity hash.** In addition, the sha256 of the canonical `/api/search` HTTP response bodies (frozen eval × hybrid/dense/bm25, k = 10, `library=wesley`) is recorded on the base tree and on the code PR head before the floors change (plumbing only, `Floors` passed through, old floor values), and must be identical. G2's `/api/search` HTTP response sha256 strips only `took_ms`, `abstain` and `confidence`; `why` is included and must be identical on base and on the code-PR head before the floors change. Once #97 merges, G2 names `scripts/parity_hash.py --strip abstain --strip confidence` (`took_ms` is stripped by default); this is not a merge condition.
- **G3 fusion `w = 1.0`, no LLM, no PRC models.** `git diff <base>..<code PR head> -- src/preached/rank.py src/preached/search.py src/preached/fts.py search/models.toml app/ uv.lock pyproject.toml` is empty. No model or dependency is added. **No new API fields:** the key set of every `/api/search` and `/healthz` response, including `confidence` and `confidence.signals`, is unchanged. (If the code PR must change `app/` (§3.5), it says so, `app/` is removed from the empty-diff list and "no new API fields" is the guard for it.)
- **G4 the citable W3 sentence is untouched.** It occurs verbatim, unchanged, in `README.md:52`, `docs/DEMO-SCRIPT.md:107`, `docs/SUBMISSION-DRAFT.md:33` and `reports/W3-CONFIRMATORY.md:180`, and none of those files is in the code PR's diff.

## 8. Regression illustrations (PR #89 and #90; gating nothing)

The 41 probe queries and 25 spot-check queries (all LLM-written, not hand-written) are re-run under both arms and reported as a before/after level table. They are **not** used to fit, choose or check any parameter, floor, list or threshold, are not re-graded, and pass or fail nothing. Cases worth reading in that table, named for the failure mode they show, with no prediction of their outcome: zero-BM25 `weak` on good results (probe a1, a2, b1, b2, b4; spot check 9, 10, 14); OR-mode agreement on out-of-domain queries (probe d1, d2; spot check 22, 23); `strong` on a bad top 3 (probe c3, e6; spot check 6, 12); false abstains (probe b6; spot check 13).

## 9. Disclosure: what the drafting agent saw

Drafted by Claude Code (claude-opus-5-5). It read `src/preached/abstain.py`, `search/abstain.toml`, `src/preached/fts.py`, `src/preached/stats.py` (signatures), the `--abstain` section of `search/bench.py`, the `/api/search` handler in `app/server.py`, `eval/README.md`, `reports/W4-FRESH-BLIND-PREREG.md`, and both W5 reports in full, including all 66 queries and their outcomes. It counted the frozen eval's groups and took its sha256. It ran no search, read no corpus text, and did not open `/cache`. Depth 20 is the CTO's example value. τ = 0.05 and the thresholds 0.10 / 0.80 / 0.15 are the agent's; the ~210-question brief, the ≥ 20 strong banners and the 50 / 40 minimum n are the CTO's r1 ruling (MF4). All were chosen with the probe figures in view (out-of-domain abstains 4 of 6 and 2 of 4; strong-on-bad 2 of 15 in the probe; false abstains 1 of 30 and 1 of 21). The candidate's values (agreement depth 20, τ = 0.05, thresholds 0.10 / 0.80 / 0.15, ≥ 20 strong banners, minimum n 50 / 40, the ~210-question brief, seeds 520261031 / 520261032) were chosen after viewing the PR #89 and #90 probe results; those 66 probe queries are excluded from all fitting, choosing and scoring. The 66 queries are LLM-written. The values freeze at this PR's merge commit; a change needs an amendment merged before any question is written (§0).

## 10. Open points (resolved in r2; O1, O2, O4 and O5 restated in r3 per the CTO's r2 rulings)

- **O1 loader scope: adopted, narrowed.** The loader and writer (`load_calibrations`, `floor_for`, `calibration_toml`, `src/preached/abstain.py:215-339`) read and write one new key, `zero_floor`; its provenance is written into the entry's existing `fitted_on` and `results` strings, and no other key is added to any entry (§3.5). The common-word list is **not** in `search/abstain.toml` (§3.2). All plumbing is listed in §3.5.
- **O2 other entries: adopted.** Granite torch fp32 is refit by §3.4, gating nothing. The `embeddinggemma-2` calibration is **dropped**, not refit; the drop is recorded in the `search/abstain.toml` header comment (model, date, reason: not refit under ADR 0002) (§3.4).
- **O3 additions: adopted.** Disjointness from the bench `PROBES`, `eval/nl-questions-w3polish.jsonl` and the W4 fresh set (§4), and W4's exposure list read as covering the W5 reports (§1).
- **O4 τ and thresholds: fixed** as in §3.2 and §6.2 with the MF4 minimums; frozen at this PR's merge (§0, §9).
- **O5 scoring script: adopted.** A separate script (not `search/bench.py --abstain`) scores both arms on the API path (`search_with_confidence`, hybrid, k = 10). It reads floors from `search/abstain.toml` at a commit sha it records, **never calls `fit_floor`** (a test monkeypatches `fit_floor` to raise and runs the script on a fixture), and writes every §6.1 number with numerator, denominator, CI and W/T/L. Its commit sha and the `abstain.toml` sha256 are recorded in the dev-check report, before the single confirmation run. It reads confirmation rows only in that one run.

## 11. What this does not do

- It writes, suggests or paraphrases no question, runs no retrieval and reads no corpus text.
- It changes no code, floor, label, weight, OR-shape rule or the AND→OR behaviour. The AND→OR fallback, quote boost, new API levels, fusion weights and ranking are out of scope (ADR 0002).
- It does not decide the author option. That is Patrick's call (§1).
- It makes no accuracy claim and does not touch the W3 sentence.

## 12. Checklist

Patrick:

- [ ] Author option ticked in §1, with date and time.
- [ ] Questions written per W4 §1 for that option to the ~210-question brief (120 in-domain, 90 `ood`); drops only, with reasons. **Binding minimum (CTO ruling, MF4):** `confirm` must hold **≥ 50 answerable** and **≥ 40 OOD** questions (classes from labels, §5.3), and the candidate arm **≥ 20 `strong` banners** (§6.2); below any, the result is inconclusive and nothing ships. **Drop rule, pre-stated:** drops are made only before the freeze PR, only for the reasons above and the §4 near-duplicate rule, each listed with its text and reason, and never after the freeze. Freeze feasibility check, derived from those minimums and not a power calculation: after drops, the §4 split must give `confirm` at least 50 in-domain-tagged and 40 `ood`-tagged questions (at least 100 in-domain and 79 `ood` kept, since `confirm` takes ⌈n/2⌉ per tag); otherwise one replacement pass, then C.
- [ ] **Patrick, one step (after grading, before anything is committed):** in the repo root on your own machine, run `uv run python scripts/seal_confirm.py <graded-sheet.csv>`. It writes `eval/confidence_dev_verdicts.csv` (dev rows only) and `W5-confirm-verdicts.csv` in a local sealed location (confirmation rows only, outside the repo), prints only the confirmation file's sha256, and deletes nothing else. Patrick stores the sealed file in a 1Password vault that no agent, bot, service account or CLI integration can read (or on offline media), and deletes the local copy after the sha is printed. Then commit `eval/confidence_dev_verdicts.csv` plus `eval/confidence_confirm_verdicts.sha256` (the printed sha). Do not commit the graded sheet; keep it with the sealed file (§5.3).
- [ ] KEY not opened until verdicts are committed; sheet graded blind as `human:patrick-blind-w5`.

CTO:

- [ ] ADR 0002 and this note reviewed: depth 20, τ, the zero-floor and dense-floor fitting rules, the thresholds, the 50 / 40 / 20 minimums, seeds `520261031` (split) and `520261032` (sheet), the §3.5 plumbing. Values freeze at the merge commit.
- [ ] Freeze PR reviewed: disjointness and near-duplicates, split written, question-file sha256, this note's sha256 and its merge sha recorded; merged before any retrieval.
- [ ] Pool run: read-only temp copy, sha unchanged, no empty list or crash, no level or signal recorded.
- [ ] Dev verdicts committed unchanged; dev label commit hash and the sealed confirmation file's sha256 recorded.
- [ ] Code PR reviewed: scope (`abstain.py`, `abstain.toml`, the §3.5 callers, the DF list function and its pin test, scoring script, tests), G1-G4 tests, floors fitted on dev only.
- [ ] Dev check reported (a failure ends this pre-registration); confirmation split scored once; every §6 number with its CI; claim wording (if any) approved before it appears anywhere.

## 13. R3 (99-XF-RETUNE-ADR-R3): CTO r2 CONDITIONAL at 0d1516d addressed

P = `reports/W5-CONFIDENCE-RETUNE-PREREG.md`, A = `docs/adr/0002-confidence-retune.md`, line numbers at the r3 head (the r3 sections are appended after §12, so these lines don't move).

| Item | Where |
|---|---|
| MF-R2-1 all-common subgroup replaces the hand-picked stem subgroup; CTO r1 measurement (321 of 8992 stems) stated as a measurement | P:65 (§3.2), P:169 (§6.4); A:33 |
| MF-R2-2 O5 scoring script: API path, floors from `abstain.toml` at a recorded sha, never calls `fit_floor` (monkeypatch test), every §6.1 number with n, CI, W/T/L, shas recorded before the confirmation run | P:200 |
| MF-R2-3 one new key `zero_floor`, provenance in the existing `fitted_on` / `results` strings, no other key; bench's overwrite refusal reads `fitted_on` | P:92, P:97, P:196; A:40, A:80 |
| MF-R2-4 `embeddinggemma-2` drop recorded in the `search/abstain.toml` header comment | P:85, P:197; A:80 |
| MF-R2-5 pinned bare-float `decide` test | P:94 (§3.5); A:68 |
| MF-R2-5 HTTP parity hash (base tree versus code PR head, plumbing only) | P:182 (G2); A:68 |
| MF-R2-6 Patrick's one-step seal instruction, ordering, script name | P:124-127 (§5.3), P:215 (checklist); sha placement fixed at P:122 |
| MF-R2-7 binding minimum, drop rule and freeze feasibility check (split arithmetic, not a power calculation) | P:48, P:214; A:61 |
| MF-R2-7 CTO choice: OOD raised to 90, brief ~210 (120 + 90), `confirm` 45 `ood` (5-question margin) | P:5, P:42, P:45-46, P:48-49, P:160, P:192, P:214; A:3, A:61 |
| MF-R2-8 pin test's read-only copy: `copy_index` from `$PREACHED_CACHE/index/wesley.sqlite`, source sha before and after, clean skip, synthetic CI fixture, source-file sha pinned | P:64 |

Deviations and changes the CTO should check:

- **Bare-float test cite.** MF-R2-5 cites `tests/test_abstain.py:38-55`. The bare-float `decide` tests are the whole `DecideTests` class, `tests/test_abstain.py:36-63`: `test_bm25_only_is_unrated_or_none` ends at `:56`, and `test_as_dict` (`:58-63`) also calls `decide` with a bare float. P:94 cites `:36-63`.
- **`why` now exists.** MF-R2-5's note says no `why` field exists on e434539 or 6eb260f. Main has since merged PR #88 (now in this branch's base, 1a0a340): every hit carries `why` (`app/server.py:329`, `:732`), with BM25 and dense ranks and the cosine read off the candidate lists. Stated at P:182. CTO ruled: `why` is included in the G2 HTTP hash.
- **Re-pinned for the new base.** Merging origin/main (1a0a340) inserted one line in `app/server.py` at `:329` and one at `:732` (PR #88), so every cite below `:732` moves down 2. Every `app/server.py` cite was re-pinned by reading the file at 1a0a340: `:1309-1319`→`:1311-1321`, `:1351`→`:1353`, `:1407`→`:1409`, `:1413`→`:1415`, `:1420-1421`→`:1422-1423`, `:1587`→`:1589`, `:1796-1809`→`:1798-1811` (P:63, P:95, P:98, P:182; A:42, A:45). The other cited files are byte-identical between e434539 and 1a0a340 (`README.md` changed only below line 74, so `README.md:52` holds). PR #89 and PR #90 are now on main, and their reports match the PR heads byte for byte, so P:5 and A:9 no longer cite the PR branches.
- **Restated to match.** O1 and O2 (P:196-197) and A:40 now use the MF-R2-3 and MF-R2-4 wording. §10's heading says so.

## 14. R4 (99-XH-RETUNE-ADR-R4): CTO r3 CONDITIONAL at 94b93e5 addressed

P = this file. Line numbers are at the r4 head; §14 sits before `## PR BODY`, so no earlier line moved.

- **MF-R3-1 (G2 HTTP hash).** P:182 now reads exactly: G2's `/api/search` HTTP response sha256 strips only `took_ms`, `abstain` and `confidence`; `why` is included and must be identical on base and on the code-PR head before the floors change. The parenthetical saying the strip was not harmless and the hash did not cover `why` is deleted. The §13 `why` bullet (P:247) and the PR BODY r3 `why` bullet (P:331) record that CTO ruled `why` is included in the G2 HTTP hash. `docs/adr/0002-confidence-retune.md` does not repeat the stripped text, so it is untouched.
- **MF-R3-2 (sealed file).** P:124 and P:215 now say Patrick stores the sealed file in a 1Password vault that no agent, bot, service account or CLI integration can read (or on offline media), and deletes the local copy after the sha is printed. No line names the old home-directory sealed folder any more.
- **SF-R3-1 (not a merge condition).** P:182 notes that once #97 merges, G2 names `scripts/parity_hash.py --strip abstain --strip confidence` (`took_ms` is stripped by default).
- **Nit.** The PR BODY stat header cites the current base (8d46f14) and the new stat.

## PR BODY

The live PR #93 body is synced from this section.

Docs only: step 1 of the CTO's confidence/abstain retune. This PR adds an ADR and a draft pre-registration. It changes no code, labels, floors or weights, adds no questions and runs no retrieval.

- `docs/adr/0002-confidence-retune.md`: the decision record for the CTO's final scope. It changes only `abstain.py` `compute_signals`/`decide`, the `abstain.toml` floor and the plumbing named in §3.5:
  - agreement checked at depth 20;
  - OR-mode agreement ignores matches made only of common words, with the list built from document frequency;
  - queries with 0 BM25 rows are decided against their own cosine floor.

  The AND→OR fallback, quote boost, new API levels, fusion weights and ranking are out of scope.
- `reports/W5-CONFIDENCE-RETUNE-PREREG.md`:
  - a new dev set, disjoint from the frozen eval, the 41 #89 probe queries and the 25 #90 spot-check queries (those serve only as regression illustrations), from a ~210-question brief (120 in-domain + 90 out-of-domain);
  - the label provenance disclosure;
  - three primary metrics with exact formulas and thresholds: false-abstain rate on answerable questions, abstain rate on out-of-domain questions, and the share of strong banners on a bad top 3;
  - a confirmation split assigned by seed, sealed by Patrick and scored once;
  - guards: frozen-eval hit@10 and abstain don't regress, responses are identical once confidence fields are stripped (plus an HTTP parity hash), fusion w=1.0 with no LLM and no PRC models, and the W3 sentence is untouched.

**BLOCKED:** the dev set needs fresh labelled questions. That depends on Patrick's pending A/B/C author choice in `reports/W4-FRESH-BLIND-PREREG.md` §1, so the author is PENDING PATRICK. Open points O1–O5 are **resolved** (§10 of the pre-registration; O1, O2, O4 and O5 restated in r3 per the CTO's r2 rulings).

`git diff --stat origin/main...HEAD` (base: current origin/main, 8d46f14):

```
 docs/adr/0002-confidence-retune.md     |  89 +++++++++
 reports/W5-CONFIDENCE-RETUNE-PREREG.md | 337 +++++++++++++++++++++++++++++++++
 2 files changed, 426 insertions(+)
```

## r2 (99-XB-RETUNE-ADR-R2): CTO r1 CONDITIONAL at 896c1c43 addressed

P = `reports/W5-CONFIDENCE-RETUNE-PREREG.md`, A = `docs/adr/0002-confidence-retune.md` (line numbers at 0d1516d).

| Item | Where |
|---|---|
| MF1 post-hoc sentence, verbatim | P:5, P:185 (§9); A:3 |
| MF2 freeze at this PR's merge commit; amendments only before any question is written; freeze PR records prereg sha256 + merge sha | P:7, P:11, P:14, P:101; A:5 |
| MF3 dev-check failure terminal; confirmation levels/signals/labels sealed; §6.1-6.2 and §6.6 unamendable once dev data exists | P:7, P:17, P:111, P:115, P:121, P:166; A:5, A:62-63 |
| MF4 minimums 50 / 40 / ≥ 20 strong; ~200-question brief (120 + 80, raised to 90 OOD in r3); 17-21% false-pass reason; PENDING PATRICK; 20/15 screening-rules fallback as conditional | P:39-48, P:150-153; A:61 |
| MF5 plumbing named and cited (church path then at `app/server.py:1587`, now `:1589` after the r3 merge of main), how `zero_floor` reaches `decide`, CLI and bench follow, G3 | P:90-97 (new §3.5), P:176; A:38-45, A:69 |
| MF5 common-word list out of `abstain.toml` (computed from the served index, cached per `index_version`, size + sha256 pinned in a test) | P:63-64; A:33 |
| MF6 probe queries are LLM-written | P:5, P:33, P:103, P:181; A:20, A:74 |
| SF zero_floor needs ≥ 5 bad zero-BM25 dev cases | P:88; A:34 |
| SF doctrinal-stem subgroup at τ = 0.05 (replaced in r3 by the all-common subgroup, MF-R2-1) | P:65, §6.4; A:33 |
| SF index drift vs the list's index sha | P:64 |
| SF G2 parity runs never log levels or signals | P:175; A:68 |
| SF DF counts overlapping chunks | P:62 |
| SF O1-O5 resolved, embeddinggemma-2 calibration dropped | P:85, P:187-193; A:36, A:80 |

## r3 (99-XF-RETUNE-ADR-R3): CTO r2 CONDITIONAL at 0d1516d addressed

Merged origin/main (1a0a340) in with a normal merge, no conflicts (no rebase, no force-push). The full map is §13 of the pre-registration:

P = `reports/W5-CONFIDENCE-RETUNE-PREREG.md`, A = `docs/adr/0002-confidence-retune.md`, line numbers at the r3 head (the r3 sections are appended after §12, so these lines don't move).

| Item | Where |
|---|---|
| MF-R2-1 all-common subgroup replaces the hand-picked stem subgroup; CTO r1 measurement (321 of 8992 stems) stated as a measurement | P:65 (§3.2), P:169 (§6.4); A:33 |
| MF-R2-2 O5 scoring script: API path, floors from `abstain.toml` at a recorded sha, never calls `fit_floor` (monkeypatch test), every §6.1 number with n, CI, W/T/L, shas recorded before the confirmation run | P:200 |
| MF-R2-3 one new key `zero_floor`, provenance in the existing `fitted_on` / `results` strings, no other key; bench's overwrite refusal reads `fitted_on` | P:92, P:97, P:196; A:40, A:80 |
| MF-R2-4 `embeddinggemma-2` drop recorded in the `search/abstain.toml` header comment | P:85, P:197; A:80 |
| MF-R2-5 pinned bare-float `decide` test | P:94 (§3.5); A:68 |
| MF-R2-5 HTTP parity hash (base tree versus code PR head, plumbing only) | P:182 (G2); A:68 |
| MF-R2-6 Patrick's one-step seal instruction, ordering, script name | P:124-127 (§5.3), P:215 (checklist); sha placement fixed at P:122 |
| MF-R2-7 binding minimum, drop rule and freeze feasibility check (split arithmetic, not a power calculation) | P:48, P:214; A:61 |
| MF-R2-7 CTO choice: OOD raised to 90, brief ~210 (120 + 90), `confirm` 45 `ood` (5-question margin) | P:5, P:42, P:45-46, P:48-49, P:160, P:192, P:214; A:3, A:61 |
| MF-R2-8 pin test's read-only copy: `copy_index` from `$PREACHED_CACHE/index/wesley.sqlite`, source sha before and after, clean skip, synthetic CI fixture, source-file sha pinned | P:64 |

Deviations and changes the CTO should check:

- **Bare-float test cite.** MF-R2-5 cites `tests/test_abstain.py:38-55`. The bare-float `decide` tests are the whole `DecideTests` class, `tests/test_abstain.py:36-63`: `test_bm25_only_is_unrated_or_none` ends at `:56`, and `test_as_dict` (`:58-63`) also calls `decide` with a bare float. P:94 cites `:36-63`.
- **`why` now exists.** MF-R2-5's note says no `why` field exists on e434539 or 6eb260f. Main has since merged PR #88 (now in this branch's base, 1a0a340): every hit carries `why` (`app/server.py:329`, `:732`), with BM25 and dense ranks and the cosine read off the candidate lists. Stated at P:182. CTO ruled: `why` is included in the G2 HTTP hash.
- **Re-pinned for the new base.** Merging origin/main (1a0a340) inserted one line in `app/server.py` at `:329` and one at `:732` (PR #88), so every cite below `:732` moves down 2. Every `app/server.py` cite was re-pinned by reading the file at 1a0a340: `:1309-1319`→`:1311-1321`, `:1351`→`:1353`, `:1407`→`:1409`, `:1413`→`:1415`, `:1420-1421`→`:1422-1423`, `:1587`→`:1589`, `:1796-1809`→`:1798-1811` (P:63, P:95, P:98, P:182; A:42, A:45). The other cited files are byte-identical between e434539 and 1a0a340 (`README.md` changed only below line 74, so `README.md:52` holds). PR #89 and PR #90 are now on main, and their reports match the PR heads byte for byte, so P:5 and A:9 no longer cite the PR branches.
- **Restated to match.** O1 and O2 (P:196-197) and A:40 now use the MF-R2-3 and MF-R2-4 wording. §10's heading says so.

Monitor check: `git diff --stat origin/main...HEAD` (above) lists exactly the two in-scope files. No runs, no tests, /cache not opened. Needs CTO r3 review (docs only).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
