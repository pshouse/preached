# W8-GUARD-FOLLOWUPS-2

CTO non-blocking follow-ups after #84 (`a0e5efc`, ancestor of `origin/main` `e434539`). Tests-only branch `test/w8-guard-followups-2`.

`app/`, `src/`, and `docs/` are untouched. `docs/DEPLOY.md` is not cited by this change, so its pins stay as they are. No test file besides `tests/test_cache_guard.py` needed an edit for the arming check.

## What changed

- **(a) TestResult sentinel.** `install()` returns early only when `unittest.result.TestResult` already has `_preached_cache_guard_installed`. The module flag `_installed` and the `_depth` counter do not do that job. `_depth` makes a second wrap report one failure, so the older once-load and two-run tests stay green if the sentinel is removed. `test_testresult_sentinel_blocks_a_second_wrap_on_its_own` runs in a child with temp caches. It requires the attribute after the first `install()`, an unchanged `startTestRun` / `stopTestRun` on the second `install()`, and a new pair of hooks after the attribute is deleted while `_installed` is still true.
- **(b) `io.open` at import.** `_real_io_open = io.open` is a module-level assignment, and no function assigns that name. `test_io_open_is_captured_at_import_time` checks that with `ast`, then in a child replaces `io.open` after import, installs the hooks, and requires restore to put back the import-time function. A capture inside `_install_write_hooks` would restore the replacement instead.
- **(c) Temp-dir assert in `_remove_temp_tree`.** The helper resolves the path and calls `_assert_under_temp` before `shutil.rmtree`. Every other caller passes a directory from `_temp_root()`, so deleting the assert left the suite green. `test_remove_temp_tree_refuses_a_path_outside_the_temp_dir` still deletes a real temp tree, then calls the helper on `/preached-guard-not-under-temp` (outside the temp dir, not `/cache`, and not present). `shutil.rmtree` is patched to record the call. The assert raises `outside the temp dir` and `rmtree` is not called.
- **(d) Arming line is the first import.** `test_every_test_module_imports_the_guard` parses each `tests/test_*.py` with `ast`. A module docstring and `from __future__` imports may come first. The next statement must be the arming call, compared with `ast.dump`, not as a substring. `test_cache_guard.py` uses that same line as its first import. `test_arming_order_rejects_an_import_before_the_line` rejects an `import` before the call, an arming call nested in a function, and a string that only contains the source. No other test file was out of order, so none was edited.
- **(e) `immutable=1`.** A SQLite URI under a watched root is refused when any percent-decoded query parameter has a case-folded key `immutable` and a value SQLite's `sqlite3_uri_boolean` would treat as true (`yes` / `on` / `true` in any case, or a non-zero atoi). `mode` stays exact: `Mode` is not `mode`, and `RO` is not `ro`. The message is `cache guard: refusing an immutable SQLite open`. `test_sqlite_uri_with_immutable_is_refused` refuses `immutable=1`, `IMMUTABLE=1`, `Immutable=1`, `immutable=TRUE`, `immutable=%31`, `%69mmutable=1`, mixed-case percent-encoding of the key, encoded `true`, `immutable=1` before `mode=ro`, `immutable=1` followed by `immutable=0`, and `immutable=01`. `mode=ro`, `mode=ro&cache=shared`, `immutable=0`, `immutable=false`, `immutable=FALSE`, an empty `immutable`, and `IMMUTABLE=0` still read. The same URI outside the watched root still opens, which is what `tests/test_eval_leak.py` does on a temp file.
- **(f) Outside sqlite unlink.** In `test_writable_sqlite_open_under_a_watched_root_is_refused`, the sibling `{root.name}-outside.sqlite` was removed with `outside.unlink()` and no check of its own (that was the old line 294). It now goes through `_assert_under_temp` before `unlink`. The directory `rmtree` above it already had a temp-dir check.

## Mutants (temporary, reverted; `cmp` matched the pre-mutant bytes)

Mutant env `/tmp/preached-w8mut-ZcfM` for `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, and `TORCH_HOME`. Each edit was restored from the byte copy taken before it.

| Mutant | New test | Older tests |
|---|---|---|
| (a) `install()` returns on `_installed` instead of the TestResult sentinel | RED. Child exit 5, `clearing only the sentinel did not rewrap`. `AssertionError: 5 != 0` | OK. `test_two_runs_in_one_process_do_not_recurse_and_a_temp_write_works` and `test_unittest_tests_test_coverage_loads_the_guard_once`. `Ran 2 tests in 0.844s` |
| (c) `_remove_temp_tree` uses `path.resolve()` and skips `_assert_under_temp` | RED. `AssertionError not raised`. The path does not exist, so `rmtree` was not entered | OK. `test_chmod_or_replace_of_a_protected_directory_is_caught` and `test_sqlite_uri_with_duplicate_or_non_ro_mode_is_refused`. `Ran 2 tests in 0.164s` |
| (e) `immutable = False` in the sqlite hook | RED, 11 subtest failures. `OperationalError not raised` for every refused query, including `?mode=ro&immutable=1`, `?mode=ro&IMMUTABLE=1`, `?mode=ro&immutable=%31`, and `?mode=ro&%69mmutable=1` | OK. `test_sqlite_uri_with_duplicate_or_non_ro_mode_is_refused` and `test_writable_sqlite_open_under_a_watched_root_is_refused`. `Ran 2 tests in 0.178s` |

Focused run on the restored tree, before the full suite: `Ran 31 tests in 2.398s`, OK (`tests.test_cache_guard`).

## Verification

`PREACHED_REQUIRE_DENO=1 uv run python -m unittest discover -s tests`

Temp base `/tmp/preached-w8suite-XV66` (under `tempfile.gettempdir()`, outside `/cache`). These variables pointed at subdirectories of that base: `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME`. `install()` then points `XDG_CACHE_HOME` and `DENO_DIR` at another directory it creates under `tempfile.gettempdir()`.

**Ran 1125 tests in 245.469s, OK (skipped=12).** 0 failures, 0 errors, so 0 `test_every_cited_file_line_holds_its_string` failures. The skip count is this machine's empty temp cache. It is not a property of the branch.

Cache snapshot, `find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`, taken before any test run and after the suite: 132732 lines before, 132732 after. added 0, removed 0, changed 0. No env var in these runs pointed at `/cache`.

## PR BODY

Cache-guard follow-ups after #84. Tests only. The TestResult sentinel, the import-time `io.open` capture, and the temp-dir assert in `_remove_temp_tree` each have a test that goes red when that check is removed. The arming check uses `ast` and requires the arming call to be the first import. SQLite URIs with `immutable=1`, including case and percent-encoding variants, are refused under a watched root. The outside-sqlite unlink checks the temp dir before it removes the file.

Mutants for the sentinel, the temp-dir assert, and the immutable check each went red and were reverted. Full suite on the restored tree, every cache env var on a temp dir, `PREACHED_REQUIRE_DENO=1`: **Ran 1125 tests in 245.469s, OK (skipped=12)**, 0 failures. `find /cache -xdev` before and after: 132732 lines both times, no differences. `app/`, `src/`, and `docs/` are untouched, so DEPLOY.md cites stay as they are.

```
 reports/W8-GUARD-FOLLOWUPS-2.md |  49 +++++++
 tests/cache_guard.py            | 105 ++++++++++++--
 tests/test_cache_guard.py       | 300 ++++++++++++++++++++++++++++++++++++++--
 3 files changed, 432 insertions(+), 22 deletions(-)
```

## R2

CTO review of `12c687a` (PR #92). `origin/main` had moved to `83121da`; that merge was clean. This round edits only `tests/cache_guard.py`, `tests/test_cache_guard.py`, `tests/test_cache_guard_immutable_fuzz.py`, and this report. `app/`, `src/`, and `docs/` are not edited here, so DEPLOY.md cites are not re-pinned. The (e) bullet still describes the round-1 check (a non-zero atoi). The code now uses the clearly-false rule below. The round-1 sentence that said the test refused "a later `immutable=1` after `immutable=0`" was wrong: the query was `immutable=1` followed by `immutable=0`. That sentence is corrected in the paragraph above (`reports/W8-GUARD-FOLLOWUPS-2.md:13`).

SQLite in this run is 3.53.1 (`uv run python`). Red and green used the guard bytes from `12c687a` (the merge did not touch `tests/cache_guard.py`).

| Item | Where |
|---|---|
| MF1. Cut a decoded key and value at the first NUL, then enable `immutable` unless the value is clearly false (empty, `no` / `off` / `false` in any case, or all decimal zeros). Hex and other text are refused. Over-refusing `0x0` is intended. | `tests/cache_guard.py:24` (policy), `:479` (`_cut_at_nul`), `:492` (`_sqlite_immutable_value_enables`), `:508` (`_sqlite_immutable_enabled`), `:545` (the hook) |
| MF1 pins. `0x1`, `0X1`, `yes%00`, `true%00x`, `immutable%00junk=1`. | `tests/test_cache_guard.py:387` through `:391` |
| MF2. Any enabling occurrence, case-insensitive, refuses. The new queries are `?mode=ro&IMMUTABLE=0&immutable=1` and `?mode=ro&immutable=0&immutable=1`. | `tests/cache_guard.py:520` (the loop keeps going after a false value), `tests/test_cache_guard.py:392` and `:393`. Wording: `reports/W8-GUARD-FOLLOWUPS-2.md:13` |
| MF3. Each MF1 class is pinned in the unit test (hex `:387`-`:388`, NUL-cut value `:389`-`:390`, NUL-cut key `:391`). The differential fuzz generates URIs from seed `20261031`, asks real SQLite whether each opens immutable by reading through an EXCLUSIVE lock, and requires the armed guard to refuse every one that does. It skips when the build has no URI support. | `tests/test_cache_guard_immutable_fuzz.py:28` (seed), `:32` (pinned classes), `:193` (lock oracle), `:230` (the test), `:238` (the skip) |
| N1. The module docstring no longer lists `UV_CACHE_DIR` as a cache variable this guard is about. The uv cache is excluded: a top-level `uv` directory under a watched root is not snapshotted and is not a refused write. | `tests/cache_guard.py:3` through `:10` |

Clearly false values that still read: `immutable=00`, `immutable=no`, and `immutable=off` (`tests/test_cache_guard.py:414` through `:416`), plus the round-1 allowed list.

**Red on `12c687a`, green after the fix.** `test_sqlite_uri_with_immutable_is_refused` failed five subtests, each `OperationalError not raised`:

- `?mode=ro&immutable=0x1`
- `?mode=ro&immutable=0X1`
- `?mode=ro&immutable=yes%00`
- `?mode=ro&immutable=true%00x`
- `?mode=ro&immutable%00junk=1`

`?mode=ro&IMMUTABLE=0&immutable=1` and `?mode=ro&immutable=0&immutable=1` already passed on `12c687a`, because that guard already walked every key. They are the mutant pins, not the red/green pair. The fuzz on that same guard, seed `20261031`, failed: 282 of 390 URIs that SQLite 3.53.1 opened immutable were not refused (0.190s). The sample started `0x1`, `0X1`, `0x10`, `0xA`, `yes%00`, `true%00x`, `on%00`, `immutable%00junk=1`. After the fix the same four tests passed: `Ran 4 tests in 0.224s`, OK. The fuzz itself is under a second.

**First-key-only mutant, reverted.** `_sqlite_immutable_enabled` returned on the first case-insensitive `immutable` key instead of continuing. `test_sqlite_uri_with_immutable_is_refused` then failed only `?mode=ro&IMMUTABLE=0&immutable=1` and `?mode=ro&immutable=0&immutable=1` (`OperationalError not raised`). `immutable=1&immutable=0` stayed green. The fuzz failed 22 of 390, sample starting at `?mode=ro&IMMUTABLE=0&immutable=1`. The file was written back from the byte copy taken before the edit; the restored bytes matched.

SQLite 3.53.1 keeps the first value and matches the key with strcmp, so `?mode=ro&immutable=0&immutable=1` does not open immutable, and `?mode=ro&IMMUTABLE=0&immutable=1` does. The guard refuses both.

**Suite.** `PREACHED_REQUIRE_DENO=1` `HF_HUB_OFFLINE=1` `ORT_DISABLE_TELEMETRY=1` `uv run python -m unittest discover -s tests`. Temp base `/tmp/preached-w8r2-suite.E33e` (under `tempfile.gettempdir()`, outside `/cache`). These variables pointed at subdirectories of that base: `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME`.

**Ran 1142 tests in 244.551s, OK (skipped=12).** 0 failures, 0 errors, so 0 `test_every_cited_file_line_holds_its_string` failures. The skip count is this machine's empty temp cache.

Cache snapshot, `find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`, before any test run and after the suite: 132725 lines before, 132725 after. added 0, removed 0, changed 0. No env var in these runs pointed at `/cache`.

Head: `a1b8f26a7546357bbf0ffeab9dfc56dbc0608107` (parent of the commit that records this sha).

```
 reports/W8-GUARD-FOLLOWUPS-2.md          |  95 ++++++++++
 tests/cache_guard.py                     | 116 ++++++++++--
 tests/test_cache_guard.py                | 314 ++++++++++++++++++++++++++++++-
 tests/test_cache_guard_immutable_fuzz.py | 276 +++++++++++++++++++++++++++
 4 files changed, 774 insertions(+), 27 deletions(-)
```
