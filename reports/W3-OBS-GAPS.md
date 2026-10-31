# W3-OBS-GAPS: observability gaps (CTO 10:24 ET, #48 review SF1/SF2)

Branch `fix/w3-obs-gaps`, from origin/main `bbdb1ba` (#48 and #42 merged).

## 1. What was done

**Reload fallbacks log once per transition.** `App._serve_keyword_only(note, message)` (`app/server.py:1131`) logs `message` at ERROR only when `fallback_note` changes, so repeated requests in the same fallback log nothing more. Exact alert strings, now constants:

| Line | Where | Trigger |
|---|---|---|
| `ERROR stored vectors do not match search/models.toml; serving BM25 only` | defined `app/server.py:281`; emitted `:1136` via the call at `:1168` (`_reload_cached_index`, EmbeddingMismatch/RuntimeError) | vectors no longer match on reload |
| `ERROR index status unreadable after reload; serving BM25 only` | defined `app/server.py:283` (`INDEX_STATUS_LOG`); emitted `:1136` via the call at `:1211` (`_refresh_if_stale`, stamp read fails), only when `_weights_ok` | index status unreadable on reload, dense side was loaded |
| `ERROR embedding model unavailable; serving BM25 only` | defined `app/server.py:282`; **startup only**, `:839` (reload no longer emits it) | embedder load failed at startup |
| `ERROR stored vectors do not match search/models.toml; serving BM25 only` (startup, with traceback) | `app/server.py:836` | EmbeddingMismatch at startup |
| `ERROR could not read the index stamp` + traceback | `app/server.py:1088` (`_capture_stamp`) | once per outage, then DEBUG |
| `INFO stopped cleanly` | `app/server.py:3216` (clean stop path) | last line of the clean stop path; the stuck path's ERROR is unchanged and it never logs this |

CTO #51 r1 fixes: the reload status-read failure no longer reuses the "embedding model unavailable" string (D2 page rule `deploy-embedding-unavailable-bm25`); it has its own line (S1). With no weights loaded (`--bm25-only`, or a startup load failure) the reload fallback logs no D1/D2 line at all (MF1), and on recovery `fallback_note` is restored to its startup value so `/healthz` `fallback` does not stay true. `/healthz` `dense:false` is unchanged as the backstop.

## 2. Tests (6 new, +2 in FIX1)

The 2 FIX1 tests: `Bm25OnlyStatusReadTests.test_a_status_read_failure_logs_no_d1_or_d2_line_and_healthz_recovers` and `ReloadFallbackLogTests.test_the_stamp_traceback_is_logged_once_per_outage`.

- `tests/test_obs_gaps.py`: `test_stored_vectors_that_no_longer_match_log_one_error_line` (3 requests, exactly one line), `test_an_unreadable_index_status_logs_one_error_line_per_transition` (also relogs after recovery then a new failure), `test_the_clean_stop_ends_with_stopped_cleanly`, `test_the_stuck_stop_does_not_say_it`.
- SF1: `tests/test_church_harden.py` `StartupPauseTests.test_a_pause_after_startup_is_logged_even_in_the_deferred_mode`.
- SF2: `tests/test_church_harden.py` `ReserveUpperBoundServeTests.test_a_second_over_cap_connection_is_refused_while_the_reserve_is_held` (real server, cap 2, reserve 1; the reserve held idle, a second /healthz is 503).
- Optional: shutdown-test docstring corrected (no signal is sent there); `test_bench_api` now patches `tempfile.tempdir`, so no `preached-bench-*.stderr` is left in $TMPDIR (1 leaked before, 0 after). The signalled-child "church handle closed" check was not added: the child's handle state is not observable from outside without new instrumentation.

## 3. Mutant checks (applied, test failed, reverted)

FIX1 mutants (all in `tests/test_obs_gaps.py`):

| Mutant | Result |
|---|---|
| MF1: drop the `_weights_ok` gate (always pass `INDEX_STATUS_LOG`) | `Bm25OnlyStatusReadTests` FAILS |
| S1: emit `UNAVAILABLE_LOG` on the reload again | `test_an_unreadable_index_status_logs_one_error_line_per_transition` FAILS |
| MF1 recovery: remove `fallback_note = self._base_note` | `Bm25OnlyStatusReadTests` FAILS |
| S2: stamp failure always ERROR | `test_the_stamp_traceback_is_logged_once_per_outage` and `Bm25OnlyStatusReadTests` FAIL |

Original mutants:

| Mutant | Result |
|---|---|
| SF1: `log_startup_pause` no longer sets `_defer_pause_log = False` | new SF1 test FAILS |
| SF2: `_reserved_total >= health_reserved` -> `>` | new SF2 test FAILS (the in-process `tests.test_exposure` tests also fail on it) |
| reload log always fires (`if True`) | `test_obs_gaps` FAILS (per-request logging) |
| `logging.info("stopped cleanly")` removed | `test_obs_gaps` FAILS |

## 4. Checks

Full suite: 979 tests OK (FIX1; 977 before) (`uv run python -m unittest discover -s tests`). `uv lock --check`: resolved, clean. No new deps. gitleaks is not installed here; not run.

## 5. DEPLOY.md

#45 has NOT merged (docs/DEPLOY.md lacks the "rule drafted, disabled" rows, and `tests/test_deploy_alerts.py` does not exist). Code and tests only; DEPLOY.md untouched. The citations and the OPEN -> MET flips still need doing after #45 merges, against the line numbers above.
