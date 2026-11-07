# 99-XW-TEST-VENV-HYGIENE: tests no longer write a bare `.venv` into the worktree

## PR BODY (r2, superseded by r3 below)

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

---

# r2 (99-XX1-PR106-MERGE-MAIN-MF1-MF3): merge of origin/main 2c89365, MF1-MF3 closed

Code head under test: `b9fb0ee956c4a0153037c7e2a6eca47925951637` (merge commit `05d51a0`, then one follow-up commit; this report is committed on top, tests unchanged by it). Host: `preached-sandbox` (Linux 7.2.15-1-omarchy). Pre-merge head was `4e2b39921e42543c6a2eef9679924b4d91bd89b1` (confirmed). Normal merge commit, no rebase, no force-push.

`git diff --stat origin/main...HEAD` (code head b9fb0ee; 0 behind / 4 ahead of origin/main 2c89365):
```
 reports/W5-VENV-HYGIENE.md   | 60 +++ (before this r2 section)
 tests/test_deploy.py         | 39 +++++++++++++++-----
 tests/test_onnx_pin_repro.py |  9 ++++-
 tests/test_shutdown.py       |  2 +-
 tests/test_venv_hygiene.py   | 86 ++++++++++++++++++++++++++++++++++++++++++++
```
Same five files as r1, plus `reports/` r2 text. No production code.

## MF1 closed: conflicts composed, nothing side-picked
Two conflict regions, both in tests/test_deploy.py, both resolved by editing (no `--ours/--theirs`):
1. `BundleTests._env` (tests/test_deploy.py:451-455): `child_env(os.environ, **{"PATH": <sys.executable dir>:$PATH, **extra})`. Main's `child_env(os.environ, ...)` and the branch's interpreter-first PATH both survive; a caller-supplied `PATH` still wins.
2. `test_planted_bytecode_does_not_run` (tests/test_deploy.py:1474-1475): `probe = [sys.executable, ...]` and `base = child_env(PYTHONPATH=...)`.
test_onnx_pin_repro.py and test_shutdown.py auto-merged; main's other child_env hunks (ImportGuardTests, `_serve_env`, bundle checker calls, direct-server start/cleanup, `_sandbox_env`, shutdown helpers) are untouched. `git diff origin/main..HEAD -- tests/test_deploy.py` removes exactly one `child_env` line (`return child_env(os.environ, **extra)` in `_env`), replaced by the composed `child_env(...)` call above; no child_env call is net-removed. tests/test_subproc_env_guard.py (AST guard) is GREEN in both matrix runs.

## MF2 closed
### (a) Launcher/PATH audit (before -> after)
| change | before | after | coverage of launcher fallback |
|---|---|---|---|
| planted-bytecode probe; two direct-start tests | `ROOT/.venv/bin/python` | `sys.executable` | already an explicit interpreter, not launcher lookup; direct `python`/`python -B`/`uv run` launcher variants still iterated in the direct-start test |
| shutdown `PYTHON` | `ROOT/.venv/bin/python` | `Path(sys.executable)` | explicit interpreter; no launcher |
| fixture `.venv` symlinks (source, bundle, `_serve_env`) | `ROOT/.venv` | `Path(sys.prefix)` | serve.sh `-x $ROOT/.venv/bin/python` branch (scripts/serve.sh:75) and build-bundle.sh `$SOURCE/.venv/bin/python` branch (:55) still taken, via the link |
| `BundleTests._env`, `_serve_env` | inherited PATH | interpreter dir prepended | build-bundle.sh `command -v python3` fallback (:58) now resolves to the suite interpreter, never a bare one; the fallback line itself is unchanged and unreached by the suite |
| secret-name serve test | `bash ROOT/scripts/serve.sh`, cwd ROOT | `bash <tmp>/tree/scripts/serve.sh`, cwd tmp tree with `.venv`->sys.prefix | exercises the same `-x .venv/bin/python` branch only. serve.sh's missing-`.venv` `uv run` fallback (serve.sh:76-77,165,214) is **UNTESTED**: the direct-start `uv run` subtest (test_deploy.py:1616-1624) starts `app/server.py` directly, does NOT execute scripts/serve.sh, and so does NOT cover that shell fallback (follow-up S2: add an isolated test that reaches it) |
| ONNX export subprocess | args unchanged | adds `UV_PROJECT_ENVIRONMENT=<tmp>/uv-env` | `uv run` still used; env under tmp |
`scripts/demo.sh` does not exist in this tree (scripts/ has serve.sh, build-bundle.sh, smoke-bundle.sh); nothing to audit there. docs/DEPLOY.md:454 ("uses `bundle/.venv/bin/python` when that exists") describes the unchanged scripts; no production script or DEPLOY cite changed, so no re-pin.

Byte identity: the copied serve.sh is now asserted equal to `scripts/serve.sh` (tests/test_deploy.py, secret-name test).

src/ and app/ symlink write-through (throwaway worktree, `find src app scripts` listing before/after the secret-name test): in a plain run `app/__pycache__/{__init__,server}.cpython-312.pyc` appeared. Cause isolated: merely `import tests.test_deploy` (the test process importing app.server) creates it, before app.server sets its pycache prefix; same on main. With `PYTHONDONTWRITEBYTECODE=1` in the outer env the before/after listings are `cmp`-identical, so serve.sh and the server it launches write nothing through the links. The pre-existing import-time .pyc is untracked/ignored; not changed here.

### (b) Guard mutants
The regex guard flagged comments/strings; I replaced it with an AST detector (`worktree_venv_lines`, tests/test_venv_hygiene.py) plus a spelling test and a comment/string false-positive test. Mutant = a line appended to tests/test_deploy.py, run `tests.test_venv_hygiene`, then restored from a copy (`cmp` identical, `git diff` empty):
| mutant | result | after revert |
|---|---|---|
| `ROOT / ".venv" / "bin" / "python"` | RED (failures=1) | GREEN, cmp identical |
| `ROOT / '.venv'` | RED | GREEN, cmp identical |
| `ROOT.joinpath(".venv")` | RED | GREEN, cmp identical |
| `ROOT.joinpath('.venv')` | RED | GREEN, cmp identical |
| `# comment ROOT / ".venv"` (false-positive) | OK (not flagged) | GREEN |

### (c) Full-suite matrix, sha b9fb0ee, host preached-sandbox
Both: `uv run --frozen python -m unittest discover -s tests`, `env -i`, one `mktemp -d` base for PREACHED_CACHE, PREACHED_ONNX_DIR, HF_HOME, DENO_DIR, XDG_CACHE_HOME, HOME, TORCH_HOME, UV_CACHE_DIR, UV_PYTHON_INSTALL_DIR; `ORT_DISABLE_TELEMETRY=1`, `HF_HUB_OFFLINE=1`, `PREACHED_REQUIRE_DENO=1`; `PREACHED_GUARD_REAL_SRC` unset.
| run | venv | result | checkout `git status` after |
|---|---|---|---|
| A: /tmp worktree, in-tree `.venv` (UV_PROJECT_ENVIRONMENT=<wt>/.venv) | in tree | Ran 1197 total (1182 passed, 15 skipped), OK, exit 0 | clean |
| B: separate /tmp worktree, no `.venv` in tree | UV_PROJECT_ENVIRONMENT outside repo | Ran 1197 total (1182 passed, 15 skipped), OK, exit 0 | clean, no `.venv` created |

### (d) /cache (rule 5 addendum)
`find /cache -xdev -printf '%p\t%s\t%T@\n' | LC_ALL=C sort` before: 139814 lines, sha256 `d2909d2092c778381ae84725728bd3df1c73e7ccd6ac1797d16d7eb7d566ceb7`; after: 139814 lines, same sha256; diff: none. (r1's 132824 count was a different `find` form.)

### (e) gitleaks
`gitleaks` is not on PATH in this sandbox (`which gitleaks` fails); not installed, not run.

## MF3 closed
Real position against merge base used (`origin/main` 2c89365; the old merge base was `ebc058d`): before the merge the branch was 19 behind / 2 ahead of origin/main; after the merge, at b9fb0ee, it is 0 behind / 4 ahead (`git rev-list --left-right --count origin/main...HEAD` = `0 4`; at 05d51a0 alone 0 3, at report head 2df0c1b 0 5). The ebc058d/b090554 counts (1174 OK/12 skipped; main+guard 39 failures/2 errors) are historical and not evidence for this merge; the evidence is the matrix above.

## PR BODY (r2, superseded by r3 below)
Stop tests from writing a bare `.venv` into the worktree (later deploy/shutdown tests picked its numpy-less interpreter). Tests now link bundles to `sys.prefix`, pin `sys.executable`, and build the ONNX-export env under a temp dir. A guard test fails if a test names `ROOT/.venv` (AST-based, ignores comments/strings) or if the suite creates a worktree `.venv`. Test-only; no production code.

r2: merged origin/main 2c89365 (normal merge commit). Two conflicts in tests/test_deploy.py composed by editing: `BundleTests._env` keeps `child_env(os.environ, ...)` and the interpreter-first PATH; the planted-bytecode probe uses `sys.executable` and `child_env(PYTHONPATH=...)`. All other main-side child_env changes are untouched; the AST child_env guard is green.

Base: at code head b9fb0ee, 0 behind / 4 ahead of origin/main 2c89365 (merge commit 05d51a0 alone is 3 ahead; the final report head 2df0c1b is 0 behind / 5 ahead; was 19 behind / 2 ahead before the merge). The earlier ebc058d/b090554 results (1174 OK/12 skipped; main 39F/2E) are historical, not evidence for this merge.

Evidence at b9fb0ee on preached-sandbox: full suite Ran 1197 total (1182 passed, 15 skipped), OK, both with an in-tree /tmp `.venv` and with `UV_PROJECT_ENVIRONMENT` outside the repo; checkout clean after each. Guard mutants for `ROOT / ".venv"`, `ROOT / '.venv'`, `ROOT.joinpath(".venv")` and `ROOT.joinpath('.venv')` go RED then GREEN after revert; a comment/string is not flagged. The copied serve.sh is asserted byte-identical; src/app symlinks are not written through by serve.sh (listing identical with bytecode off). /cache listing unchanged (139814 lines, same sha256). gitleaks not available in the sandbox. Launcher/PATH audit table in reports/W5-VENV-HYGIENE.md.

---

# r3 (99-XX3-PR106-R2-MF4-DOCS): MF4 docs-only correction

Base head 2df0c1b425803d709d05d40dc98fdc70d4c124ae (= origin/test/w5-venv-hygiene, clean). origin/main unchanged at 2c8936583d3939ea5a8e5ae39c2af6eb62d7cbac; not merged, no rebase, no force-push. Only this file changed (`git diff --stat 2df0c1b..HEAD`: `reports/W5-VENV-HYGIENE.md`, one file). No code, test, guard or app change; no DEPLOY cite touched.

## MF4 closed
- Launcher-audit row "secret-name serve test" rewritten: that test exercises only the `-x .venv/bin/python` branch. serve.sh's missing-`.venv` `uv run` fallback (serve.sh:76-77,165,214) is UNTESTED. The direct-start `uv run` subtest (test_deploy.py:1616-1624) starts `app/server.py` directly, does NOT execute scripts/serve.sh, and does NOT cover that fallback. Follow-up S2 (isolated test reaching the shell fallback) is not part of this PR. No sentence claims serve.sh fallback coverage from direct-start evidence.
- N1: positions qualified by exact head: 05d51a0 alone 0 behind / 3 ahead (verified `git rev-list --left-right --count origin/main...05d51a0` = `0 3`), b9fb0ee 0/4, report head 2df0c1b 0/5.
- N2: counts as total with skips: author host preached-sandbox at b9fb0ee 1197 total / 1182 passed / 15 skipped; the reviewer's host (grok-bot-vm) got 1197 total / 1183 passed / 14 skipped. Not relabelled across hosts.
- The exact diff is `git diff 2df0c1b..HEAD -- reports/W5-VENV-HYGIENE.md` (6 insertions, 6 deletions in r3 content hunks: the launcher-audit row, the two matrix rows, the MF3 paragraph, and the PR BODY base/evidence paragraphs; plus this section).

## Full suite on the doc-fix head
Source: commit 334a268238f735da1fcc9f2acda63d2df43d5a70 (doc fix; tests tree identical to 2df0c1b, this r3 section added after). Host preached-sandbox. /tmp worktree with in-tree `.venv` (`uv sync --frozen`), `env -i`, one `mktemp -d` for HOME, XDG_CACHE_HOME, PREACHED_CACHE, PREACHED_ONNX_DIR, HF_HOME, DENO_DIR, TORCH_HOME, UV_CACHE_DIR, UV_PYTHON_INSTALL_DIR, TMPDIR; `ORT_DISABLE_TELEMETRY=1`, `HF_HUB_OFFLINE=1`, `PREACHED_REQUIRE_DENO=1`; PREACHED_GUARD_REAL_SRC unset.
Result: `Ran 1197 tests in 255.100s` / `OK (skipped=15)`, exit 0 (1197 total / 1182 passed / 15 skipped); worktree `git status` clean after.

## /cache (rule 5 addendum)
`find /cache -xdev -printf '%p\t%s\t%T@\n' | LC_ALL=C sort` before: 139814 lines, sha256 `d2909d2092c778381ae84725728bd3df1c73e7ccd6ac1797d16d7eb7d566ceb7`; after: 139814 lines, same sha256; diff: none.

## PR BODY
Stop tests from writing a bare `.venv` into the worktree (later deploy/shutdown tests picked its numpy-less interpreter). Tests now link bundles to `sys.prefix`, pin `sys.executable`, and build the ONNX-export env under a temp dir. A guard test fails if a test names `ROOT/.venv` (AST-based, ignores comments/strings) or if the suite creates a worktree `.venv`. Test-only; no production code.

r2: merged origin/main 2c89365 (normal merge commit). Two conflicts in tests/test_deploy.py composed by editing: `BundleTests._env` keeps `child_env(os.environ, ...)` and the interpreter-first PATH; the planted-bytecode probe uses `sys.executable` and `child_env(PYTHONPATH=...)`. All other main-side child_env changes are untouched.

r3 (docs only, MF4): the launcher audit no longer implies serve.sh fallback coverage. The direct-start `uv run` subtest does not execute scripts/serve.sh; serve.sh's missing-`.venv` `uv run` fallback is UNTESTED (follow-up S2). Base positions are qualified by head: 05d51a0 0/3, b9fb0ee 0/4, report head 2df0c1b 0/5 vs origin/main 2c89365 (unchanged). Counts are total with skips: author host (preached-sandbox) 1197 total / 1182 passed / 15 skipped; reviewer host 1197 / 1183 / 14. Only reports/W5-VENV-HYGIENE.md changes in r3.

Evidence on preached-sandbox (r3 doc head, tests tree identical to 2df0c1b): `Ran 1197`, `OK (skipped=15)`, in-tree /tmp `.venv`, temp caches; /cache listing unchanged (139814 lines, same sha256). gitleaks not available in the sandbox (reviewer ran 8.30.1 clean on main..2df0c1b).
