# W8-GUARD-FOLLOWUPS

CTO r2 should-fixes after PR #78 merged (`origin/main` `3d4a0aa`). New branch `fix/w8-guard-followups`.

## What changed

- **SF-a.** Every `tests/test_*.py` module arms the guard. The line is `__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()`. `install` is idempotent. Package imports (`__package__ == "tests"`) load `tests.cache_guard`. Discovery, `python -m unittest test_x` inside `tests/`, and `python tests/test_x.py` load the top-level `cache_guard` module, because those invocations put `tests/` on `sys.path` and leave `__package__` empty. `tests/__init__.py` still calls `install` for `python -m unittest tests.<module>`. `ArmingInvocationTests` writes a temporary `tests/test_arming_probe.py` (deleted in `tearDown`) that writes `leaked.bin` under a temp `PREACHED_CACHE`, and requires each of these three commands to exit non-zero with `cache guard` and `leaked.bin` in the output:
  - `python -m unittest discover -s tests -p test_arming_probe.py` (the pattern does not match `test_cache_guard.py`)
  - `python -m unittest test_arming_probe` with the working directory `tests/`
  - `python tests/test_arming_probe.py`
  `test_every_test_module_imports_the_guard` requires that line in every test module except `test_cache_guard.py`, which calls `cache_guard.install()` itself.
- **SF-b.** `hybrid_load_ready` is true only when the index is a file and the pinned revision directory holds `manifest.json` plus every name from `required_filenames("fp32")`: `model.fp32.onnx`, `tokenizer.json`, and `pooling.json`. An int8-only directory is not ready, so the hybrid SIGTERM test skips instead of passing on a BM25 fallback. `test_int8_only_dir_skips_hybrid_load` builds that directory under the temp dir, asserts `hybrid_load_ready` is false before `TestCase.run`, and requires one skip whose message names `PREACHED_CACHE`. The server is not started. `test_hybrid_load_ready_follows_the_loader_filenames` also requires `pooling.json` and rejects int8 once the fp32 graph is removed.
- **Snap noise.** Ignored only when the entry is a regular file named `<sibling>.box-store-snap-<digits>` and that sibling is already in the same directory. A directory, a symlink, a non-digit tail, a leading-dot name such as `.box-store-snap-9`, and a file with no sibling stay in the snapshot and in write classification. `test_box_store_snap_names_are_ignored` covers those cases.
- **b2.** The guard docstring states that a file created under a watched root and deleted before the run ends leaves no trace in the before/after listing. The write hook records the creating open, so the run still fails. `test_a_write_under_a_watched_cache_is_remembered_after_it_is_removed` is that case.
- **Skip text.** `tests/test_embed_backend.py` skip messages say `granite onnx artifacts are not in PREACHED_CACHE`.
- **CTO 3a.** `tests/test_shutdown.py` takes `REAL_INDEX` and `ONNX_DIR` from `$PREACHED_CACHE` (`PREACHED_ONNX_DIR` when that is set). An unset `PREACHED_CACHE` stays on a private temp directory. The server subprocess receives `PREACHED_CACHE` and `PREACHED_ONNX_DIR` when they are set, so model load uses that tree. The hybrid skip message names `PREACHED_CACHE`. `tests/test_coverage.py` reads `$PREACHED_CACHE/asr-repro` and skips with `needs the clips in PREACHED_CACHE/asr-repro` when the variable is unset or `c01.wav` is absent. Neither file contains a `/cache` path.

`app/server.py`, `docs/DEPLOY.md`, and the pins in `tests/test_deploy_alerts.py` are unchanged. No DEPLOY cite re-pin.

## Mutants (temporary, reverted; the tree matches the pre-mutant bytes)

Each mutant was edited in place, the listed tests went red, and the file was written back from the bytes taken before the edit. Mutant env: `/tmp/preached-w8mut-4UMZ` (and `/tmp/preached-w8mut2-...` for the directory glob) for `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, and `TORCH_HOME`.

| Mutant | Result |
|---|---|
| SF-b: manifest + tokenizer + (fp32 or int8), pooling not required | RED, 2 failures. `test_int8_only_dir_skips_hybrid_load` and `test_hybrid_load_ready_follows_the_loader_filenames`: `True is not false`, raised before the server started |
| `_snap_noise_file` uses `*.box-store-snap-*` | RED. `index/orphan.box-store-snap-4` is absent from the diff |
| `_snap_noise_file` returns false for every name | RED. The diff lists `index/wesley.sqlite.box-store-snap-4` |
| `_ignored_name` hides `*.box-store-snap-*`, including directories | RED. The diff is empty, so the real file and the real directory are hidden |
| `install` returns immediately | RED, 3 failures. Each child printed `Ran 1 test ... OK` and exited 0 |
| Arming line removed from `tests/test_abstain.py` | RED. `missing == ['test_abstain.py']` |
| `_record` returns immediately (create-then-delete leaves no trace and is not recorded) | RED. `notes == []` |

The full suite below is the restored tree. It includes these tests. Focused run before the mutants, same temp-cache rule: `Ran 23 tests in 1.046s`, OK (`tests.test_cache_guard` plus the three hybrid-readiness probes).

## Must-run proof

`test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` and `test_envelope_matches_the_audio` skip when the files are absent. With `PREACHED_CACHE` pointed at a temp directory that holds read-only copies, both run.

Copy destination `/tmp/preached-proof-5paj87x4`, created with `tempfile.mkdtemp` under `tempfile.gettempdir()`, resolved, and rejected if it was `/cache` or inside it. `shutil.copyfile` (new inode, not a hardlink or a symlink), then mode `0444`. Sources were regular files under `/cache` and were only read:

- `index/wesley.sqlite` (189042688 bytes)
- `models/granite-english-r2-onnx/47ea694b257b703fee9253d75c2b1f2985180498/model.fp32.onnx`, `tokenizer.json`, `pooling.json`, `manifest.json`
- `asr-repro/c01.wav`, `asr-repro/c03.wav`

`PREACHED_ONNX_DIR` was unset, so the hybrid test derived the ONNX root from `$PREACHED_CACHE/models/granite-english-r2-onnx`. `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, and `TORCH_HOME` pointed at a different temp directory. A read-only `open_readonly` of the copied index creates `wesley.sqlite-wal` and `wesley.sqlite-shm` (SQLite WAL does this even for `mode=ro`). Those sidecars were left in the temp copy so the guarded run's before/after listing did not see a new `-wal`. The copied sqlite, graph, and wavs stayed mode `0444`.

`PREACHED_SHUTDOWN_RUNS=1`: `Ran 2 tests in 6.246s`, OK. Both tests `ok`, zero skips.

Default `PREACHED_SHUTDOWN_RUNS` (3), hybrid test alone: `Ran 1 test in 19.384s`, OK. Not skipped.

On the empty suite cache the same two tests skip, and the messages name `PREACHED_CACHE`:

- `skipped 'needs the Wesley index and the pinned ONNX model under PREACHED_CACHE'`
- `skipped 'needs the clips in PREACHED_CACHE/asr-repro'`

`test_cached_fp32_and_tokenizer_match_the_pins` on that empty cache: `skipped 'granite onnx artifacts are not in PREACHED_CACHE'`.

## Verification

`PREACHED_REQUIRE_DENO=1 uv run python -m unittest discover -s tests`

Temp base `/tmp/preached-w8suite-nB3y` (under `tempfile.gettempdir()`, outside `/cache`). These variables pointed at subdirectories of that base: `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME`. `install()` then points `XDG_CACHE_HOME` and `DENO_DIR` at another directory it creates under `tempfile.gettempdir()`.

**Ran 1105 tests in 256.006s, OK (skipped=12).** 0 failures, 0 errors, so 0 `test_every_cited_file_line_holds_its_string` failures.

The skip count is the same 12 as the r1 suite. The two must-run tests are among them on this empty temp cache, with the messages above. They ran on the proof copy.

Cache snapshot, `find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`, taken before any test run and after the suite: 132687 lines before, 132707 after. The differing paths are concurrent writers on this host, in trees this run did not use: `/cache/xdg/claude-cli-nodejs/...` mcp logs (size and mtime), the `/cache/demo-kill` directory mtime, and the mtime of `/cache/index/cc-speech.sqlite-shm` (size still 32768). Zero differing paths outside the excluded top-level directories (`uv`, `uv-python`, `venvs`, `xdg`, `demo-kill`) except that `-shm` mtime. No env var in these runs pointed at `/cache`. The suite's own guard passed, which is the in-process check that the run did not change a watched path.

## R2 (CTO CHANGES at e314301)

Review SHA `e314301a69dce9566ccd30b4d80175ad7b5b0cf8`. Merged `origin/main` with a merge commit (no rebase). `tests/test_listen_backlog.py` arrived on that merge without an arming line.

### MF1

`tests/test_listen_backlog.py` now calls the same arming line as the other modules. On the merged tree it was the only `tests/test_*.py` missing that line. `test_every_test_module_imports_the_guard` walks every `tests/test_*.py` and passes.

### MF2

`ArmingInvocationTests` no longer writes `tests/test_arming_probe.py` into the checkout. `setUp` uses `tempfile.mkdtemp()`, copies `cache_guard.py` and the probe into that tree's `tests/`, and runs the three invocations there. Every path is resolved and rejected unless it is under `tempfile.gettempdir()` and outside `/cache` before `rmtree`. After each run, `tests/` and `tests/__pycache__` have no `test_arming_probe*`.

Tests: `test_discover_pattern_that_skips_this_module_is_armed`, `test_unittest_from_inside_tests_is_armed`, `test_running_the_file_as_a_script_is_armed`, `test_every_test_module_imports_the_guard`.

### MF3

`install()` is idempotent per process. The second of `tests.cache_guard` and top-level `cache_guard` aliases itself onto the first module in `sys.modules`. A sentinel on `unittest.result.TestResult` refuses a second wrap of `startTestRun` / `stopTestRun`. `builtins.open` and `io.open` are captured when the first instance is imported, and restore writes those originals back.

The checks run in subprocesses with temp caches. Importing the module is what `python -m unittest <module>` does before its tests. Each module also imports a top-level test module, which is the second load. One deliberate write then shows how many times the guard reports.

- `test_unittest_tests_test_coverage_loads_the_guard_once` imports `tests.test_coverage` (which imports `test_youtube`). Requires `loaded_names=2 distinct=1`, exactly one cache-guard failure, and `io.open` / `builtins.open` identical to the originals captured before the import.
- `test_unittest_tests_test_church_harden_loads_the_guard_once` does the same for `tests.test_church_harden` (which imports `test_shutdown` and the other top-level test modules).
- `test_two_runs_in_one_process_do_not_recurse_and_a_temp_write_works` loads both names, runs two unittest passes, writes with `open()` and `Path.write_bytes` under a temp dir that is not `PREACHED_CACHE`, and checks that both opens are the originals.

Mutant: `_adopt_loaded_guard` returns immediately, `install()` keys only off the module-level `_installed` flag, and `_install_write_hooks` recaptures `io.open` at hook time. RED, 3 failures. Both package commands printed `loaded_names=2 distinct=2`. The two-run test printed `guard loaded twice`. Reverted from the pre-mutant bytes (`cmp` matched).

### MF4

A SQLite URI under a watched root is allowed only when it has exactly one `mode` parameter and that value is `ro`. There is no case fold and no strip. `mode=ro&mode=rw`, `mode=rw&mode=ro`, `mode=ro&mode=ro`, `mode=RO`, and `mode=rwc` raise the cache-guard `OperationalError`. `mode=ro` and `mode=ro&cache=shared` still read.

Test: `test_sqlite_uri_with_duplicate_or_non_ro_mode_is_refused`.

Mutant: the first `mode` value wins, case-insensitive, so `mode=ro&mode=rw` is treated as readonly. RED, 3 subtest failures. `?mode=ro&mode=rw` reached SQLite (`access mode not allowed: rw`, no `cache guard`). `?mode=ro&mode=ro` opened. `?mode=RO` reached SQLite (`no such access mode: RO`). Reverted.

### SF1

`builtins.open` is hooked as well as `io.open`. They start as one object, so replacing only `io.open` leaves `open()` unhooked. pathlib writes go through `io.open` and did not catch that.

Test: `test_builtin_open_under_a_watched_cache_is_remembered_after_it_is_removed` (`open(..., "wb")`, then the file is deleted before the notes are read).

Mutant: delete `builtins.open = _hooked_builtin_open`. RED. The new test's notes were `[]`. The pathlib create-then-delete test in the same run stayed green (1 failure, 2 tests). Reverted.

### SF2

Directory entries compare inode and mode, so a chmod or `os.replace` of a protected directory is a change. Directory timestamps stay ignored.

Test: `test_chmod_or_replace_of_a_protected_directory_is_caught` (chmod of an empty directory, and `os.replace` of an empty directory with the same permission bits and a new inode).

Mutant: `_visible` returns `(0,)` for directories. RED. The diff was empty, so the chmod was invisible. Reverted.

### SF3

`tests/test_coverage.py` `CacheRootTests.test_unset_preached_cache_does_not_fall_back_to_the_cache_path` unsets `PREACHED_CACHE` and forces `is_file` true for any `/cache` path. `_asr_repro_root` must return `None` and must not touch `/cache`.

Mutant: `os.environ.get("PREACHED_CACHE") or "/cache"`. RED. The function returned `PosixPath('/cache/asr-repro')`. Reverted.

### N2

The `tests/cache_guard.py` module docstring names all six variables: `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, and `UV_CACHE_DIR`.

### Mutants and the suite

Mutant env: `/tmp/preached-w8r2-aeP4` for `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME`, `HF_HUB_CACHE`, and `HUGGINGFACE_HUB_CACHE`. Each mutant was restored from the byte copy taken before the edit.

Focused run on the restored tree, before the full suite: `Ran 27 tests in 2.218s`, OK (`tests.test_cache_guard` and `tests.test_coverage.CacheRootTests`).

`PREACHED_REQUIRE_DENO=1 uv run python -m unittest discover -s tests`

**Ran 1117 tests in 256.480s, OK (skipped=12).** 0 failures, 0 errors, so 0 `test_every_cited_file_line_holds_its_string` failures.

Cache snapshot, `find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`, taken before any test run and after the suite: 132732 lines before, 132732 after. added 0, removed 0, changed 0. No env var in these runs pointed at `/cache`.

`app/`, `src/`, and `docs/` are untouched. DEPLOY.md cites stay as they are.

## PR BODY

CTO r2 follow-ups on the cache guard after #78, and the review fixes from e314301. The guard arms for every test module, including `tests/test_listen_backlog.py`. `install()` is one guard per process. Hybrid SIGTERM requires the fp32 export. The must-run paths come from `PREACHED_CACHE`.

- Every `tests/test_*.py` calls `install()` on import. The arming probe is a temp copy of `cache_guard.py` plus the probe module. `discover -p`, `python -m unittest test_x` inside that `tests/`, and `python tests/test_x.py` each fail a deliberate write. The repo `tests/` directory is not written.
- `tests.cache_guard` and top-level `cache_guard` are one module. `builtins.open` and `io.open` are captured at the first import and restored to those originals. `python -m unittest tests.test_coverage` and `tests.test_church_harden` load the guard once and report one guard failure. Two runs in one process do not recurse, and a temp write works.
- A SQLite URI under a watched root is allowed only with exactly one `mode=ro`. `mode=ro&mode=rw`, a repeated `mode=ro`, and any other mode are refused. Builtin `open()` is hooked. A chmod or `os.replace` of a protected directory is visible. `test_coverage` does not fall back to `/cache` when `PREACHED_CACHE` is unset.
- Hybrid load is ready only when the Wesley index exists and the pinned revision holds `manifest.json` and every name from `required_filenames("fp32")`. Snap noise is a regular file named `<sibling>.box-store-snap-<digits>` whose sibling is in the same directory.
- `REAL_INDEX`, the ONNX directory, and `asr-repro` come from `$PREACHED_CACHE`.

Mutants for a second guard module, a first-mode-only SQLite check, an unhooked builtin `open()`, a directory comparison that ignores inode and mode, and a `/cache` fallback in `test_coverage` each went red and were reverted. Full suite on the restored tree, every cache env var on a temp dir, `PREACHED_REQUIRE_DENO=1`: **Ran 1117 tests in 256.480s, OK (skipped=12)**, 0 failures. `find /cache -xdev` before and after: 132732 lines both times, no differences. `app/`, `src/`, and `docs/` are untouched, so DEPLOY.md cites stay as they are.

```
 reports/W8-GUARD-FOLLOWUPS.md     | 223 ++++++++++++++++++
 tests/__init__.py                 |   6 +-
 tests/cache_guard.py              | 179 +++++++++++----
 tests/test_abstain.py             |   2 +
 tests/test_align.py               |   2 +
 tests/test_api_path.py            |   2 +
 tests/test_app_js.py              |   2 +
 tests/test_apply_grades.py        |   2 +
 tests/test_bench_api.py           |   2 +
 tests/test_bench_failclosed.py    |   2 +
 tests/test_cache_guard.py         | 466 +++++++++++++++++++++++++++++++++++++-
 tests/test_church_harden.py       |   2 +
 tests/test_church_r2.py           |   2 +
 tests/test_church_wire.py         |   2 +
 tests/test_classics.py            |   2 +
 tests/test_corpus.py              |   2 +
 tests/test_coverage.py            |  61 ++++-
 tests/test_cpu_guard.py           |   2 +
 tests/test_dedupe.py              |   2 +
 tests/test_deploy.py              |   2 +
 tests/test_deploy_alerts.py       |   2 +
 tests/test_deploy_regex.py        |   2 +
 tests/test_embed_backend.py       |  14 +-
 tests/test_eval_leak.py           |   2 +
 tests/test_eval_only.py           |   2 +
 tests/test_exposure.py            |   2 +
 tests/test_gate_signals.py        |   2 +
 tests/test_hard_conditions.py     |   2 +
 tests/test_html_503.py            |   2 +
 tests/test_ingest.py              |   2 +
 tests/test_keepalive_cap.py       |   2 +
 tests/test_label_sheet.py         |   2 +
 tests/test_libraries.py           |   2 +
 tests/test_licenses.py            |   2 +
 tests/test_listen_backlog.py      |   2 +
 tests/test_mobile_ux.py           |   2 +
 tests/test_obs_gaps.py            |   2 +
 tests/test_onnx_pin_repro.py      |   2 +
 tests/test_port_busy.py           |   2 +
 tests/test_preroll_paths.py       |   2 +
 tests/test_priv_allowlist.py      |   2 +
 tests/test_priv_links.py          |   2 +
 tests/test_priv_reload.py         |   2 +
 tests/test_priv_review_symlink.py |   2 +
 tests/test_priv_seek.py           |   2 +
 tests/test_priv_skip.py           |   2 +
 tests/test_priv_skip_fixup.py     |   2 +
 tests/test_priv_skip_links.py     |   2 +
 tests/test_priv_wesley_writers.py |   2 +
 tests/test_privacy.py             |   2 +
 tests/test_privacy_merge.py       |   2 +
 tests/test_privacy_wire.py        |   2 +
 tests/test_privacy_wire_fix.py    |   2 +
 tests/test_search.py              |   2 +
 tests/test_server.py              |   2 +
 tests/test_shutdown.py            | 114 +++++++---
 tests/test_side.py                |   2 +
 tests/test_store.py               |   2 +
 tests/test_synthetic_sermon.py    |   2 +
 tests/test_timestamps_eval.py     |   2 +
 tests/test_youtube.py             |   2 +
 61 files changed, 1080 insertions(+), 91 deletions(-)
```

This report is part of the head commit. The stat is `git diff --stat origin/main...HEAD`.

