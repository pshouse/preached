# 99-XW-TEST-VENV-HYGIENE: tests no longer write a bare `.venv` into the worktree

## PR BODY

Tests no longer create a bare `.venv` in the repo worktree. Test-only change; no production script or DEPLOY-cited file is touched.

**Cause.** `tests/test_deploy.py` linked its bundle fixtures' `.venv` to `ROOT/.venv`. In a worktree with no `.venv` that link dangles, and the `uv run --frozen --no-sync ...` launcher test (and `serve.sh` run from the checkout, which falls back to `uv run`) then created a bare `ROOT/.venv` with no numpy. Later tests chose its interpreter (`test_shutdown.PYTHON`, the `ROOT/.venv/bin/python` probes in `test_deploy`), so 17-39 tests failed depending on order. Main fails the same way.

**Fix (tests only).**
- `test_deploy.py`: bundle fixtures link `.venv` to `VENV = Path(sys.prefix)`; the interpreter is `sys.executable`; `_env`/`_serve_env` put `sys.executable`'s bin first on `PATH` (`build-bundle.sh` otherwise uses `python3` from `PATH` when `ROOT/.venv` is absent); `test_serve_sh_drops_secret_names` runs a copy of `serve.sh` in a temp checkout-shaped tree instead of `ROOT`.
- `test_shutdown.py`: `PYTHON = Path(sys.executable)`.
- `test_onnx_pin_repro.py`: the `uv run --group bench` export gets `UV_PROJECT_ENVIRONMENT` under its temp dir.
- New `tests/test_venv_hygiene.py` (imports `cache_guard` first): fails if any test names `ROOT / ".venv"`, and fails if a `.venv` appeared in the worktree during the run.

No new dependencies. DEPLOY.md cites: none of the edited files is cited with line pins, so nothing to re-pin.

## Stat

`git diff --stat origin/main..HEAD` (code commit b090554, before this report):

```
 tests/test_deploy.py         | 35 +++++++++++++++++++++++++++--------
 tests/test_onnx_pin_repro.py |  9 ++++++++-
 tests/test_shutdown.py       |  2 +-
 tests/test_venv_hygiene.py   | 41 +++++++++++++++++++++++++++++++++++++++++
 4 files changed, 77 insertions(+), 10 deletions(-)
```

## Red on main, green on the branch

Guard test copied onto a clean main worktree (no `.venv`):
- Guard alone: `test_no_test_names_the_worktree_venv` FAILS, listing `test_deploy.py` (x5) and `test_shutdown.py:44`.
- `unittest tests.test_deploy tests.test_venv_hygiene`: both guard tests FAIL; `.venv` now exists in the worktree.
- Branch, same plus `test_onnx_pin_repro` and `test_shutdown`: guard passes, no `.venv` afterwards.

## Trap repro

On main (fresh worktree, no `.venv`; a venv at `/tmp/vh/env` runs the tests):
1. `python -m unittest tests.test_shutdown` alone: 14 tests, OK (1 skipped).
2. `python -m unittest tests.test_deploy`: 71 tests, 28 failures and 1 error; `.venv` (no numpy) appears at `ROOT/.venv`.
3. `python -m unittest tests.test_shutdown` again: FAILED (failures=7, errors=1, skipped=1). It now picks `.venv/bin/python`.

On the branch the same sequence leaves no `.venv`, and deploy and shutdown pass.

## Test results

Machine: `preached-sandbox` (Linux 7.2.8 omarchy). Command (rule 5 temp dirs):
`PREACHED_REQUIRE_DENO=1` with temp `PREACHED_CACHE`, `HF_HOME`, `PREACHED_ONNX_DIR`, `DENO_DIR`, `XDG_CACHE_HOME`, `TORCH_HOME`; `UV_PROJECT_ENVIRONMENT=/tmp/vh/env`, scratch `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR`; `ORT_DISABLE_TELEMETRY=1`; `HF_HUB_OFFLINE=1`; `PREACHED_GUARD_REAL_SRC` unset; then `python -m unittest discover -s tests`.

| tree | sha | result |
|---|---|---|
| main + guard test, worktree without `.venv` | ebc058d | Ran 1174: 39 failures, 2 errors, 12 skipped; `.venv` created |
| branch | b090554 (code) | Ran 1174: OK, 12 skipped; no `.venv` created |

The run counts the new guard tests (1174 on both sides includes them; main's number is with the guard copied in).

/cache listing (`find /cache -printf '%p %s %T@\n'`, 132824 entries) before and after all runs: identical.

## Notes
- The three `HealthzSearchModeTests` errors only appear under `python -m unittest tests.test_onnx_pin_repro` (`No module named 'test_server'`); they also occur on main and pass under `discover -s tests`.
