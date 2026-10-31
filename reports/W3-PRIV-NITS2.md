# 24-W3-PRIV-NITS2: non-blocking follow-ups from PR #21

- **N1:** new `MkdirRaceTests.test_directory_removed_between_eexist_and_retry_fails_closed_without_looping`. The rival creates the directory (EEXIST) and removes it before the retry. The code must raise `RuntimeError` after exactly one `mkdir`. The test fails an unbounded retry loop: I swapped one in and it failed ("mkdir retried more than a bounded number of times"), then restored the code. `privacy.py` is unchanged; it already retries once.
- **N3:** `Victim` records the file and directory `st_mtime_ns` and `untouched()` compares them, so the swapped-component test now checks mtimes too.
- **N4:** `reports/W3-PRIV-WIRE.md` now quotes the `audio_policy.py` error text ("church libraries accept only 'none' (Patrick's decision; no play link on name passages)").
- **Nit:** the comment in `test_priv_skip_fixup.py` now says 120 leaf numbers per trunk (the SQLite cap), not 126.
- **Docs:** the round-5 turbo p95/p99 timings in `W3-PRIV-WIRE.md` are marked unreliable (CPU whose MKL AMX int8 path corrupted ASR output). `SEEK_SLACK_S = 1.5 s` stands as a decision; re-measuring on clean output is a low-priority follow-up.

Tests: 563 pass (`uv run python -m unittest discover -s tests`). `uv lock --check`: OK (79 packages resolved).
