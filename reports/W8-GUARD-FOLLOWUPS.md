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

## PR BODY

CTO r2 follow-ups on the cache guard after #78. The guard arms for every test invocation that loads a test module, hybrid SIGTERM requires the fp32 export, and the two must-run tests take their paths from `PREACHED_CACHE`.

- Every `tests/test_*.py` calls `install()` on import. The call is idempotent. `discover -p` that does not load `test_cache_guard.py`, `python -m unittest test_x` inside `tests/`, and `python tests/test_x.py` each fail a deliberate write under a temp cache. `python -m unittest tests.<module>` still arms through `tests/__init__.py`.
- Hybrid load is ready only when the Wesley index exists and the pinned revision directory holds `manifest.json` and every name from `required_filenames("fp32")` (`model.fp32.onnx`, `tokenizer.json`, `pooling.json`). An int8-only directory skips. The skip message names `PREACHED_CACHE`.
- Snap noise is a regular file named `<sibling>.box-store-snap-<digits>` whose sibling is in the same directory. A directory, a symlink, or a real file with a similar name stays visible. The guard docstring records b2: create-then-delete leaves no trace in the before/after listing, and the write hook still fails the run.
- `REAL_INDEX`, the ONNX directory, and `asr-repro` come from `$PREACHED_CACHE`. The server subprocess is given that variable when it is set. Skip messages in `tests/test_embed_backend.py` say `PREACHED_CACHE`.
- With a temp `PREACHED_CACHE` holding read-only copies of the Wesley index, the fp32 export, and `c01.wav` / `c03.wav`, `test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` (default 3 runs) and `test_envelope_matches_the_audio` run and pass. On an empty temp cache they skip, naming `PREACHED_CACHE`.

Mutants for int8-or-fp32 readiness, a broad snap glob, ignoring no snap names, hiding snap-named directories, a no-op `install`, a test module missing the arming line, and a write hook that does not record each went red and were reverted. Full suite on the restored tree, every cache env var on a temp dir, `PREACHED_REQUIRE_DENO=1`: **Ran 1105 tests in 256.006s, OK (skipped=12)**, 0 failures. `find /cache -xdev` before and after: 132687 lines then 132707. The extra lines are concurrent `/cache/xdg` logs, `/cache/demo-kill`, and `cc-speech.sqlite-shm`. Cited files are unchanged, so DEPLOY.md cites stay as they are.

```
 reports/W8-GUARD-FOLLOWUPS.md     | 147 +++++++++++++++++++++++++++++++++++++
 tests/__init__.py                 |   6 +-
 tests/cache_guard.py              |  71 ++++++++++++++----
 tests/test_abstain.py             |   2 +
 tests/test_align.py               |   2 +
 tests/test_api_path.py            |   2 +
 tests/test_app_js.py              |   2 +
 tests/test_apply_grades.py        |   2 +
 tests/test_bench_api.py           |   2 +
 tests/test_bench_failclosed.py    |   2 +
 tests/test_cache_guard.py         | 149 ++++++++++++++++++++++++++++++++++++--
 tests/test_church_harden.py       |   2 +
 tests/test_church_r2.py           |   2 +
 tests/test_church_wire.py         |   2 +
 tests/test_classics.py            |   2 +
 tests/test_corpus.py              |   2 +
 tests/test_coverage.py            |  27 +++++--
 tests/test_cpu_guard.py           |   2 +
 tests/test_dedupe.py              |   2 +
 tests/test_deploy.py              |   2 +
 tests/test_deploy_alerts.py       |   2 +
 tests/test_deploy_regex.py        |   2 +
 tests/test_embed_backend.py       |  14 ++--
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
 tests/test_shutdown.py            | 114 +++++++++++++++++++++--------
 tests/test_side.py                |   2 +
 tests/test_store.py               |   2 +
 tests/test_synthetic_sermon.py    |   2 +
 tests/test_timestamps_eval.py     |   2 +
 tests/test_youtube.py             |   2 +
 60 files changed, 565 insertions(+), 69 deletions(-)
```

This report is part of the head commit. The stat is `git diff --stat origin/main..HEAD` (`origin/main` is `3d4a0aa`).
