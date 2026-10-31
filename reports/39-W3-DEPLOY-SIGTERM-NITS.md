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
PR: see the PR head SHA below.
