# 39-W3-DEPLOY-SIGTERM-NITS

Precondition: PR #32 merged (merge commit af06a44 is on origin/main; `gh` is not installed here, so checked via git).

## Changes
1. **Start-up KeyboardInterrupt**: `__main__` catches it and exits 130, no traceback. SIGTERM in any phase is now `SystemExit(0)` (one handler, installed at the top of `app/server.py`); the `main()` handler that raised KeyboardInterrupt is gone.
2. **Exit-code policy**: SIGTERM always exits 0 (a requested stop). Documented in `docs/DEPLOY.md`; no `SuccessExitStatus=143` needed. The old early-phase test that expected 143 now expects 0.
3. **Importers**: the handler and signal mask are installed only when run as `__main__`; an importer gets the temp dir plus atexit but no handler (test).
4. **Temp-dir leak window**: SIGTERM is blocked (`pthread_sigmask`) from before `mkdtemp` until atexit and the handler are in place, then unblocked, so a pending SIGTERM is handled with cleanup registered.
5. **`scripts/synthetic_sermon.py`**: `--jitter-seed N` (seeded random word lengths/gaps, 1-4 s pauses) and `--timings FILE` (caller word times, validated). Default output is byte-identical (tested).

## Tests (new)
SIGTERM at imports (existing, now rc 0), between mkdtemp and handler, inside main() before listening, Ctrl-C inside main (rc 130): each no traceback and no temp-dir leak. Plus import-installs-no-handler, default-unchanged/seeded jitter/coverage gate, caller timings.

Full suite: 705 tests, OK. gitleaks: not installed on this machine, NOT run.
No new dependencies.
PR: not opened (`gh` is not installed here); branch `chore/w3-deploy-sigterm-nits` pushed. Head SHA of the code commit: e3d7abd85e0ea1373cc92c5442a88486abe5da67 (the report commit follows it).

## CTO r1 fixes

Merged `origin/main` (cd3ad8f) first, as merge commit 4d8752c. The review file `/workspace/reports/preached-pr36-review.md` is not on this machine (no `/workspace`), so I worked from the verbatim items in the task.

**Ownership vs #29.** Before coding I read `git diff origin/main origin/feat/w3-exposure -- app/server.py tests/` (at 1523103). #29 does not touch `daemon_threads`, `block_on_close`, thread joining or `main()`'s `finally`. It does override `shutdown_request`, `server_close`, `process_request` and `process_request_thread`. So there were no lines of theirs to copy, and this branch stays out of those four methods. Its additions are `finish_request`, `drain`, `_live` (at the end of the class), the `daemon_threads`/`block_on_close` lines, `serve_until_stopped`, `App.close_embedder` and `OnnxEmbedder.close`. `import socket` is the same line #29 adds. `git merge-tree HEAD origin/feat/w3-exposure` now merges with **no conflict**. An earlier docstring conflict was removed by moving the note into a comment. I did not merge feat/w3-exposure into this branch. On a scratch copy of that merged tree, `tests/test_shutdown.py` passed at 30 runs per mode and `tests/test_exposure.py` passed (51 tests).

### Item → commit / test

| Item | Commit | Test |
|---|---|---|
| MUST-FIX / CTO ruling: SIGTERM under load. Stop accepting, wake idle keep-alive handlers (SHUT_RD, then SHUT_RDWR at half the bound), join the handler threads (non-daemon, `block_on_close`, bounded at `DRAIN_TIMEOUT_S` = 10 s), then close sqlite, then drop the ORT session. While serving, the signal handler raises nothing: `server.shutdown()` runs on another thread. So the accept thread is never interrupted between `_threads.append` and `start` (the join race). `drain` also drops any never-started thread so socketserver's join cannot raise. If a thread is still alive at the bound, the index and session stay open and the process exits 1 (interpreter exit waits for that thread; it cannot crash) | 534fe7d, 7fe55a1, f854415 | `tests/test_shutdown.py` `LoadedSigtermTests` (bm25 + hybrid) |
| S1: SIGTERM during `import onnxruntime` became ImportError and the server served BM25. The handler now records the request, and `serve_until_stopped` checks it before serving | 534fe7d | `test_sigterm_swallowed_by_an_import_still_stops_before_serving` |
| S2: non-zero SystemExit while serving exited 0. SystemExit is no longer caught | 534fe7d | `test_nonzero_exit_while_serving_is_kept` (rc 3) |
| S3: DEPLOY wording. Dropped "always" and "before listening". Now: the first moments before the handler die by signal (keep `SuccessExitStatus=143` for that window); Ctrl-C during module imports prints a traceback and dies by SIGINT; drain timeout exits 1. Every claim names the test that proves it | e76accd | — |
| S4: golden sha256 of the default CLI synthetic sermon (WAV + JSON). Checked by hand: changing seed 7 to 8 fails it | 7415dcb | `test_default_cli_output_is_pinned` |
| S5: SIGTERM while serving | 534fe7d | `test_sigterm_while_serving_idle_exits_zero`, `test_idle_keep_alive_connection_does_not_hold_the_stop` (< 5 s, not the 15 s header deadline) |
| Nit: bad `--timings` gave a traceback. Now a usage error (exit 2), checked before anything is written | 7415dcb | `test_bad_timings_are_a_usage_error` |
| Nit: a failing mkdtemp left SIGTERM blocked. Now unblocked in a `finally` | 534fe7d | `test_failed_mkdtemp_leaves_sigterm_unblocked` |

### Proof runs

The loaded test starts `app/server.py` as a script, waits until 16 clients have had at least 16 searches answered 200, sends SIGTERM, and requires rc 0, no traceback and no `preached-pycache-*` left. It uses the real `/cache/index/wesley.sqlite` and the pinned ONNX model (both present here; hybrid is skipped without them).

- At head f854415, `PREACHED_SHUTDOWN_RUNS=30`: **bm25 30/30, hybrid 30/30. 0 non-zero rc, 0 leaked temp dirs, 0 tracebacks.** The same 30 + 30 also passed at 534fe7d (before the comment-only and test-env commits) and on the #29-merged scratch tree.
- Control: the same tests on the pre-fix server (4d8752c, 4 runs each) failed bm25 2/4 and hybrid 3/4. The swallowed-import test failed there too: that server kept serving. A side repro on the pre-fix server gave bm25 -11 in 1/6 runs (with a leaked dir) and hybrid -6 ("terminate called without an active exception") in 5/6, which matches the review.
- The default is 3 runs per mode, so the suite stays about 2 minutes.

### Checks

- Full suite: `.venv/bin/python -m unittest discover -s tests`: **753 tests, OK**.
- `uv lock --check`: OK (resolved 79 packages). No new dependencies.
- Code head SHA: f85441555bd3d908f59829d9f61dc75167df8fd5 (this report commit follows it).

### Open

- If a handler thread is still busy 10 s after SIGTERM, the process waits for it and exits 1. The tests never reach this path (they finish in under a second). systemd's TimeoutStopSec stays the outer bound.
- After the #29 merge, `server_close` (and so #29's `refusals.flush()`) is skipped on that stuck-thread path. In every drained stop it still runs.
