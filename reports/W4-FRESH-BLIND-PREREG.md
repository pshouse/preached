# W4-FRESH-BLIND-PREREG: amendment to `reports/W3-FUSION-PREREG.md` for the fresh blind set

Branch `docs/w4-fresh-prereg`, from main `e07da40`. Date: 2026-10-31. Status: **DRAFT for CTO review. The author option is PENDING PATRICK.**

**This note has no questions and no results.** It changes no code, no index, no `eval/` file, no label and no weight. No question has been written, and no retrieval has been run for it. The agent that drafted it (Claude Code, claude-opus-5-5) read only the prereg, `reports/W3-CONFIRMATORY.md`, the `W3-LABEL-SHEET*` reports, `eval/README.md`, `eval/pool.py` and `eval/apply_grades.py`, plus the seed constants in `src/preached/stats.py` and the path helpers in `src/preached/paths.py` and `search/bench.py`. It read no corpus text and ran no search.

Why this exists: the CTO ruled (2026-10-31, 12:20, 12:37 and 12:41 ET, after PR #54) that no accuracy or improvement claim may be made until "do not ship" rules 3 and 4 of `reports/W3-FUSION-PREREG.md` are evaluated on a fresh blind set. PR #54 (`reports/W3-CONFIRMATORY.md`) chose `w = 0.5` but could not evaluate rules 3 and 4, because no fresh set exists. Step 1 of the CTO's process is this amendment, reviewed by the CTO **before any question is written**.

## 0. Order of steps (nothing skips ahead)

1. This amendment is merged after CTO review. Patrick records the author option (§1).
2. The questions are written under §1 and §2.
3. **Freeze PR** (§4): `eval/fresh_questions.jsonl` with its sha256, author, time and the brief verbatim. The CTO reviews it. **No retrieval of any kind runs on the set until that PR is merged.**
4. **Pool and sheet** (§5): one retrieval run of baseline and `w = 0.5`, then the blind sheet and KEY.
5. Patrick grades blind. Verdicts are committed unchanged, then labels are applied in their own commit (§5).
6. **Score** (§6) with the frozen scorer. The CTO reviews the report before any claim appears anywhere.

## 1. Author: PENDING PATRICK

> **PENDING PATRICK: tick exactly one of A, B or C and date it. Until one is ticked, nothing below step 1 happens.**
>
> - [ ] **A.** Patrick writes the questions.
> - [ ] **B.** A fresh non-PRC LLM session writes them.
> - [ ] **C.** Skip the fresh set.
>
> Chosen: ____ Date and time (ET): ____

**(A) Patrick, from his own knowledge.** Patrick writes the 30 questions to the brief in §2. He works from memory and general knowledge only. He uses no Preached search, index, corpus, transcripts, eval files, reports or earlier results while writing. Under A, author and grader are the same person, and every report says so (§5). Disclosed deviation from the prereg: its fresh-set section says the writer must not have seen `reports/W3-RETRIEVAL-DIAG.md` or the prereg, and Patrick has seen the prereg. He also graded the W3 blind sheet, so he has seen 23 corpus chunks. The CTO lists A as an allowed option, and this deviation is recorded here, before any question exists.

**(B) A fresh non-PRC LLM session.** A new chat session with no repo, corpus, index, memory, files, tools, browsing or system prompt beyond the provider default. The model must never have been used on Preached: no Claude and no Grok model. It must not be from a PRC-based developer (AGENTS.md §3), and a model with unclear lineage is excluded. It gets **only** the brief in §2, verbatim, as the whole first message. Its output is disclosed as LLM-written (`provenance: llm-written:<model>`). The freeze PR records the model name and version, the provider, every setting that was visible (temperature and so on, or "provider default"), the date and time, the brief verbatim, and the full raw reply verbatim. Patrick may only **drop** questions (§2). He may not reword, merge, split or reorder them, and he may not fix spelling.

**Who may NOT author, under any option:** Claude (any model or session), Grok (any model or session), any other agent or model that has seen the repo, corpus, index, eval questions, diag report or prereg, the CTO, and any reviewer of Preached PRs. None of them may write, suggest, paraphrase, brainstorm, seed, edit or pick questions. That includes example questions in the brief. The brief in §2 has none, and none may be added.

**(C) Skip.** No fresh set is written. Then:

- no accuracy, "improves" or "better" claim about retrieval appears anywhere (README, DEMO-SCRIPT, SUBMISSION-DRAFT, app, talk);
- the only retrieval-quality statements are #54's descriptive numbers and its CI, described as "no significant difference" (the sentence in §7);
- the fusion weight stays at `w = 1.0` (shipped), and `w = 0.5` is never shipped.

## 2. Brief (fixed and verbatim)

Under A, Patrick writes to this brief. Under B, this is the whole first message, character for character:

```
Write 30 questions a churchgoer or student might type into a search box to find a John Wesley sermon passage, in your own words, one per line. Mix: 10 about a named topic or doctrine, 10 everyday plain-language questions, 10 that paraphrase an idea without its usual keywords. Do not quote Wesley.
```

- **Count:** 30. **Strata quotas:** 10 named-topic/doctrine, 10 everyday plain-language, 10 paraphrase-without-keywords. Under A, Patrick tags each question's stratum while writing. Under B, the stratum is the reply's own grouping if it gives one. If it gives none, it is the 1–10, 11–20, 21–30 position order, which matches the brief's order, and the freeze PR says which rule applied. Strata are reported descriptively and gate nothing.
- **Drops (before freeze only):** Patrick may drop a question that is a duplicate, is not a question someone would type to find a Wesley passage, quotes Wesley, or is unreadable. Each drop is listed in the freeze PR with its text and a one-line reason. No drop may happen after any retrieval.
- **Minimum 25 after drops.** If fewer than 25 remain, the set is not frozen and nothing is run. The failed set and its drop reasons are still committed in the freeze PR, for the record. **One** replacement pass is allowed: a complete new set of 30 from scratch under the same option (A: Patrick writes a new 30; B: a new fresh session, same model, settings and brief). Nothing is carried over from the first set. If the replacement also falls below 25, option C applies. There is no top-up, no mixing of sets and no third pass.
- More than 30 is not allowed. Under B, a reply with more than 30 lines keeps the first 30 and drops the rest. A reply with fewer than 30 is taken as it is, and the minimum of 25 still applies.

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

The CTO reviews that PR for leakage (title words, Wesley quotes, scripture phrasing that matches an index form, anything that echoes the existing eval questions) and for the pins above. **No retrieval, pooling, FTS/BM25 query, dense query or grep of the corpus runs on any question until that PR is merged.** The sha256 recorded there is checked before every later step. After the merge, no question is added, dropped or edited.

## 5. Grading

**Amendment to the prereg's labelling method (CTO ruling, recorded here for review).** The prereg's fresh-set section says relevant passages are found by reading and grep before any ranker runs. This amendment replaces that with **pooled blind grading**, as the CTO's process directs. The grader still never sees a ranking, a rank, a ranker name or a weight, which meets the prereg's requirement that labelling is done by someone who has not seen the baseline or weighted rankings. Pooling the top 10 of both systems judges every chunk that hit@10, MRR@10 and nDCG@10 can count, so those metrics are complete. Recall@5 is not (§6).

- **The one retrieval run.** From a checkout where `src/` and `search/` match `387e9599796f467a7d5cac82e438314b3f347d37` (verify with `git diff 387e959 HEAD -- src search` showing empty output; it is empty at `e07da40`), the frozen scorer (§6) computes the raw-path top 10 (`hybrid_rrf`, no `--dedupe`) for baseline and `w = 0.5` on every frozen question. It uses the same index, model and settings as #54. The per-question top-10 ids are written to `/cache/w4-fresh/pool.json` and its sha256 is recorded. This is the only time rankers see the set. The run uses `/cache/index/wesley.sqlite` read-only (`mode=ro&immutable=1`, `PRAGMA query_only`). Its sha256 must equal `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b` before and after the run, with 8,383 chunks and 8,383 `granite-english-r2` vectors (fingerprint `13e0ed78bb32d86b`, fp32, torch CPU, `MKL_ENABLE_INSTRUCTIONS=AVX512`).
- **Pool:** per question, the union of the two top-10 lists.
- **Shuffle seed: `420261031`.** That is "4" for W4 followed by today's date. It is new, and it differs from the W3 sheet seed (`20261031`) and the bootstrap seed (`20261030`). **Why it can't be tuned:** it is fixed in this document before any question, pool or ranking exists. It only orders the sheet rows and assigns opaque ids, so it cannot change which chunks are pooled, any verdict or any score. Changing it needs a new amendment merged before the pool is built.
- **Sheet:** the same generator logic and KEY flow as the W3 sheet (`scripts/make_label_sheet.py`, PR #43; verdicts and KEY applied as in #50). The labeller sees exactly these columns: `row id, question id, question, chunk id, chunk text, verdict, notes`. Rows are shuffled with the seed above, and the ids are opaque (`L…`, `Q…`, `C…`, assigned in order of first appearance; the digits widen if there are more than 99). Stratum, provenance, the real `wesley-NNN-cNNNN` ids, sermon titles, ranks, rankers and which system returned a chunk appear only in the KEY, which Patrick does not open until verdicts are committed. The generator currently reads the fixed W3 source file. Pointing it at the W4 pool, seed and output paths is a **separate code PR**, reviewed before the pool is built. In that PR the W3 sheet must still reproduce byte-for-byte (`tests/test_label_sheet.py`).
- **Grader:** Patrick, blind, as `found_by: human:patrick-blind-w4`. Verdicts are 0, 1 or 2 per row, with the same meanings as on the W3 sheet. **If option A was chosen, author = grader is disclosed** in the sheet PR and in every report.
- **Verdict to label (the #50 rulings, unchanged):** verdicts are committed unchanged (CSV plus sha256) before anything is applied. (a) Verdict 2 is grade 2 in the primary labels. Verdict 1 never enters the primary labels: it goes to a fresh partial-verdicts file, used only for the sensitivity analysis "verdict 1 counted as grade 1". (b) Labels carry `status: confirmed`, `found_by: human:patrick-blind-w4` and a `sheet_row` whose verdict equals the label grade. (c) Quote anchors follow c1, then c2, then c3, as amended in W3-LABEL-C-AMEND. c1 is the longest KEY segment, and it applies only if the KEY carries a quote for the row (a pooled chunk normally has none). c2 is the first chunk-unique shortest-whole-word span of at least 40 characters, skipping spans over 160. If neither gives a span, c3 applies: the row stops for the CTO. The quote is only an anchor, because Patrick judges the whole chunk. Labels are applied in their own commit, whose hash is recorded before scoring. No label changes after that commit.
- A question with no verdict-2 chunk in its pool is reported as unanswerable-in-pool and is not scored, as in the prereg's selection rule.

## 6. Scoring

- **Frozen scorer:** `/cache/w3-confirmatory/run.py`, sha256 `f4172c8ddf5813e4879ce970a1f25b9495feb91ce22b7dc0ba17bb593eb05ff9`, reproduced verbatim in `reports/W3-CONFIRMATORY.md` (appendix), run against code at `387e9599796f467a7d5cac82e438314b3f347d37`. Its sha256 is checked before every use.
- **Open point for the CTO (O1).** `run.py` loads `eval/questions.jsonl` via `bench.load_questions()` and has only the `select` and `after` phases, so it cannot score `eval/fresh_questions.jsonl` unmodified. Proposed: a thin wrapper that checks `run.py`'s sha256, imports it unchanged, and uses its `searcher_for`, `WeightedSearcher`, `or_shape`, `paired`, `lost`, `gained` and `METRICS` with `bench.evaluate` on the fresh file. The wrapper is committed and reviewed with or before the freeze PR, before any retrieval. The CTO must approve this, or name another way, before step 3.
- **Scoring rerun must match the pool.** The scorer recomputes the top 10 after labels are frozen. It must reproduce `/cache/w4-fresh/pool.json` id for id (same index hashes, model and settings). Any mismatch stops the run for the CTO, and nothing is reported as a result.
- **Pre-declared metrics,** each with its 95% bootstrap CI (10,000 resamples, seed `20261030`) and the paired difference, its CI and W/T/L against baseline. Baseline and `w = 0.5` are scored on the answerable fresh questions, once:
  - **hit@10 (primary; gates rules 3 and 4).** The primary labels are verdict-2 only, so lenient, strict and base hit@10 are the same number here. It is reported as "hit@10".
  - nDCG@10, MRR@10;
  - Recall@5, reported as **pool-relative** (relevant means judged relevant inside the pooled top 10s, not across the corpus);
  - lost and gained question ids;
  - per stratum, descriptively, with n;
  - sensitivity "verdict 1 counted as grade 1": the same table, reported alongside and gating nothing.
- **Claims stay strictly within the CI.** If neither rule 3 nor rule 4 fires and the paired hit@10 CI lies wholly above zero, the claim may state the fresh-set difference with its CI and n, and say who wrote and graded the questions. Otherwise the result is reported as it is, and §7 remains the only citable sentence. Either way, **the CTO reviews the report before any claim appears in the demo, submission, README or app.** The default weight changes only in a separate PR after that review.

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
- [ ] A: questions written from memory only, with no Preached search, index, corpus or results; statement given. B: fresh session, non-PRC, not Claude or Grok, no tools or memory, brief pasted verbatim; model, settings and raw reply saved.
- [ ] Drops only, each with a reason; no rewording. At least 25 kept (else §2's single replacement pass, then C).
- [ ] KEY not opened until verdicts are committed.
- [ ] Sheet graded blind as `human:patrick-blind-w4`.

CTO:

- [ ] This amendment reviewed: seed `420261031`, pooled grading in place of grep labelling (§5), the A deviation (§1), O1 scorer approach (§6).
- [ ] Sheet generator PR reviewed; the W3 sheet still reproduces byte-for-byte.
- [ ] Freeze PR reviewed for leakage and pins; sha256 recorded; merged **before** any retrieval.
- [ ] Pool run: index sha256 unchanged before and after; `pool.json` sha256 recorded.
- [ ] Verdicts committed unchanged; label commit hash recorded; c3 rows ruled.
- [ ] Scorer sha256 checked; rerun matched the pool; every §6 metric reported with its CI.
- [ ] Rules 3 and 4 evaluated as written; claim wording within the CI approved before it appears anywhere.
