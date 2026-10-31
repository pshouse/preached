# W3-LABEL-NITS

Test-only nits from the CTO's #50 r3. No label, prereg, `app/` or `docs/` change; `eval/*` and `reports/W3-LABEL-*` are byte-identical.

- **S6** `tests/test_eval_leak.py`: the anchor test reads chunk text from `chunks.jsonl`, else from the index sqlite opened `file:...?mode=ro&immutable=1` (never written or copied). It skips only when neither exists. Passes with `PREACHED_CACHE=/cache` and with an index-only dir; skips with an empty dir. Mutation: truncating the sqlite text makes it fail (13 subtests) on the index-only path.
- **N2** `tests/test_label_sheet.py`: `PINNED_KEY_SHA256` pins `W3-LABEL-SHEET-KEY.md`. Mutation: appending a space to KEY.md fails `test_literal_pins_seed_sheet_hash_and_header`.
- **N3** `tests/test_eval_leak.py`: a mirror without a source line fails with `mirror has no source line: q-means L16`. Mutation: deleting that source line from `partial_verdicts.jsonl`.

All mutations were reverted.

Full suite with `PREACHED_CACHE=/cache`: 987 tests, OK, 0 skipped. `uv lock --check`: clean (79 packages).
