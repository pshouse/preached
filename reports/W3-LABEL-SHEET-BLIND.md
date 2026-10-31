# W3-LABEL-SHEET-BLIND

Branch `docs/w3-label-sheet` (PR #43). Docs/data only; no change to `src/`, the index, `eval/questions.jsonl` or grades.

- **Head SHA of the change:** `71887e8aabe639ae952ec8f60e95a99497e77354` (merge of origin/main `d436541`, which contains b364085, done first as commit 2d9f254; no rebase, no force-push).
- **Caveats:** `gh` and `sandbox.sh` do not exist here, so I used plain git and could not confirm PR #43 is still open; the branch head was 3b9441b as the precondition expects. origin/main had moved past b364085 to d436541, so I merged that.

## Final sheet columns (exactly)
`row id, question id, question, chunk id, chunk text, verdict, notes` (verdict and notes blank). Rows L01..L24, question ids Q01..Q18 (opaque; the real `p-`/`q-` ids encode the split, so they are in the KEY only). Dropped from the sheet: group, sermon title, currently labelled passages, why flagged, where it ranks. Ranks and ranker names live only in the KEY; W3-FUSION-PREREG.md does not need them visible to the labeller.

## Seed
`20261031` (`random.Random(seed).shuffle` over the source rows), recorded in `reports/W3-LABEL-SHEET-KEY.md` and `scripts/make_label_sheet.py`. The KEY is now generated too, with the row/question id mapping.

## Files
- `scripts/make_label_sheet.py` generates the sheet and KEY from `reports/W3-LABEL-SHEET-KEY-source.json` (the 24 rows of the 3b9441b sheet, verbatim). `--check` compares with the committed files.
- `tests/test_label_sheet.py` covers (a) and (b) below.
- Prereg note updated to list exactly what the labeller sees.
- Copy refreshed at `/cache/w3-label-sheet/W3-LABEL-SHEET.csv` (where the previous run put it; the old `make.py` there is removed as stale).

## Verification
- (a) Generator rerun with the KEY seed: sha256 `d450127cc54015abf98e18c040e48a09cb3582665f3d09de2025f5afb0c7c60e` for both the regenerated and the committed sheet; `--check` prints "up to date"; the /cache copy has the same sha256.
- (b) Case-insensitive search for blind, held-out, heldout, split, grade, rank, hit, bm25, dense, hybrid: none in the header and none in any column other than question and chunk text (test passes).
- Quotes: all 24 rows' quoted segments (split at ` ... `) appear in their own chunk text, 0 failures. The p-013 and p-030 explanations are in the KEY only. The quote column itself is not on the sheet.
- Suite: `python3 -m unittest discover -s tests`: Ran 835 tests, OK.
- Update: the chunk id column is now opaque (`C01`..), no longer the real `wesley-NNN-cNNNN` id; see `W3-LABEL-SHEET-OPAQUE.md`.
