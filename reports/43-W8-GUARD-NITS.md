# 43-W8-GUARD-NITS

CTO non-blocking nits from PR #92. Branch `test/w8-guard-nits` from `origin/main` `6d07f64` (the #92 merge). Tests and reports only. `app/`, `src/`, and `docs/` are untouched. `docs/DEPLOY.md` does not cite these files, so its pins stay as they are.

## What was done

- **N1.** Bullet (e) in `reports/W8-GUARD-FOLLOWUPS-2.md` is marked superseded. The round-1 sentence stays as history: a non-zero atoi, the `sqlite3_uri_boolean` true values. The current rule is the clearly-false rule already written in that report's R2 section. The R2 paragraph that says the bullet still describes the round-1 check is unchanged; it is the record of that review.
- **N2.** `test_sqlite_uri_with_immutable_is_refused` allows `?mode=ro&immutable=0%00` (`tests/test_cache_guard.py:418`). The docstring lists it with the other zeros (`:351`). The decoded value is cut at the first NUL, which leaves `0`, and that is clearly false, so the guard does not refuse the open. On SQLite 3.53.1 the same URI opens, and a read through an EXCLUSIVE lock returns `database is locked`, so SQLite does not treat it as immutable either.
- **N3.** The `tests/cache_guard.py` module docstring names every excluded top-level directory: `uv`, `uv-python`, `venvs`, `xdg`, and `demo-kill` (`:9-10`). Those are the names in `_EXCLUDED_DIRS` (`:105`). A write under one of them is not snapshotted and is not refused. The old sentence that described only the uv cache is gone.
- **N4.** `test_guard_refuses_every_uri_sqlite_opens_immutable` calls `self.fail` when `_uri_supported` is false (`tests/test_cache_guard_immutable_fuzz.py:239`). The module docstring says the test fails (`:7-8`). It does not skip. This SQLite build has URI support, so the fail path did not run; the fuzz itself passed.

## How to run it

Same temp-cache rule as the suite below. Focused:

`uv run python -m unittest tests.test_cache_guard tests.test_cache_guard_immutable_fuzz`

Full suite: `PREACHED_REQUIRE_DENO=1` `HF_HUB_OFFLINE=1` `ORT_DISABLE_TELEMETRY=1` `uv run python -m unittest discover -s tests`, with `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME`, and `UV_PYTHON_INSTALL_DIR` each a subdirectory of one `mktemp -d` under `tempfile.gettempdir()`.

## Results

SQLite 3.53.1 (`uv run python`). Host `preached-sandbox`, 24 cores, Linux 7.2.8-9-omarchy.

Focused run, the tree committed as `38c5363`: `Ran 32 tests in 2.813s`, OK. That is `tests.test_cache_guard` and `tests.test_cache_guard_immutable_fuzz`.

Full suite on `38c5363e663eb823c3e8de99e18a768b7f05f8cb`, host `preached-sandbox`: **Ran 1156 tests in 252.721s, OK (skipped=12)**. 0 failures, 0 errors, so 0 `test_every_cited_file_line_holds_its_string` failures. The skip count is this machine's empty temp cache at that sha. It is not a property of the branch. The report commit after `38c5363` adds only this file.

Temp base `/tmp/preached-w8nits-suite.XaYSIH` (under `tempfile.gettempdir()`, outside `/cache`), removed after the run. The project venv's Python is a symlink into `/cache/uv-python`. `UV_PYTHON_INSTALL_DIR` for the run was the scratch subdirectory, not that path. No cache env var pointed at `/cache`.

Cache snapshot, `find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`, before any test run and after the suite: 132823 lines before, 132823 after. sha256 `55cb67aa9dcf532de1b634f4af32d4b03569f43e6afee472065eb34610e14c45` both times. added 0, removed 0, changed 0.

## Open issues

None. The #92 report's R2 row still says the fuzz skips when URI support is missing. That sentence records the #92 code. The current test fails instead (`tests/test_cache_guard_immutable_fuzz.py:239`).

## Dependencies

None.

## PR BODY

Cache-guard nits from the #92 review. Tests and reports only.

- `?mode=ro&immutable=0%00` is allowed in `test_sqlite_uri_with_immutable_is_refused` (`tests/test_cache_guard.py:418`). The NUL cuts the value to `0`.
- The cache_guard docstring names the excluded directories `uv`, `uv-python`, `venvs`, `xdg`, and `demo-kill` (`tests/cache_guard.py:9-10`, matching `_EXCLUDED_DIRS` at `:105`).
- The differential fuzz fails when the SQLite build has no URI support (`tests/test_cache_guard_immutable_fuzz.py:239`). It does not skip.
- Bullet (e) in `reports/W8-GUARD-FOLLOWUPS-2.md` is marked superseded. The round-1 atoi sentence stays as history. The current rule is the clearly-false rule in that report's R2 section.

Full suite on `38c5363e663eb823c3e8de99e18a768b7f05f8cb`, host `preached-sandbox`: **Ran 1156 tests in 252.721s, OK (skipped=12)**. The skip count is this machine's empty temp cache at that sha. 0 failures. `find /cache -xdev` before and after: 132823 lines both times, sha256 `55cb67aa9dcf532de1b634f4af32d4b03569f43e6afee472065eb34610e14c45`, no differences. `app/`, `src/`, and `docs/` are untouched, so DEPLOY.md cites stay as they are.

```
 reports/43-W8-GUARD-NITS.md              | 58 ++++++++++++++++++++++++++++++++
 reports/W8-GUARD-FOLLOWUPS-2.md          |  2 +-
 tests/cache_guard.py                     |  4 +--
 tests/test_cache_guard.py                |  3 +-
 tests/test_cache_guard_immutable_fuzz.py |  4 +--
 5 files changed, 65 insertions(+), 6 deletions(-)
```
