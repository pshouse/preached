# W3: church hardening (deploy hard conditions 1-2)

Addresses CTO review r3 on #37 (merged): church-deploy hard conditions 1 and 2, S1-S4 and the nits. Full report: `reports/W3-CHURCH-HARDEN.md`.

**Nothing deployed. Only synthetic church fixtures are used. No new dependencies.**

## Hard conditions
- **HC1: a busy file at startup is a pause, not a drop.** This covers a writer's lock and WAL mode while `--ack-review` runs.
  - `open_church_readonly` raises `ChurchStartPaused`. It is a `ChurchRefused`, so the CLI is unchanged.
  - The server logs the existing `INFO church side paused: <why>` once.
  - It retries the open on later church requests, after 1 s, doubling to 30 s.
  - When the open succeeds it logs `church side: <slug>, read-only, ...` and, after the next church search, `INFO church side resumed`. No restart is needed.
  - A real refusal found on a retry logs `ERROR church side refused:` and ends the retries.
  - Test: a real server is started while another process holds `BEGIN EXCLUSIVE`. The church side resumes after `ROLLBACK`, with no restart.
- **HC2: a real server with the church side on**, tested under:
  - #29's per-client request slot and connection cap (`busy`, `over-cap`)
  - health buckets (`/healthz` has its own 429)
  - refusal-log flush (`refused <class> flush suppressed=N`)
  - SIGTERM with a church search in flight (rc 0)
  - the stuck path (rc 1, flush logged first, church connection left open)
  - 16-client load

## Should-fixes
- **S1:** a test for a symlink inside a 0777 dir pointing at a safe dir.
- **S2:** tests for 0 and 2 new fds at connect. Both are refused; no attacker text.
- **S3:** `ChurchSigtermTests` now takes an in-flight church request at SIGTERM. It asserts rc 0, no `dropped`, no `Traceback`.
- **S4:** the church connection is closed when the searcher fails to build.

## Nits
- **Non-regular file:** a FIFO, directory or device at the church name is named as such, not "not found".
- **Sticky directory:** the refusal names the owner below the sticky directory.
- **Searcher-build refusal:** it is one line, `ERROR church side refused: its searcher could not be built (<Type>: <msg>)`, with no traceback.
- **Tripwire:** it now counts a walrus, tuple unpacking, default args, containers, loops, call arguments and `store.__dict__`.

## Mutants
The CTO's three mutants **survive main's tests** and are **killed here**:
- the name-path walk removed
- the exactly-one-new-fd check removed
- the church close moved ahead of the drain

Six more mutants of the new code are all killed. Under load, the moved close logs `church side dropped` in 10/10 runs while still exiting 0.

## Results
- Suite: **961 OK**.
- `uv lock --check`: OK.
- Loaded SIGTERM with the church side on, **30/30 runs rc 0**:
  - 0 `dropped`, 0 `refused`, 0 `Traceback`
  - 241 church 200s logged after `INFO stopping`

## Alert strings
Server start no longer logs `ERROR church side refused: ...locked by a writer...` or the WAL refusal. Both are now `INFO church side paused:`.

The full added, removed and changed table with file:line is in the report.

## Reconcile with #56
#56 (DEPLOY consolidate) is unmerged. When the two meet, #56 needs these changes:
- its alert table row 1 and its "never start the server while `--ack-review` runs" text
- `tests/test_deploy_alerts.py::test_a_writer_lock_at_startup_is_refused_with_the_paged_line`

The report lists each one. This branch's DEPLOY edit is minimal: the church gate intro and item 4.

## Dependencies
None.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
