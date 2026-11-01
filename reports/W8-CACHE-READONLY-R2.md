# W8-CACHE-READONLY-R2

CTO r1 on PR #78 (pre-work head 3391ada) asked for changes. This round fixes MF1, MF2, SF1, SF2 and SF3. `origin/main` (`1777fb1`, PR #71) is merged in as `21fbc2d` before these commits.

## What changed

- **MF1.** `test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` skips at runtime unless `hybrid_load_ready` is true. That calls `GRANITE_REVISION`, `VARIANT_FILES` and `required_filenames` from `preached.artifacts`. The index must be a file, and `ONNX_DIR / GRANITE_REVISION` must hold `manifest.json`, the tokenizer name from `required_filenames("fp32")`, and either `VARIANT_FILES["fp32"]` (`model.fp32.onnx`) or `model.int8.onnx`. An empty ONNX directory skips. `test_empty_onnx_dir_skips_hybrid_load` patches the module globals to a present index and an empty temp ONNX directory, runs the real method through `TestCase.run`, and requires one skip and zero failures. The old `is_file() and is_dir()` check is true in that probe, and `hybrid_load_ready` is false, so the server is not started. `test_hybrid_load_ready_follows_the_loader_filenames` covers an fp32 export, an int8-only export, a missing tokenizer, and a missing index.
- **MF2.** `-wal` sidecars of watched files stay in the snapshot. `-shm` stays ignored, and the excluded top-level directories (`uv`, `uv-python`, `venvs`, `xdg`, `demo-kill`) still hide their own `-wal` files. For the duration of a run, `sqlite3.connect` records and raises `sqlite3.OperationalError` (message starts `cache guard: refusing a writable SQLite open`) when the filesystem path is under a watched root and the open is not a URI whose every `mode` parameter is `ro`. `:memory:` is left alone. `test_open_wal_insert_is_caught_while_the_connection_is_open` and `test_open_wal_update_is_caught_while_the_connection_is_open` keep the connection open on a temp fake cache and require the only diff path to be `index/wesley.sqlite-wal`, with the main database entry unchanged. `test_writable_sqlite_open_under_a_watched_root_is_refused` covers a plain path and a `mode=rw` URI, allows `mode=ro`, and allows a connect outside the root.
- **SF1.** `snapshot_tree` uses `lstat` and does not follow links. Files and symlinks compare inode, mode, size, mtime and ctime. Directories compare inode and mode only, so a snap file that only moves a parent directory's timestamps is not a failure. Tests cover a same-size same-mtime `os.replace`, a new file symlink, a symlink to a directory (listed, not descended), an empty directory, and a chmod-only change.
- **SF2.** `python -m unittest discover -s tests` does not import the `tests` package, so `tests/__init__.py` alone does not arm discovery. `tests/test_cache_guard.py` calls `install()` at import, including when discovery loads it as a top-level module. `python -m unittest tests.<module>` still arms through the package. The remaining gap, documented on `cache_guard` and in `tests/__init__.py`: `python -m unittest test_x` with the working directory inside `tests/` does not arm the guard. There is no `tests/README`.
- **SF3.** A path component matching `*.box-store-snap-*` (the `*` may be empty, so `.box-store-snap-N` matches) is ignored in the snapshot and in write classification. `docs/DEPLOY.md` describes that box snapshot daemon. That file is unchanged.
- **S3 and S4, already true on this tree.** `test_fp32_directory_without_int8_loads` copies the graph under `tempfile.gettempdir()` and fails the test if that directory sits inside `PREACHED_CACHE` or `/cache`. `tests/test_shutdown.py` has no `/cache` string.

Cited files stay as they are (`app/server.py`, `docs/DEPLOY.md`, the pins in `tests/test_deploy_alerts.py`). There is no DEPLOY.md re-pin. `src/preached/artifacts.py` stays as it is.

## Mutants (temporary, reverted; the tree matches the pre-mutant bytes)

Each mutant was edited in place, the listed tests went red, and the file was written back from `/tmp/cache_guard.py.good`, `/tmp/test_cache_guard.py.good` or `/tmp/test_shutdown.py.good`. Mutant env: `/tmp/preached-w8mut-JEc3` for `PREACHED_CACHE`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME` and `PREACHED_ONNX_DIR`. Cache snapshot around that script: 132661 lines before and after, 0 changed, 0 outside `/cache/uv`.

| Mutant | Result |
|---|---|
| baseline, same bytes as the restored files | `Ran 18 tests in 0.567s`, OK (`tests.test_cache_guard` plus the two hybrid-ready probes). Temp base `/tmp/preached-w8-BO8d`. Cache snapshot 132661 lines, 0 changed |
| d/d3: exclude `-wal` again | RED, 2 failures. `assertIn("index/wesley.sqlite-wal", before)`: the wal is absent from the snapshot. Insert and update both fail |
| SF1: files compare size and mtime only | RED, `FAILED (failures=3)`: `test_same_size_same_mtime_replace_is_caught`, `test_chmod_only_change_is_caught`, `test_directory_timestamps_are_ignored_and_file_ctime_is_not` (empty diff, `0 != 1`) |
| SF1: skip symlink directories | RED, error, `KeyError: 'linkdir'` |
| SF1: skip symlink files | RED, error, `KeyError: 'models/alias'` |
| SF1: skip directories | RED, error, `KeyError: 'models/empty'` |
| SF3: stop ignoring snap names | RED, failure: the diff lists `index/wesley.sqlite.box-store-snap-4` |
| MF1: `hybrid_load_ready` reduced to `index.is_file() and onnx_dir.is_dir()` | RED, `test_empty_onnx_dir_skips_hybrid_load`: `True is not false`, raised before `TestCase.run`, so the server was not started |
| MF2: sqlite hook is a passthrough to the real `connect` | RED, `OperationalError not raised` |
| SF2: remove `cache_guard.install()` from `test_cache_guard.py` | RED, child `AssertionError: discovery import did not arm the guard` |

The full suite below is the restored tree. It includes these tests.

## Verification

`PREACHED_REQUIRE_DENO=1 uv run python -m unittest discover -s tests`

Temp base `/tmp/preached-w8suite-mplF` (under `tempfile.gettempdir()`, outside `/cache`). These variables pointed at subdirectories of that base: `PREACHED_CACHE`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `PREACHED_ONNX_DIR`, `UV_CACHE_DIR`, `TORCH_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`. `install()` then points `XDG_CACHE_HOME` and `DENO_DIR` at another directory it creates under `tempfile.gettempdir()`.

**Ran 1080 tests in 243.301s, OK (skipped=12).** 0 failures, 0 errors, so 0 `test_every_cited_file_line_holds_its_string` failures.

The 12 skips:

- `test_coverage.CorruptedAsrFixtureTests.test_envelope_matches_the_audio` — needs the clips in `PREACHED_CACHE/asr-repro`
- `test_deploy_regex.DeployRegexTests.test_infra_yaml_matches_when_the_file_is_present` — infra alerts yaml absent
- `test_embed_backend.FdLoadTests.test_load_refuses_a_symlinked_graph` — granite onnx artifacts are not in `/cache`
- `test_embed_backend.FdLoadTests.test_real_graph_has_no_external_data` — granite onnx artifacts are not in `/cache`
- `test_embed_backend.ImportGuardTests.test_youtube_embed_path_does_not_import_torch` — granite onnx artifacts are not in `/cache`
- `test_embed_backend.RealOnnxTests.test_cached_fp32_and_tokenizer_match_the_pins` — granite onnx artifacts are not in `/cache`
- `test_embed_backend.RealOnnxTests.test_fp32_directory_without_int8_loads` — granite onnx artifacts are not in `/cache`
- `test_embed_backend.RealOnnxTests.test_fp32_query_is_unit_normalized` — granite onnx artifacts are not in `/cache`
- `test_eval_leak.TitleLeakTest.test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk` — needs `chunks.jsonl` or the index sqlite in `PREACHED_CACHE`
- `test_onnx_pin_repro.ExportIsByteIdenticalTests.test_exports_under_any_ambient_seed_are_byte_identical_and_are_the_pin` — Granite weights are not in the temp `PREACHED_CACHE`
- `test_onnx_pin_repro.MutantGraphTests.test_one_flipped_initializer_value_is_refused` — granite onnx artifacts are not under the temp `PREACHED_CACHE` or `PREACHED_ONNX_DIR`
- `test_shutdown.LoadedSigtermTests.test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` — needs the Wesley index and the pinned ONNX model under `PREACHED_CACHE`

Cache snapshot, `find /cache -xdev -printf '%p\t%s\t%T@\n'`, before and after this suite: 132661 lines both, 0 changed lines, 0 outside `/cache/uv`. The same holds for the focused run and the mutant run. The nine `-wal` files outside the excluded top-level directories were unchanged: `/cache/index/cc-speech.sqlite-wal`, `edwards.sqlite-wal`, `spurgeon.sqlite-wal`, `wesley-onnx-fp32.sqlite-wal`, `wesley-onnx-int8.sqlite-wal`, `wesley-torch-cpu.sqlite-wal`, `wesley.sqlite-wal`, `/cache/w3-asr/gate-sweep/clean/church.sqlite-wal`, `/cache/w3-asr/gate-sweep/hidden/church.sqlite-wal`.

`PREACHED_SHUTDOWN_RUNS` stayed at its default. bm25 SIGTERM ran. Hybrid SIGTERM skipped because the temp ONNX directory and temp index do not hold the pinned export.

## PR BODY

CTO r1 on PR #78. The suite must not write a real cache, an open SQLite WAL connection must not hide an insert or update, and hybrid SIGTERM must skip when the pinned ONNX export is absent.

- Hybrid load skips unless the Wesley index exists and the pinned revision directory holds `manifest.json`, the loader's tokenizer, and an fp32 or int8 graph. An empty ONNX directory skips. The check calls `preached.artifacts` (`GRANITE_REVISION`, `VARIANT_FILES`, `required_filenames`).
- The cache guard keeps `-wal` files in the snapshot, still ignores `-shm` and the tool-cache directories, and refuses a writable `sqlite3.connect` under a watched root. `mode=ro` URIs pass. Snapshots compare inode, mode and ctime (directories: inode and mode only) and ignore `*.box-store-snap-*`.
- Discovery (`python -m unittest discover -s tests`) arms the guard because `test_cache_guard` calls `install()`. `python -m unittest test_x` with the working directory inside `tests/` still does not arm; that is documented on the module.
- `test_fp32_directory_without_int8_loads` already copies under the temp dir and refuses a temp dir inside a cache. `tests/test_shutdown.py` has no `/cache` string.

Mutants for excluding `-wal`, size/mtime-only identity, skipped symlinks, skipped directories, watched snap names, `is_dir`-only hybrid readiness, a passthrough sqlite hook, and discovery without `install()` each went red and were reverted. Full suite on the restored tree, every cache env var on a temp dir, `PREACHED_REQUIRE_DENO=1`: **Ran 1080 tests in 243.301s, OK (skipped=12)**, 0 failures. `find /cache -xdev` before and after: 132661 lines, 0 differences. Cited files are unchanged, so DEPLOY.md cites stay as they are.

```
 reports/W8-CACHE-READONLY-R2.md |  86 +++++++
 scripts/build-bundle.sh         |   8 +-
 tests/__init__.py               |  10 +
 tests/cache_guard.py            | 510 ++++++++++++++++++++++++++++++++++++++++
 tests/test_cache_guard.py       | 468 ++++++++++++++++++++++++++++++++++++
 tests/test_coverage.py          |  10 +-
 tests/test_deploy.py            |  20 ++
 tests/test_embed_backend.py     |  31 ++-
 tests/test_shutdown.py          | 112 ++++++++-
 9 files changed, 1236 insertions(+), 19 deletions(-)
```

This report is part of the head commit. The stat is `git diff --stat origin/main..HEAD` (`origin/main` is `1777fb1`). It is the whole branch, which is PR #78's files plus this report.
