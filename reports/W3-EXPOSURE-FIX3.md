# 44-W3-EXPOSURE-FIX3: CTO round 3 must-fix on PR #29

Branch `feat/w3-exposure` (PR #29). Precondition: the PR was open at `1523103` (GitHub API, since `gh` is not installed). New head: the commit that adds this file (`git rev-parse origin/feat/w3-exposure`). Code commits: `cd1dc47`, `f3de617`. No rebase or force-push. No deploys, no secrets, no church data. No dependencies added.

The full item map, mutation checks and run tables are in `reports/W3-EXPOSURE-HARDEN.md` under "Round 3 fixes".

## 1. What was done

- **M1 (Expect: 100-continue + Connection: close bypass).** The connection slot is no longer freed in `end_headers`. That hook also ran for the interim `100 Continue`, so such a request left both connection caps for its whole life. `Handler.finish` now frees the slot after `wfile` is flushed and before the socket is closed. That follows the CTO ruling: release after the final body is flushed, so a slow reader stays inside the caps. The `PreachedServer.shutdown_request` override was removed because `finish` covers every way a handler ends. The `process_request_thread` backstop stays. `server_close` (refusal flush), production `daemon_threads = True` and `main()` are untouched.
- **Report note corrected.** The round-2 note "at most one response per connection" in `W3-EXPOSURE-HARDEN.md` is replaced with what was wrong with it.
- **Should 2.** New tests for closes without a response (header deadline, idle keep-alive): the slot must be free while the socket is still open.
- **Should 3.** The harness join is kept.

## 2. How to run

```
uv run python -m unittest tests.test_exposure.SlotReleaseTests
uv run python -m unittest tests.test_exposure
uv run python -m unittest discover -s tests
```

## 3. Results

- New `SlotReleaseTests` (4 tests). On the old server code, all 4 fail. With the Expect probe, 10 held searches ran at cap 4; with the fix, exactly 4. With the CTO's one-line 1xx guard, 3 fail (slow reader, both close tests).
- `tests.test_exposure`: 55 tests. Quiet: 0/20 runs failed. Loaded (24 busy loops): 0/5.
- `SlotFairnessTests`: 0/20 quiet. 2/20 loaded; the round-2 head also fails 2/20 loaded (per-key request-slot race and a scarce-timing test, neither touched here).
- `SlotReleaseTests`: 0/20 quiet, 0/20 loaded.
- Full suite: 784 tests, OK. `uv lock --check` clean.

## 4. Open issues and risks

- **Reconnect race under load.** With release after the flush, a peer at its per-peer cap that reconnects the instant it has read a closing response can get an accept-time 503 (`Retry-After: 1`) before its old handler reaches `finish`. Measured with a cap of 1, no reserve and a separate client process: 0/1000 quiet, 41-67% loaded. The round-2 head refused 0/1000 under the same load. This is the trade-off of the CTO's ruling. It is limited to peers at their cap (default 4), and a trusted proxy is exempt. Left for the CTO to decide.
- The per-key in-flight request slot (`acquire_slot`) race from round 2 is unchanged and still flakes one test under heavy load.
- The PR body was not updated (no `gh` on this machine).

## 5. Dependencies

None.
