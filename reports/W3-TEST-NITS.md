# W3-TEST-NITS

Branch `chore/w3-test-nits` from origin/main `387e959` (contains `22aff36`). Tests and this report only. No production change, no new dependencies.

## Items

| Item | Result | Test |
| --- | --- | --- |
| #40 N1 | Already on main (`f6e5278`). `check()` rejects a duplicated `ia_items` entry and an item whose keys are not `ia_identifier`, `tracks`, and `ITEM_FIELDS`. Re-proved below. | `tests/test_licenses.py`: `test_guard_catches_a_duplicated_item`, `test_guard_catches_an_extra_key_in_an_item` |
| #40 N4 | The `addCleanup` restore was already on main (`f6e5278`). This branch registers a `sys.path` equality check first (cleanups run last-in first-out), so dropping the restore fails the test. | `tests/test_shutdown.py::DrainingGateTests` |
| #40 N6 | Already on main. A 4301-digit integer makes `fetch_metadata` raise `ValueError` (the 4300-digit conversion limit). That video is marked `error`, the import exits 1, and the next video is imported. The test passes, so the path fails safe. Production code was not changed. | `tests/test_youtube.py::test_metadata_integer_over_4300_digits_fails_closed_and_the_loop_continues` |
| #43 N2 | Already on main. The test recomputes `random.Random(20261031).shuffle` and checks the sheet's question and chunk-text order, and the KEY `orig #` column, against that order. | `tests/test_label_sheet.py::test_row_order_is_the_seeded_shuffle_of_the_source` |
| #42 r5 N1 | Added `from _sqlite3 import connect` and `__import__('_sqlite3')` next to the existing `import _sqlite3` case, so the ImportFrom arm and the `"_sqlite3"` string arm are each tested on their own. | `tests/test_hard_conditions.py::test_every_bypass_form_is_seen` |

## Mutant proofs

Each mutant was reverted before the full suite.

| Mutant | Result |
| --- | --- |
| Remove the duplicate-length check in `check()` | `test_guard_catches_a_duplicated_item` fails (`AssertionError` not raised). The extra-key test and the manifest test pass. |
| Remove the item key-set check in `check()` | `test_guard_catches_an_extra_key_in_an_item` fails (`AssertionError` not raised). The duplicate test and the manifest test pass. |
| Remove the `sys.path` restore in `DrainingGateTests` | The test fails. `sys.path` still starts with `/work/preached`. |
| `ImportFrom` matches `sqlite3` only | One subtest fails: `from _sqlite3 import connect` scans `(False, 0, 0)`. `import _sqlite3` and `__import__('_sqlite3')` pass. |
| String rule drops the exact `"_sqlite3"` match | One subtest fails: `__import__('_sqlite3')` scans `(False, 0, 0)`. `from _sqlite3 import connect` and `__import__('sqlite3')` pass. |
| `_json_from_stdout` swallows `ValueError` and returns a small dict | The huge-int test fails: `ValueError` not raised. |
| The import loop catches `RuntimeError` only | The huge-int test errors. `ValueError: Exceeds the limit (4300 digits) for integer string conversion: value has 4301 digits` leaves the loop. |
| Drop the shuffle, regenerate the sheet and KEY, and set `PINNED_SHEET_SHA256` to those bytes | `test_literal_pins_seed_sheet_hash_and_header` and `test_regenerates_byte_for_byte_from_key_seed` pass. `test_row_order_is_the_seeded_shuffle_of_the_source` fails on row 0. |

## Verification

- `uv run --frozen python -m unittest discover -s tests`: 979 tests, OK (244.5 s). The two new `_sqlite3` rows are subtests, so the count matches origin/main.
- `uv lock --check`: resolved, no change. No new dependencies.
