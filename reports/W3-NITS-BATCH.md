# W3-NITS-BATCH (tests/docs only)

Branch `chore/w3-nits-batch3` off origin/main ad78a75. The name `chore/w3-nits-batch` was already taken by an earlier, already-merged branch (53785f7), so I did not reuse or reset it.

| Item | Change | Evidence |
|---|---|---|
| #51 S1 | `tests/test_obs_gaps.py` `StartupModelFailureRecoveryTests`: `encode=None`, `fallback_note=FALLBACK_NOTE`; the status read fails, then recovers; asserts the note is `FALLBACK_NOTE` again and that no D-line (UNAVAILABLE / STATUS_UNREADABLE / MISMATCH) was logged. The one ERROR is the stamp traceback. | Mutant: `self._base_note = None` at app/server.py:962 (startup note forced to None). The new test FAILS (1 failure, 7 tests); mutant reverted, `app/` is untouched in the diff. |
| #51 N1 | `reports/W3-OBS-GAPS.md` section 2 names the 2 FIX1 tests (`Bm25OnlyStatusReadTests.test_a_status_read_failure_logs_no_d1_or_d2_line_and_healthz_recovers`, `ReloadFallbackLogTests.test_the_stamp_traceback_is_logged_once_per_outage`; from commit 8cd3104). | diff |
| #58 S1 | `tests/test_eval_leak.py`: `index.resolve().as_uri() + "?mode=ro&immutable=1"`. Still read-only; the index is never written or copied. `test_label_sheet.py` builds no sqlite URI; the only one is in test_eval_leak.py. | diff |
| #58 S2 | `# gitleaks:allow` on the `PINNED_KEY_SHA256` line in `tests/test_label_sheet.py`. | diff |
| #59 nit | `scan_sqlite_use` docstring says `<expr>.sqlite3`. The same placeholder in the comment at the later test (about line 357) was changed too, for consistency. | diff |

## Checks

- Full suite with `PREACHED_CACHE=/cache`: 996 tests OK, no skips reported.
- `uv lock --check`: resolved, clean.
- gitleaks is not installed here; not run.
