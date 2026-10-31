# W3-OBS-GAPS: observability gaps (CTO 10:24 ET, #48 review SF1/SF2)

Branch `fix/w3-obs-gaps`, from origin/main `bbdb1ba` (#48 and #42 merged).

## 1. What was done

**Reload fallbacks log once per transition.** `App._serve_keyword_only(note, message)` (`app/server.py:1119`) logs `message` at ERROR only when `fallback_note` changes, so repeated requests in the same fallback log nothing more. Exact alert strings, now constants:

| Line | Where | Trigger |
|---|---|---|
| `ERROR stored vectors do not match search/models.toml; serving BM25 only` | defined `app/server.py:281`; emitted `:1125` via the call at `:1156` (`_reload_cached_index`, EmbeddingMismatch/RuntimeError) | vectors no longer match on reload |
| `ERROR embedding model unavailable; serving BM25 only` | defined `app/server.py:282`; emitted `:1125` via the call at `:1196` (`_refresh_if_stale`, stamp read fails) | index status unreadable on reload |
| startup variants (unchanged text, now use the constants) | `app/server.py:835`, `:838` | load at startup |
| `INFO stopped cleanly` | `app/server.py:3201` | last line of the clean stop path; the stuck path's ERROR is unchanged and it never logs this |

Mapping note: the reload path has no model *load*, so the "unavailable" string is used for the status-read failure (the only other reload fallback). `/healthz` `dense:false` is unchanged as the backstop. Not logged on reload: `not _weights_ok` (weights never loaded; startup already logged it).

## 2. Tests (6 new, suite 977 OK)

- `tests/test_obs_gaps.py`: `test_stored_vectors_that_no_longer_match_log_one_error_line` (3 requests, exactly one line), `test_an_unreadable_index_status_logs_one_error_line_per_transition` (also relogs after recovery then a new failure), `test_the_clean_stop_ends_with_stopped_cleanly`, `test_the_stuck_stop_does_not_say_it`.
- SF1: `tests/test_church_harden.py` `StartupPauseTests.test_a_pause_after_startup_is_logged_even_in_the_deferred_mode`.
- SF2: `tests/test_church_harden.py` `ReserveUpperBoundServeTests.test_a_second_over_cap_connection_is_refused_while_the_reserve_is_held` (real server, cap 2, reserve 1; the reserve held idle, a second /healthz is 503).
- Optional: shutdown-test docstring corrected (no signal is sent there); `test_bench_api` now patches `tempfile.tempdir`, so no `preached-bench-*.stderr` is left in $TMPDIR (1 leaked before, 0 after). The signalled-child "church handle closed" check was not added: the child's handle state is not observable from outside without new instrumentation.

## 3. Mutant checks (applied, test failed, reverted)

| Mutant | Result |
|---|---|
| SF1: `log_startup_pause` no longer sets `_defer_pause_log = False` | new SF1 test FAILS |
| SF2: `_reserved_total >= health_reserved` -> `>` | new SF2 test FAILS (the in-process `tests.test_exposure` tests also fail on it) |
| reload log always fires (`if True`) | `test_obs_gaps` FAILS (per-request logging) |
| `logging.info("stopped cleanly")` removed | `test_obs_gaps` FAILS |

## 4. Checks

Full suite: 977 tests OK (`uv run python -m unittest discover -s tests`). `uv lock --check`: resolved, clean. No new deps. gitleaks is not installed here; not run.

## 5. DEPLOY.md

#45 has NOT merged (docs/DEPLOY.md lacks the "rule drafted, disabled" rows, and `tests/test_deploy_alerts.py` does not exist). Code and tests only; DEPLOY.md untouched. The citations and the OPEN -> MET flips still need doing after #45 merges, against the line numbers above.
