# W5-SUBPROC-ENV-HELPER: child-process env helper

Machine: preached-sandbox. Base: origin/main 3aef7ca. Branch: test/w5-subproc-env-helper.

## PR BODY

Since #94, `src/preached/__init__.py` keeps ORT telemetry off for children that import `preached`. Children that import onnxruntime directly, or get a stripped env, were not covered (`tests/test_deploy.py` passed `env={PATH}` only).

- `tests/subproc_env.py`: `child_env(base=None, /, *, keep=(), **extra)` builds a child env. It always sets `ORT_DISABLE_TELEMETRY=1` (not overridable), a scratch `HOME` and a scratch `XDG_CACHE_HOME` (temp dirs, removed at exit; the removal asserts the path is under the temp root). `keep` lets a test keep an `XDG_CACHE_HOME` it placed on purpose (cache-guard tests).
- Every `subprocess` call with `env=` in `tests/` now goes through it: test_deploy (including the `{PATH}` sites at :1462 and :1596), test_shutdown, test_onnx_pin_repro, test_embed_backend, test_hard_conditions, test_cache_guard.
- `scripts/bench_api.py` and `scripts/compare_responses.py` set `ORT_DISABLE_TELEMETRY=1` inline. They run standalone (`compare_responses.py` under `python3 -I`), so they cannot import the tests helper.
- `tests/test_subproc_env_guard.py` (arms `cache_guard` first): an AST scan that fails on any `subprocess.run/Popen/call/check_call/check_output` with `env=` in `tests/` that does not trace to `child_env`. The same scan holds `scripts/` to "names ORT_DISABLE_TELEMETRY". 10 detector tests cover what it flags and passes.
- Deliberate exception: `tests/test_ort_telemetry_off.py` sets or drops the variable on purpose to prove `preached` turns it off, so it is left alone; the scan passes it because the enclosing function names the flag.
- No `app/server.py` or DEPLOY-cited file changed, so no DEPLOY cites moved. DEPLOY.md mentions test files by name only, not by line.

No new dependencies.

## Red/green

Red: the guard and helper copied into a `git archive origin/main` tree, run alone:

    FAIL: test_every_script_subprocess_env_names_the_flag
    AssertionError: Lists differ: ['scripts/bench_api.py', 'scripts/compare_responses.py'] != []
    FAIL: test_every_test_subprocess_env_carries_the_flag
    First list contains 40 additional elements. (first: 'tests/test_cache_guard.py:679')
    Ran 13 tests ... FAILED (failures=2)

Green, on the branch:

    Ran 13 tests in 0.732s
    OK

## Stat (git diff --stat origin/main..HEAD)

```
 reports/W5-SUBPROC-ENV-HELPER.md |  47 +++++++++
 scripts/bench_api.py             |   1 +
 scripts/compare_responses.py     |   1 +
 tests/subproc_env.py             |  56 ++++++++++
 tests/test_cache_guard.py        |  13 ++-
 tests/test_deploy.py             |  34 +++---
 tests/test_embed_backend.py      |   7 +-
 tests/test_hard_conditions.py    |   3 +-
 tests/test_onnx_pin_repro.py     |  14 ++-
 tests/test_shutdown.py           |   8 +-
 tests/test_subproc_env_guard.py  | 221 +++++++++++++++++++++++++++++++++++++++
 11 files changed, 365 insertions(+), 40 deletions(-)
```

## Tests

Suite command (rule-5 temp caches, `uv run`): `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=$(mktemp -d) HF_HOME=$(mktemp -d) PREACHED_ONNX_DIR=$(mktemp -d) DENO_DIR=$(mktemp -d) XDG_CACHE_HOME=$(mktemp -d) UV_CACHE_DIR=$(mktemp -d) TORCH_HOME=$(mktemp -d) UV_PYTHON_INSTALL_DIR=$(mktemp -d) ORT_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 uv run python -m unittest discover -s tests`

Machine preached-sandbox, tree 3aef7ca plus this change: `Ran 1169 tests in 260.591s, OK (skipped=12)`. Zero `test_every_cited_file_line_holds_its_string` failures.

An earlier run found 5 church-test errors, because I had given `test_shutdown._env` a keyword that other tests' patched lambdas do not accept. I restored the signature and the rerun is clean.

## Cache snapshot

`find /cache -printf '%p %s %T@\n' | sort` before and after the runs (132823 entries): no difference.
