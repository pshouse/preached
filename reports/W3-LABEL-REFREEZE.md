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
