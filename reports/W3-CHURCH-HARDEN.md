# W3-CHURCH-HARDEN: CTO #37 r3, church-deploy hard conditions 1 and 2, S1-S4, nits

Precondition checked: PR #37 is merged (`2b7ac93`, an ancestor of `origin/main`).

The branch is `fix/w3-church-harden`, cut from `origin/main` at `f1de31e` (#44).
- `sandbox.sh` is not on this machine, so git ran directly, in the worktree `.worktrees/fix/w3-church-harden`.
- **56-W3-DEPLOY-CONSOLIDATE (#56, `docs/w3-deploy-consolidate`) is not merged**, so `docs/DEPLOY.md` edits are kept minimal and listed under "Reconcile with #56" below.
- History uses merge commits only. Nothing was rebased or force-pushed. No new dependencies. Nothing was deployed. Every church file is a synthetic fixture.

**Code head: `89b4b86`.** The commit that adds this report follows it and changes only `reports/`.

## What was done

| Item | Commit | Tests (all in `tests/test_church_harden.py` unless named) |
|---|---|---|
| **HC1** a busy file at startup is a pause, retried with backoff | `082af44`, `89b4b86` | `StartupPauseTests` (7), `StartPausedFormsTests` (3), `StartupLockServeTests` (real server) |
| **HC2** church side on under #29's caps, health buckets and refusal-log flush, SIGTERM and the stuck path | `b9833d8` | `CapsAndFlushServeTests`, `HealthBucketServeTests`, `StuckChurchServeTests`, `LoadedChurchSigtermTests` |
| **S1** symlink inside a 0777 dir pointing at a safe dir | `b9833d8` | `NameWalkTests` |
| **S2** 0 and 2 new fds at connect | `b9833d8` | `NewDescriptorCountTests` (2) |
| **S3** in-flight church request at SIGTERM | `b9833d8` | `test_church_r2.ChurchSigtermTests` (rewritten) |
| **S4** close the church connection when the searcher fails to build | `082af44` | `SearcherBuildFailureTests` (2) |
| Nit: FIFO/dir/device reported as "not found" | `082af44` | `NotRegularFileTests` |
| Nit: sticky-dir refusal names the wrong reason | `082af44` | `test_church_r2` sticky tests (updated) |
| Nit: DEPLOY "one line" vs the searcher-build traceback | `082af44` (code), `89b4b86` (DEPLOY) | `SearcherBuildFailureTests` |
| Nit: tripwire misses (walrus, tuple unpacking, default args, containers, loops, `store.__dict__`) | `b9833d8` | `test_hard_conditions.RawConnectGuardTests.test_every_bypass_form_is_seen` (+21 cases) |
| Nit: stale pause line in the PR body | not done | `gh` is not installed, so PR #37's (merged) body cannot be edited. This PR's body is written fresh. |

### HC1: a busy start is a pause, not a refusal

**Library: `src/preached/library.py`**
- New `ChurchStartPaused(ChurchRefused)` (`:679`). It carries:
  - `str(exc)`: the old refusal text. The CLI (`search/query.py --side`) catches `ChurchRefused` and is unchanged.
  - `.reason`: the pause reason.
- `open_church_readonly` raises it in four places:
  - **Lock at connect** (`:895`). Not seen in practice, but covered.
  - **Lock at the shape read** (`church_file_problem` raises `ChurchPaused`, `:468`).
  - **Lock at the publish-gate read** (`visible_sql`, `:921`).
  - **WAL mode** (`:883`).

  The WAL case is included because `--ack-review` keeps the file in WAL mode while it writes (`mark_your_church_exclusive` / `leave_delete_mode`). Without it, "never start the server while `--ack-review` runs" would still be needed.

**Server: `app/server.py`**
- `open_church` turns `ChurchStartPaused` into `ChurchPaused(reason)` and logs nothing. Other refusals log exactly as before.
- `main` no longer opens the church file itself. It hands `build_app` a `church_open` callable (`functools.partial(open_church, ...)`, `:3094`).
- `build_app` wraps that callable in a `start()` that also builds the gated searcher (`build_church_searcher`, `:869`).
- `App.__init__` calls `_church_start_if_due` (`:1397`) once at startup.
- **On a pause:**
  - The existing `INFO church side paused: <reason>` line is logged once.
  - The next try is scheduled `CHURCH_RETRY_FIRST_S = 1.0` s later. The wait doubles each time, capped at `CHURCH_RETRY_MAX_S = 30.0` s (`:270`).
- **Retries run on requests only:**
  - triggered by `/api/side` (`_church_ready`), or by any `/api/search?library=<non-classic>`
  - a request before the due time does not try
  - no background thread, so shutdown is unchanged
- **When the open succeeds:**
  - the usual `INFO church side: <slug>, read-only, through the publish gate` line is logged
  - the side is installed through the same checks as before (`_install_church`, `:1361`)
  - the existing `INFO church side resumed` is logged after the first church search that completes
- **When a retry finds a real refusal:** it logs `ERROR church side refused: ...` and stops retrying. The church side is then off until restart, as at startup.
- A lock while the searcher builds is a pause too. `load_church_searcher` no longer turns a busy vector read into a permanent BM25 fallback.

**While paused**, the church side looks exactly as it does in a mid-run pause:
- `/api/side` has `"present": false`.
- `/api/search?library=<church>` gives the generic 400.
- `/healthz` is unchanged.

**Real-server test (`StartupLockServeTests`):**
- Setup: a separate process holds `BEGIN EXCLUSIVE` on the church file while the server starts.
- While locked: `/api/side` has no church column, and `library=sample` gives 400.
- After `ROLLBACK`, without a restart: the church side returns, with results on both endpoints.
- Log: exactly one `paused` line, then `church side: sample, ...`, then exactly one `resumed`. Exit 0. No `refused`, `dropped` or traceback.

**Finding (the fix fails closed):** If a connection *in the same process* holds the lock, SQLite's unix VFS keeps the closed connection's descriptor and hands it to the next open. The one-new-descriptor check then refuses the retry ("no new descriptor"). In production `--ack-review` is another process, so this does not arise. The in-process tests therefore hold the lock from a child process (`lock()` in the test file).

### HC2: the church server under #29

All four use the real `app/server.py` script with `PREACHED_CHURCH_SIDE=enabled` and the privacy config. Where a test holds a church search, it does so inside its church check (the request thread only, under the App lock, before any church read).

- **`CapsAndFlushServeTests`**
  - Env: `PREACHED_MAX_CLIENT_REQUESTS=1`, `PREACHED_MAX_CLIENT_CONNECTIONS=2`.
  - A church `/api/side` is held for 3 s.
  - Three searches get 503 `busy`: one `refused busy` line, then `refused busy flush suppressed=2` at shutdown.
  - The held connection plus an idle one fill the per-client cap. The next connection gets 503 `over-cap`.
  - SIGTERM during the hold: the held church request finishes 200 with church results, logged after `INFO stopping`. rc 0. No dropped, refused, failed or traceback.
- **`HealthBucketServeTests`**
  - Env: `PREACHED_RATE_LIMIT=3`, `PREACHED_HEALTH_RATE_LIMIT=2`.
  - The church search, `/api/side` and a classic search are 200. Three more church searches get 429: one `refused 429-client` line, then `flush suppressed=2` at shutdown.
  - `/healthz` gives 200, 200, then 429 from its own bucket, with `"church": null`.
- **`StuckChurchServeTests`**
  - A church search is held past `DRAIN_TIMEOUT_S` (13 s), and two searches are refused `busy`.
  - SIGTERM: rc 1, `handler thread(s) still running`, `index left open`.
  - `refused busy flush suppressed=1` is logged before the stuck handler finishes.
  - The held church search then wakes to an **open** church connection and logs `GET /api/side 200`. No dropped or traceback.
- **`LoadedChurchSigtermTests`**
  - 16 clients alternate `/api/side` and `/api/search?library=sample`, then SIGTERM.
  - Every run must give rc 0, with no traceback, dropped, refused or failed line, and no leaked bytecode dir.
  - `PREACHED_SHUTDOWN_RUNS` runs (default 3), as `test_shutdown`.

### S1-S4
- **S1**
  - Setup: `<0777 dir>/link → safe/`, and the church file is named as `<0777 dir>/link/church.sqlite`.
  - The real path is entirely safe, so only the walk on the name given can refuse it.
  - The test checks the refusal at open and in the per-request check.
- **S2**
  - Setup: SQLite is pointed at an attacker's file around the connect, and the descriptor snapshot is made to report 0 new files, or 2 (`[attacker, checked]`).
  - Both counts are refused with the exact messages, and no attacker text is served.
- **S3**
  - `ChurchSigtermTests` now holds a church `/api/search?library=sample` in its check when SIGTERM arrives.
  - Asserts: response 200 with results, rc 0, logged after `INFO stopping`, no `dropped`, no `Traceback`, no `refused`.
- **S4**
  - `build_church_searcher` closes the church connection on any build failure, then logs one line without a traceback.
  - On a lock it raises `ChurchPaused`. It closes the connection then only if the start opened it; a retry opens a new one.

### Tripwire
`scan_sqlite_use` now counts a module name used any way other than these three: `module.attr`, a plain `name = module`, or `getattr`/`vars` first argument.
- **Counted as an open** (raw for sqlite3, writer for `store` / `preached`):
  - walrus
  - tuple unpacking
  - default argument
  - container element
  - loop iterable
  - call argument
  - a dunder on the module (`store.__dict__`, `preached.store.__dict__`, `sqlite3.__dict__`)
  - `vars(preached)` / `getattr(preached, ...)`
- **Repo-wide counts are unchanged:** `RAW_CONNECTS` and `WRITER_CONNECTS` both pass.
- **Not followed** (as ruled): `exec`, star imports, `import_module("preached.store")`.

## Alert strings: added, removed, changed

Line numbers are on this branch at `89b4b86`. "main" means `origin/main` `f1de31e`. The log format is unchanged, `%(levelname)s %(message)s`.

| Change | String | Where (this branch) | Was (main) |
|---|---|---|---|
| **Removed at server start** (now a pause) | `ERROR church side refused: the church file is locked by a writer (database is locked); it is not opened` | none at server start. It becomes `INFO church side paused: the church file is locked by a writer (database is locked)` (`app/server.py:1463`; reason from `src/preached/library.py:468`, `:895`, `:921`, or `app/server.py:883`) | `app/server.py:2668`, text `library.py:468`, `:865` |
| **Removed at server start** (now a pause) | `ERROR church side refused: <file> is in WAL journal mode; run --ack-review (it leaves DELETE mode) before serving it` | none at server start. It becomes `INFO church side paused: <file> is in WAL journal mode` (`app/server.py:1463`, reason `library.py:884`). The CLI still prints the old text (`library.py:883`). | `app/server.py:2668`, text `library.py:839` |
| **Removed at server start** (now a pause) | `ERROR church side refused: <file> cannot be opened (database is locked)` and `... cannot be read (database is locked)` | none at server start. A busy error is a pause, as above (`library.py:895`, `:921`). Non-busy errors are unchanged. | `library.py:848`, `:869` |
| **Changed** (prefix kept; traceback gone) | `ERROR church side refused: its searcher could not be built (<Type>: <message>)` | `app/server.py:886` | `ERROR church side refused: its searcher could not be built` plus traceback, `app/server.py:1633` |
| **Added** (defensive; an unexpected exception from the start) | `ERROR church side refused: the church file could not be opened (<exc>)` | `app/server.py:1419` | none |
| **Changed** refusal reason (after `church side refused: `) | `<file> is not a regular file (a FIFO / a directory / a character device / a block device / a socket); it is not opened` | `library.py:868` | `<file> not found; the church side is empty` (`library.py:826`), which is still used for a missing file (`library.py:864`) |
| **Added** refusal reason | `<file> cannot be checked (<OSError class>); it is not opened` (stat of the name fails other than ENOENT) | `library.py:866` | none (main's `is_file()` reported "not found") |
| **Changed** refusal/drop reason | `directory <below> in sticky directory <dir> is owned by uid <n>, not the serving uid or root`. A sibling `... in sticky directory <dir> cannot be checked (<class>)` is at `:733`. | `library.py:739` | `directory <dir> above the church file is group- or world-writable (mode 1777)`, `library.py:724` |

**Unchanged text, moved lines:**
- `church side refused: %s`: `app/server.py:1381`, `:2787`, `:2794`, `:2805` (main `:983`, `:2663`, `:2668`, `:2679`).
- `church side refused: the publish gate did not turn on`: `:1386` (main `:988`).
- `church side dropped: %s`: `:1455` (main `:1351`).
- `church side paused: %s`: `:1463` (main `:1359`).
- `church side resumed`: `:1522` (main `:1418`).
- `church search failed; that side is empty`: `:1525`, with traceback (main `:1421`).
- `#29`'s `refused <class> ...` and `refused <class> flush suppressed=N`: not touched.

## Reconcile with #56 (DEPLOY consolidate, unmerged)

**Edits on this branch (`docs/DEPLOY.md`, church gate section only):**
1. The intro paragraph:
   - a busy start is a pause, retried after 1 s, doubling to 30 s, with no restart
   - every refusal is one line
   - the searcher-build line's new form
2. Gate item 4: a WAL-mode file is "not opened" (was "refused at start"), and a file left in WAL stays paused until `--ack-review` leaves DELETE mode.

**Changes #56 needs when the two meet:**
- **`docs/DEPLOY.md` (#56's version):**
  - The "Until fixed, never start the server while `--ack-review` runs" text (#56 `:620-632`) can go.
  - Alert table row 1, the PAGE on `church side refused: the church file is locked by a writer`, no longer fires at start. The equivalent condition is now row 4, the `paused` window. Its `cannot be opened`/`cannot be read (database is locked)` forms go too.
  - Row 2's note "followed by a traceback" (`:1633`), and the "one case adds a traceback" paragraph (#56 `:683-687`), are obsolete.
  - The WAL refusal row (#56 `:752`) is now a server pause; the CLI keeps that text.
  - Every `app/server.py` / `library.py` line number in #56's table moves (see the table above).
- **`tests/test_deploy_alerts.py` (#56):**
  - `test_a_writer_lock_at_startup_is_refused_with_the_paged_line` asserts the removed start-up line. It must change to assert the pause, or be dropped.
  - Its writer is in the same process. With the retry fix that is fine for a single open, but see the HC1 finding above for reopens.
  - `SEARCHER_NOT_BUILT` is still a prefix of the new line, but any check that a traceback follows must go.

## How to run

```
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_church_harden tests.test_church_r2 tests.test_church_wire tests.test_hard_conditions
PREACHED_SHUTDOWN_RUNS=30 uv run python -m unittest tests.test_church_harden.LoadedChurchSigtermTests
uv lock --check
python3 -I /tmp/mut-harden/mut.py "$PWD"          # mutation runner, not committed
uv run python /tmp/mut-harden/loaded.py "$PWD" 30  # per-run rc and log counts, not committed
```

## Results

- **Full suite:** `uv run python -m unittest discover -s tests`, **961 tests, OK** (206.8 s). The new tests are the 21 in `tests/test_church_harden.py`. `ChurchSigtermTests` was rewritten in place, and the WAL test and the two sticky tests were updated in place, so their count is unchanged. The 21 new tripwire cases are subtests.
- **`uv lock --check`:** passed (79 packages). `pyproject.toml` and `uv.lock` are unchanged.
- **gitleaks:** not installed here (`which gitleaks`: none). A grep of the diff for key, token, password and private-key patterns found nothing.

### Mutants

Each mutant was applied alone. Then `tests.test_church_harden tests.test_church_r2 tests.test_church_wire tests.test_hard_conditions` was run, and the file was restored. `git status` was clean after every run.

| Mutant | On main's tests (`f1de31e`) | On this branch | Failing tests (this branch) |
|---|---|---|---|
| CTO: name-path walk removed (`_ancestor_problem` walks the real path only) | **SURVIVED** (OK) | **KILLED** | `NameWalkTests.test_a_symlinked_directory_in_a_world_writable_dir_is_refused` |
| CTO: exactly-one-new-fd check removed (last new file, or none, accepted) | **SURVIVED** (OK) | **KILLED** | `NewDescriptorCountTests` (both) |
| CTO: church close moved ahead of `server.drain()` | **SURVIVED** (OK) | **KILLED** | `ChurchSigtermTests`, `CapsAndFlushServeTests`, `StuckChurchServeTests`, `LoadedChurchSigtermTests` |
| HC1: no retry after a start pause | n/a | KILLED | 7 (`StartupPauseTests` ×6, `StartupLockServeTests`) |
| HC1: `open_church` lets the start pause through as a refusal | n/a | KILLED | 8 |
| HC1: no backoff (retry on every request) | n/a | KILLED | `test_a_writer_lock_at_startup_is_a_pause_...` |
| S4: connection not closed when the searcher fails | n/a | KILLED | `SearcherBuildFailureTests` (2) |
| Nit: searcher-build refusal logged with a traceback | n/a | KILLED | `SearcherBuildFailureTests` (2) |
| Nit: non-regular file reported as "not found" | n/a | KILLED | `NotRegularFileTests` |

The moved-close mutant under load reproduces the CTO's numbers. Over 10 loaded runs of `loaded.py`:
- every run gave rc 0
- **10/10 runs logged `church side dropped`**

So exit code alone could not catch it.

### Loaded SIGTERM, church side on, 30 runs

`uv run python /tmp/mut-harden/loaded.py "$PWD" 30`: 16 clients alternate `/api/side` and `/api/search?library=sample` (BM25, synthetic fixture), then SIGTERM.

| Measure | Result |
|---|---|
| rc | **0 in 30/30** |
| `church side: sample, read-only, ...` | 30 (one per run) |
| `INFO stopping` | 30 |
| `church side dropped` | **0** |
| `church side refused` | 0 |
| `church side paused` | 0 |
| `church search failed` | 0 |
| `Traceback` | **0** |
| `still running` (stuck) | 0 |
| leaked bytecode dirs | 0 |
| 200 responses seen by clients | 876 (25-33 per run) |
| church/side 200s logged after `INFO stopping` (in flight at the stop) | 241 (6-10 per run) |

The committed `LoadedChurchSigtermTests` with `PREACHED_SHUTDOWN_RUNS=30` also passed (40.4 s).

### New test output

```
CapsAndFlushServeTests.test_caps_refusal_log_flush_and_sigterm_with_a_church_search_in_flight ... ok
HealthBucketServeTests.test_health_has_its_own_bucket_with_the_church_side_on ... ok
LoadedChurchSigtermTests.test_sigterm_under_church_load_exits_zero ... ok
NameWalkTests.test_a_symlinked_directory_in_a_world_writable_dir_is_refused ... ok
NewDescriptorCountTests.test_no_new_descriptor_is_refused ... ok
NewDescriptorCountTests.test_two_new_descriptors_are_refused_even_when_one_is_the_checked_file ... ok
NotRegularFileTests.test_each_kind_is_named ... ok
SearcherBuildFailureTests.test_the_connection_is_closed_and_one_line_is_logged ... ok
SearcherBuildFailureTests.test_through_main_s_open_too ... ok
StartPausedFormsTests.test_a_lock_at_the_connect ... ok
StartPausedFormsTests.test_a_lock_at_the_publish_gate_read ... ok
StartPausedFormsTests.test_a_lock_at_the_shape_read ... ok
StartupLockServeTests.test_started_while_locked_the_church_side_resumes ... ok
StartupPauseTests.test_a_lock_during_the_searcher_build_is_a_pause_and_closes_that_connection ... ok
StartupPauseTests.test_a_refusal_found_on_a_retry_ends_the_retries ... ok
StartupPauseTests.test_a_search_for_the_church_slug_also_retries_the_open ... ok
StartupPauseTests.test_a_writer_lock_at_startup_is_a_pause_and_the_church_side_resumes_without_a_restart ... ok
StartupPauseTests.test_a_writer_lock_at_startup_through_main ... ok
StartupPauseTests.test_the_backoff_doubles_to_the_cap ... ok
StartupPauseTests.test_wal_mode_at_startup_is_a_pause_until_ack_review_leaves_delete_mode ... ok
StuckChurchServeTests.test_a_stuck_church_search_exits_one_and_flushes ... ok
ChurchSigtermTests.test_church_server_exits_zero_on_sigterm_with_a_church_search_in_flight ... ok
Ran 22 tests in 24.782s
OK
```

## Open issues, risks, exclusions

- **A WAL file never approved now pauses instead of paging.** A church file that is left in WAL mode and never `--ack-review`ed now gives one `INFO church side paused` line and retries every 30 s, instead of `ERROR church side refused`.
  - Infra Ops sees it only through the `paused` window rule (#56 row 4).
  - This is the fix's intent: starting during `--ack-review` must not need a restart.
- **Retries need traffic.** The open is retried only when a church request arrives (`/api/side`, or a non-classic `library=`). An idle server stays paused until its next church request, so the `resumed` line comes no sooner than that.
- **A successful late open runs under the App lock.** It builds the searcher and loads vectors there, so other requests wait for that one open. That is milliseconds on the fixture, and grows with the church file's size.
- **In-process lock holder.** See the HC1 finding: a retry fails closed (refused) if a connection in the server process itself holds a lock on the church file. No such connection exists in the server.
- **Label and sample flag.** `read_label` / `is_sample_library` still swallow SQLite errors. A writer's lock taken in the instant between the start's checks and its label read would give the default label and no sample flag. This is unchanged from main.
- **Not done:** editing PR #37's merged body (the "stale pause line" nit) needs `gh`, which is not installed. gitleaks is not installed either.
- **PR not opened:** `gh` is not installed and there is no token. The branch is pushed. The PR body is `reports/W3-CHURCH-HARDEN-pr-body.md`.
- Same-uid races (#33) and the page-cache gap are unchanged.

## Dependencies added

None.
