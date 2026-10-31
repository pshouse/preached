# W3-LABEL-REFREEZE

Branch `eval/w3-label-refreeze` off origin/main `96195be`. Date: 2026-10-31. Nothing was run on any labels: no ranker, bench or eval.

## 1. What was done

- **Verdict file committed unchanged:** `reports/W3-LABEL-VERDICTS.csv`, sha256 `99837f0e1470a34c8cc7f1f7448c2faaf4fb61239c495c1a75be6ab981332fe8` (commit `e081113`). It is a byte copy of `/cache/label-sheet/W3-LABEL-VERDICTS-patrick.csv`. **Path note:** the task named `~/agents/preached/cache/label-sheet/`, which does not exist; the file is in `/cache/label-sheet/` (mtime 2026-10-31 10:09), next to a copy of the pinned sheet.
- **Checked against the pin:** the copy of the sheet in `/cache/label-sheet/` and `reports/W3-LABEL-SHEET.csv` both have sha256 `6141beaa…9b12`. Parsed as CSV, the verdict file has the same 25 rows (header + L01..L24) and only column `verdict` differs. Every verdict is in {0, 1, 2}. Every note is empty. Each row's question text and chunk text equal the KEY source row (`reports/W3-LABEL-SHEET-KEY-source.json`) mapped via `reports/W3-LABEL-SHEET-KEY.md`.
- **Labels:** none changed. `eval/questions.jsonl` is unchanged (blob `6c9c861`). **There is no label commit**, so no hash to record (see §3).
- **Prereg:** one dated Amendments line appended to `reports/W3-FUSION-PREREG.md`. Earlier lines are untouched.

## 2. Per-row table

"Old label" is the state of that chunk for that question in `eval/questions.jsonl` (whether it appears in any label's `chunk_ids`). All 24 are unlabelled.

| L id | real question id | group | chunk id | verdict | old label | new label |
| --- | --- | --- | --- | --- | --- | --- |
| L01 | q-perfection-plain | plain | wesley-083-c0013 | 0 | none | none (no change) |
| L02 | q-forgiveness | plain | wesley-026-c0071 | 2 | none | **pending CTO** |
| L03 | p-015 | plain-blind | wesley-028-c0009 | 0 | none | none (no change) |
| L04 | q-means-plain | plain | wesley-016-c0078 | 0 | none | none (no change) |
| L05 | q-new-birth-plain | plain | wesley-125-c0021 | 0 | none | none (no change) |
| L06 | p-030 | plain-blind | wesley-024-c0012 | 1 | none | **pending CTO** |
| L07 | p-002 | plain-blind | wesley-135-c0024 | 1 | none | **pending CTO** |
| L08 | p-013 | plain-blind | wesley-049-c0011 | 2 | none | **pending CTO** |
| L09 | p-007 | plain-blind | wesley-033-c0051 | 1 | none | **pending CTO** |
| L10 | p-022 | plain-blind | wesley-075-c0026 | 0 | none | none (no change) |
| L11 | q-money-plain | plain | wesley-089-c0027 | 1 | none | **pending CTO** |
| L12 | q-wilderness-plain | plain | wesley-046-c0012 | 0 | none | none (no change) |
| L13 | q-catholic-spirit-plain | plain | wesley-038-c0036 | 0 | none | none (no change) |
| L14 | p-002 | plain-blind | wesley-135-c0007 | 0 | none | none (no change) |
| L15 | p-009 | plain-blind | wesley-024-c0012 | 0 | none | none (no change) |
| L16 | q-means-plain | plain | wesley-016-c0079 | 1 | none | **pending CTO** |
| L17 | q-perfection-plain | plain | wesley-076-c0058 | 0 | none | none (no change) |
| L18 | p-021 | plain-blind | wesley-016-c0080 | 0 | none | none (no change) |
| L19 | p-007 | plain-blind | wesley-022-c0013 | 1 | none | **pending CTO** |
| L20 | q-justification-plain | plain | wesley-005-c0032 | 2 | none | **pending CTO** |
| L21 | p-009 | plain-blind | wesley-024-c0011 | 1 | none | **pending CTO** |
| L22 | p-008 | plain-blind | wesley-065-c0036 | 0 | none | none (no change) |
| L23 | p-027 | plain-blind | wesley-080-c0042 | 0 | none | none (no change) |
| L24 | p-002 | plain-blind | wesley-135-c0004 | 0 | none | none (no change) |

## 3. Counts and why nothing was applied

- Verdicts: **0 × 14, 1 × 7, 2 × 3.** By group: plain 10 rows (0 × 6, 1 × 2, 2 × 2), plain-blind 14 rows (0 × 8, 1 × 5, 2 × 1).
- **Applied: 14 rows, all no-ops.** Verdict 0 on an unlabelled chunk leaves it unlabelled under any reading, so no edit is needed.
- **Ambiguous: 10 rows** (L02, L06, L07, L08, L09, L11, L16, L19, L20, L21). Each would add a new label. The prereg says only "apply the accepted verdicts to `eval/questions.jsonl` in their own commit". It does not say what a verdict changes. The points it leaves open:
  1. **Verdict 1 → grade?** Sheet scale 1 is "related but only a partial answer". Label grade 1 (`eval/README.md`) is "also acceptable: Wesley substantially addresses the question". These are different bars. Lenient hit@10, the selection metric, counts every grade-1 label, so this choice moves `w` selection directly. (7 rows: L06, L07, L09, L11, L16, L19, L21.)
  2. **Verdict 2 → grade 2** reads the same in both definitions ("directly answers"). But adding the label still needs choices the prereg does not make (3 rows: L02, L08, L20):
     - **`status` / provenance:** a label Patrick confirmed has no allowed value. `tests/test_eval_leak.py` accepts only `None` (meaning an original Grok W1-B label) or `proposed` with `found_by: llm-proposed:claude`. Both would misattribute it. It also requires every `plain-blind` label to be `proposed` (affects L08 and all plain-blind verdict-1 rows).
     - **Quote:** labels are quotes, with `chunk_ids` derived from them (`eval/validate.py`). Patrick judged the whole chunk. Most KEY quotes contain ` ... `, so they are not contiguous text and can't be used as label quotes as they stand.
     - **Rewrite families (L20, also L11, L16):** the tests require a `-plain` rewrite to carry exactly its original's `relevant` list. So a label on `q-justification-plain` would also change `names-topic` `q-justification`, which was not on the sheet.
     - **L08 specifically:** the KEY marks this row as an artefact. The chunk holds the same Matt 18:15 text as p-013's existing grade-2 label, whose quote begins "First" and so matches only `wesley-049-c0013`. Verdict 2 could mean adding this chunk to that label, or a new label.
- **For CTO to rule:** (a) the verdict-1 → grade mapping; (b) the `status`/`found_by` value for Patrick-confirmed labels (this needs a one-line test change); (c) how to pick the quote; (d) whether a rewrite's label is mirrored to its original; (e) L08: extend p-013's existing label or add a new one. Once ruled, the 10 rows go into `eval/questions.jsonl` in one commit. Its hash then goes into the prereg Amendments, and only then is anything run.

## 4. How to check

```
sha256sum reports/W3-LABEL-VERDICTS.csv reports/W3-LABEL-SHEET.csv
git diff origin/main -- eval/questions.jsonl          # empty
uv run python scripts/make_label_sheet.py --check     # up to date
uv lock --check
uv run python -m unittest discover -s tests
```

## 5. Test results

- `uv run python -m unittest discover -s tests`: **Ran 961 tests, OK** (the ERROR lines in the log come from tests that exercise failure paths).
- `scripts/make_label_sheet.py --check`: up to date. `uv lock --check`: OK (79 packages resolved).

## 6. Open issues and dependencies

- Labels are **not** re-frozen yet. The frozen test must not run until the 10 rows are ruled on and applied.
- No dependencies added. No code, index, grade or abstain setting changed.

---

## 7. W3-LABEL-APPLY (CTO #50 rulings), 2026-10-31

Nothing was run on the new labels. Only the test suite ran, plus `uv lock --check`.

### What was done

- **Merge:** `9487b08` merges origin/main. The task pinned main at `0f2b553`, but origin/main had moved on to `76990e8` (PR #48, church-hd), which contains `0f2b553`. I merged `origin/main` as instructed, so the branch also has #48.
- **Tests (ruling b):** `c98aa3a` changes `tests/test_eval_leak.py` only. It adds status `confirmed`, which requires `found_by` to match `^human:patrick-blind-w3$` and a `sheet_row` that exists in `reports/W3-LABEL-VERDICTS.csv` with verdict equal to the label's grade. Plain-blind labels may be `proposed` or `confirmed`. The original and proposed rules are unchanged. New test `test_confirmed_label_needs_a_valid_sheet_row` checks that a confirmed label fails with a missing, None, unknown (`L99`) or wrong-verdict (`L01`, verdict 0) sheet_row, or with the wrong `found_by`.
- **Labels (rulings a, c, d, e):** `3e419c9612940475f021635220ebbd2d9c13b08b`, one commit that changes `eval/questions.jsonl` and adds `eval/partial_verdicts.jsonl`. Nothing reads the partial file: no code, scorer or test opens it. Each line has `question_id`, `sheet_row`, `verdict`, an optional `mirrored_from` and a grade-1 `label`.
- **Prereg amendment:** `895e0d6` adds one dated line to `reports/W3-FUSION-PREREG.md`. It covers mappings (a)–(e), Patrick's 10:34 ET confirmation of (a), the pre-declared sensitivity analysis "verdict 1 counted as grade 1" (never used to select `w`), and the label commit hash.

### Quote rule (c), as applied

The KEY quote (`reports/W3-LABEL-SHEET-KEY-source.json`, field `quote`) is split into its double-quoted strings, and each string is split at `...`. A segment qualifies when it meets all three conditions:
- it appears verbatim in the row's chunk;
- it is at least 40 characters long;
- `preached.metrics.contains_quote` over `CHUNKS_JSONL` matches exactly that one chunk. This is the matching `eval/validate.py` uses.

The longest qualifying segment becomes the label quote. Segments were never trimmed further. Most failures happen because neighbouring chunks overlap, so a segment near a chunk edge appears in two or three chunks.

### Per-row table

| L id | question | verdict | action | quote length / segment | chunk_id |
| --- | --- | --- | --- | --- | --- |
| L02 | q-forgiveness | 2 | **primary grade 2**, `q-forgiveness-conf-01` | 85 / "All our trespasses and sins are forgiven us, if we forgive, and as we forgive, others" | wesley-026-c0071 |
| L06 | p-030 | 1 | partial file, grade 1, `p-030-part-01` | 87 / "Not that we can in any wise condemn the intermixing solitude or retirement with society" (58-char segment 1 also in c0011) | wesley-024-c0012 |
| L07 | p-002 | 1 | partial file, grade 1, `p-002-part-01` | 88 / "the strong emotion, the secret workings of soul which a parent feels on such an occasion" (segment 2 also in c0025, c0026) | wesley-135-c0024 |
| L08 | p-013 | 2 | **STOPPED (c)**, applied under c2, see §8 | only segment, 95 chars, "If thy brother shall sin against thee, go and tell him of his fault, between thee and him alone", matches c0011 and c0013 | wesley-049-c0011 |
| L09 | p-007 | 1 | **STOPPED (c)**, applied under c2, see §8 | 48 and 44 chars, both in c0050 and c0051 | wesley-033-c0051 |
| L11 | q-money-plain | 1 | **STOPPED (c)**, applied under c2, see §8 | 43 chars in c0026 and c0027; 14 chars under 40 and in c0028 | wesley-089-c0027 |
| L16 | q-means-plain | 1 | partial file, grade 1, `q-means-part-01`, mirrored to q-means | 106 / "May you not advise him also, to meditate on what he reads, that it may have its full force upon his heart?" | wesley-016-c0079 |
| L19 | p-007 | 1 | **STOPPED (c)**, applied under c2, see §8 | 74 chars in c0012 and c0013; 20 chars under 40 | wesley-022-c0013 |
| L20 | q-justification-plain | 2 | **primary grade 2**, `q-justification-conf-01`, mirrored to q-justification | 45 / "God justifieth not the godly, but the ungodly" (47-char segment 1 also in c0031) | wesley-005-c0032 |
| L21 | p-009 | 1 | **STOPPED (c)**, applied under c2, see §8 | 45 chars in c0009–c0011; 60 chars in c0010 and c0011 | wesley-024-c0011 |
| other 14 | | 0 | no change (unlabelled) | | |

Every new label has `status: confirmed`, `found_by: human:patrick-blind-w3`, `sheet_row` and `quote_source: key-segment`, with `chunk_ids` set to the single chunk.

### Rows stopped under (c), for the CTO

- **L08 (verdict 2):** ruling (e) expected a new grade-2 label on p-013 for c0011. The KEY row is an artefact note whose only quoted text is the Matt 18:15 passage. That passage appears in both c0011 and c0013, so no segment resolves to c0011 alone. No label was added. The existing `p-013-g2-01` (c0013) is untouched. **The net primary change is L02 + L20 (+ q-justification), not L02 + L08 + L20.**
- **L09, L11, L19, L21 (verdict 1):** these are left out of the partial file, so the sensitivity analysis currently covers 3 of the 7 verdict-1 rows (L06, L07, L16).
- One possible ruling: allow a sub-span of a segment, or take the quote from the chunk text instead of the KEY quote. Either is a change to (c), so I did neither.

### Commits

| step | hash |
| --- | --- |
| merge origin/main | `9487b08` |
| tests | `c98aa3a` |
| labels | `3e419c9612940475f021635220ebbd2d9c13b08b` |
| prereg amendment | `895e0d6` |

### How to check

```
git show 3e419c9 --stat
uv run python -m unittest tests.test_eval_leak
uv run python -m unittest discover -s tests
uv lock --check
```

### Results

- `uv run python -m unittest discover -s tests` on the label commit: **Ran 972 tests, OK.** The baseline before was 961; the merge brought in 10 tests and `c98aa3a` added 1. `tests.test_eval_leak`: 16 tests, OK. The ERROR lines in the log are logging from failure-path tests.
- `uv lock --check`: OK (79 packages). No dependencies added.

---

## 8. W3-LABEL-C-AMEND (CTO #50 amended rule c, and the 10:59 ET review), 2026-10-31

Nothing was run on the labels. Only the test suite, `eval/validate.py` (read-only check, no `--write`) and `uv lock --check` ran.

### What was done

- **Merge:** `5116c00` merges origin/main at `bbdb1bad666f9cc1412ee3d791943354674ed02e` (PR #42), as its own merge commit.
- **Labels:** `ecc3f6755f89674722050bf2ba1dc0a64191e3fd`, one commit that changes `eval/questions.jsonl` (L08) and `eval/partial_verdicts.jsonl` (L09, L11 and its mirror, L19, L21).
- **Tests (MF1, MF2, S1):** `e542744`, `tests/test_eval_leak.py` only.
- **MF3:** `8a3a85f`. `eval/apply_grades.py` now refuses to rewrite while any plain-blind question has a `confirmed` label, and lists those labels. `--check` still runs. New `tests/test_apply_grades.py`. I chose refusal over keeping the labels because keeping them would mean rebuilding p-013 from its grade file and then re-adding Patrick's label, which adds a merge path. Refusing has no merge path to get wrong.
- **Prereg (MF4):** `575bb4e` appends a new dated Amendments line to `reports/W3-FUSION-PREREG.md` with rules c1/c2/c3, the exact c2 step and length rule, the outcome, and label commit `ecc3f67`. The earlier lines are unchanged.

### Rule c2, exactly as applied

For each row, c1 is tried first, as in §7. It found nothing for all five rows (each segment is in two or three chunks, or is under 40 chars). Then c2 runs:

1. Split the chunk text (`CHUNKS_JSONL`, the file `eval/validate.py` reads) into words, where a word is a maximal run of non-whitespace (`\S+`).
2. **Step:** try start word 0, 1, 2, … in order, one word per step.
3. **Length:** at each start, the span is the raw chunk text from the start of that word to the end of the first word that brings the span to **≥ 40 characters**. That is the shortest whole-word span of at least 40 chars. A span longer than 160 chars is skipped (none were).
4. Accept the **first** span whose `preached.metrics.contains_quote` hits over all chunks are exactly `[chunk_id]`. Nothing else is tried after that, and nothing is picked by hand.
5. If no start qualifies, the row is c3 (stop). No row reached c3.

The script was a scratch file outside the repo. It is fully described by the five steps above, and the new test re-checks every result.

### Per-row table (amended rule c)

| L id | question | verdict | rule | outcome | quote_source | start word | span length | quote | chunk_id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L08 | p-013 | 2 | c2 | **primary grade 2**, `p-013-conf-01` | chunk-unique | 0 | 44 | "But how can we avoid giving offense to some," | wesley-049-c0011 |
| L09 | p-007 | 1 | c2 | partial file, grade 1, `p-007-part-01` | chunk-unique | 25 | 42 | "though it go no farther than the heart. Be" | wesley-033-c0051 |
| L11 | q-money-plain | 1 | c2 | partial file, grade 1, `q-money-part-01`, mirrored to q-money | chunk-unique | 42 | 42 | "of God on earth as angels do in heaven. He" | wesley-089-c0027 |
| L19 | p-007 | 1 | c2 | partial file, grade 1, `p-007-part-02` | chunk-unique | 24 | 42 | "will justify it in the sight of God? Anger" | wesley-022-c0013 |
| L21 | p-009 | 1 | c2 | partial file, grade 1, `p-009-part-01` | chunk-unique | 38 | 42 | "here revealed to man by Jesus Christ. When" | wesley-024-c0011 |
| L02 | q-forgiveness | 2 | c1 | primary grade 2, `q-forgiveness-conf-01` (unchanged, §7) | key-segment | | 85 | | wesley-026-c0071 |
| L20 | q-justification-plain | 2 | c1 | primary grade 2, `q-justification-conf-01`, mirrored (unchanged) | key-segment | | 45 | | wesley-005-c0032 |
| L06 | p-030 | 1 | c1 | partial, `p-030-part-01` (unchanged) | key-segment | | 87 | | wesley-024-c0012 |
| L07 | p-002 | 1 | c1 | partial, `p-002-part-01` (unchanged) | key-segment | | 88 | | wesley-135-c0024 |
| L16 | q-means-plain | 1 | c1 | partial, `q-means-part-01`, mirrored (unchanged) | key-segment | | 106 | | wesley-016-c0079 |

No row is pending CTO amendment c2. Net primary change: grade-2 labels for L02, L08 and L20 (plus the L20 mirror on q-justification). The sensitivity file now holds all 7 verdict-1 rows (9 lines with the 2 mirrors).

- **L08, duplicate-text artefact:** the KEY's Matt 18:15 sentence is in both c0011 and c0013. The existing `p-013-g2-01` quote starts with "First," so it matches only c0013 and is untouched. The new c2 anchor is the opening of c0011, which is in no other chunk. p-013 now has two grade-2 labels, one per chunk.
- The c2 anchors are short and often stop mid-sentence (e.g. "… Be"). This is by design: the rule allows no choosing, and the quote only anchors the chunk Patrick judged as a whole.

### CTO review items

| item | change | proof |
| --- | --- | --- |
| MF1 | A `confirmed` label in `eval/questions.jsonl` must have grade 2 and sheet verdict `"2"`. New negative cases in `test_confirmed_label_needs_a_valid_sheet_row`: verdict-1 row with grade 1 (`L06`); grade 1 on a verdict-2 row; verdict-1 row with grade 2. The same function with `primary=False` (partial file) accepts the L06 grade-1 label. | CTO mutation "L06 partial label appended to p-030": **FAIL** `1 != 2 : p-030-part-01`. CTO mutation "L16 appended to q-means and q-means-plain": **FAIL** `1 != 2 : q-means-part-01`. Both reverted. |
| MF2 | New `test_partial_verdicts_are_verdict_1_labels_with_exact_mirrors`: every line has verdict 1, sheet verdict `"1"`, label grade 1, label sheet_row equal to the line's, status confirmed, and passes the confirmed-label check. Each `mirrored_from` line equals its source label exactly and is on the `rewrite_of` of that -plain question. | CTO mutation "sheet_row L01 + found_by nobody on L06's partial label": **FAIL** in this test (`'L01' != 'L06'`) and in the anchor test (`['wesley-024-c0012'] != ['wesley-083-c0013']`). Reverted. |
| MF3 | `apply_grades.py` refuses to write; `confirmed_plain_blind()` lists the labels it would lose. | `tests/test_apply_grades.py` (4 tests). Against the old `apply_grades.py`, the refusal test fails and the 2 helper tests error. |
| MF4 | New prereg Amendments line (`575bb4e`); this table. | |
| S1 | `found_by` is checked with `assertEqual`. A trailing `\n` is a new negative case. | |
| scope | New `test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk`: every confirmed label (primary and partial) resolves, by `eval/validate.py`'s own `contains_quote` over its `CHUNKS_JSONL`, to exactly the KEY chunk of its `sheet_row`; `chunk_ids` equals that; `quote_source` is `key-segment` or `chunk-unique`. Skipped if the corpus is absent from `/cache`. | |

### How to check

```
git show ecc3f67 --stat
uv run python -m unittest tests.test_eval_leak tests.test_apply_grades
uv run python -m unittest discover -s tests
uv lock --check
```

### Results

- `uv run python -m unittest discover -s tests` at `8a3a85f` (the label, test and MF3 commits; the prereg and report commits after it touch no code or test inputs): **Ran 978 tests, OK, 0 skipped.** That is 972 before + 2 new in `tests/test_eval_leak.py` (18 now) + 4 in the new `tests/test_apply_grades.py`. The origin/main merge changed existing tests but added none. The ERROR lines in the log come from logging in failure-path tests.
- `tests.test_eval_leak tests.test_apply_grades`: 22 tests, OK.
- `eval/validate.py` (read-only): all graded quotes match at least one chunk.
- `uv lock --check`: OK (79 packages). No dependencies added.

### Open issues and dependencies

- Labels are applied for all 10 ruled rows. Nothing runs on them until the CTO signs off.
- `eval/apply_grades.py` can no longer rewrite `eval/questions.jsonl` while p-013 holds a confirmed label. Any future re-grade of plain-blind items needs a merge rule from the CTO first.
- No dependencies added.

## 9. W3-LABEL-MF5 (CTO #50 r2), 2026-10-31

No label line changed and nothing was run on the labels. Tests and docs only.

- **c2 ruling:** CTO ruling 2026-10-31: c2 is the shortest-whole-word-span reading as recorded in 575bb4e. No relabel. Appended to the 2026-10-31 c2 amendment in `reports/W3-FUSION-PREREG.md`.
- **S4:** the prereg now has a "Confirmatory run steps" section: run `test_eval_leak` with `PREACHED_CACHE` set, confirm 0 skips for that test, record the output in the run report. CI does not fail on the skip.
- **MF5:** `test_partial_verdicts_are_verdict_1_labels_with_exact_mirrors` now also checks, for every non-mirror line on a question with `rewrite_of`, that exactly one line exists with `question_id == rewrite_of`, `mirrored_from` that question and the same `sheet_row`; and that no question has two lines for one `sheet_row`. Mutations (each reverted): delete L11's `q-money` mirror line: **FAIL** `0 != 1 : q-money-plain L11: needs exactly one mirror on q-money`. Duplicate the L06 line: **FAIL** `duplicate line: p-030 L06`.
- **S5 (done, trivial):** new `test_key_segment_quotes_are_key_segments_of_their_row`: every `key-segment` quote is one of the quoted KEY segments (split at ` ... `) of its `sheet_row` in `reports/W3-LABEL-SHEET-KEY.md`. Passes on the current labels.
- **Results:** `uv run python -m unittest discover -s tests`: **Ran 979 tests, OK** (978 + 1 new, `tests/test_eval_leak.py` now 19). `uv lock --check`: OK (79 packages). No dependencies added.
