# W3-CHURCH-FIX2: CTO round 2 on PR #37 (feat/w3-church-wire)

Precondition checked: PR #37 was OPEN at `6f6637d589cddd14f88c84c584db09015ef01cff` (GitHub API). The branch was pushed to the existing `feat/w3-church-wire` with merge commits only: no rebase, no force-push. Nothing was deployed. Every church file in the tests is a synthetic fixture.

Two sandbox gaps:
- `sandbox.sh` is not on this machine (searched `/`), so git ran directly.
- The review file `/workspace/reports/preached-pr37-review.md` is not here either (`/workspace` does not exist). I worked from the CTO items quoted verbatim in the task.

**Code head: `ad2feee`.** The commit that adds this report follows it. The branch head is the follow-up commit that records that SHA (report text only).

## What was done

| Item | Commit | Tests |
|---|---|---|
| **MF1** merge conflict with #36 in `serve_until_stopped` | `e59f79e` (merge of `origin/main` `5779961`, which includes #36 `f9f7551` and #39) | `ChurchSigtermTests.test_church_server_exits_zero_on_sigterm` (`ad2feee`), plus all of main's `test_shutdown` |
| **MF2** a parent-directory swap | `5a779df` | `ParentDirectorySwapTests` (8 tests) |
| **A** (folded into MF2) SQLite's fd must be the checked inode | `5a779df` | `test_sqlites_descriptor_must_be_the_checked_inode` |
| **B** FIFO blocks `wal_mode` forever | `5a779df` | `FifoTests` (4 tests, each run in a thread with a 5 s bound) |
| **E** separate `dropped` and `refused` lines | `86f1529` | `AlertStringTests`; `ChurchRefusalWhileServingTests.assert_church_gone` now requires `dropped` and forbids `refused` |
| **D** a writer lock stalls the server 5.07 s, then drops the church side | `5a779df` (`busy_timeout 0`, busy during the check is a pause), `86f1529` (busy during the search is a pause) | `WriterLockTests` (2 tests) |
| **F** one INFO line per paused request | `86f1529` | `WriterLockTests` (20 requests during the lock give 1 line, then 1 `resumed`); the WAL pause test in `test_church_wire` |
| **C** tripwire misses | `9eaac1c` | `RawConnectGuardTests.test_every_bypass_form_is_seen`: 15 new cases |
| **Nit** page-cache wording | `efc4375` | n/a (docs) |
| **(4)** operator-chosen church slug | `efc4375` | n/a (docs) |

### MF1
- I kept #36's drain-then-close block byte for byte.
- In the drained branch, `if app.church_connection is not None: app.church_connection.close()` now runs after `connection.close()` and before `app.close_embedder()`.
- When the drain gives up, the church connection stays open, as #36 does for the index.
- `scripts/build-bundle.sh` also conflicted: main added `-P`, and this branch puts `src` on `PYTHONPATH` for `copy_index`. The merged line keeps both.
- Main had moved on to `5779961` (#39), so the suite count is 847 after the merge, not the reviewer's 833.

### MF2 and A
- **Directory walk.** `church_path_problem` now ends with a new `_ancestor_problem`. It walks every directory from `/` down, on both `abspath(path)` and `realpath(path)`, `lstat`-ing each component without following it. Each directory must be owned by the serving euid or root and must not be group- or world-writable.
  - Exception: a root-owned sticky directory whose next component is owned by the serving euid or root.
  - A symlink component is checked for owner only. Its target is covered by the real-path walk.
- **When it runs.** The walk runs at open (`open_church_readonly`) and on every request (`church_file_problem` → `church_path_problem`).
- **fd-inode check.** After the connect, `open_church_readonly` takes a `_descriptors()` snapshot diff, through a new `_one_new_file` helper that `_Checked` now uses too. Exactly one new regular file must be open, and it must be the `(st_dev, st_ino)` checked before the connect. Otherwise: `<name> is not the file SQLite opened (the name changed); it is not opened`.
- **The CTO probe** (`<0777 dir>/sub/church.sqlite`, with `sub` swapped around the connect) is now refused before any connect, and the swap function is never called. The fd check is tested separately: the same swap inside a directory chain that passes the walk is refused by the fd check alone.
- **Sticky rule, testing.** This sandbox's `/tmp` is owned by the user and is not sticky. The sticky rule is therefore tested with a patched `os.lstat`: allowed, next component not ours, sticky but not root-owned, and root-owned but not sticky.

### B
- `wal_mode(path, identity=None)` opens with `O_RDONLY | O_NONBLOCK | O_NOFOLLOW`, then `fstat`s. It reads only a regular file, and with `identity` only that inode, using `os.pread`. Anything else gives `None`.
- Both callers now treat `None` as a refusal:
  - at open: `<name> cannot be read as the regular file that was checked; it is not opened`
  - per request: `<name> cannot be read as the regular file that was opened; refused` (a drop).
- At open, the identity is now taken before the header read.

### D
- `PRAGMA busy_timeout = 0` is set on the church connection in `open_church_readonly`.
- A busy or locked error (`is_busy`, any extended code of `SQLITE_BUSY`/`SQLITE_LOCKED`) is treated as a pause in two places:
  - the per-request shape read: `_church_shape_problem(..., busy_pauses=True)` raises `ChurchPaused`
  - the search itself, in `App._church_search`.
- Under a writer's `BEGIN EXCLUSIVE`, each `/api/side` took under 1 s in the test, against 5.07 s before. The church side was skipped, not dropped, and came back after the writer's `ROLLBACK`.
- `--ack-review` and the other writer paths are unchanged (`busy_pauses` defaults to False).

### E and F
- `App._church_ready` now logs `church side dropped:` for any per-request problem.
- Startup refusals (`open_church`, `App.__init__`, `load_church_searcher`) keep `church side refused:`.
- A pause is logged once when it starts. `church side resumed` is logged only after a church search completes again.
  - The first version logged `resumed` as soon as the check passed. With the lock taken after the check, that flapped `paused`/`resumed` on every request. The new test caught it, and it is fixed in `86f1529`.

### C
`scan_sqlite_use` now also sees:
- modules rebound to another name (`db = sqlite3`, `s = store`, `s = preached.store`, chained, iterated to a fixpoint)
- dotted `preached.store.connect` (through `import preached.store`, `import preached`, `import preached as p`)
- `getattr(store, "connect")`, and `getattr(store, <non-constant>)`
- `from . import store` and `from .. import store as s`.

As ruled, it is a regression guard only. `exec`, star imports and `import_module("preached.store")` are still not followed (docstring says so). The repo-wide counts (`RAW_CONNECTS`, `WRITER_CONNECTS`) are unchanged.

### DEPLOY (`efc4375`)
- the full directory chain and sticky exception, and the fd-inode check
- the alert lines (below)
- busy pauses, and `busy_timeout` 0
- "A file edited or corrupted in place, without a new inode, can still be served from SQLite's page cache"
- "The church slug ... is chosen by the operator and hard to guess. It is not the church's public name."

## Alert strings

The server logs with `format="%(levelname)s %(message)s"`, so these are the exact line prefixes:

| Event | Exact line | Where |
|---|---|---|
| Startup refused | `ERROR church side refused: <reason>` | `open_church`, `App.__init__`, `load_church_searcher` (that one also prints a traceback via `logging.exception`) |
| Mid-run dropped | `ERROR church side dropped: <reason>` | `App._church_ready`; logged once, then the church side is off until restart |
| Pause start | `INFO church side paused: <reason>` | `App._church_pause`; reason is `<name> is in WAL journal mode` or `the church file is locked by a writer (database is locked)` |
| Pause end | `INFO church side resumed` | `App._church_search`, after the first church search that completes after a pause |

The CLI (`search/query.py --side`) prints `church side refused: <reason>` on stderr, unchanged.

## How to run

```
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_church_r2 tests.test_church_wire tests.test_hard_conditions
uv lock --check
python3 -I /tmp/mutr2/mut.py        # mutation runner, not committed
python3 -I /tmp/parr2/parity.py     # no-church parity, origin/main vs branch, not committed
```

## Results

- `uv run python -m unittest discover -s tests`: **864 tests, OK** (128.8 s). That is 847 after the merge, plus 17 in `tests/test_church_r2.py`. The 15 new tripwire cases are subtests of an existing test.
- `uv lock --check`: passed (79 packages). `pyproject.toml` and `uv.lock` are unchanged from main.
- **No-church parity**, `origin/main` `5779961` vs this branch:
  - Setup: `git archive` plus `git init`; same venv; `/cache/index/wesley.sqlite`; ONNX fp32.
  - CLI: **20/20** stdout, stderr and exit. That is 5 queries × 3 modes, `--side` × 3, spurgeon, edwards.
  - HTTP: **42/42** status and body (`took_ms` masked). This includes `library=sample`, `mychurch`, `spurgeon` and `wesley` on both endpoints.
  - Server log: equal apart from the random port. Both exit 0.
- **Wesley sha256** `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b`, unchanged.

### Mutation results

Each mutation was applied alone, then `tests.test_church_r2 tests.test_church_wire tests.test_hard_conditions` was run, then the file was reverted.

| Mutation | Result | Failing tests |
|---|---|---|
| MF2: `_ancestor_problem` not called | KILLED | 5 (CTO probe, grandparent, real path, ancestor owner, per-request) |
| MF2: real path not walked | KILLED | `test_the_real_path_is_walked_as_well_as_the_name` |
| MF2: sticky exception removed | KILLED | sticky allowed test |
| MF2: sticky next-component owner ignored | KILLED | 2 sticky tests |
| A: fd-inode comparison off | KILLED | `test_sqlites_descriptor_must_be_the_checked_inode` |
| B: plain blocking `os.open` | KILLED | 4 `FifoTests` (each blocked past 5 s) |
| B: `O_NOFOLLOW` off | KILLED | `test_wal_mode_reads_only_the_expected_regular_file` |
| B: identity not compared | KILLED | same |
| B: `S_ISREG` check removed | **SURVIVED, equivalent** | `os.pread` on a FIFO raises ESPIPE, so the function still returns None. A character device gives a non-SQLite header, also None. Kept as defence in depth. |
| E: drop logs `refused` | KILLED | 7 |
| D: `busy_timeout = 5000` | KILLED | 2 `WriterLockTests` |
| D: busy in the check not a pause | KILLED | `test_a_lock_seen_by_the_check_is_a_pause` |
| D: busy in the search not a pause | KILLED | `test_a_lock_taken_after_the_check_is_a_pause_too` |
| F: pause logged on every request | KILLED | 2 `WriterLockTests` |
| MF1: the pre-merge `church_connection.close()` (out of scope) | KILLED | `test_church_server_exits_zero_on_sigterm` (exit 1, `NameError`) |
| C: rebinding, dotted, relative from-import, `getattr` on store (each off) | KILLED (4/4) | `test_every_bypass_form_is_seen` subtests |

## Open issues, risks, exclusions

- **Same-uid races remain (#33).** The walk stops other users, not a process running as the serving uid.
- **Narrow pause flip.** A writer can lock the file between the WAL-header read and the shape read. That is now a pause, not a drop. A lock taken mid-search returns no church results for that request and logs a pause.
- **Startup during a lock.** With `busy_timeout` 0, a server started while a writer holds the lock refuses the church side (`ERROR church side refused: ... locked by a writer ...`). Before, it waited 5 s. The fix is a restart after `--ack-review` finishes.
- **Startup refusal log.** `load_church_searcher`'s refusal still uses `logging.exception`, so it adds a traceback after the `ERROR church side refused:` line.
- **Tripwire limits.** It still does not follow `exec`, star imports or `import_module("preached.store")`, as ruled.
- **Not run here:** gitleaks (not installed in this sandbox). The PR body was not updated: `gh` is not installed. The PR body should get this report's item table.

## Dependencies added

None.
