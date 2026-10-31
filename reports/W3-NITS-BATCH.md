# 44-W3-NITS-BATCH: CTO follow-ups from #25 r2, #35, #34, #36 r2

Branch `chore/w3-nits-batch` from origin/main f9f7551. Merge commits only. No new dependencies.
The review files under /workspace/reports were not on this machine; the items below are from the task text.

## 1. Item -> commit / test map

| Item | Commit | Test / evidence |
|---|---|---|
| #25 (1) README Spurgeon/Edwards licence wording (retired CC Public Domain Certification) | 2c57f16 | README.md licence section |
| #25 (2) drift guard compares every generated field (ia_url, librivox_url, work, series, licenseurl, audio_format, tracks, text_source_url) | 2c57f16 | `tests/test_licenses.py` (`test_every_generated_field_matches_the_manifest`, `test_guard_catches_each_field`) |
| #25 (3) provenance note: `license_note` is hand-written, not generated | 2c57f16 | `wesley.provenance.json` note; `test_note_does_not_claim_the_license_note_is_generated` |
| #25 (4) `abstain_rows` must pass `allow_eval_only=True` | e928eb2 | `tests/test_eval_only.py::test_abstain_rows_passes_the_flag` |
| #25 nit: build_app tests fail on TypeError | e928eb2 | `tests/test_search.py` passes a real `static_dir` |
| #25 nit: HOUSEKEEPING.md "left as is" | 2c57f16 | reports/HOUSEKEEPING.md |
| #35 S1 overflowing metadata duration keeps the listed one | 150199a | `tests/test_youtube.py::test_huge_metadata_duration_keeps_the_listed_one` (listed 60 -> seen == [60.0]; listed None -> unchecked) |
| #35 S2 gitleaks clean | e3b2992 | reports/38-W3-YT-DURATION-NITS.md |
| #35 nits: one float conversion; huge-int rows de-duplicated | 150199a | `stated_duration`; the 2**1024 row moved out of `test_bad_stated_duration_is_unchecked`. The "rejects bool" commit message is history and is left. |
| #34 S6 README 0.42 s / 0.76 s figures | 2c57f16 | README.md:25 now quotes no timing figure |
| #36 S2 loaded test is probabilistic | b07a618, 96d8090 | Deterministic `InFlightTests.test_search_in_flight_at_sigterm_finishes_before_the_index_closes`; DEPLOY names the 30-run real-index loaded run as the gate |
| #36 S3 stuck path (rc 1) and Ctrl-C while serving (rc 0) | 96d8090 | `test_stuck_handler_exits_one_leaves_the_index_open_and_ignores_a_second_ctrl_c`, `test_ctrl_c_while_serving_exits_zero` |
| #36 S4 draining gate (M9) | 96d8090 | `DrainingGateTests` |
| #36 S5 "143" only on the uv run path | b07a618 | docs/DEPLOY.md |
| #36 S6 second Ctrl-C does not force an exit | b07a618 | docs/DEPLOY.md; also asserted in the stuck-path test |

Not done: the stuck-path RefusalLog flush (belongs to #29; it is not on main).

## 2. Mutation results (each reverted afterwards)

| Mutant | Result |
|---|---|
| (4) drop `allow_eval_only=True` from `abstain_rows` (bench.py:632) | `test_abstain_rows_passes_the_flag` errors (RuntimeError: eval-only) |
| build_app guard removed (`if False:`) | both `test_build_app_*` fail with `AssertionError: ValueError not raised` (were TypeError) |
| (2) append "x" to each of ia_url, librivox_url, work, series, licenseurl, audio_format, tracks, text_source_url | `test_guard_catches_each_field` asserts each raises |
| #35 S1 pipeline sets `duration_s = None` on overflow | `test_huge_metadata_duration_keeps_the_listed_one` fails (listed=60) |
| #35 pipeline `except OverflowError` replaced | same test fails (listed=60 and None) |
| #35 `stated_duration` `except OverflowError` replaced | 6 errors in `test_coverage` |
| #36 S4 / M9: remove the `draining` gate in `finish_request` | `DrainingGateTests` fails |
| #36 stuck path exits 0 instead of 1 | stuck-path test fails |
| #36 drain removed and handler threads daemon / not joined (the pre-#36 state) | in-flight test fails (client gets no response) |
| #36 drain call removed alone | stuck-path and idle keep-alive tests fail; in-flight test still passes, because `server_close` joins non-daemon threads, so it does not guard that single line |

## 3. Results

- `uv lock --check`: ok.
- `uv run python -m unittest discover -s tests`: 766 tests, OK (was 694+ before this batch; this adds 8 shutdown/licence/youtube tests and moves rows).
- Not run: the real-index 30-run loaded shutdown check (no `/cache` index with the pinned model on this machine).
- `gh` is not installed here, so no PR was opened. Title to use: "W3: nits batch (CTO #25 r2, #35, #34, #36)".

Head SHA: the commit that adds this report (see the push); last code commit 96d8090.

---

# W3-NITS-BATCH, round 3 (tests/docs only; CTO should-fixes from #51, #58, #59)

Branch `chore/w3-nits-batch3` off origin/main ad78a75. The name `chore/w3-nits-batch` was already taken by an earlier, already-merged branch (53785f7), so I did not reuse or reset it.

| Item | Change | Evidence |
|---|---|---|
| #51 S1 | `tests/test_obs_gaps.py` `StartupModelFailureRecoveryTests`: `encode=None`, `fallback_note=FALLBACK_NOTE`; the status read fails, then recovers; asserts the note is `FALLBACK_NOTE` again and that no D-line (UNAVAILABLE / STATUS_UNREADABLE / MISMATCH) was logged. The one ERROR is the stamp traceback. | Mutant: `self._base_note = None` at app/server.py:962 (startup note forced to None). The new test FAILS (1 failure, 7 tests); mutant reverted, `app/` is untouched in the diff. |
| #51 N1 | `reports/W3-OBS-GAPS.md` section 2 names the 2 FIX1 tests (`Bm25OnlyStatusReadTests.test_a_status_read_failure_logs_no_d1_or_d2_line_and_healthz_recovers`, `ReloadFallbackLogTests.test_the_stamp_traceback_is_logged_once_per_outage`; from commit 8cd3104). | diff |
| #58 S1 | `tests/test_eval_leak.py`: `index.resolve().as_uri() + "?mode=ro&immutable=1"`. Still read-only; the index is never written or copied. `test_label_sheet.py` builds no sqlite URI; the only one is in test_eval_leak.py. | diff |
| #58 S2 | `# gitleaks:allow` on the `PINNED_KEY_SHA256` line in `tests/test_label_sheet.py`. | diff |
| #59 nit | `scan_sqlite_use` docstring says `<expr>.sqlite3`. The same placeholder in the comment inside `scan_sqlite_use` itself (`tests/test_hard_conditions.py`, about line 357) was changed too, for consistency. | diff |

## Checks

- Full suite with `PREACHED_CACHE=/cache`: 996 tests OK, no skips reported.
- `uv lock --check`: resolved, clean.
- gitleaks is not installed here; not run. It was since run by the CTO and is clean.

## Round 4 (92-W3-NITS-BATCH4), branch `chore/w3-nits-batch4` off 048e72f

Tests and reports only. Each item was checked against current main first.

| Item | Result | Where |
|---|---|---|
| #65 S1 | Fixed. The disk snapshot assertion moved into the `finally`, after `conn.close()`. | `tests/test_eval_leak.py` `ReadonlyUriTest` |
| #65 N1 | Fixed. Comment on `NAMES`: `'a b'` documents that a space is fine (SQLite accepts it) and is not a regression guard. | `tests/test_eval_leak.py` `ReadonlyUriTest.NAMES` |
| #50 r3 S6 | Already on main, unchanged. `load_chunk_texts()` falls back to the index sqlite opened read-only (`immutable=1`). | `tests/test_eval_leak.py:47-60` |
| #50 N2 | Already on main, unchanged. Literal `PINNED_KEY_SHA256`, asserted against `gen.KEY`. | `tests/test_label_sheet.py:25`, `:43` |
| #50 N3 | Already on main, unchanged. `self.fail(f"mirror has no source line: {where}")`. | `tests/test_eval_leak.py:209` |
| #42 r5 N1 | Already on main, unchanged. `from _sqlite3 import connect` and `__import__('_sqlite3')` cases. | `tests/test_hard_conditions.py:519-522`. #42 N1 landed without the `connect()` call; the CTO accepted that. |
| #43 N2 | Already on main, unchanged. Recomputes `random.Random(PINNED_SEED).shuffle` and checks row order and the KEY `orig #` order. | `tests/test_label_sheet.py:105-117` |
| #43 N3 | Already on main, unchanged. Last line says the chunk id column is now opaque (`C01`..). | `reports/W3-LABEL-SHEET-BLIND.md` (last line) |
| #40 N1 | Already on main, unchanged. Duplicate `ia_items` and extra-key tests. | `tests/test_licenses.py:72-85`. The optional creator-vs-author check from #40 N1 was not taken. |
| #40 N4 | Already on main, unchanged. `DrainingGateTests` saves and restores `sys.path`, and asserts the restore. | `tests/test_shutdown.py:318-326` |
| #40 N6 | Already on main, unchanged. 4301-digit int fails closed and the loop continues. | `tests/test_youtube.py:713` |

No item needed a non-test code change, so nothing is waiting on the CTO.

### Mutant checks (recorded, then reverted)

- #65 S1: URI built as `f"file:{index.resolve()}?mode=ro&immutable=1"` with the SELECT assertion also removed. `ReadonlyUriTest` fails on `'h#frag'` (parent listing `['h', 'h#frag']` vs `['h#frag']`) and on `'all %?# x'` (`['all %', 'all %?# x']`). It also errors on `'pct%41'` and `'q?mode=rw'`. So the disk guard stands alone. Unmutated, the test passes.
- #65 N1 is a comment only; no behaviour to mutate.
- The "already on main" items add no new tests in this round, so there is nothing new to mutate.

### Checks

- Full suite with `PREACHED_CACHE=/cache`: Ran 997 tests, OK, 0 skips. Correction (#66 N3): the count on main 1793b06 is 998, not 997. After the deno hard-fail and port-busy change (one new test) it is 999; see `reports/W3-DENO-HARDFAIL-PORTBUSY.md`.
- `uv lock --check`: resolved 79 packages, clean.
