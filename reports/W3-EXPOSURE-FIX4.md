# 44-W3-EXPOSURE-FIX4: flush refusal counts on the stuck-drain path (PR #29 r4 must-fix)

Branch `feat/w3-exposure` (PR #29, still open). PR #36 is merged into main.

- Merge of origin/main (with #36): `5808118`
- Fix + test: `ef0045e`
- Head: the commit that adds this report (the `git log -1` on the pushed branch)

## 1. What was done

1. **Merged origin/main into the branch** with a merge commit (no rebase, no force-push). It merged cleanly with no conflicts.
   #36's stop order is unchanged: `serve_until_stopped` stops the serve loop, then `drain()` runs, handler threads stay
   non-daemon (`daemon_threads = False`, `block_on_close = True`), and the normal path calls `server_close()`, then
   `connection.close()`, then `app.close_embedder()`.
2. **The must-fix** (`app/server.py`, `serve_until_stopped`): when `drain()` returns stuck threads (the exit 1 path),
   the RefusalLog is flushed right away:
   `refusals = getattr(server, "refusals", None); if refusals is not None: refusals.flush()`.
   `server_close()` is **not** called there. With `block_on_close` it joins the stuck thread, so a systemd SIGKILL
   would arrive before the flush. The CTO marked that call as optional, and leaving it out is the safe choice.
   sqlite and the embedder stay open on this path, as before.
3. **Test** `AuditLogTests.test_suppressed_counts_are_flushed_when_a_handler_is_stuck` (`tests/test_exposure.py`):
   - holds one `/api/search` handler inside the search, which ignores the socket shutdown that drain sends
   - logs 13 suppressed `429-client` refusals and 12 suppressed `busy` refusals
   - stops the serve loop and runs the real `serve_until_stopped` with a 0.3 s drain bound
   - requires `SystemExit(1)`, both `flush suppressed=N` lines, and the handler **still alive** after the return
   - requires that neither `connection.close` nor `close_embedder` was called

## 2. How to run

```
uv lock --check
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_exposure.AuditLogTests.test_suppressed_counts_are_flushed_when_a_handler_is_stuck
for i in $(seq 10); do uv run python -m unittest discover -s tests -p test_exposure.py; done
for i in $(seq 10); do uv run python -m unittest discover -s tests -p test_exposure.py -k SlotFairnessTests; done
```

## 3. Results

- Full suite: **814 tests, OK** (138 s). `tests.test_shutdown`: all 7 ran, none skipped, including hybrid under load.
- `uv lock --check`: OK (79 packages resolved).
- `tests/test_exposure.py` x10: 10/10 OK (56 tests each, 30–32 s).
- `SlotFairnessTests` x10: 10/10 OK (10 tests each, about 10.7 s).
- Mutation checks on the new test:
  - Flush removed (stuck branch only logs the error): **FAIL**, `'refused 429-client flush suppressed=13' not found`.
  - Flush replaced by a bare `server_close()`: **FAIL**, `0 != 1 : the handler must still be stuck when the counts
    are logged`. The `server_close()` join waited on the stuck handler until its 5 s hold timed out.
  - Fix restored: OK.

## 4. Open issues / risks

- The task said to use `sandbox.sh` for git, but no `sandbox.sh` exists in the repo, `/task`, or anywhere on the
  filesystem. I used plain `git` in the worktree. There was no force-push and no history rewrite.
- `gh` is not installed. I checked the precondition through git instead: the branch head is not an ancestor of
  `origin/main`, so #29 is not merged, and #36's merge commit `f9f7551` is on `origin/main`. I did not add a PR comment.
- During the test, the stuck handler logs `request failed: BrokenPipeError` when it is finally released, because drain
  had already shut its socket. This is expected and harmless.

## 5. Dependencies added

None.
