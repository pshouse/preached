# W3-NITS-BATCH2: parked CTO nits from #40 and #43

Branch `chore/w3-nits-batch2`, off origin/main 96195be (contains 3e7465a). Tests, README and one appended report line only; no change to `src/`, the sheet bytes, DEPLOY.md, the tripwire scanner, `tests/test_hard_conditions.py`, the label-sheet KEY files or the prereg.

| Item | Change | Test |
| --- | --- | --- |
| #40 N1 | `check()` in `tests/test_licenses.py` rejects a duplicated `ia_items` entry and any item whose key set differs from `ia_identifier`, `tracks` + `ITEM_FIELDS` | `test_guard_catches_a_duplicated_item`, `test_guard_catches_an_extra_key_in_an_item` |
| #40 N2 | README uses CC's name: "Copyright-Only Dedication (based on United States law) or Public Domain Certification", retired 2010-10-11 | none (docs) |
| #40 N4 | `DrainingGateTests` saves `sys.path` and restores it with `addCleanup` | `tests/test_shutdown.py::DrainingGateTests` (the fix is in the test itself) |
| #40 N6 | No behaviour change. Pins the fail-closed path: a 4301-digit integer makes `fetch_metadata` raise `ValueError`; the import marks that video `error`, exits 1 and imports the next video | `tests/test_youtube.py::test_metadata_integer_over_4300_digits_fails_closed_and_the_loop_continues` |
| #40 N5 | Skipped as instructed (historical report wording) | n/a |
| #43 N2 | Test recomputes `random.Random(20261031).shuffle` over the source and asserts the sheet's row order, and the KEY's `orig #` column order, equal it | `tests/test_label_sheet.py::test_row_order_is_the_seeded_shuffle_of_the_source` |
| #43 N3 | One line appended to `W3-LABEL-SHEET-BLIND.md` saying the chunk id column is now opaque (see `W3-LABEL-SHEET-OPAQUE.md`) | none (docs) |

## Verification
- `uv run --frozen python -m unittest discover -s tests`: Ran 965 tests, OK.
- `uv lock --check`: resolved, no change. No new dependencies.
- `scripts/make_label_sheet.py --check`: up to date; `W3-LABEL-SHEET.csv` sha256 still `6141beaa...5369b12`.
- Caveats: `gh` and `sandbox.sh` are not available, so the PR is opened by hand from the compare URL.
