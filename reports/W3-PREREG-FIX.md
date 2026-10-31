# W3-PREREG-FIX: CTO #47 r1 must-fixes and should-fixes

Branch `docs/w3-prereg-align` (PR #47). Docs only. Prereg commit: `cc5fad6`. The head SHA is the commit that adds this report; it is given in the hand-off message, since a file can't contain its own commit's SHA.

Precondition checked: PR #47 is `open` (unauthenticated GitHub API), head was `b1f9a7a` and included `reports/W3-PREREG-S2.md`. origin/main had no new commits, so no merge was needed.

## Items

| item | what changed in `reports/W3-FUSION-PREREG.md` |
| --- | --- |
| MF1 | Rule 3 now uses the CTO's example wording: "the 95% paired-bootstrap CI (10,000 resamples, seed recorded) of the paired hit@10 difference includes zero and at least one fresh-set question is lost". The CI method is named once, in rule 3: the percentile interval from `preached.stats.paired_bootstrap` (10,000 resamples, default seed 20261030, as in `src/preached/stats.py`). "Lost" is defined: a relevant passage is in the top 10 under the baseline and none is in the top 10 under the chosen `w`. Rule 4 is unchanged and still covers "not positive". |
| MF2 | The disclosure line now says that every question and label used here, selection groups included, is LLM-written or LLM-chosen and not confirmed by a person until `eval/review/review-2026-10-30.csv` is filled in. It names who made what: Grok W1-B originals (all selection-group grade-2 labels and the 12 `-p2` grade-1 labels), Claude `-plain` rewrites and proposed labels, Grok `plain-blind` questions. |
| S1 | Fresh-set relevant passages are found before any ranker runs, by reading the sermons and plain grep, as in W1-B. FTS5/BM25 and dense search count as rankers and are not allowed. |
| S2 | The fresh-set writer must not be a model from a PRC-based developer (AGENTS.md §3) and must not have seen `reports/W3-RETRIEVAL-DIAG.md` or this prereg. |
| S3 | New "Amendments" section: one line dated 2026-10-31, PR #47, saying the changes came before any run of the frozen test. |
| N1 | The header now names `docs/w3-prereg-align` (PR #47) and says the file was first written on `docs/w3-label-sheet` (PR #43). |

## MF2 provenance checks

| claim | verified against | result |
| --- | --- | --- |
| No label is confirmed by a person | `eval/README.md` L41 "Status: pending" | holds |
| The original 40 questions and labels were chosen by the Grok CLI agent (W1-B) | `eval/README.md` L35; `reports/W1-B.md` L11, L38 | holds |
| Every grade-2 label in the selection groups is from W1-B | `eval/questions.jsonl`: all 58 grade-2 labels in `plain`/`names-topic`/`title-keyword`/`scripture-keyword` have no `status` or `found_by`, so none are EVAL-GRADE proposals. `-plain` twins carry their original's labels (EVAL-DELEAK) | holds |
| 12 grade-1 `-p2` labels with no `found_by` | `eval/questions.jsonl`: exactly 12 (6 passages: q-worry, q-assurance, q-riches, q-perfection, q-justification, q-new-birth, each on the original and its `-plain` twin). `q-worry-p2` dates from `b9b94c1` "Add the graded Wesley question set" (W1-B) | holds |
| The `-plain` rewrites were written by Claude (EVAL-DELEAK) | `reports/EVAL-DELEAK.md` L3 (agent Claude) and L224 | **partly.** EVAL-DELEAK wrote 20. The other 3 (`q-worry-plain`, `q-assurance-plain`, `q-faith-works-plain`) were written in EVAL-GRADE (`reports/EVAL-GRADE.md` L41, L272), also by Claude, and `q-satan-plain` was later reworded there (L347). The prereg says "20 in EVAL-DELEAK, 3 in EVAL-GRADE". Both `plain` originals (`q-prayer`, `q-forgiveness`) are Grok W1-B questions. |
| Proposed labels were made by Claude | `eval/README.md` L7, L37; every `status: proposed` label has `found_by: llm-proposed:claude` | holds |
| `plain-blind` questions were written by Grok | `eval/README.md` L23; all 30 have `provenance: llm-written:grok` | holds |

## Checks

- `uv run python -m unittest discover -s tests`: Ran 940 tests, OK.
- Sheet pin unchanged: `sha256sum reports/W3-LABEL-SHEET.csv` = `6141beaaed326f48a12813b95cb812cccd14f8e4eea55632ca063100f5369b12`, which equals `PINNED_SHEET_SHA256` in `tests/test_label_sheet.py`. The label sheet, KEY, generator, `eval/questions.jsonl` and grades were not touched.
- gitleaks: not installed, not run.
- No sandbox.sh or gh in this environment: plain git in the existing worktree. No rebase or force-push.

## Open issues

- None new. The labels are still unreviewed by a person, as disclosed.

## Dependencies

None.

## Diff (b1f9a7a..cc5fad6)

    diff --git a/reports/W3-FUSION-PREREG.md b/reports/W3-FUSION-PREREG.md
    index e4d7021..2c5edaf 100644
    --- a/reports/W3-FUSION-PREREG.md
    +++ b/reports/W3-FUSION-PREREG.md
    @@ -1,12 +1,12 @@
     # W3-FUSION-PREREG: pre-registration for proposal #1 (query-shape-aware fusion weight)
     
    -Branch `docs/w3-label-sheet`. Date: 2026-10-31. Source: §7 proposal 1 of `reports/W3-RETRIEVAL-DIAG.md` (PR #42). **This note has no results. It changes no search code, no index, no `eval/questions.jsonl`, no grades, and no abstain settings.** It is committed before any run of the test below.
    +Branch `docs/w3-prereg-align` (PR #47; first written on `docs/w3-label-sheet`, PR #43). Date: 2026-10-31. Source: §7 proposal 1 of `reports/W3-RETRIEVAL-DIAG.md` (PR #42). **This note has no results. It changes no search code, no index, no `eval/questions.jsonl`, no grades, and no abstain settings.** It is committed before any run of the test below.
     
     ## Disclosures
     
     - **The author of the hypothesis has seen the blind failures.** The idea came from reading the `plain-blind` misses and from EVAL-GRADE's dense-vs-hybrid result on those same questions. `plain-blind` is therefore not held out for any variant (the author read every blind failure, and the OR-shape rule is close to a long-question detector). It may be reported only as an in-sample check. The confirmatory test is the fresh blind set below, which is required before any accuracy claim, not only before shipping.
     - The exploratory numbers in the diag report (V10, V11) are scratch results from the same questions and are not evidence for any accuracy claim.
    -- The `plain-blind` questions were LLM-written (Grok, `llm-written:grok`), and every `plain-blind` label was proposed by an LLM (Claude) and is unconfirmed by a person. The same holds for all grade-1 labels in `eval/questions.jsonl`.
    +- **Every question and every label used here, selection groups included, is LLM-written or LLM-chosen and unconfirmed by a person** until `eval/review/review-2026-10-30.csv` is filled in (`eval/README.md`, "Human review: pending"). The original 40 questions and their labels, including every grade-2 label in the selection groups that decide `w` and the 12 grade-1 `-p2` labels with no `found_by`, were chosen by the Grok CLI agent (W1-B). The 23 `-plain` rewrites were written by Claude (20 in EVAL-DELEAK, 3 in EVAL-GRADE), and every `status: proposed` label (`llm-proposed:claude`) was proposed by Claude. The 30 `plain-blind` questions were written by Grok (`llm-written:grok`).
     
     ## Labels are re-frozen after Patrick's pass
     
    @@ -39,7 +39,7 @@ Branch `docs/w3-label-sheet`. Date: 2026-10-31. Source: §7 proposal 1 of `repor
     
     ## Fresh-blind-set confirmation (before any accuracy claim)
     
    -Write 20 to 30 new questions, by a person or by an LLM that has not seen the corpus or this repo's questions. The set is confirmatory and is required before any accuracy claim, not only before shipping. Freeze the wording and the labels and commit them before any ranker runs on the set; no ranker may have been run on them. Labelling is done by someone who has not seen the baseline or weighted rankings for them. Then run baseline and the chosen `w` once.
    +Write 20 to 30 new questions, by a person or by an LLM that has not seen the corpus or this repo's questions. The writer must not be a model from a PRC-based developer (AGENTS.md §3), and must not have seen `reports/W3-RETRIEVAL-DIAG.md` or this prereg. The set is confirmatory and is required before any accuracy claim, not only before shipping. Freeze the wording and the labels and commit them before any ranker runs on the set; no ranker may have been run on them. Labelling is done by someone who has not seen the baseline or weighted rankings for them. Relevant passages are found before any ranker runs, by reading the sermons and by plain text search (grep) of the corpus, as in W1-B. FTS5/BM25 and dense search are rankers and may not be used to find them. Then run baseline and the chosen `w` once.
     
     Each question carries a provenance field (for example `person-written` or `llm-written:<model>`). If an LLM writes the set, the report discloses it as LLM-written, and says whether the labels were confirmed by a person.
     
    @@ -49,10 +49,14 @@ Any of the following:
     
     1. The chosen `w` has a negative paired hit@10 difference on the pooled selection groups.
     2. It loses more than one question in any one selection group, or any in `title-keyword` or `scripture-keyword` (those must be unchanged by construction; a change means the rule is wrong).
    -3. On the fresh blind set, the paired difference is not positive, or its 95% CI includes zero together with a loss.
    +3. On the fresh blind set, the 95% paired-bootstrap CI (10,000 resamples, seed recorded) of the paired hit@10 difference includes zero and at least one fresh-set question is lost. The CI is the percentile interval from `preached.stats.paired_bootstrap` (default seed 20261030). A question is lost when a relevant passage is in the top 10 under the baseline and none is in the top 10 under the chosen `w`.
     4. On the fresh blind set, the chosen `w` does not beat baseline in hit@10.
     5. The abstain behaviour or `--dedupe` results degrade versus baseline (more false answers on unanswerable items, or lower hit@10 with `--dedupe`).
     
     `plain-blind` is in-sample and gates nothing; a loss there is reported as a warning.
     
     A mixed result is reported as mixed. It is not rescued by adding a third weight, changing the rule, or editing labels.
    +
    +## Amendments
    +
    +- 2026-10-31, PR #47: plain-blind made in-sample only with the fresh blind set confirmatory (CTO #42 r1), labeller exposure answer recorded (CTO #43 S2), and rule 3, label provenance and fresh-set rules made precise (CTO #47 r1); all made before any run of the frozen test.
