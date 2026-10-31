# W3-CHURCH-HD: church hard conditions HD1 + HD3 (CTO #46)

## 1. What was done

- **HD1.** `main` builds the App with `defer_church_pause_log=True`. A pause found while the App is built is held and logged by `App.log_startup_pause()`, which `serve_forever` calls right after `INFO listening on`. So a church file that is locked or in WAL at start logs `listening on` first, then `church side paused: ...`. Without the flag (`build_app` in tests, other callers) the pause is logged at once, as before.
- **Refusal ends a pause (CTO 08:52).** When a pause ends in a refusal on a retry, `INFO church side pause ended: refused` is logged. It goes immediately **after** the refusal `ERROR church side refused: ...` line, not before. The refusal line is written inside the start/open code, so it already exists when the retry loop sees the failure. It is logged only if a pause was open.
- **HD3 / C7.** The busy 503 (request slot and over-cap at accept) and both 429s (search bucket, health bucket) are asserted to carry `Retry-After`.
- **HD3 / C8.** New tests fill the global rate cap and the health global cap from 127.0.0.2 and up, and fill the global connection cap with the `/healthz` reserve from several sources.
- **S3c.** Tests that `serve_until_stopped` closes the classic and church connections, and leaves them open when a handler is stuck.

## 2. Log strings (Infra Ops alert rules key on these)

| String | Change | Where (app/server.py) |
|---|---|---|
| `INFO church side paused: <why>` | text unchanged; at startup now logged **after** `INFO listening on` | held at 1472, emitted at 1482 (`log_startup_pause`), called from `serve_forever` at 2745 |
| `INFO listening on http://<host>:<port>` | unchanged | 2741 |
| `INFO church side pause ended: refused` | **new** | 1431 |
| `INFO church side resumed` | unchanged | `_church_search` |

Moved: the pause log call was at origin/main `server.py:1463`, now `1474` (not deferred) and `1472`/`1482` (deferred startup case). `listening on` moved from 2719 to 2741.
`docs/DEPLOY.md` cites no `file:line` (it names `app/server.py` and the log strings only), so nothing there to update. DEPLOY was not edited. Its line 59-61 says the server "logs the `paused` line" on a busy start, which is still true.

## 3. How to run

    uv run python -m unittest tests.test_church_harden
    uv run python -m unittest discover -s tests
    uv lock --check

New or changed tests (tests/test_church_harden.py): `StartupLockServeTests` (order for the startup lock; new WAL-start order test), `StartupPauseTests` (held pause log; refusal ends pause), `HealthBucketServeTests` and `CapsAndFlushServeTests` (Retry-After), `GlobalRateServeTests`, `ConnectionCapAndReserveServeTests`, `ChurchClosedAtShutdownTests`. I confirmed that the order, held-log and refusal tests fail against the old `app/server.py`.

## 4. Results

Full suite: 967 tests OK (`unittest discover -s tests`). `uv lock --check` passes.

## 5. Open issues

- The `pause ended: refused` line follows the refusal line instead of preceding it (see section 1).
- Shutdown close test (S3c) is in process with fake connections, not through a signalled child.

## 6. Dependencies

None added. `uv lock --check` passes.
