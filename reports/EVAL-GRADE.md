# EVAL-GRADE: wider grading and blind plain questions for the eval (PR #17)

Branch `feat/eval-deleak` (PR #17), after merging `origin/main` (PR #10 and #14) and `origin/feat/eval-plainq`. Agent: Claude (Opus 5.5). Date: 2026-10-30.

**Nothing in search, fusion, the default model, or `search/abstain.toml` changed.** Every label added here has status `"proposed"` until Patrick confirms it in the review sheet. Nothing was fitted or tuned on proposed labels.

## Bottom line

Headline for the default (Granite English R2 + BM25, hybrid RRF). Every nDCG is shown next to sermon@10 and sermon@50 (CTO should-fix a):

| group | n | nDCG@10 strict | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| plain | 25 | 0.028 | 0.132 | 0.08 | **0.72** | 0.56 | 0.84 |
| plain-blind | 28 | 0.032 | 0.027 | 0.07 | **0.11** | 0.36 | 0.82 |
| names-topic | 23 | 0.480 | 0.402 | 0.70 | 0.96 | 0.96 | 0.96 |

hit@10 means at least one labelled passage is in the top 10. Strict counts grade-2 labels only. Lenient also counts the proposed grade-1 labels.

- **On `plain`, the 0.028 is mostly narrow labels.** Counting every passage a reader judged acceptable, the default puts one in the top 10 for 18 of 25 `plain` questions (0.72 [0.52, 0.88]). Strict, it does so for 2. Lenient nDCG@10 is 0.132, still low, because these questions now have 3 to 22 acceptable passages each, which raises the ideal.
- **On questions written blind to the corpus, retrieval really is failing.** The default finds an acceptable passage in the top 10 for 3 of 28 answerable `plain-blind` questions (0.11 [0.00, 0.21]), and the right sermon in the top 10 for 10 of 28. sermon@50 is 0.82, so the material is reachable but ranked too low. These labels were picked from the same rankers' top 20 plus the grader's own corpus search, so this is not a pooling artefact.
- **BM25 is what drags the default down on blind questions.** Granite dense alone has lenient hit@10 0.39 vs 0.11 for the default on `plain-blind`: +0.29 [+0.14, +0.46], with 8 wins and 0 losses. On `plain` the two are tied (−0.04 [−0.20, +0.12]). On `names-topic` dense alone is worse on lenient nDCG (−0.064 [−0.12, −0.01]). **I did not change anything.** Patrick decides, after confirming labels.
- **The 0.8129 abstain floor holds on the old set but not with `plain-blind`.**
  - Refit on the 63 questions without `plain-blind`: 0.8129, unchanged.
  - Refit on all 93: 0.7753, with abstain recall 0 on the unanswerable questions.
  - With the shipped floor, 2 answerable blind questions would show "nothing found" (`p-016` "help i messed up bad", `p-017` "why wont he answer"). The 2 blind unanswerable questions score above the floor.
  - The lowest `plain` top cosine is now `q-worry-plain` at 0.7998. That is 0.013 *below* the floor; BM25/dense agreement keeps it at `weak`.
  - I did not write the floor.
- **Review sheet:** `eval/review/review-2026-10-30.csv` (93 rows).

## 1. What was done

1. **Merges.**
   - `origin/main` into `feat/eval-deleak` (merge commit `9ad3f80`). One conflict in `search/bench.py`, where #10 changed the docstring and report fields and #17 added groups. I kept both sides. Full tests: 362 OK.
   - `origin/feat/eval-plainq` (Grok's 30 blind questions, `60b0db3`). It merged cleanly.
2. **CTO should-fix from #10:** `search/query.py` now prints an `ArtifactError` (missing or bad ONNX artifact) as one `error: ...` line and exits 1, with no traceback. Test: `test_query_artifact_error_is_one_line`.
3. **Leak lint (CTO should-fixes c and d)**, in `scripts/check_title_leak.py`:
   - **Quote and scripture phrases (c).** A `plain` question fails if it shares two consecutive content words (stopwords skipped, stems compared) with its grade-2 quote, or with the key scripture of its grade-2 sermon (`eval/key_scripture.json`, rebuilt from the corpus with `--write-scripture`). A pair made only of generic words ("God", "Lord", "Jesus") does not count.
   - **Title words (d).** 3-letter title words now count ("sin"). `-ial`/`-ied` and doubled consonants stem together ("denied" ~ "Self-denial", "sinning" ~ "sin"). There is a short hand-picked synonym list per title (`SYNONYMS`; for example devil → Satan's Devices, grief → Mourning, gossip → Evil-speaking). Paraphrases such as "weighed down" are deliberately not in it.
   - **Expected sermons only.** Title checks use the expected (non-proposed) labels. The wide grade-1 labels come from sermons like *Born of God*, which would otherwise make "God" a leak.
   - **`plain-blind` is reported, not failed.** Its wording is frozen. One note: `p-003` says "money", a title word of *The Use of Money*. It was written blind, so this is a coincidence, not a leak.
   - **Results.** The new checks flagged `q-worry` ("taking thought"), `q-assurance` ("child of God", "assurance") and also `q-faith-works` ("good works" in its quote, "saved by faith" from Eph 2:8). Each moved to `names-topic` and got a `-plain` twin with the same labels. The original lines are unchanged apart from `group`. The 20 accepted rewrites all pass and were not touched.
   - **Tests:** 7 new tests in `tests/test_eval_leak.py`.
4. **Wider grading (step 1)**, a pooled method that can be rerun:
   1. `eval/pool.py` pools, per question family, the top 20 of BM25 and of each of 3 models × 3 modes (EmbeddingGemma 2, Granite English R2, Arctic v1; dense, hybrid RRF, hybrid weighted). A family is an original plus its `-plain` twin, since they share labels.
      - Its top 10 matched the bench's lists on all 550 question × ranker pairs.
      - Pool size: 85 chunks per family on average (38–150).
      - The reading file also holds every other chunk of the grade-2 sermon (the "own reading" pass).
      - `eval/pool/pool-2026-10-30.jsonl` is committed (ids and ranks).
   2. Readers judged every pooled chunk against the bar in `eval/pool/BRIEF.md`: shown alone, it gives the asker a real piece of Wesley's answer, not just the topic. One label per passage, and none on a chunk already labelled. For `plain-blind` questions they also searched the corpus (grep, BM25) beyond the pool. **The readers were 11 Claude subagents (LLM), not people.** One pass covered the extra chunks the three new twins pulled in; it added 6 labels.
   3. `eval/apply_grades.py --check` validated every judgment: quote in its chunk, 6–60 words, one-line reason, no shared chunks. `eval/validate.py` passes.
   4. Existing labels are unchanged. Each new label has `status: "proposed"`, a one-line `reason`, and `found_by`.
5. **New questions (step 2).** All 30 `plain_candidates.jsonl` questions are now in `questions.jsonl` as group `plain-blind`, with the wording byte-identical.
   - 28 answerable, each with a proposed grade-2 label and 0–8 grade-1 labels.
   - 2 unanswerable, each with a reason:
     - `p-004`: a spouse giving up on the marriage.
     - `p-023`: missing church for a Sunday shift.
   - 0 excluded.
6. **Bench.** `search/bench.py` scores three label sets:
   - pre-grading: the plain metric names. These reproduce EVAL-DELEAK exactly: 2,750 per-question metric and top-10 comparisons, 0 differences.
   - `_strict`: grade 2 only.
   - `_lenient`: adds the proposed grade-1 labels.

   It adds `hit@10`, `sermon@10`, and `sermon@50`. sermon@50 comes from a separate limit-50 call, so the scored top 10 is the same call as before. Items marked `excluded` are skipped, and `--questions` / `--exclude-group` can rerun an older set. The Markdown has a strict vs lenient table per group.
7. **Review sheet (step 4).** `scripts/review_sheet.py` writes `eval/review/review-2026-10-30.csv` with the requested columns. The grade-2 cell holds the whole chunk with the labelled quote marked « ». Already-existing grade-1 labels are listed after it as unchanged. `.gitignore` ignored every `review/` directory (that rule protects privacy-review output), so I added an exception for `/eval/review/` only.

### Labels added

| | count |
| --- | --- |
| proposed grade-1 on the 35 existing answerable families | 456 (median 13 per family, range 3–22) |
| … of which on `names-topic`/`plain` twin families | 343 |
| … on `q-prayer` + `q-forgiveness` | 14 |
| … on keyword items (scripture 58, title 41) | 99 |
| proposed grade-2 on `plain-blind` | 28 |
| proposed grade-1 on `plain-blind` | 102 (median 4) |
| **total proposed** | **586** |

Twins share labels, so a family's labels are counted once.

## 2. How to run it

```bash
cd /work/preached/.worktrees/feat/eval-deleak
uv run python scripts/check_title_leak.py                      # lint (exit 1 on a plain leak)
uv run --group bench eval/pool.py                              # pool -> eval/pool/pool-<date>.jsonl, /cache/eval-pool/<date>/
#   ... readers write /cache/eval-pool/<date>/grades/<family>.json per eval/pool/BRIEF.md ...
uv run python eval/apply_grades.py --check /cache/eval-pool/2026-10-30/grades
uv run python eval/apply_grades.py --pool eval/pool/pool-2026-10-30.jsonl /cache/eval-pool/2026-10-30/grades
uv run python eval/validate.py                                 # quotes vs chunks (slow now: ~700 quotes)
uv run --group bench search/bench.py --tag grade --note "..."  # comparison
uv run --group bench search/bench.py --abstain --models granite-english-r2 embeddinggemma-2 --tag grade
uv run --group bench search/bench.py --abstain --models granite-english-r2 embeddinggemma-2 --tag grade-noblind --exclude-group plain-blind
uv run python scripts/grade_summary.py eval/results/2026-10-30-grade.json   # the tables below
uv run python scripts/review_sheet.py                          # eval/review/review-<date>.csv
uv run python -m unittest discover -s tests
```

Results: `eval/results/2026-10-30-grade.{json,md}`, `eval/results/2026-10-30-abstain-grade.{json,md}`, `eval/results/2026-10-30-abstain-grade-noblind.{json,md}`. Same models, revisions, prompts, fp32, RRF k=60, weighted 0.5, and bootstrap seed as EVAL-DELEAK. Corpus vectors were cached (fingerprints match). Queries ran on CPU.

## 3. Results

Per group, every model. Columns: nDCG@10 under the three label sets, hit@10 strict and lenient, and sermon@5/10/50. ⚠ = lineage unclear, eval-only. `unanswerable` is in the abstain section.

### plain (25)

| model | mode | n | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 25 | 0.000 | 0.004 | 0.037 | 0.000 | 0.320 | 0.120 | 0.200 | 0.640 |
| embeddinggemma-2 | dense | 25 | 0.028 | 0.028 | 0.148 | 0.080 | 0.800 | 0.520 | 0.600 | 0.880 |
| embeddinggemma-2 | hybrid_rrf | 25 | 0.013 | 0.013 | 0.110 | 0.040 | 0.680 | 0.320 | 0.520 | 0.800 |
| embeddinggemma-2 | hybrid_weighted | 25 | 0.000 | 0.000 | 0.096 | 0.000 | 0.680 | 0.320 | 0.480 | 0.800 |
| granite-english-r2 | dense | 25 | 0.078 | 0.078 | 0.152 | 0.200 | 0.680 | 0.400 | 0.600 | 0.880 |
| granite-english-r2 | hybrid_rrf | 25 | 0.028 | 0.028 | 0.132 | 0.080 | 0.720 | 0.400 | 0.560 | 0.840 |
| granite-english-r2 | hybrid_weighted | 25 | 0.025 | 0.025 | 0.108 | 0.080 | 0.680 | 0.400 | 0.560 | 0.800 |
| arctic-embed-l ⚠ | dense | 25 | 0.105 | 0.105 | 0.160 | 0.120 | 0.800 | 0.520 | 0.640 | 0.880 |
| arctic-embed-l ⚠ | hybrid_rrf | 25 | 0.030 | 0.030 | 0.115 | 0.080 | 0.760 | 0.440 | 0.680 | 0.920 |
| arctic-embed-l ⚠ | hybrid_weighted | 25 | 0.062 | 0.062 | 0.111 | 0.120 | 0.680 | 0.400 | 0.560 | 0.880 |

### plain-blind (28 answerable)

| model | mode | n | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 28 | 0.000 | 0.000 | 0.011 | 0.000 | 0.107 | 0.143 | 0.143 | 0.429 |
| embeddinggemma-2 | dense | 28 | 0.066 | 0.066 | 0.068 | 0.143 | 0.321 | 0.429 | 0.500 | 0.750 |
| embeddinggemma-2 | hybrid_rrf | 28 | 0.038 | 0.038 | 0.037 | 0.071 | 0.143 | 0.286 | 0.286 | 0.750 |
| embeddinggemma-2 | hybrid_weighted | 28 | 0.028 | 0.028 | 0.030 | 0.071 | 0.179 | 0.286 | 0.393 | 0.786 |
| granite-english-r2 | dense | 28 | 0.080 | 0.080 | 0.073 | 0.214 | 0.393 | 0.321 | 0.536 | 0.893 |
| granite-english-r2 | hybrid_rrf | 28 | 0.032 | 0.032 | 0.027 | 0.071 | 0.107 | 0.357 | 0.357 | 0.821 |
| granite-english-r2 | hybrid_weighted | 28 | 0.047 | 0.047 | 0.042 | 0.143 | 0.214 | 0.286 | 0.429 | 0.786 |
| arctic-embed-l ⚠ | dense | 28 | 0.046 | 0.046 | 0.054 | 0.071 | 0.286 | 0.179 | 0.321 | 0.679 |
| arctic-embed-l ⚠ | hybrid_rrf | 28 | 0.018 | 0.018 | 0.032 | 0.036 | 0.214 | 0.143 | 0.214 | 0.679 |
| arctic-embed-l ⚠ | hybrid_weighted | 28 | 0.036 | 0.036 | 0.044 | 0.036 | 0.250 | 0.214 | 0.250 | 0.679 |

### names-topic (23)

| model | mode | n | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 23 | 0.277 | 0.272 | 0.279 | 0.565 | 0.913 | 0.913 | 0.913 | 1.000 |
| embeddinggemma-2 | dense | 23 | 0.302 | 0.297 | 0.320 | 0.609 | 1.000 | 0.783 | 0.957 | 1.000 |
| embeddinggemma-2 | hybrid_rrf | 23 | 0.420 | 0.416 | 0.389 | 0.652 | 1.000 | 0.957 | 0.957 | 0.957 |
| embeddinggemma-2 | hybrid_weighted | 23 | 0.406 | 0.403 | 0.396 | 0.696 | 1.000 | 0.957 | 0.957 | 1.000 |
| granite-english-r2 | dense | 23 | 0.371 | 0.360 | 0.338 | 0.565 | 0.913 | 0.826 | 0.913 | 1.000 |
| granite-english-r2 | hybrid_rrf | 23 | 0.480 | 0.472 | 0.402 | 0.696 | 0.957 | 0.957 | 0.957 | 0.957 |
| granite-english-r2 | hybrid_weighted | 23 | 0.447 | 0.438 | 0.398 | 0.696 | 0.957 | 0.957 | 0.957 | 1.000 |
| arctic-embed-l ⚠ | dense | 23 | 0.391 | 0.377 | 0.382 | 0.609 | 1.000 | 0.826 | 0.870 | 0.957 |
| arctic-embed-l ⚠ | hybrid_rrf | 23 | 0.427 | 0.421 | 0.388 | 0.696 | 1.000 | 0.957 | 0.957 | 0.957 |
| arctic-embed-l ⚠ | hybrid_weighted | 23 | 0.462 | 0.453 | 0.416 | 0.739 | 1.000 | 0.913 | 0.957 | 0.957 |

### title-keyword (3)

| model | mode | n | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 3 | 0.544 | 0.544 | 0.462 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| embeddinggemma-2 | dense | 3 | 0.544 | 0.544 | 0.519 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| embeddinggemma-2 | hybrid_rrf | 3 | 0.544 | 0.544 | 0.479 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| embeddinggemma-2 | hybrid_weighted | 3 | 0.667 | 0.667 | 0.543 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | dense | 3 | 1.000 | 1.000 | 0.661 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | hybrid_rrf | 3 | 0.667 | 0.667 | 0.544 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | hybrid_weighted | 3 | 0.767 | 0.767 | 0.561 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| arctic-embed-l ⚠ | dense | 3 | 0.649 | 0.649 | 0.562 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| arctic-embed-l ⚠ | hybrid_rrf | 3 | 0.544 | 0.544 | 0.450 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| arctic-embed-l ⚠ | hybrid_weighted | 3 | 0.667 | 0.667 | 0.482 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |

### scripture-keyword (7)

| model | mode | n | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 7 | 0.876 | 0.876 | 0.486 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embeddinggemma-2 | dense | 7 | 0.842 | 0.842 | 0.488 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embeddinggemma-2 | hybrid_rrf | 7 | 0.947 | 0.947 | 0.586 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| embeddinggemma-2 | hybrid_weighted | 7 | 0.947 | 0.947 | 0.555 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | dense | 7 | 0.704 | 0.704 | 0.394 | 0.857 | 0.857 | 0.714 | 0.714 | 0.857 |
| granite-english-r2 | hybrid_rrf | 7 | 0.895 | 0.895 | 0.513 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | hybrid_weighted | 7 | 0.895 | 0.895 | 0.519 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| arctic-embed-l ⚠ | dense | 7 | 0.313 | 0.313 | 0.201 | 0.571 | 0.571 | 0.571 | 0.571 | 1.000 |
| arctic-embed-l ⚠ | hybrid_rrf | 7 | 0.847 | 0.847 | 0.506 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| arctic-embed-l ⚠ | hybrid_weighted | 7 | 0.876 | 0.876 | 0.498 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### overall (86 answerable)

| model | mode | n | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 86 | 0.164 | 0.164 | 0.145 | 0.256 | 0.488 | 0.442 | 0.465 | 0.709 |
| embeddinggemma-2 | dense | 86 | 0.198 | 0.196 | 0.208 | 0.337 | 0.721 | 0.616 | 0.709 | 0.884 |
| embeddinggemma-2 | hybrid_rrf | 86 | 0.224 | 0.223 | 0.213 | 0.314 | 0.628 | 0.558 | 0.616 | 0.849 |
| embeddinggemma-2 | hybrid_weighted | 86 | 0.218 | 0.217 | 0.208 | 0.314 | 0.640 | 0.558 | 0.640 | 0.872 |
| granite-english-r2 | dense | 86 | 0.240 | 0.237 | 0.214 | 0.384 | 0.674 | 0.535 | 0.686 | 0.919 |
| granite-english-r2 | hybrid_rrf | 86 | 0.243 | 0.241 | 0.216 | 0.337 | 0.616 | 0.605 | 0.651 | 0.884 |
| granite-english-r2 | hybrid_weighted | 86 | 0.242 | 0.239 | 0.213 | 0.372 | 0.640 | 0.581 | 0.674 | 0.872 |
| arctic-embed-l ⚠ | dense | 86 | 0.198 | 0.195 | 0.202 | 0.302 | 0.674 | 0.512 | 0.605 | 0.849 |
| arctic-embed-l ⚠ | hybrid_rrf | 86 | 0.217 | 0.215 | 0.204 | 0.326 | 0.674 | 0.547 | 0.640 | 0.860 |
| arctic-embed-l ⚠ | hybrid_weighted | 86 | 0.248 | 0.245 | 0.215 | 0.349 | 0.663 | 0.547 | 0.616 | 0.849 |

Lenient nDCG is *lower* than strict on the keyword groups and `names-topic`. That is expected: a keyword query like `Romans 8:16` now has 14 acceptable passages, so the ideal DCG rises faster than what the top 10 finds. On groups with many acceptable passages, read hit@10 and MRR@10 lenient rather than lenient nDCG.

### Paired Δ against Granite hybrid RRF (95% CI, wins/ties/losses)

| group | row | Δ hit@10 lenient | Δ nDCG@10 lenient | Δ sermon@10 |
| --- | --- | --- | --- | --- |
| plain | Granite dense | −0.040 [−0.20, +0.12] (2/20/3) | +0.020 [−0.02, +0.06] | +0.040 [−0.16, +0.24] |
| plain | Gemma 2 dense | +0.080 [−0.12, +0.28] (4/19/2) | +0.016 [−0.03, +0.07] | +0.040 [−0.16, +0.24] |
| plain | Arctic dense ⚠ | +0.080 [−0.16, +0.32] (6/15/4) | +0.028 [−0.03, +0.10] | +0.080 [−0.20, +0.36] |
| plain | BM25 | −0.400 [−0.60, −0.20] (0/15/10) | | |
| plain-blind | Granite dense | **+0.286 [+0.14, +0.46] (8/20/0)** | +0.046 [+0.01, +0.08] | +0.179 [+0.00, +0.36] |
| plain-blind | Gemma 2 dense | +0.214 [+0.04, +0.39] (7/20/1) | +0.040 [+0.00, +0.08] | +0.143 [+0.00, +0.32] |
| plain-blind | Arctic dense ⚠ | +0.179 [+0.00, +0.36] (6/21/1) | +0.027 [−0.02, +0.08] | −0.036 [−0.21, +0.14] |
| names-topic | Granite dense | −0.043 [−0.17, +0.09] | −0.064 [−0.12, −0.01] | −0.043 [−0.13, +0.00] |

### CTO cross-check (on the same 25 `plain` ids the CTO used, i.e. EVAL-DELEAK's set)

| | CTO | this run |
| --- | --- | --- |
| Granite hybrid sermon@10 / sermon@50 | 15/25, 21/25 | 15/25, 21/25 |
| Granite dense sermon@10 / sermon@50 | 17/25, 24/25 | 16/25, 23/25 |
| share of default top-10 slots that look relevant but are unlabelled | 28% (12 questions) | 16% hold a proposed label (40 of 250 slots, all 25) |
| lenient hit@10, default | — | 19/25 |

The hybrid counts match. Dense is one question lower on each; I did not find why (possibly the CTO's run used another query-vector path). The CTO's 28% was an eyeball estimate. Ours is stricter: the bar asks for an answer to the question, not just relevance to it.

### Lint

```
$ uv run python scripts/check_title_leak.py
questions.jsonl: 93 questions; groups {"names-topic": 23, "plain": 25, "plain-blind": 30, "scripture-keyword": 7, "title-keyword": 3, "unanswerable": 5}
note p-003 (plain-blind, wording frozen): title word "money" (The Use of Money) ~ "money"
plain questions checked: 25; leaking: 0
plain-blind questions checked: 30; overlapping (note only): 1
```

Negative control: the same file with the 23 `names-topic` originals moved to `plain` flags all 23 (`leaking: 23`).

### Abstain floor recheck (API path, hybrid, k=10; not written)

| set | model | refit floor | shipped | unanswerable abstained (LOO) | false abstain (LOO) |
| --- | --- | --- | --- | --- | --- |
| 63 (no plain-blind) | Granite | 0.8129 | 0.8129 | 3/5 | 0 |
| 63 (no plain-blind) | Gemma 2 | 0.7413 | 0.7413 | 3/5 | 0 |
| 93 (all) | Granite | **0.7753** | 0.8129 | 0/7 | 1/86 |
| 93 (all) | Gemma 2 | **0.6735** | 0.7413 | 0/7 | 1/86 |

With the **shipped** Granite floor (0.8129) on all 93 questions:

- **Unanswerable:** 4/5 originals abstain. `p-004` (0.8202) and `p-023` (0.8363) do not.
- **Answerable `plain-blind`:** 2 of 28 abstain (`p-016` 0.7754, `p-017` 0.7985) and 9 are `weak`.
- **`plain`:** 0 abstain and 1 is `weak`. That one is `q-worry-plain` at 0.7998, so the old +0.0095 margin is now −0.0131.

Gemma 2 with its shipped floor has 1 blind abstain (`p-016`) and 21 of 28 blind questions `weak`.

In short, the floor is set by `u-book-of-mormon` (0.8129). Short, vague, real-user questions sit below it. A refit that avoids false abstains drops below every unanswerable question and abstains on nothing. **Recommendation:** do not refit on proposed labels (that would break should-fix b). After Patrick confirms which blind questions are answerable, decide whether the floor should keep "nothing found" at all, or only rank-order the `weak` banner.

## 4. What it means: "retrieval is failing" vs "labels too narrow"

- **Labels too narrow** explains most of the `plain` 0.028. With acceptable passages counted, the default puts one in the top 10 for 72% of `plain` questions. 16% of all its top-10 slots there are acceptable but were unlabelled.
- **Retrieval failing** is real for the blind questions: 11% lenient hit@10 and 36% sermon@10. These questions were written by someone who never saw the corpus (short, emotional, modern), so they are the closest thing we have to real users.
  - Dense alone does about 3.5× better there (0.39). Fusing with BM25 hurts because the lexical list is noise for "help i messed up bad".
  - sermon@50 is ~0.82 for every model, so the passages exist and a better ranker could reach them.
- **Mixed on `plain` rewrites.** The rewrites keep enough doctrinal vocabulary that hybrid does as well as dense.
- So both diagnoses are right, for different populations. Before any fusion change, Patrick should confirm the labels (especially `plain-blind`), and the next comparison should lead with `plain-blind` lenient hit@10 and sermon@10.

## 5. Open issues, risks, exclusions

- **All 586 new labels are an LLM's judgment** (Claude subagents, 11 passes), not a person's. They are status `proposed`, and Patrick confirms them in the CSV. Spot check: I read 12 random labels and all met the bar. The graders' borderline notes, which belong in the review:
  - `p-020` (fear of becoming an abusive parent): grade-2 only, from *On Family Religion*. The grader suggests it may be unanswerable.
  - `p-009` (lonely at church) and `p-027` (dating app) are answerable on a loose reading.
  - `p-023` could flip to answerable with *On Zeal*.
  - The five "probably unanswerable" modern questions (`p-026`–`p-030`) were all judged answerable: Wesley speaks to the underlying need (sleep and time, choosing a spouse, fear of tomorrow, gathering for worship) without naming the app, AI, or livestream. That is a judgment call and it matters for the abstain eval.
  - Some grade-2 passages for grief or doubt are stern in tone (*On Mourning for the Dead* calls prolonged grief sinful). Graders avoided harsh passages where they could, and say so in the reasons.
- **Pooling bias.** The pool is the union of the evaluated rankers' top 20, so lenient metrics favour pooled systems over a future unpooled one. The "own reading" pass (the rest of the grade-2 sermon, plus corpus search on `plain-blind`) reduces this but does not remove it.
- **Grader quote length.** About 35 quotes are 41–52 words, over the brief's 10–40 target but inside the 6–60 check.
- **Adjacent chunks.** A few families have labels on two neighbouring chunks that make separate numbered points (the grader's notes name `wesley-029-c0043/c0044` and others). The check forbids only a shared chunk. Patrick may want to drop one of each pair.
- **Twins share labels.** A `-plain` rewrite carries its original's full label list. A grade-1 passage chosen for the titled wording is not always ideal for the rewrite.
- **`q-worry-plain`, `q-assurance-plain`, `q-faith-works-plain`** are new LLM-written rewrites. They were committed (`5a5369f`) before any model ran on them.
- **PR #17 body:** this environment has no `gh` CLI and no GitHub token, so I could not edit it. The text is in `reports/EVAL-GRADE-pr-body.md` to paste.
- **`eval/validate.py` is slow** now (about 2 minutes, quotes × chunks). It is unchanged apart from skipping excluded items.
- **Not done, per the brief:** no change to search, fusion weights, the default model, or `search/abstain.toml`.

## 6. Dependencies added

None. `uv lock --check`: `Resolved 79 packages`, exit 0.

## Tests

`uv run python -m unittest discover -s tests`: **369 tests, OK**. That is 362 after the main merge, plus 1 in `tests/test_embed_backend.py` (ArtifactError one line) and 6 in `tests/test_eval_leak.py` (3-letter words, inflections and synonyms, quote/scripture phrases, proposed-title skip, `plain-blind` not failing, proposed labels marked).
