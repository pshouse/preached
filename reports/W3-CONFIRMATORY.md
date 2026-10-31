# W3-CONFIRMATORY: run of the frozen fusion test under `reports/W3-FUSION-PREREG.md`

Branch `eval/w3-confirmatory`, from merged main **`387e9599796f467a7d5cac82e438314b3f347d37`** (the #50 merge). Date: 2026-10-31. Everything below was run from that commit. The branch adds only this report.

## Headline

- **`w = 0.5`**, chosen by the pre-declared rule alone (pooled lenient hit@10 on the 58 answerable selection questions: 51 for 0.5 and 50 for 0.25, so no tie; baseline 50).
- **The fresh blind set does not exist, so the confirmatory test was not run.** The prereg calls that set "the confirmatory test", "required before any accuracy claim, not only before shipping". `eval/` has no such set: the groups are `plain` 25, `names-topic` 23, `title-keyword` 3, `scripture-keyword` 7, `plain-blind` 30 and `unanswerable` 5. I could not write one: the writer must not have seen the corpus, this repo's questions or the prereg, and I have seen all three. So "do not ship" rules 3 and 4 **cannot be evaluated**. **This run supports no accuracy claim.**
- Of the rules that could be evaluated, none fires: rule 1 (pooled paired difference +0.017, not negative), rule 2 (one names-topic loss, no keyword-group change) and rule 5 (abstain on unanswerable items unchanged; `--dedupe` pooled selection hit@10 unchanged). Several metrics go against `w = 0.5`. They are listed in §4 and are not hidden by the headline.
- **Disclosure:** every question and label scored here was written or chosen by an LLM (Grok and Claude), except the three grade-2 labels and seven partial verdicts Patrick judged on the blind sheet. Details are in §6.

## 1. Pre-run checks (CTO conditions a–d)

**(a) Frozen files.** sha256 in this checkout against the #50 merge tree (`git show 387e959:<path> | sha256sum`):

| file | sha256 (checkout = 387e959 tree) |
| --- | --- |
| `reports/W3-FUSION-PREREG.md` | `adae5bd30b85b7f7a87071257801c29a6bfe3887681343a04eef2bda33e3997c` MATCH |
| `eval/questions.jsonl` | `5f8d0918888747c2a281d31c95c56ca7edbff659373ab2fcccfe309baad12c53` MATCH |
| `eval/partial_verdicts.jsonl` | `730692bcf6a089e8c4de6ca7c61e479427dd1a7010fc2e7f0cbec24bd643887f` MATCH |
| `reports/W3-LABEL-VERDICTS.csv` | `99837f0e1470a34c8cc7f1f7448c2faaf4fb61239c495c1a75be6ab981332fe8` MATCH (starts `99837f0e`, ends `332fe8`, as the CTO gave it) |

`git diff ecc3f67 387e959 -- eval/questions.jsonl eval/partial_verdicts.jsonl` is empty: the label files are exactly as in the recorded label commit `ecc3f67`. Nothing differed, so the run went ahead.

**(b) S4, the first step.** `PREACHED_CACHE=/cache` (the cache root holding `corpus/`, not `/cache/index`). Full output:

```
$ PREACHED_CACHE=/cache uv run --frozen python -m unittest -v tests.test_eval_leak
test_confirmed_label_needs_a_valid_sheet_row (tests.test_eval_leak.TitleLeakTest.test_confirmed_label_needs_a_valid_sheet_row) ... ok
test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk (tests.test_eval_leak.TitleLeakTest.test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk) ... ok
test_each_names_topic_question_has_a_plain_rewrite_with_the_same_labels (tests.test_eval_leak.TitleLeakTest.test_each_names_topic_question_has_a_plain_rewrite_with_the_same_labels) ... ok
test_enemy_and_trick_are_synonyms_of_satans_devices (tests.test_eval_leak.TitleLeakTest.test_enemy_and_trick_are_synonyms_of_satans_devices) ... ok
test_every_question_has_a_known_group (tests.test_eval_leak.TitleLeakTest.test_every_question_has_a_known_group) ... ok
test_fell_away (tests.test_eval_leak.TitleLeakTest.test_fell_away) ... ok
test_inflection_and_synonym_of_title (tests.test_eval_leak.TitleLeakTest.test_inflection_and_synonym_of_title) ... ok
test_key_segment_quotes_are_key_segments_of_their_row (tests.test_eval_leak.TitleLeakTest.test_key_segment_quotes_are_key_segments_of_their_row) ... ok
test_modern_verse_wording (tests.test_eval_leak.TitleLeakTest.test_modern_verse_wording) ... ok
test_partial_verdicts_are_verdict_1_labels_with_exact_mirrors (tests.test_eval_leak.TitleLeakTest.test_partial_verdicts_are_verdict_1_labels_with_exact_mirrors) ... ok
test_plain_blind_leaks_do_not_fail (tests.test_eval_leak.TitleLeakTest.test_plain_blind_leaks_do_not_fail) ... ok
test_plain_questions_do_not_share_title_words (tests.test_eval_leak.TitleLeakTest.test_plain_questions_do_not_share_title_words) ... ok
test_proposed_grade1_titles_are_not_checked (tests.test_eval_leak.TitleLeakTest.test_proposed_grade1_titles_are_not_checked) ... ok
test_proposed_labels_are_marked_and_explained (tests.test_eval_leak.TitleLeakTest.test_proposed_labels_are_marked_and_explained) ... ok
test_quote_and_scripture_phrases_leak (tests.test_eval_leak.TitleLeakTest.test_quote_and_scripture_phrases_leak) ... ok
test_single_distinctive_word (tests.test_eval_leak.TitleLeakTest.test_single_distinctive_word) ... ok
test_stemming_matches_inflections (tests.test_eval_leak.TitleLeakTest.test_stemming_matches_inflections) ... ok
test_stopwords_and_short_words_are_ignored (tests.test_eval_leak.TitleLeakTest.test_stopwords_and_short_words_are_ignored) ... ok
test_three_letter_title_words_count (tests.test_eval_leak.TitleLeakTest.test_three_letter_title_words_count) ... ok

----------------------------------------------------------------------
Ran 19 tests in 1.583s

OK
```

19 tests, 0 skips. The anchor test `test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk` ran and passed.

**(c) Private index, read-only.** `/cache/index/wesley.sqlite` was opened only with `mode=ro&immutable=1` plus `PRAGMA query_only`. It was not copied and not written. sha256 of the file and its sidecars before the run, after both phases, and again after the full test suite:

```
909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b  wesley.sqlite      (mtime 2026-10-30 15:39:09.550258600)
fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb  wesley.sqlite-shm  (mtime 2026-10-31 11:31:44.800632829)
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  wesley.sqlite-wal  (mtime 2026-10-31 05:53:14.896741796)
```

All three were identical each time, with the same mtimes. Index content as read by the run: 8,383 chunks, 8,383 `granite-english-r2` vectors (fingerprint `13e0ed78bb32d86b`, fp32), `chunks_sha256` `198339132f68…e363b2`, and row content hash `801b4552f494…eee375`. These are the values `reports/W3-RETRIEVAL-DIAG.md` §8 publishes.

**Why `search/bench.py` was not run directly.** bench opens its `--index` with the writer `store.connect`, which migrates the file and re-syncs chunks into it (`ensure_chunks`). That is why the diag ran it on a copy, and (c) forbids both writing and copying. The run therefore uses a scratch script that calls **bench's own scoring code**: `bench.evaluate` (raw `hybrid_rrf` top 10, plus a separate top-50 call, as bench does), `bench.score`/`label_set` (lenient = every label), `api_search` for `--dedupe` (via `run_mode`), and `abstain.search_with_confidence`, `bench.abstain_summary` and `bench.abstain_eval` for abstain. Query vectors are Granite English R2 on CPU through torch (`load_model(spec, device="cpu")` and `encode_query`, dtype fp32), exactly as in bench's `cpu_eval`.

**(d)** `MKL_ENABLE_INSTRUCTIONS=AVX512` was set for every run. No ONNX backend was used; the queries were encoded with torch, which is bench's default.

## 2. How the frozen change was applied

- The script lives in `/cache/w3-confirmatory/run.py` (sha256 `f4172c8ddf5813e4879ce970a1f25b9495feb91ce22b7dc0ba17bb593eb05ff9`) and is reproduced verbatim in the appendix. It is outside the repo, so this branch changes no code or tests. A `.py` file under `reports/` would also have needed a new `RAW_CONNECTS` entry in `tests/test_hard_conditions.py`.
- `w = 1.0` (baseline) is the unmodified product `Searcher`. For `w` in {0.5, 0.25}, a `Searcher` subclass overrides `hybrid`. When `fusion == "rrf"` and the query is OR-shape, it passes `weights=[1.0, w]` (semantic first, BM25 second) to `reciprocal_rank_fusion` with k = 60. Otherwise it calls the shipped `hybrid` unchanged. `weighted` fusion is untouched. `api_search` calls `searcher.hybrid`, so the `--dedupe` and abstain paths get the same change.
- **The OR-shape rule is the prereg's "That is" definition:** `scripture_match(query) is None and len(content_terms(query)) > 4`, evaluated on the query string only. A literal `" OR " in to_fts_query(query)` test differs on 5 questions (`k-romans-8-16`, `k-philippians-3-12`, `k-1-corinthians-10-13`, `k-matthew-6-34`, `k-2-corinthians-2-11`). They are scripture references whose NEAR form joins two `NEAR(...)` clauses with `OR`. The prereg puts the NEAR form at `[1, 1]`, and so does the diag's V10, so they stay at `[1, 1]`. No question has zero content terms and more than 4 tokens, so that edge case never arises. OR-shape counts: plain 25/25, names-topic 23/23, plain-blind 28/30, title-keyword 0/3, scripture-keyword 0/7, unanswerable 1/5.
- Equivalence check before the run: with `w = 1.0`, the subclass's top 50 matched the shipped `hybrid` in ids and scores on one OR-shape and one AND-shape query. Those were made-up strings, not eval questions.
- **Order of runs.** Phase `select` scored only the four selection groups, for `w` ∈ {1.0, 0.5, 0.25}, on the raw path, and wrote the choice. Phase `after` read the choice and then ran plain-blind (baseline and the chosen `w`, once), `--dedupe`, abstain and the sensitivity analysis. Neither phase was rerun.
- Bootstrap: `preached.stats` default, 10,000 resamples, seed 20261030. Intervals are 95% percentile intervals. "W/T/L" means paired wins/ties/losses against baseline.

## 3. Selection (decides `w`): lenient hit@10, raw ranker, primary labels

| | n | baseline (w=1) | w=0.5 | w=0.25 |
| --- | --- | --- | --- | --- |
| **pooled selection** | 58 | 50/58 = 0.862 [0.776, 0.948] | **51/58 = 0.879 [0.793, 0.948]** | 50/58 = 0.862 [0.776, 0.948] |
| plain | 25 | 0.720 [0.520, 0.880] | 0.760 [0.600, 0.920] | 0.760 [0.600, 0.920] |
| names-topic | 23 | 0.957 [0.870, 1.000] | 0.957 [0.870, 1.000] | 0.913 [0.783, 1.000] |
| title-keyword | 3 | 1.000 | 1.000 | 1.000 |
| scripture-keyword | 7 | 1.000 | 1.000 | 1.000 |

Rule: the higher pooled hit@10 wins (51 > 50), and a tie would have gone to 0.5. **Chosen `w = 0.5`.**

Paired against baseline (lenient hit@10):

| group | w=0.5: diff [95% CI] W/T/L | lost / gained | w=0.25: diff [95% CI] W/T/L | lost / gained |
| --- | --- | --- | --- | --- |
| pooled | +0.017 [−0.034, +0.086] 2/55/1 | | +0.000 [−0.069, +0.069] 2/54/2 | |
| plain | +0.040 [+0.000, +0.120] 1/24/0 | — / q-mourning-plain | +0.040 [+0.000, +0.120] 1/24/0 | — / q-mourning-plain |
| names-topic | +0.000 [−0.130, +0.130] 1/21/1 | q-worry / q-money | −0.043 [−0.174, +0.087] 1/20/2 | q-justification, q-worry / q-money |
| title-keyword | +0.000 0/3/0 | — | +0.000 0/3/0 | — |
| scripture-keyword | +0.000 0/7/0 | — | +0.000 0/7/0 | — |

## 4. Every reported metric, chosen `w = 0.5` against baseline

Pooled selection groups, raw path (n = 58), with paired differences. Metrics that move against `w = 0.5` are in bold.

| metric | baseline | w=0.5 | paired diff [95% CI] W/T/L |
| --- | --- | --- | --- |
| hit@10 lenient (primary) | 0.862 [0.776, 0.948] | 0.879 [0.793, 0.948] | +0.017 [−0.034, +0.086] 2/55/1 |
| hit@10 strict (grade 2) | 0.466 [0.345, 0.603] | 0.500 [0.379, 0.638] | +0.034 [+0.000, +0.086] 2/56/0 |
| nDCG@10 lenient | 0.308 [0.251, 0.367] | 0.315 [0.259, 0.372] | +0.007 [−0.008, +0.023] 22/18/18 |
| **MRR@10 lenient** | 0.596 [0.493, 0.699] | 0.594 [0.495, 0.695] | **−0.002 [−0.038, +0.036] 8/43/7** |
| **Recall@5 lenient** | 0.112 [0.087, 0.139] | 0.108 [0.085, 0.135] | **−0.003 [−0.012, +0.005] 4/47/7** |

Per group, w = 0.5 (baseline in brackets). plain: nDCG@10 lenient 0.160 (0.138), MRR 0.394 (0.395), R@5 0.085 (0.079). **names-topic: nDCG 0.394 (0.401), MRR 0.678 (0.681), R@5 0.115 (0.129).** title-keyword and scripture-keyword are identical on every metric. bench's base `hit@10` (all labels except proposed grade-1 ones) comes out equal to strict here: the 12 unproposed grade-1 labels in the selection groups change no hit. Lenient counts the 807 proposed grade-1 labels (LLM-proposed by Claude), so lenient hit@10 is the primary metric, as the prereg says.

### `--dedupe` (API path: top 100, `dedupe_adjacent` to 10), lenient hit@10

| group | n | baseline | w=0.5 | paired diff W/T/L | lost / gained |
| --- | --- | --- | --- | --- | --- |
| **pooled selection** | 58 | 0.879 [0.793, 0.966] | 0.879 [0.793, 0.948] | +0.000 [−0.069, +0.069] 2/54/2 | |
| plain | 25 | 0.760 | 0.760 | +0.000 [−0.120, +0.120] 1/23/1 | **q-money-plain** / q-mourning-plain |
| names-topic | 23 | 0.957 | 0.957 | +0.000 [−0.130, +0.130] 1/21/1 | **q-worry** / q-money |
| title-keyword | 3 | 1.000 | 1.000 | 0/3/0 | |
| scripture-keyword | 7 | 1.000 | 1.000 | 0/7/0 | |
| plain-blind (in-sample) | 28 | 0.179 [0.036, 0.321] | 0.357 [0.179, 0.536] | +0.179 [+0.036, +0.321] 5/23/0 | — / p-007, p-011, p-022, p-025, p-028 |
| all answerable | 86 | 0.651 [0.547, 0.744] | 0.709 [0.616, 0.802] | +0.058 [−0.012, +0.128] 7/77/2 | |

nDCG@10 lenient on `--dedupe`: **names-topic 0.456 vs 0.485 baseline (lower)**; plain 0.176 vs 0.153; plain-blind 0.075 vs 0.039; keyword groups identical.

### Abstain (shipped floor 0.8129 for granite-english-r2/torch/fp32 from `search/abstain.toml`, not refit)

There are 5 labelled unanswerable items (the `unanswerable` group). Separately, `p-004` and `p-023` are unlabelled plain-blind questions; they are reported on their own below and are not counted in the 5. There are 86 answerable items.

| path | w | abstained (`none`) on the 5 labelled unanswerable | `none` on answerable (false abstain) | `weak` on answerable | levels strong/weak/none |
| --- | --- | --- | --- | --- | --- |
| raw | 1.0 | 4/5 (80.0%) | 2/86 (2.3%: p-016, p-017) | 11/86 (12.8%) | 76/11/6 |
| raw | 0.5 | 4/5 (80.0%) | 2/86 (2.3%: p-016, p-017) | **12/86 (14.0%)** | 75/12/6 |
| dedupe | 1.0 | 4/5 (80.0%) | 2/86 (2.3%) | 11/86 (12.8%) | 76/11/6 |
| dedupe | 0.5 | 4/5 (80.0%) | 2/86 (2.3%) | **12/86 (14.0%)** | 75/12/6 |

- Labelled unanswerable levels are identical under both weights: 4/5 abstain. `u-book-of-mormon`, `u-nuclear-weapons`, `u-smartphones` and `u-vaccines` get `none`. **`u-pretrib-rapture` gets `strong`, a false answer under both weights.**
- Unlabelled: `p-004` and `p-023` (plain-blind, no labels) also get `strong` under both weights. They are not in the 4/5 and are not scored as unanswerable.
- Rule 5 does **not** fire. The prereg defines "degrade" as more false answers on unanswerable items, or lower hit@10 with `--dedupe`; neither moved.
- **Against us:** `p-013` (answerable) moves from `strong` to `weak` under `w = 0.5`, on both paths. Rule 5 names false answers on unanswerable items, and this is not one. It is a minor adverse move, disclosed here: `weak` on answerable items goes from 11 to 12 of 86. It does not trigger rule 5.
- For reference only, what `search/bench.py --abstain` itself would print: it refits a floor in memory (never written; `--write-calibration` was not used). That fitted floor is 0.7753 under both weights, and with it the in-sample and leave-one-out abstain recall on unanswerable items is 0.0, against 4 of the 5 labelled unanswerable items with the shipped floor. The shipped 0.8129 was fitted on a smaller, older set (35 answerable + 5 unanswerable); today's set is 86 answerable + 5 labelled unanswerable. The floor is not refit here, as the prereg says.

## 5. In-sample check and sensitivity analysis

### plain-blind (in-sample only; not held out and not confirmatory; gates nothing)

Raw path, n = 28 answerable, run once after `w` was chosen: lenient hit@10 is **0.143 [0.036, 0.286] for baseline and 0.321 [0.143, 0.500] for w = 0.5**, paired +0.179 [+0.036, +0.321], 5/23/0 (gained p-007, p-010, p-011, p-022, p-028; no losses, so no warning). Strict hit@10 is 0.107 vs 0.179, nDCG@10 lenient 0.034 vs 0.064, MRR@10 lenient 0.057 vs 0.099. The author of the hypothesis designed it after reading these failures (prereg, Disclosures), so this number is not evidence.

### Sensitivity: verdict 1 counted as grade 1 (pre-declared; never used to choose `w`)

Primary labels plus the 9 grade-1 labels in `eval/partial_verdicts.jsonl` (7 sheet rows: L06 p-030, L07 p-002, L16 q-means-plain + q-means, L09 p-007, L11 q-money-plain + q-money, L19 p-007, L21 p-009). Raw path, lenient hit@10, side by side with the primary result:

| group | primary: base / 0.5 / 0.25 | sensitivity: base / 0.5 / 0.25 | sensitivity diff vs base, w=0.5 [CI] W/T/L | w=0.25 [CI] W/T/L |
| --- | --- | --- | --- | --- |
| pooled selection (58) | 0.862 / 0.879 / 0.862 | 0.879 [0.793, 0.966] / 0.897 [0.810, 0.966] / 0.879 [0.793, 0.949] | +0.017 [−0.034, +0.086] 2/55/1 | +0.000 [−0.069, +0.069] 2/54/2 |
| plain (25) | 0.720 / 0.760 / 0.760 | 0.760 / 0.800 / 0.800 | +0.040 [+0.000, +0.120] 1/24/0 | +0.040 [+0.000, +0.120] 1/24/0 |
| names-topic (23) | 0.957 / 0.957 / 0.913 | 0.957 / 0.957 / 0.913 | +0.000 [−0.130, +0.130] 1/21/1 (lost q-worry) | −0.043 [−0.174, +0.087] 1/20/2 |
| title-keyword (3) | 1 / 1 / 1 | 1 / 1 / 1 | 0/3/0 | 0/3/0 |
| scripture-keyword (7) | 1 / 1 / 1 | 1 / 1 / 1 | 0/7/0 | 0/7/0 |
| plain-blind (28, in-sample; base and chosen w only) | 0.143 / 0.321 / — | 0.250 [0.107, 0.429] / 0.393 [0.214, 0.571] / — | +0.143 [+0.036, +0.286] 4/24/0 | — |

Under the sensitivity labels the pooled selection hits are 51 / 52 / 51, so the ranking of the two weights would be the same. That is reported, not used.

## 6. "Do not ship" rules

| rule | result |
| --- | --- |
| 1. negative pooled paired hit@10 difference on selection groups | **not triggered:** +0.017 [−0.034, +0.086], 2/55/1. The CI includes zero. |
| 2. more than one loss in any selection group, or any loss in title- or scripture-keyword | **not triggered:** names-topic loses 1 (q-worry) and gains 1 (q-money). Keyword groups are unchanged on every metric. |
| 3. fresh-set CI includes zero and at least one fresh question lost | **not evaluable: no fresh blind set exists** |
| 4. chosen `w` does not beat baseline on the fresh set | **not evaluable: no fresh blind set exists** |
| 5. abstain or `--dedupe` degrade | **does not fire** (the prereg defines degrade as more false answers on unanswerable items, or lower hit@10 with `--dedupe`; neither moved): unanswerable levels are identical, and pooled `--dedupe` selection hit@10 is 0.879 → 0.879 (2/54/2). Disclosed as a minor adverse move: p-013 moves strong → weak (weak on answerable 11 → 12 of 86); on `--dedupe` q-money-plain and q-worry are lost (and two gained); names-topic `--dedupe` nDCG@10 falls 0.485 → 0.456. |

**This is a mixed and incomplete result.** On the selection data the pre-declared change gains one question net, with an interval that includes zero. Rules 1, 2 and 5 do not fire. The confirmatory evidence the prereg requires is missing. Under the prereg, nothing here may be read as an accuracy gain.

**The only citable statement:** "In a pre-registered blind evaluation (58 questions, labels written with AI help and graded blind), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086)." The default weight stays 1.0; this PR changes no weight. No third weight was tried, the rule was not changed and no label was edited.

**Who ran this.** Run by agent Claude Code, model claude-opus-5-5 (Anthropic), session claude-20261031-120632, task 77-W3-CONFIRMATORY, on omarchy in the Preached sandbox on 2026-10-31, roughly 12:06–12:17 EDT. This agent wrote `run.py` and executed both phases (`select` and `after`). It had already seen the corpus, the questions, the diag report and the prereg, which is why it cannot author the fresh blind set. The git commit author is the repo owner's identity, not the runner.

**Provenance (f).** Every question is LLM-written: the 40 originals and labels by Grok (W1-B), the 23 `-plain` rewrites by Claude, the 30 `plain-blind` questions by Grok (`llm-written:grok`), and every `status: proposed` label by Claude. Every grade-2 label in the selection groups was LLM-chosen and is not confirmed by a person. The exceptions are the three Patrick-judged grade-2 labels (L02 `q-forgiveness`, L08 `p-013`, L20 `q-justification` and `q-justification-plain`) and the 7 verdict-1 rows used only in the sensitivity analysis. `eval/review/review-2026-10-30.csv` is still pending. The selection groups are also small (3 and 7 questions in the keyword groups).

## 7. How to run

```sh
git worktree add -b eval/w3-confirmatory /work/preached/.worktrees/eval/w3-confirmatory origin/main   # at 387e959
cd /work/preached/.worktrees/eval/w3-confirmatory
for f in reports/W3-FUSION-PREREG.md eval/questions.jsonl eval/partial_verdicts.jsonl reports/W3-LABEL-VERDICTS.csv; do
  [ "$(sha256sum < $f)" = "$(git show 387e9599796f467a7d5cac82e438314b3f347d37:$f | sha256sum)" ] && echo "MATCH $f" || echo "DIFF $f"; done
PREACHED_CACHE=/cache uv run --frozen python -m unittest -v tests.test_eval_leak        # S4: 19 tests, 0 skips
sha256sum /cache/index/wesley.sqlite*                                                    # before
export MKL_ENABLE_INSTRUCTIONS=AVX512
uv run --frozen --group bench python /cache/w3-confirmatory/run.py select /cache/w3-confirmatory/out
uv run --frozen --group bench python /cache/w3-confirmatory/run.py after  /cache/w3-confirmatory/out
sha256sum /cache/index/wesley.sqlite*                                                    # after: identical
uv lock --check
PREACHED_CACHE=/cache uv run --frozen python -m unittest discover -s tests
```

Raw outputs: the prereg names no raw result files, so they stay in `/cache/w3-confirmatory/` and are not committed. Per-question top-10 ids and metrics for every configuration are in `out/select.json` (sha256 `63904a58d472114c477631dccd4f2307d19e10b3905c0bead64008af2fa3a37e`, 152 KB) and `out/after.json` (sha256 `676a8ab7e322ef6db24643de2d6c6e5bed9d315da5bc477785e1d7c82fac5a6d`, 596 KB). Logs are `select.log` (`cd0ab86d…`) and `after.log` (`c60a4b98…`). The select log line is `{"pooled": {"1.0": 50, "0.5": 51, "0.25": 50}, "n": 58, "chosen_w": 0.5}`.

Environment: i9-12900K, CPU query encoding, torch 2.15.0+cu132, sentence-transformers 6.2.0, transformers 5.22.1, numpy 2.5.4. Granite English R2 revision as pinned in `search/models.toml`.

## 8. Checks, open issues, dependencies

- `uv lock --check`: OK (79 packages). `uv run python -m unittest discover -s tests` (with `PREACHED_CACHE=/cache`) on 387e959: **979 tests, OK**.
- **Open: the fresh blind set.** It must be written by a person, or by a non-PRC LLM that has seen neither the corpus, this repo's questions, the diag report nor the prereg. It must be frozen and committed with provenance before any ranker runs on it, and labelled by grep and reading, not by a ranker. Only then can rules 3 and 4 be run (baseline and `w = 0.5`, once). Until then no accuracy claim can be made. Per (g), no claim is made in README, DEMO-SCRIPT, SUBMISSION-DRAFT or the app.
- Open: `u-pretrib-rapture` (labelled) and the unlabelled `p-004` and `p-023` get `strong` under both weights (an existing abstain weakness, not caused by `w`). bench's own in-memory refit on today's labels (0.7753) would abstain on none of the unanswerable items. Not acted on: the floor is not refit by rule.
- Not done (CTO, out of scope): the optional #50 r3 nits S6, N2 and N3.
- Dependencies added: none. No code, test or label change.

## Appendix: `/cache/w3-confirmatory/run.py` (sha256 `f4172c8d…eb05ff9`), verbatim

```python
"""W3-CONFIRMATORY run under reports/W3-FUSION-PREREG.md (scratch, NOT product code; nothing here is in src/).

Usage (from the worktree root, MKL_ENABLE_INSTRUCTIONS=AVX512 set):
  uv run --frozen --group bench python /cache/w3-confirmatory/run.py select OUTDIR
  uv run --frozen --group bench python /cache/w3-confirmatory/run.py after  OUTDIR

Phase "select" scores the selection groups only (plain, names-topic, title-keyword,
scripture-keyword) for w in {1.0 (baseline), 0.5, 0.25} on the raw ranker path and picks w by
the prereg rule. Phase "after" reads that choice and then runs plain-blind (in-sample),
--dedupe, abstain (shipped floor, not refit) and the partial_verdicts sensitivity analysis.

Scoring is search/bench.py's own (bench.evaluate / bench.score / api_search / abstain), with the
same Granite English R2 torch CPU query vectors. bench.py itself is not run because it migrates
and re-syncs chunks into its --index; the index is opened mode=ro&immutable=1 instead and never
copied or written.
"""
import json, sqlite3, sys, hashlib, copy
from pathlib import Path
root = Path.cwd()
sys.path.insert(0, str(root / "src")); sys.path.insert(0, str(root / "search"))
from preached import env  # noqa
import preached.fts as fts
from preached import abstain
from preached.models import MODELS
from preached.embed import load_model, encode_query
from preached.search import Searcher, CANDIDATES as SEARCH_CANDIDATES
from preached.paths import INDEX_PATH
from preached.rank import reciprocal_rank_fusion, weighted_fusion
from preached.stats import bootstrap_ci, paired_bootstrap, SEED, RESAMPLES
import bench

MODEL = "granite-english-r2"
SELECTION = ("plain", "names-topic", "title-keyword", "scripture-keyword")
GRID = (0.5, 0.25)
METRICS = ("hit@10_lenient", "hit@10_strict", "hit@10", "ndcg@10_lenient", "mrr@10_lenient", "recall@5_lenient")


def open_immutable(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def or_shape(query: str) -> bool:
    """Prereg rule, exact: no scripture reference and more than 4 content terms."""
    return fts.scripture_match(query) is None and len(fts.content_terms(query)) > 4


class WeightedSearcher(Searcher):
    """Searcher.hybrid with the frozen change: fusion="rrf" passes weights=[1.0, w] on OR-shape queries."""

    def __init__(self, *a, w: float, **kw):
        super().__init__(*a, **kw)
        self.w = w

    def hybrid(self, query, vector, limit, fusion="rrf", rrf_k=60, dense_weight=0.5, candidates=SEARCH_CANDIDATES):
        if fusion != "rrf" or not or_shape(query):
            return super().hybrid(query, vector, limit, fusion=fusion, rrf_k=rrf_k, dense_weight=dense_weight,
                                  candidates=candidates)
        self._refresh()
        where = self._where()
        lexical = self._lexical(query, candidates, where)
        semantic = self._semantic(vector, candidates, where)
        fused = reciprocal_rank_fusion([[r for r, _ in semantic], [r for r, _ in lexical]], k=rrf_k,
                                       weights=[1.0, self.w])
        return self._pack(fused, limit, where)


def searcher_for(con, w):
    if w == 1.0:
        return Searcher(con, model=MODEL, allow_eval_only=True)  # shipped, unchanged
    return WeightedSearcher(con, model=MODEL, allow_eval_only=True, w=w)


def index_identity(con):
    meta = dict(con.execute("SELECT key, value FROM meta WHERE key IN ('chunks_sha256', 'embeddings:granite-english-r2')").fetchall())
    h = hashlib.sha256(); n = 0
    for row in con.execute("SELECT chunk_id, sermon_title, scripture, text FROM chunks ORDER BY chunk_id"):
        h.update("\x1f".join("" if v is None else str(v) for v in row).encode() + b"\n"); n += 1
    emb = con.execute("SELECT count(*) FROM embeddings WHERE model = ?", (MODEL,)).fetchone()[0]
    return {"meta": meta, "chunks": n, "embeddings": emb, "content_sha256": h.hexdigest()}


def with_partials(questions):
    qs = copy.deepcopy(questions)
    by_id = {q["id"]: q for q in qs}
    added = []
    for line in (root / "eval" / "partial_verdicts.jsonl").read_text().splitlines():
        if line.strip():
            p = json.loads(line)
            by_id[p["question_id"]]["relevant"].append(p["label"])
            added.append((p["question_id"], p["sheet_row"], p["label"]["chunk_ids"]))
    return qs, added


def group_table(per, groups, ids_ok):
    out = {}
    for g, ids in groups.items():
        ids = [i for i in ids if i in per and i in ids_ok]
        if ids:
            out[g] = {"n": len(ids), **{m: bootstrap_ci([per[i][m] for i in ids]) for m in METRICS}}
    return out


def paired(per_a, per_b, ids, metric="hit@10_lenient"):
    ids = sorted(ids)
    return paired_bootstrap([per_a[i][metric] for i in ids], [per_b[i][metric] for i in ids])


def lost(per_w, per_0, ids, metric="hit@10_lenient"):
    return sorted(i for i in ids if per_0[i][metric] > 0 and per_w[i][metric] == 0)


def gained(per_w, per_0, ids, metric="hit@10_lenient"):
    return sorted(i for i in ids if per_0[i][metric] == 0 and per_w[i][metric] > 0)


def main():
    phase, outdir = sys.argv[1], Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    con = open_immutable(INDEX_PATH)
    spec = MODELS[MODEL]
    all_q = bench.load_questions()
    groups = bench.question_groups(all_q)
    loaded = load_model(spec, device="cpu", batch_size=1)
    cache = {}

    def encode(text):
        if text not in cache:
            cache[text] = encode_query(loaded, text)
        return cache[text]

    shape = {q["id"]: {"or_shape": or_shape(q["query"]), "fts_has_OR": " OR " in fts.to_fts_query(q["query"]),
                       "fts": fts.to_fts_query(q["query"])} for q in all_q}
    base = {"index_path": str(INDEX_PATH), "index": index_identity(con), "model": spec.record(),
            "cpu_dtype": loaded.dtype, "bootstrap": {"seed": SEED, "resamples": RESAMPLES},
            "questions_sha256": hashlib.sha256((root / "eval" / "questions.jsonl").read_bytes()).hexdigest(),
            "partial_sha256": hashlib.sha256((root / "eval" / "partial_verdicts.jsonl").read_bytes()).hexdigest()}

    if phase == "select":
        sel = [q for q in all_q if q.get("group") in SELECTION]
        ans = [q["id"] for q in sel if q["relevant"]]
        per = {}
        for w in (1.0, *GRID):
            per[w] = bench.evaluate(searcher_for(con, w), sel, ("hybrid_rrf",), encode=encode)["per_query"]["hybrid_rrf"]
        pooled = {w: sum(per[w][i]["hit@10_lenient"] for i in ans) / len(ans) for w in per}
        chosen = 0.5 if pooled[0.5] >= pooled[0.25] else 0.25  # tie -> milder (0.5)
        out = {**base, "phase": "select", "selection_groups": SELECTION, "n_answerable": len(ans),
               "pooled_hit@10_lenient": {str(w): v for w, v in pooled.items()},
               "pooled_hits": {str(w): int(sum(per[w][i]["hit@10_lenient"] for i in ans)) for w in per},
               "chosen_w": chosen,
               "by_group": {str(w): group_table(per[w], {g: groups[g] for g in SELECTION}, set(ans)) for w in per},
               "pooled": {str(w): {m: bootstrap_ci([per[w][i][m] for i in ans]) for m in METRICS} for w in per},
               "vs_baseline": {str(w): {"pooled": paired(per[w], per[1.0], ans),
                                        "pooled_metrics": {m: paired(per[w], per[1.0], ans, m) for m in METRICS},
                                        "by_group": {g: {**paired(per[w], per[1.0], [i for i in groups[g] if i in ans]),
                                                         "lost": lost(per[w], per[1.0], [i for i in groups[g] if i in ans]),
                                                         "gained": gained(per[w], per[1.0], [i for i in groups[g] if i in ans])}
                                                     for g in SELECTION}} for w in GRID},
               "shape": {i: shape[i] for i in shape if i in {q["id"] for q in sel}},
               "per_query": {str(w): per[w] for w in per}}
        (outdir / "select.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
        print(json.dumps({"pooled": out["pooled_hits"], "n": len(ans), "chosen_w": chosen}))
        return

    sel_out = json.loads((outdir / "select.json").read_text())
    w = sel_out["chosen_w"]
    floor = abstain.floor_for(MODEL, backend="torch")
    ans_all = [q["id"] for q in all_q if q["relevant"]]
    sel_ans = [q["id"] for q in all_q if q["relevant"] and q.get("group") in SELECTION]
    blind_ans = [q["id"] for q in all_q if q["relevant"] and q.get("group") == "plain-blind"]
    out = {**base, "phase": "after", "chosen_w": w, "shipped_floor": floor}

    # plain-blind, in-sample, once: baseline vs chosen w, raw path
    blind = [q for q in all_q if q.get("group") == "plain-blind"]
    pb = {x: bench.evaluate(searcher_for(con, x), blind, ("hybrid_rrf",), encode=encode)["per_query"]["hybrid_rrf"]
          for x in (1.0, w)}
    out["plain_blind"] = {"n": len(blind_ans), **{str(x): {m: bootstrap_ci([pb[x][i][m] for i in blind_ans]) for m in METRICS}
                                                   for x in pb},
                          "vs_baseline": {**paired(pb[w], pb[1.0], blind_ans),
                                          "lost": lost(pb[w], pb[1.0], blind_ans), "gained": gained(pb[w], pb[1.0], blind_ans)},
                          "per_query": {str(x): pb[x] for x in pb}}

    # --dedupe (API path), all groups, baseline vs chosen w
    dd = {x: bench.evaluate(searcher_for(con, x), all_q, ("hybrid_rrf",), encode=encode, dedupe=True)["per_query"]["hybrid_rrf"]
          for x in (1.0, w)}
    out["dedupe"] = {"by_group": {str(x): group_table(dd[x], groups, set(ans_all)) for x in dd},
                     "pooled_selection": {str(x): bootstrap_ci([dd[x][i]["hit@10_lenient"] for i in sel_ans]) for x in dd},
                     "pooled_all": {str(x): bootstrap_ci([dd[x][i]["hit@10_lenient"] for i in ans_all]) for x in dd},
                     "vs_baseline": {"pooled_selection": paired(dd[w], dd[1.0], sel_ans),
                                     "pooled_all": paired(dd[w], dd[1.0], ans_all),
                                     "by_group": {g: {**paired(dd[w], dd[1.0], [i for i in ids if i in ans_all]),
                                                      "lost": lost(dd[w], dd[1.0], [i for i in ids if i in ans_all]),
                                                      "gained": gained(dd[w], dd[1.0], [i for i in ids if i in ans_all])}
                                                  for g, ids in groups.items() if any(i in ans_all for i in ids)}},
                     "per_query": {str(x): dd[x] for x in dd}}

    # abstain with the shipped floor (not refit), raw and dedupe paths
    ab = {}
    for x in (1.0, w):
        s = searcher_for(con, x)
        rows = {"raw": [], "dedupe": []}
        for q in all_q:
            v = encode(q["query"])
            raw_hits = s.hybrid(q["query"], v, 10, fusion="rrf", rrf_k=60)
            sig = abstain.compute_signals(s, q["query"], v, raw_hits)
            rows["raw"].append(_row(q, sig, abstain.decide(sig, floor, has_results=bool(raw_hits)), raw_hits))
            d_hits, conf = abstain.search_with_confidence(s, q["query"], v, "hybrid", 10, floor)
            r = _row(q, conf.signals, conf, d_hits)
            rows["dedupe"].append(r)
        ab[str(x)] = {p: {"summary": bench.abstain_summary(rows[p], [r["level"] for r in rows[p]]),
                          "by_group": {g: bench.abstain_summary([r for r in rows[p] if r["group"] == g],
                                                                [r["level"] for r in rows[p] if r["group"] == g])
                                       for g in groups},
                          "rows": rows[p]} for p in rows}
        # what `search/bench.py --abstain` itself prints (fits floors in memory; never written; not used)
        ab[str(x)]["bench_fitted_reference"] = {k: v for k, v in bench.abstain_eval(copy.deepcopy(rows["dedupe"])).items()
                                                if k in ("floor", "in_sample", "leave_one_out", "uncalibrated")}
    out["abstain"] = ab

    # sensitivity: verdict 1 counted as grade 1 (primary + eval/partial_verdicts.jsonl); raw path; never selects w
    sq, added = with_partials(all_q)
    sens = {}
    for x in (1.0, *GRID):
        qs = sq if x == w or x == 1.0 else [q for q in sq if q.get("group") in SELECTION]  # plain-blind once: baseline + chosen
        sens[x] = bench.evaluate(searcher_for(con, x), qs, ("hybrid_rrf",), encode=encode)["per_query"]["hybrid_rrf"]
    out["sensitivity"] = {"added_labels": added,
                          "pooled_selection": {str(x): bootstrap_ci([sens[x][i]["hit@10_lenient"] for i in sel_ans]) for x in sens},
                          "by_group": {str(x): group_table(sens[x], groups, set(sens[x])) for x in sens},
                          "vs_baseline": {str(x): {"pooled_selection": paired(sens[x], sens[1.0], sel_ans),
                                                   "by_group": {g: {**paired(sens[x], sens[1.0], [i for i in ids if i in sens[x]]),
                                                                    "lost": lost(sens[x], sens[1.0], [i for i in ids if i in sens[x]]),
                                                                    "gained": gained(sens[x], sens[1.0], [i for i in ids if i in sens[x]])}
                                                                for g, ids in groups.items() if any(i in sens[x] for i in ids)}}
                                          for x in GRID},
                          "plain_blind_vs_baseline": paired(sens[w], sens[1.0], blind_ans),
                          "per_query": {str(x): sens[x] for x in sens}}
    out["shape"] = shape
    (outdir / "after.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    print("done", w)


def _row(q, sig, conf, hits):
    texts = [h.text for h in hits]
    row = {"id": q["id"], "group": q.get("group", "ungrouped"), "answerable": bool(q["relevant"]),
           "bm25_hits": sig.bm25_hits, "dense_top": sig.dense_top, "agreement": sig.agreement, "level": conf.level,
           "top10": [h.chunk_id for h in hits[:10]]}
    if q["relevant"]:
        row["recall@5"] = bench.recall_at(texts, bench.label_set(q["relevant"]), 5)
        row["mrr@10"] = bench.mrr_at(texts, bench.label_set(q["relevant"]), 10)
    return row


if __name__ == "__main__":
    main()
```
