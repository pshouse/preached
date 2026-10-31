# W4-FRESH-BLIND-PREREG: amendment to `reports/W3-FUSION-PREREG.md` for the fresh blind set

Branch `docs/w4-fresh-prereg`, from main `e07da40`. Date: 2026-10-31. Status: **DRAFT r2 for CTO review (addresses the CTO's #64 r1 changes MF1–MF3, S1–S5, N1–N3). The author option is PENDING PATRICK.**

**This note has no questions and no results.** It changes no code, no index, no `eval/` file, no label and no weight. No question has been written, and no retrieval has been run for it. The agent that drafted it (Claude Code, claude-opus-5-5) read only the prereg, `reports/W3-CONFIRMATORY.md`, the `W3-LABEL-SHEET*` reports, `eval/README.md`, `eval/pool.py` and `eval/apply_grades.py`, plus the seed constants in `src/preached/stats.py` and the path helpers in `src/preached/paths.py` and `search/bench.py`. It read no corpus text and ran no search. For r2 it also took the sha256 of the W3 sheet, KEY and KEY-source and of `/cache/w3-confirmatory/run.py`, and ran the §5 code-identity `git diff`. It did not open the W3 sheet, the KEY or the question text in `eval/questions.jsonl`.

Why this exists: the CTO ruled (2026-10-31, 12:20, 12:37 and 12:41 ET, after PR #54) that no accuracy or improvement claim may be made until "do not ship" rules 3 and 4 of `reports/W3-FUSION-PREREG.md` are evaluated on a fresh blind set. PR #54 (`reports/W3-CONFIRMATORY.md`) chose `w = 0.5` but could not evaluate rules 3 and 4, because no fresh set exists. Step 1 of the CTO's process is this amendment, reviewed by the CTO **before any question is written**.

## 0. Order of steps (nothing skips ahead)

1. This amendment is merged after CTO review. Patrick records the author option (§1).
2. The questions are written under §1 and §2.
3. **Freeze PR** (§4): `eval/fresh_questions.jsonl` with its sha256, author, time and the brief verbatim. The CTO reviews it. **No retrieval of any kind runs on the set until that PR is merged.**
4. **Wrapper PR and sheet-generator PR merged** (§6, §5). The CTO reviews both. Neither runs retrieval on the fresh set.
5. **Pool and sheet** (§5): one retrieval run of baseline and `w = 0.5`, then the blind sheet and KEY.
6. Patrick grades blind. Verdicts are committed unchanged, then labels are applied in their own commit (§5).
7. **Score** (§6) with the frozen scorer. The CTO reviews the report before any claim appears anywhere.

## 1. Author: PENDING PATRICK

> **PENDING PATRICK: tick exactly one of A, B or C and date it. Until one is ticked, nothing below step 1 happens.**
>
> - [ ] **A.** Patrick writes the questions.
> - [ ] **B.** A fresh non-PRC LLM session writes them.
> - [ ] **C.** Skip the fresh set.
>
> Chosen: ____ Date and time (ET): ____

**(A) Patrick, from his own knowledge.** Patrick writes the 30 questions to the brief in §2. He works from memory and general knowledge only. He uses no Preached search, index, corpus, transcripts, eval files, reports or earlier results while writing. Under A, author and grader are the same person, and every report says so (§5). Disclosed deviation from the prereg: its fresh-set section says the writer must not have seen `reports/W3-RETRIEVAL-DIAG.md` or the prereg, and Patrick has seen the prereg. He also graded the W3 blind sheet, so besides 23 corpus chunks he has seen 18 of the existing eval questions (sheet Q01–Q18). He has also seen the #54 results and reports. The CTO lists A as an allowed option, and this deviation is recorded here, before any question exists.

**Exposure rules (apply ONLY IF A is chosen).** While writing, Patrick does not open the W3 sheet, the KEY, `eval/questions.jsonl`, any W3 or W4 report, or the agent chat's eval threads. He writes all the questions in one sitting, with no search tool of any kind.

**Near-duplicate check (every option, required by the A disclosure).** The freeze-PR leakage review (§4) checks every fresh question against all 58 existing eval questions, with particular care for the 18 sheet questions, for near-duplicates. A near-duplicate is dropped there with the reason fixed now: **"echoes an existing eval question"**. That drop counts toward the minimum of 25 (§2).

**(B) A fresh non-PRC LLM session.** A new chat session with no repo, corpus, index, memory, files, tools, browsing or system prompt beyond the provider default. The model must never have been used on Preached: no Claude and no Grok model. It must not be from a PRC-based developer (AGENTS.md §3), and a model with unclear lineage is excluded. It gets **only** the brief in §2, verbatim, as the whole first message. Its output is disclosed as LLM-written (`provenance: llm-written:<model>`). The freeze PR records the model name and version, the provider, every setting that was visible (temperature and so on, or "provider default"), the date and time, the brief verbatim, and the full raw reply verbatim. Patrick may only **drop** questions (§2). He may not reword, merge, split or reorder them, and he may not fix spelling.

**Who may NOT author, under any option:** Claude (any model or session), Grok (any model or session), any other agent or model that has seen the repo, corpus, index, eval questions, diag report or prereg, the CTO, and any reviewer of Preached PRs. None of them may write, suggest, paraphrase, brainstorm, seed, edit or pick questions. That includes example questions in the brief. The brief in §2 has none, and none may be added.

**(C) Skip.** No fresh set is written. Then:

- no accuracy, "improves" or "better" claim about retrieval appears anywhere (README, DEMO-SCRIPT, SUBMISSION-DRAFT, app, talk);
- the only retrieval-quality statement is the §7 sentence, verbatim;
- the fusion weight stays at `w = 1.0` (shipped), and `w = 0.5` is never shipped.

## 2. Brief (fixed and verbatim)

Under A, Patrick writes to this brief. Under B, this is the whole first message, character for character:

```
Write 30 questions a churchgoer or student might type into a search box to find a John Wesley sermon passage, in your own words, one per line. Mix: 10 about a named topic or doctrine, 10 everyday plain-language questions, 10 that paraphrase an idea without its usual keywords. Do not quote Wesley.
```

- **Count:** 30. **Strata quotas:** 10 named-topic/doctrine, 10 everyday plain-language, 10 paraphrase-without-keywords. Under A, Patrick tags each question's stratum while writing. Under B, the stratum is the reply's own grouping if it gives one. If it gives none, it is the 1–10, 11–20, 21–30 position order in the raw reply, before any drop, which matches the brief's order, and the freeze PR says which rule applied. Strata are reported descriptively and gate nothing.
- **Drops (before freeze only):** Patrick may drop a question that is a duplicate, is not a question someone would type to find a Wesley passage, quotes Wesley, or is unreadable. The freeze-PR leakage review may also drop a question that "echoes an existing eval question" (§1, §4). Each drop is listed in the freeze PR with its text and a one-line reason. No drop may happen after any retrieval.
- **Minimum 25 after drops.** If fewer than 25 remain, the set is not frozen and nothing is run. The failed set and its drop reasons are still committed in the freeze PR, for the record. **One** replacement pass is allowed: a complete new set of 30 from scratch under the same option (A: Patrick writes a new 30; B: a new fresh session, same model, settings and brief). Nothing is carried over from the first set. If the replacement also falls below 25, option C applies. There is no top-up, no mixing of sets and no third pass.
- More than 30 is not allowed. Under B, "lines" means non-empty question lines (blank lines and headings are not counted). A reply with more than 30 lines keeps the first 30 and drops the rest. A reply with fewer than 30 is taken as it is, and the minimum of 25 still applies.

## 3. What is tested (unchanged from the prereg)

- **`w = 0.5`, as chosen in #54. It is never re-chosen.** No other weight is run on the fresh set. The baseline is `w = 1.0` (shipped). The OR-shape rule is the prereg's "That is" definition (`scripture_match(query) is None and len(content_terms(query)) > 4`), with RRF k = 60, the semantic list first and BM25 weight `w`, exactly as in `reports/W3-CONFIRMATORY.md` §2.
- **Rules 3 and 4 are evaluated exactly as written** in `reports/W3-FUSION-PREREG.md`, section "What means 'do not ship'":
  - **Rule 3:** the 95% paired-bootstrap CI of the paired hit@10 difference includes zero **and** at least one fresh-set question is lost. The CI comes from `preached.stats.paired_bootstrap`, with 10,000 resamples and default seed `20261030` (unchanged). A question is lost when a relevant passage is in the baseline top 10 and none is in the `w = 0.5` top 10.
  - **Rule 4:** `w = 0.5` does not beat baseline in hit@10 on the fresh set. "Beat" means a paired hit@10 difference greater than 0.
- Rules 1, 2 and 5 were evaluated in #54 and are not rerun. A mixed result is reported as mixed. It is not rescued by a new weight, a rule change, a label edit or a re-drawn set.

## 4. Freeze before retrieval

A **separate PR** (not this one) adds:

- `eval/fresh_questions.jsonl`: one object per kept question, with `id` (`f-01`..), `query` exactly as written, `stratum`, `provenance` (`person-written:patrick` or `llm-written:<model>`) and `relevant: []`;
- in its PR body or a committed report: the sha256 of that file, the author option, the author, the date and time written, the brief verbatim, and for B the model, version, provider, settings and the raw reply verbatim; the drop list with reasons; for A, Patrick's statement that he used no Preached search, index, corpus or results while writing.

The CTO reviews that PR for leakage (title words, Wesley quotes, scripture phrasing that matches an index form, anything that echoes the existing eval questions) and for the pins above. It checks every fresh question against all 58 eval questions for near-duplicates, with particular care for sheet Q01–Q18, and drops each near-duplicate as "echoes an existing eval question" (§1). Those drops count toward the minimum of 25. **No retrieval, pooling, FTS/BM25 query, dense query or grep of the corpus runs on any question until that PR is merged.** The sha256 recorded there is checked before every later step. After the merge, no question is added, dropped or edited.

## 5. Grading

**Amendment to the prereg's labelling method (CTO ruling, recorded here for review).** The prereg's fresh-set section says relevant passages are found by reading and grep before any ranker runs. This amendment replaces that with **pooled blind grading**, as the CTO's process directs. The grader still never sees a ranking, a rank, a ranker name or a weight, which meets the prereg's requirement that labelling is done by someone who has not seen the baseline or weighted rankings. Pooling the top 10 of both systems judges every chunk that hit@10, MRR@10 and nDCG@10 can count, so those metrics are complete. Recall@5 is not (§6).

- **The one retrieval run.** **Code identity:** `git diff 387e959 HEAD -- src search 'eval/*.py' uv.lock pyproject.toml 'search/*.toml'` must show empty output against `387e9599796f467a7d5cac82e438314b3f347d37` (it is empty at `e48ca90`). If it is not empty, the run happens in a fresh worktree checked out at `387e959`, and the report says so. From that checkout, the frozen scorer through the §6 wrapper computes the raw-path top 10 (`hybrid_rrf`, no `--dedupe`) for baseline and `w = 0.5` on every frozen question. It uses the same index, model and settings as #54. The per-question top-10 ids are written to `/cache/w4-fresh/pool.json` and its sha256 is recorded. This is the only retrieval run before labels are frozen; the only other run is the §6 scoring rerun, which must reproduce it id for id. The run uses `/cache/index/wesley.sqlite` read-only (`mode=ro&immutable=1`, `PRAGMA query_only`). Its sha256 must equal `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b` before and after the run, with 8,383 chunks and 8,383 `granite-english-r2` vectors (fingerprint `13e0ed78bb32d86b`, fp32, torch CPU, `MKL_ENABLE_INSTRUCTIONS=AVX512`). **Stop for the CTO** on an index sha256 mismatch (before or after), an empty result list for any question or system, or a crash. Nothing is retried, patched or rerun without a CTO ruling, and no partial pool is used.
- **Pool:** per question, the union of the two top-10 lists.
- **Shuffle seed: `420261031`.** That is "4" for W4 followed by today's date. It is new, and it differs from the W3 sheet seed (`20261031`) and the bootstrap seed (`20261030`). **Why it can't be tuned:** it is fixed in this document before any question, pool or ranking exists. It only orders the sheet rows and assigns opaque ids, so it cannot change which chunks are pooled, any verdict or any score. Changing it needs a new amendment merged before the pool is built.
- **Sheet:** the same generator logic and KEY flow as the W3 sheet (`scripts/make_label_sheet.py`, PR #43; verdicts and KEY applied as in #50). The labeller sees exactly these columns: `row id, question id, question, chunk id, chunk text, verdict, notes`. Rows are shuffled with the seed above, and the ids are opaque (`L…`, `Q…`, `C…`, assigned in order of first appearance; the digits widen if there are more than 99). Stratum, provenance, the real `wesley-NNN-cNNNN` ids, sermon titles, ranks, rankers and which system returned a chunk appear only in the KEY, which Patrick does not open until verdicts are committed. The generator currently reads the fixed W3 source file. Pointing it at the W4 pool, seed and output paths is a **separate code PR**, reviewed before the pool is built. In that PR the W3 outputs must still reproduce byte-for-byte (`tests/test_label_sheet.py`), with these pins kept unchanged: sheet `reports/W3-LABEL-SHEET.csv` `6141beaaed326f48a12813b95cb812cccd14f8e4eea55632ca063100f5369b12`, KEY `reports/W3-LABEL-SHEET-KEY.md` `892207b6a9c126ec4478488804ef42a8153808c53eb1b69d665b39cafdae3d21`, KEY-source `reports/W3-LABEL-SHEET-KEY-source.json` `e6634f07aa59cf3c64d34736a7708c7dcf661d42651078557f683a5223258861`. The sha256 of the W4 sheet and of the W4 KEY are recorded in a commit before grading starts.
- **Grader:** Patrick, blind, as `found_by: human:patrick-blind-w4`. Verdicts are 0, 1 or 2 per row, with the same meanings as on the W3 sheet. **If option A was chosen, author = grader is disclosed** in the sheet PR and in every report.
- **Verdict to label (the #50 rulings, unchanged):** verdicts are committed unchanged (CSV plus sha256) before anything is applied. (a) Verdict 2 is grade 2 in the primary labels. Verdict 1 never enters the primary labels: it goes to a fresh partial-verdicts file, used only for the sensitivity analysis "verdict 1 counted as grade 1". (b) Labels carry `status: confirmed`, `found_by: human:patrick-blind-w4` and a `sheet_row` whose verdict equals the label grade. (c) Quote anchors follow c1, then c2, then c3, as amended in W3-LABEL-C-AMEND. c1 is the longest KEY segment, and it applies only if the KEY carries a quote for the row (a pooled chunk normally has none). c2 is the first chunk-unique shortest-whole-word span of at least 40 characters, skipping spans over 160. If neither gives a span, c3 applies: the row stops for the CTO. The quote is only an anchor, because Patrick judges the whole chunk. Labels are applied in their own commit, whose hash is recorded before scoring. No label changes after that commit.
- **Unanswerable-in-pool (pre-declared, because it depends on the outcome).** A question with no verdict-2 chunk in its pool is unanswerable-in-pool. Whether a question lands there depends on what both rankers returned, so it is not a neutral exclusion. Such a question is one that both systems miss: on hit@10 it is a 0/0 tie. Dropping it shrinks n and moves the paired difference away from zero, which is anti-conservative. So:
  1. The count of unanswerable-in-pool questions (and their ids and strata) is always reported.
  2. Rule 3, rule 4 and the §6 claim condition are evaluated **twice**: on the answerable-in-pool questions only, and on all frozen questions with each unanswerable-in-pool question counted as a 0/0 tie (hit@10 0 for both systems, entering the paired bootstrap as a tie). A rule that fires under either analysis is reported as fired. A claim needs the paired hit@10 CI wholly above zero under **both**.
  3. **Minimum scored n: 20 answerable-in-pool questions.** Below 20, no claim is possible: the result is reported as inconclusive, with every §6 number still reported descriptively, and §7 stays the only citable sentence.
  4. There is no new set, no replacement pass and no top-up after any retrieval. The §2 replacement pass exists only before freeze.

## 6. Scoring

- **Frozen scorer:** `/cache/w3-confirmatory/run.py`, sha256 `f4172c8ddf5813e4879ce970a1f25b9495feb91ce22b7dc0ba17bb593eb05ff9`, reproduced verbatim in `reports/W3-CONFIRMATORY.md` (appendix), run against code at `387e9599796f467a7d5cac82e438314b3f347d37`. Its sha256 is checked before every use.
- **Scorer wrapper (binding; replaces the r1 open point O1).** `run.py` loads `eval/questions.jsonl` via `bench.load_questions()` and has only the `select` and `after` phases, so it cannot score `eval/fresh_questions.jsonl` unmodified. A wrapper is added in its own PR, which the CTO reviews and which is **merged before step 5 (pool)**. That PR must meet all of (a)–(f):
  - **(a) Fail-closed pins.** Before doing anything else, the wrapper asserts: sha256 of `run.py` is `f4172c8ddf5813e4879ce970a1f25b9495feb91ce22b7dc0ba17bb593eb05ff9`; sha256 of `eval/fresh_questions.jsonl` equals the sha256 recorded in the merged freeze PR; sha256 of `/cache/index/wesley.sqlite` is `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b`; the index holds 8,383 chunks and 8,383 vectors; the embedding fingerprint is `13e0ed78bb32d86b`. Any mismatch raises and writes no output file. There is no warn-and-continue path.
  - **(b) `run.py` unchanged.** The wrapper imports `run.py` as it is. It does no monkey-patching, attribute assignment or override of anything in `run.py`, `bench`, `stats` or the search package: seeds, `RESAMPLES`, `METRICS`, k, the OR-shape rule and `load_questions` all stay as they are. The fresh file is passed as an argument, never by patching `bench.load_questions` or a path constant. If that cannot be done without patching, the wrapper author says so in the PR and stops for the CTO.
  - **(c) Same retrieval path.** The pool is built through the same `searcher_for` / `WeightedSearcher` / `run_mode(..., "hybrid_rrf", dedupe=False)` path that `run.py` uses, because `bench.evaluate` returns no top-10 ids and skips questions with `relevant: []`. The wrapper writes `pool.json` and records its sha256. The scoring rerun captures the top-10 ids too, so it can prove the id-for-id match with `pool.json`.
  - **(d) Tests shipped in the PR:** a `run.py` sha mismatch aborts; a questions-file sha mismatch aborts; an index sha mismatch aborts; no output file appears on any abort; `run.py`'s module attributes are unchanged after import and use.
  - **(e) Reproduction of #54.** The PR shows that the wrapper, pointed at `eval/questions.jsonl` on `387e959` code with the same index, reproduces #54 `select` exactly: pooled lenient hit@10 50 (`w = 1.0`) / 51 (`w = 0.5`) / 50 (`w = 0.25`) of 58, paired difference +0.017 [−0.034, +0.086], W/T/L 2/55/1. A diff of its output against `/cache/w3-confirmatory/out/select.json` is attached to the PR.
  - **(f)** No retrieval of any kind runs on `eval/fresh_questions.jsonl` until that PR is merged.
  - For the §5 0/0-tie analysis, the wrapper adds each unanswerable-in-pool question as a hit@10 tie (0 for both systems) to the per-question vectors it passes to `run.py`'s `paired`; it changes nothing inside `run.py`.
- **Scoring rerun must match the pool.** The scorer recomputes the top 10 after labels are frozen. It must reproduce `/cache/w4-fresh/pool.json` id for id (same index hashes, model and settings). Any mismatch stops the run for the CTO, and nothing is reported as a result.
- **Pre-declared metrics,** each with its 95% bootstrap CI (10,000 resamples, seed `20261030`) and the paired difference, its CI and W/T/L against baseline. Baseline and `w = 0.5` are scored on the answerable-in-pool fresh questions, once, with hit@10 also reported under the 0/0-tie analysis (§5). W4 numbers are **not comparable** to the W3 numbers in #54 (different questions and pool-based labels); only the within-set paired difference is interpreted:
  - **hit@10 (primary; gates rules 3 and 4).** Primary hit@10 counts verdict-2 labels only, so lenient, strict and base hit@10 are the same number here. It is reported as "hit@10".
  - nDCG@10, reported as **pool-relative** (the ideal ranking uses only chunks judged relevant inside the pooled top 10s); MRR@10;
  - Recall@5, reported as **pool-relative** (relevant means judged relevant inside the pooled top 10s, not across the corpus);
  - lost and gained question ids;
  - per stratum, descriptively, with n;
  - sensitivity "verdict 1 counted as grade 1": the same table, reported alongside and gating nothing.
- **Claims stay strictly within the CI.** If at least 20 questions are answerable-in-pool, neither rule 3 nor rule 4 fires under either §5 analysis, and the paired hit@10 CI lies wholly above zero under both, the claim may state the fresh-set difference with its CI and n, and say who wrote and graded the questions. Otherwise the result is reported as it is, and §7 remains the only citable sentence. Either way, **the CTO reviews the report before any claim appears in the demo, submission, README or app.** The default weight changes only in a separate PR after that review.

## 7. The only citable sentence until then

Verbatim (CTO 12:41 corrected version, as in `reports/W3-CONFIRMATORY.md` and `docs/SUBMISSION-DRAFT.md`):

> "In a pre-registered evaluation (58 questions; relevance labels drafted with AI help, a subset confirmed blind by a human), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086)."

The `w = 0.5` change stays on HOLD, and the shipped weight stays `w = 1.0`.

## 8. What this does not do

- It writes, suggests or paraphrases no question. It runs no retrieval and reads no corpus text.
- It does not re-choose `w`, add a weight, change the OR-shape rule, RRF k, the abstain floor or any label.
- It does not rerun rules 1, 2 or 5, plain-blind, `--dedupe` or abstain. Those stand as reported in #54.
- It does not change `run.py`, `make_label_sheet.py`, `eval/` or any code. Each change it calls for is a separate reviewed PR.
- It makes no accuracy claim, and it does not make one possible until §6 is done and reviewed.
- It does not decide the author option. That is Patrick's call (§1).

## 9. Checklist

Patrick:

- [ ] Author option ticked in §1 (A, B or C), with date and time.
- [ ] A: questions written from memory only, in one sitting, with no search tool and none of the W3 sheet, KEY, `eval/questions.jsonl`, W3/W4 reports or eval chat threads open; statement given. B: fresh session, non-PRC, not Claude or Grok, no tools or memory, brief pasted verbatim; model, settings and raw reply saved.
- [ ] Drops only, each with a reason; no rewording. At least 25 kept (else §2's single replacement pass, then C).
- [ ] KEY not opened until verdicts are committed.
- [ ] Sheet graded blind as `human:patrick-blind-w4`.

CTO:

- [ ] This amendment reviewed: seed `420261031`, pooled grading in place of grep labelling (§5), the A deviation and exposure rules (§1), the binding wrapper spec (§6), the unanswerable-in-pool rules and minimum n of 20 (§5).
- [ ] Wrapper PR reviewed and merged before the pool: pins fail closed, `run.py` unpatched, tests shipped, #54 `select` reproduced with the diff attached.
- [ ] Sheet generator PR reviewed; the W3 sheet, KEY and KEY-source pins unchanged; W4 sheet and KEY sha256 recorded before grading.
- [ ] Freeze PR reviewed for leakage (including near-duplicates of all 58 eval questions) and pins; sha256 recorded; merged **before** any retrieval.
- [ ] Pool run: code-identity diff empty (or run in a `387e959` worktree); index sha256 unchanged before and after; no empty result list or crash; `pool.json` sha256 recorded.
- [ ] Verdicts committed unchanged; label commit hash recorded; c3 rows ruled.
- [ ] Scorer sha256 checked; rerun matched the pool; every §6 metric reported with its CI.
- [ ] Unanswerable-in-pool count reported; rules 3 and 4 evaluated as written under both §5 analyses; claim wording within the CI approved before it appears anywhere.
