# W3-FUSION-PREREG: pre-registration for proposal #1 (query-shape-aware fusion weight)

Branch `docs/w3-label-sheet`. Date: 2026-10-31. Source: §7 proposal 1 of `reports/W3-RETRIEVAL-DIAG.md` (PR #42). **This note has no results. It changes no search code, no index, no `eval/questions.jsonl`, no grades, and no abstain settings.** It is committed before any run of the test below.

## Disclosures

- **The author of the hypothesis has seen the blind failures.** The idea came from reading the `plain-blind` misses and from EVAL-GRADE's dense-vs-hybrid result on those same questions. `plain-blind` is therefore not a clean test of this hypothesis; the fresh-blind-set step below is.
- The exploratory numbers in the diag report (V10, V11) are scratch results from the same questions and are not evidence for shipping.
- The labels in `eval/questions.jsonl` for `plain-blind`, and all grade-1 labels, are LLM-proposed and unconfirmed by a human.

## Labels are re-frozen after Patrick's pass

`reports/W3-LABEL-SHEET.csv` lists the 24 flagged chunks for Patrick's verdicts. **Labels are to be re-frozen after that pass and before the run**: apply the accepted verdicts to `eval/questions.jsonl` in their own commit, record its hash here, and run nothing until then. No label may change between that commit and the final report. Labels are never edited after seeing a run.

## Frozen change

- Only `Searcher.hybrid` with `fusion="rrf"` changes. It passes `weights=[1.0, w]` to `reciprocal_rank_fusion` (semantic list first, BM25 list second), so `w` is the BM25 weight.
- **Grid: w ∈ {0.5, 0.25}.** No other value is tried. The baseline is w = 1.0 (shipped).
- **OR-shape rule, exact:** `w` applies only when `to_fts_query(query)` (`src/preached/fts.py`) returns a string built with `" OR "`. That is: `scripture_match(query)` is `None` and `content_terms(query)` has more than 4 terms. The AND form (1 to 4 content terms, or no content terms) and the NEAR form (scripture reference) keep weights `[1, 1]`. The rule is evaluated on the query string only, never on results or group labels. The `weighted` fusion is untouched. RRF k stays 60.

## Selection

- **Selection groups:** `plain` (25), `names-topic` (23), `title-keyword` (3), `scripture-keyword` (7). Unanswerable items are not scored.
- Metric: lenient hit@10 on the raw ranker path (`search/bench.py` without `--dedupe`), `granite-english-r2`, with the re-frozen labels. Pick the `w` with the higher pooled hit@10 over the selection groups. **A tie goes to the milder weight (0.5).**
- Both weights are also reported in full for every group, with the paired win/tie/loss counts against baseline.
- **`plain-blind` is reported once, after `w` is chosen, as the held-out number.** It does not influence the choice, and it is not rerun after any other change.

## Required reruns

- `search/bench.py --abstain` on baseline and the chosen `w`, on both the raw and `--dedupe` paths. Report the abstain rate on answerable and on unanswerable items.
- `--dedupe` on baseline and chosen `w` for all groups.
- The abstain floor in `search/abstain.toml` is **not refit**, and not on proposed labels.

## Fresh-blind-set confirmation (before any ship)

Write 20 to 30 new questions, by a person or by an LLM that has not seen the corpus or this repo's questions. No ranker may have been run on them. Freeze the wording and label them, with the labelling done by someone who has not seen the baseline or weighted rankings for them, then run baseline and the chosen `w` once.

## What means "do not ship"

Any of the following:

1. The chosen `w` has a negative paired hit@10 difference on the pooled selection groups.
2. It loses more than one question in any one selection group, or any in `title-keyword` or `scripture-keyword` (those must be unchanged by construction; a change means the rule is wrong).
3. On held-out `plain-blind`, the paired difference is not positive, or its 95% CI includes zero together with a loss on the fresh blind set.
4. On the fresh blind set, the chosen `w` does not beat baseline in hit@10.
5. The abstain behaviour or `--dedupe` results degrade versus baseline (more false answers on unanswerable items, or lower hit@10 with `--dedupe`).

A mixed result is reported as mixed. It is not rescued by adding a third weight, changing the rule, or editing labels.
