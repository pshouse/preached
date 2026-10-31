# W3-LABEL-SHEET-R2-FIX: CTO #43 r2 remaining fixes

Branch `docs/w3-label-sheet` (PR #43). Docs/data/script/tests only; no change to `src/`, the index, `eval/questions.jsonl` or grades. Merge of origin/main was a no-op (already up to date). No rebase, no force-push.

- **Head SHA of the change:** `d82194ddea6fa01935da9b062d7a7de93a213c9f` (the commit before this report; the report commit sits on top).
- **Caveats:** `gh`, `sandbox.sh` and `gitleaks` are not available here: plain git, PR #43 open **not confirmed via API** (branch head was 3ed3b0d from 53-W3-LABEL-SHEET-OPAQUE-CHUNKS, whose report exists), and **gitleaks was not run**.
- **sha256 of `reports/W3-LABEL-SHEET.csv`:** `6141beaaed326f48a12813b95cb812cccd14f8e4eea55632ca063100f5369b12` (unchanged from task 53; M1 was already done there: C01..C23, real ids only in the KEY, prereg and BLIND corrected, Q01..Q18). Only the KEY changed (do-not-open note).

## M2
`tests/test_label_sheet.py` now pins the literal seed `20261031`, the committed sheet's sha256 above and the literal 7-column header.

## Mutants (each regenerated sheet and KEY, then ran `tests.test_label_sheet`; all reverted)
| mutant | result |
| --- | --- |
| SEED 20261031 -> 20261032 | FAILED (1 failure) |
| shuffle removed | FAILED (1 failure) |
| rows sorted by group (plain first) | FAILED (1 failure) |
| S4: `<!-- dense 3 -->` appended to a chunk in the source, regenerated | FAILED (3 failures) |
| S4: `<!-- dense 3 -->` inserted in the CSV only | FAILED (3 failures) |

After reverting: `--check` "up to date", tests OK.

## Should-fixes
- **S1:** `reports/w3_label_sheet_source.json` renamed to `reports/W3-LABEL-SHEET-KEY-source.json` (git mv); references updated; the KEY and prereg say do not open it, the labeller gets only the CSV not the repo, and f3d2142/3b9441b still hold unblinded sheets.
- **S2:** prereg line "Labeller exposure to earlier unblinded sheet" was left unanswered, not guessed (answered 2026-10-31, see W3-PREREG-S2).
- **S3:** verified from the source: 10 `plain-blind` questions, 4 all-lowercase (p-021, p-030, p-002, p-008); 8 `plain`, 0 all-lowercase. **Correction to the CTO wording:** those 4 are not punctuation-free, each has a period (no apostrophes, commas or question marks), so the prereg says that.
- **S4:** new test checks every question/chunk cell exactly against the source and scans all cells for `<!--`, `-->`, tags and control/format/exotic-space characters.

## Tests
`python3 -m unittest tests.test_label_sheet -v`: 6 tests, OK. Full suite `uv run python -m unittest discover -s tests`: Ran 847 tests, OK. `python3 scripts/make_label_sheet.py --check`: up to date.
