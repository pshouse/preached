# W5-SUBPROC-ENV-HELPER: child-process env helper

Machine: preached-sandbox. Base: origin/main 3aef7ca. Branch: test/w5-subproc-env-helper.

## PR BODY

Since #94, `src/preached/__init__.py` keeps ORT telemetry off for children that import `preached`. Children that import onnxruntime directly, or get a stripped env, were not covered (`tests/test_deploy.py` passed `env={PATH}` only).

- `tests/subproc_env.py`: `child_env(base=None, /, *, keep=(), **extra)` builds a child env. It always sets `ORT_DISABLE_TELEMETRY=1` (not overridable), a scratch `HOME` and a scratch `XDG_CACHE_HOME` (temp dirs, removed at exit; the removal asserts the path is under the temp root). `keep` lets a test keep an `XDG_CACHE_HOME` it placed on purpose (cache-guard tests).
- Every `subprocess` call with `env=` in `tests/` now goes through it: test_deploy (including the two `{PATH}`-only builders: main 3aef7ca :1458 `base = {"PATH": ...}`, used at :1460 and :1466, and main 3aef7ca :1596; on head e08d4dc the same sites are :1456, used at :1458 and :1464, and :1592), test_shutdown, test_onnx_pin_repro, test_embed_backend, test_hard_conditions, test_cache_guard.
- `scripts/bench_api.py` and `scripts/compare_responses.py` set `ORT_DISABLE_TELEMETRY=1` inline. They run standalone (`compare_responses.py` under `python3 -I`), so they cannot import the tests helper.
- `tests/test_subproc_env_guard.py` (arms `cache_guard` first): an AST scan that fails on any `subprocess.run/Popen/call/check_call/check_output` with `env=` in `tests/` that does not trace to `child_env`. The same scan holds `scripts/` to "names ORT_DISABLE_TELEMETRY". 10 detector tests cover what it flags and passes.
- Deliberate exception: `tests/test_ort_telemetry_off.py` sets or drops the variable on purpose to prove `preached` turns it off, so it is left alone; the scan passes it because the enclosing function names the flag.
- No `app/server.py` or DEPLOY-cited file changed, so no DEPLOY cites moved. DEPLOY.md mentions test files by name only, not by line.
- R2: `test_shutdown._env` and every other builder already went through `child_env` in R1 (the audit found no allow-list builder left in `tests/` or `scripts/`; `scripts/` set the flag inline). `test_shutdown._env` no longer forwards the real `HOME`: `child_env` gives the hybrid server child a scratch `HOME` and `XDG_CACHE_HOME`.
- R2: `tests/test_child_home_guard.py` (arms `cache_guard` first) runs test_shutdown's hybrid server child with a real index and the pinned fp32 model in a fresh temp HOME and asserts no `Microsoft`/`DeveloperTools` directory appears under HOME or XDG_CACHE_HOME. A second test runs a child that imports onnxruntime BEFORE preached and opens the model. A third proves the check can fail: the old shape (no flag, no XDG) writes a `Microsoft` dir. The tests need `PREACHED_GUARD_REAL_SRC`, which must be a read-only bind mount or a pre-made copy of a cache root, never a writable live cache; they byte-copy only the Wesley index and the fp32 export into a temp dir (rule 5), and skip with that reason when it is unset or the files are missing.
- R3: the guard refuses a source file the test process can write to (unless `PREACHED_GUARD_ALLOW_RW_SRC=1`), a non-empty `index/wesley.sqlite-wal` and an existing `index/wesley.sqlite-journal` (only the main db is copied, so committed WAL frames would be missing). Each refusal has a test (`SourceRefusalTests`, fake cache root in a temp dir). The docstring and `tests/README.md` now say the same thing.
- R2: `tests/README.md` states that allow-listed children inherit `HOME` and must use the shared helper.

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

## R2

Machine preached-sandbox. Base origin/main 3aef7ca.

- Real-model guard: RAN with `PREACHED_GUARD_REAL_SRC=/cache`, which in the agent sandbox is mounted read-only (`bwrap --ro-bind`, so the source files were not writable by the test process). It byte-copied (never opened in place) index/wesley.sqlite and the fp32 export into a temp dir; the server answered `mode: hybrid`). 3 tests OK in 3.7s, together with `test_subproc_env_guard` 16 OK. In the default suite run (variable unset) the 3 tests SKIP with reason "PREACHED_GUARD_REAL_SRC is not set: no real index and ONNX model to copy".
- Red/green: `test_guard_sees_a_telemetry_write` is the red case (child with no flag and no XDG_CACHE_HOME, importing onnxruntime first, creates `Microsoft/DeveloperTools` in the temp HOME); the other two are green. Finding: with the flag dropped from the server child's env, the server itself wrote nothing, because `preached` (since #94) sets the flag before onnxruntime loads. So the shutdown guard passes with or without the helper on current main; it locks the property, and the import-first child is the case that depends on the helper.
- Full suite (rule-5 temp caches, command below, no `PREACHED_GUARD_REAL_SRC`): `Ran 1172 tests in 253.9s, OK (skipped=15)` (12 old skips + 3 new). Zero `test_every_cited_file_line_holds_its_string` failures. No DEPLOY-cited file changed.
- /cache before/after: `find /cache -printf '%p %s %T@\n' | sort`, 132823 entries before and after, `diff` empty.

## R3

Machine preached-sandbox. Reviewed head e08d4dc9f566037d98646744c00e30690d405f35; base origin/main 3aef7ca (merge-base).

- MF1: `tests/test_child_home_guard.py` docstring now requires `PREACHED_GUARD_REAL_SRC` to be a read-only bind mount or a pre-made copy of a cache root, never a writable live cache, and says the test only byte-copies `index/wesley.sqlite` and the fp32 export. `tests/README.md` is consistent. The R2 line "RAN with PREACHED_GUARD_REAL_SRC=/cache" now says /cache is read-only in the sandbox (`bwrap --ro-bind`).
- MF2: `{PATH}`-only builders re-pinned to one sha. On main 3aef7ca: :1458 `base = {"PATH": ...}` (used at :1460 and :1466) and :1596. (On head e08d4dc: :1456, used at :1458 and :1464, and :1592.) Verified by reading both files. The old ":1462" was `canary.unlink()` on main.
- MF3: stat below is for the final head.
- MF4: guard refusals added with one test each (writable source, non-empty -wal, existing -journal), plus tests that `PREACHED_GUARD_ALLOW_RW_SRC=1` lifts only the writable refusal, that an empty -wal is accepted, and that a read-only source is accepted. SF2/SF3 not done.
- Real-model run for THIS round: `PREACHED_GUARD_REAL_SRC` pointed at a pre-made `cp` copy under /tmp (index/wesley.sqlite plus manifest.json, model.fp32.onnx, pooling.json, tokenizer.json), made read-only with `chmod -R a-w`; /cache was never the source. `test_child_home_guard` + `test_subproc_env_guard`: 21 tests OK, none skipped. Venv: `UV_PROJECT_ENVIRONMENT=/tmp/venv-r3`.
- Full suite (rule-5 temp caches incl. scratch UV_PYTHON_INSTALL_DIR, ORT_DISABLE_TELEMETRY=1, variable unset), machine preached-sandbox, tree 3aef7ca plus this branch: `Ran 1177 tests in 271.067s, OK (skipped=15)` (1172 + 5 new; the 3 real-model tests skip). Zero `test_every_cited_file_line_holds_its_string` failures. No DEPLOY-cited file changed.
- /cache before/after: `find /cache -printf '%p %s %T@\n' | sort`, 132824 entries before and after, `diff` empty.

## Stat (git diff --stat 3aef7ca..HEAD)

```
 reports/W5-SUBPROC-ENV-HELPER.md |  87 +++++++++++++++
 scripts/bench_api.py             |   1 +
 scripts/compare_responses.py     |   1 +
 tests/README.md                  |  20 ++++
 tests/subproc_env.py             |  56 ++++++++++
 tests/test_cache_guard.py        |  13 ++-
 tests/test_child_home_guard.py   | 222 +++++++++++++++++++++++++++++++++++++++
 tests/test_deploy.py             |  34 +++---
 tests/test_embed_backend.py      |   7 +-
 tests/test_hard_conditions.py    |   3 +-
 tests/test_onnx_pin_repro.py     |  14 ++-
 tests/test_shutdown.py           |   8 +-
 tests/test_subproc_env_guard.py  | 221 ++++++++++++++++++++++++++++++++++++++
 13 files changed, 647 insertions(+), 40 deletions(-)
```

## Tests

Suite command (rule-5 temp caches, `uv run`): `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=$(mktemp -d) HF_HOME=$(mktemp -d) PREACHED_ONNX_DIR=$(mktemp -d) DENO_DIR=$(mktemp -d) XDG_CACHE_HOME=$(mktemp -d) UV_CACHE_DIR=$(mktemp -d) TORCH_HOME=$(mktemp -d) UV_PYTHON_INSTALL_DIR=$(mktemp -d) ORT_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 uv run python -m unittest discover -s tests`

Machine preached-sandbox, tree 3aef7ca plus this change: `Ran 1169 tests in 260.591s, OK (skipped=12)`. Zero `test_every_cited_file_line_holds_its_string` failures.

An earlier run found 5 church-test errors, because I had given `test_shutdown._env` a keyword that other tests' patched lambdas do not accept. I restored the signature and the rerun is clean.

## Cache snapshot

`find /cache -printf '%p %s %T@\n' | sort` before and after the runs (132823 entries): no difference.
