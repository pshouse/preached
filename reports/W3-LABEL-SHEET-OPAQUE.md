# W3-LABEL-SHEET-OPAQUE: opaque chunk ids (CTO #43 r2 must-fix M1)

Branch `docs/w3-label-sheet` (PR #43). Docs/data/script/tests only; no change to `src/`, the index, `eval/questions.jsonl` or grades.

- **Head SHA:** `3fbfc50b7f262b1d75b2ab2c9733858cd8a051fa` (this report is in it; merge of origin/main 6a94caf is c3e6714 on top of 3db59e6). No rebase, no force-push.
- **Caveats:** `gh`, `sandbox.sh` and `gitleaks` are not available here, so I used plain git, could not confirm via the API that PR #43 is open (origin/docs/w3-label-sheet was at 3db59e6 as required), and **did not run gitleaks**.

## Changes
- Chunk ids on the sheet are now `C01`..`C23`, assigned by `scripts/make_label_sheet.py` after the seeded shuffle, in order of first appearance. wesley-024-c0012 appears in two rows and keeps one id. Real ids appear only in `W3-LABEL-SHEET-KEY.md` (new `sheet cid` and `real chunk id` columns).
- `tests/test_label_sheet.py`: fails on any `wesley-` id or `cNNNN` in the sheet, on a chunk text starting with a number/"Sermon"/"Upon our Lord" header, checks `C\d\d` ids, one id per chunk, and ids following shuffled order, not sermon number.
- `W3-FUSION-PREREG.md` updated to match. `W3-LABEL-SHEET-BLIND.md`: question ids corrected to Q01..Q18 (was Q01..Q16).
- Embedded-header check: no chunk text starts with or contains its sermon title, number or source header. The question for wesley-026-c0071 names "Wesley" (the author), left as is. Nothing to report beyond that.

## Sheet
- Columns: `row id, question id, question, chunk id, chunk text, verdict, notes`
- Rows L01..L24, questions Q01..Q18, chunks C01..C23.
- Seed: `20261031`
- sha256 of `reports/W3-LABEL-SHEET.csv`: `6141beaaed326f48a12813b95cb812cccd14f8e4eea55632ca063100f5369b12`
- `python3 scripts/make_label_sheet.py --check`: up to date.
- Copy refreshed at `/cache/w3-label-sheet/W3-LABEL-SHEET.csv` (same sha256). That is the path the previous run used on this machine; I did not find a separate omarchy path.

## Tests
`python3 -m unittest tests.test_label_sheet -v`: 4 tests, OK. Full suite `uv run python -m unittest discover -s tests`: Ran 845 tests, OK.
