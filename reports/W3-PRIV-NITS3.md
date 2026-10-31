# W3-PRIV-NITS3: CTO follow-ups from PR #24

Tests and docs only. No new dependencies.

## What was done
- **S1** `tests/test_priv_review_symlink.py` (`Victim`): the victim file and directory mtimes are set with `os.utime(..., ns=...)` to a fixed past value (2001-09-09) before they are recorded, so a same-tick write on a coarse-clock filesystem still changes the mtime.
- **N1** `test_directory_removed_between_eexist_and_retry_...`: now also counts opens of `race` and asserts exactly 2 (first open, one retry).
- **N2** `tests/test_priv_skip_fixup.py`: comment says the format allows usable/4-2 = 126, SQLite fills usable/4-8 = 120.
- **N3** `reports/W3-PRIV-WIRE.md`: removed the fifth-cell "Unreliable" note from the round-5 table row. The same note already stands as a blockquote above the table.
- **N4** `reports/W3-PRIV-WIRE.md`: "the `shifted` code is kept" now says `shifted` was deleted in round 6 and the `play` code is kept, matching the report's earlier note and `audio_policy.py:14`.

## S1 verification
Mutation: write the victim file and add/remove a file in its directory straight after `Victim()` records the mtimes, then run `untouched()`. 50 runs: **caught 50/50** with the fix.
The pre-fix rate could not be reproduced here: this box is btrfs on Linux 7.2 (fine-grained timestamps, no ext4 available), where the old code also caught 50/50. The CTO's 16/8 of 50 was on ext4's coarse clock.

## Results
- Tests: 619 run, OK (`uv run python -m unittest discover -s tests`).
- `uv lock --check`: passes (79 packages resolved).
