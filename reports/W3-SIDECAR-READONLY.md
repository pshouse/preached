# W3-SIDECAR-READONLY: CTO round 2 on PR #27

Branch `fix/w3-sidecar-readonly`, from `origin/main` at `0fb4e1c` (the #27 merge). Merge commits only, nothing rebased or force-pushed. No new dependencies, no models, no LLM, nothing deployed. The church side is still not wired to the publish gate. No Gaston Community Church data was used. The CTO review file (`/workspace/reports/preached-pr27-review.md`) is not on this machine, so the work follows the four items as quoted in the task.

## What was done

| item | change | commit | tests |
| --- | --- | --- | --- |
| **1** (hard condition) read-only church opens outside `library.py` | `store.open_readonly` now runs `library._sidecar_problem` before it connects. That check requires each `-wal`, `-shm` or `-journal` next to the path or its realpath to be a regular file, not a symlink, with one link, and not a classic file. If one fails, it raises the new `store.UnsafeSidecar` (a `ValueError`): `error: <path> has a -shm file with 2 hard links; it is not opened`. `search/query.py` (`open_target`, `is_library_file`) and `app/server.py` `main` turn that into `SystemExit`. Every `open_readonly` caller is covered: `query.py --library <church slug>`, `query.py --index <file>`, `server --library <church slug>`, `server --index <file>`, and the read-only helpers in `library.py` (which already checked). The import is done inside the function because `library` imports `store`. | `40edd55` | `ReadOnlyOpenSidecarTests` (3 tests). `test_a_hardlinked_sidecar_is_refused_by_both_entry_points_and_wesley_is_unchanged` covers 4 entry points (`query.open_index` with a church slug, `server.main --library <church>`, and both `--index` paths) × `-wal`/`-shm`/`-journal` on a WAL-mode church file. Each subtest rebuilds both files and asserts Wesley's sha256, size and mtime are unchanged, plus `PRAGMA integrity_check = ok`. Also `test_both_entry_points_open_the_church_file_when_its_sidecars_are_safe` (control: the server reaches `make_server`) and `test_open_readonly_refuses_a_symlinked_sidecar` |
| **2** report overclaim | `reports/W3-SIDE-RACE.md`, "Open issues and risks (round 1 on #27)": the "before anything is written" bullet is struck through and corrected with the probe results below. The "`store.open_readonly` itself does not check sidecars" bullet is struck through and marked fixed by item 1. The docstring of `test_sidecar_planted_after_the_connect_is_caught_before_the_first_write` now says a `-shm` link planted there would already be written. The optional `PRAGMA locking_mode=EXCLUSIVE` was **not** done (reason under open issues). | `1985b56` | n/a (probe script below) |
| **3** per-position recheck tests | New `RecheckPositionTests` (6 tests). Each plants a `-wal` or `-shm` link to wesley.sqlite at one point, then asserts what *that* recheck prevents before the next one runs. Later rechecks would also refuse the link, so a test that only checks for a refusal can't tell the positions apart. | `a04d3db` | see the mutation table |
| **4** gate scan gaps | `Searcher.gated` is now a read-only property backed by `_gated`. `s.gated = False`, `setattr(s, "gated", False)` and `del s.gated` raise `AttributeError`. The new `gate_on()` only turns the gate on. `App.__init__` used `searcher.gated = searcher.gated or self.gated` and now calls `searcher.gate_on()` when `self.gated`. The remaining scan gaps are accepted and listed in the docstring of `test_every_searcher_passes_the_gate_or_is_a_named_classic_builder` and below. | `59b9a96` | `ChurchGateTripwireTests.test_searcher_gated_is_read_only`, `test_app_turns_the_gate_on_for_a_searcher_built_without_it` |

### Item 3: what each position test asserts

| recheck position | test | planted | asserted (fails without that recheck) |
| --- | --- | --- | --- |
| name half of `recheck()` | `test_the_name_half_of_recheck_refuses_a_name_swapped_after_the_open` | `-shm` name swapped after `_Checked` holds the -shm descriptor | `recheck()` raises. The fd half sees no new descriptor |
| after the first read (`_Checked.__init__`) | `test_the_recheck_after_the_first_read_refuses_before_any_sibling_is_cleared` | `-wal` on the WAL-mode target, right after the connect | `_clear_church_mark` is never called, so the marked sibling keeps its mark |
| before the WAL switch | `test_the_recheck_before_the_wal_switch_leaves_a_rollback_target_unswitched` | `-wal` on a rollback-mode target while siblings are listed | the target is still `journal_mode=delete`, with its bytes unchanged |
| after the WAL switch | `test_the_recheck_after_the_wal_switch_refuses_before_the_schema_is_written` | `-wal` on a rollback target from SQLite's trace hook, just before `PRAGMA journal_mode=WAL` | `store.migrate` is never called and the target is not marked |
| before the commit | `test_the_recheck_before_the_commit_leaves_the_target_unmarked` | `-wal` name after `mark_your_church` | the mark is not committed |
| in `_clear_church_mark` | `test_the_recheck_in_clear_church_mark_keeps_the_sibling_mark` | `-wal` on the sibling after its shape read on the read-write connection | the sibling is reported as skipped and keeps its mark |

## Mutation checks

Each change below was applied on its own, then `tests.test_side` and `tests.test_youtube` were run (92 tests; script `/tmp/w3sro/mut.py`, not committed). Every mutation fails at least one test:

| mutation | failures | tests that fail |
| --- | --- | --- |
| name half of `recheck()` off | 4 | name-half, before-WAL, before-commit, `_clear_church_mark` position tests |
| fd half of `recheck()` off | 1 | `SidecarTests.test_the_descriptor_recheck_refuses_a_sidecar_the_name_check_misses` |
| all of `recheck()` off | 9 | all 6 `RecheckPositionTests`, plus the 2 `SidecarTests` planted-after tests |
| recheck after the first read removed | 1 | `test_the_recheck_after_the_first_read_refuses_before_any_sibling_is_cleared` |
| recheck before the WAL switch removed | 1 | `test_the_recheck_before_the_wal_switch_leaves_a_rollback_target_unswitched` |
| recheck after the WAL switch removed | 1 | `test_the_recheck_after_the_wal_switch_refuses_before_the_schema_is_written` |
| recheck before the commit removed | 1 | `test_the_recheck_before_the_commit_leaves_the_target_unmarked` |
| recheck in `_clear_church_mark` removed | 1 | `test_the_recheck_in_clear_church_mark_keeps_the_sibling_mark` |
| sidecar check in `open_readonly` off | 12 + 1 error | both `ReadOnlyOpenSidecarTests` refusal tests (all subtests) |
| `Searcher.gated` setter restored | 1 | `test_searcher_gated_is_read_only` |
| `searcher.gate_on()` in `App.__init__` removed | 1 | `test_app_turns_the_gate_on_for_a_searcher_built_without_it` |

Before the fix (item 1), the new tests showed the bug. A `-shm` link changed Wesley's sha256 through both `query.open_index` with a church slug and `server.main --library <church>`. Wesley then read back as `file is not a database`, and the server got as far as `make_server` on the church file.

### Item 2 probes (SQLite 3.53.1)

`/tmp/w3sro/probe.py` (not committed) plants a link to wesley.sqlite inside a window in `mark_your_church_exclusive` and records Wesley's hash and `integrity_check`:

| target | planted | window | Wesley | outcome |
| --- | --- | --- | --- | --- |
| WAL | `-wal` | after the connect, before the first read | unchanged | refused (`UnsafeOpen`) |
| WAL | `-shm` | after the connect, before the first read | **changed, `file is not a database`** | refused |
| WAL | `-journal` | after the connect | unchanged | marked (SQLite drops the non-hot journal name) |
| rollback | `-wal` | just before `PRAGMA journal_mode=WAL` | **changed, `file is not a database`** | refused |
| rollback | `-shm` | just before `PRAGMA journal_mode=WAL` | **changed, `file is not a database`** | refused |
| rollback | `-journal` | just before `PRAGMA journal_mode=WAL` | unchanged | marked |

So 3 windows write into Wesley before the recheck refuses, which matches the CTO's 3 probes. All of them need a live writer with the same uid, timed to the open. That is the residual risk round 1 accepted.

## How to run it

```bash
cd /work/preached/.worktrees/fix/w3-sidecar-readonly
uv run python -m unittest discover -s tests
uv lock --check
uv run python -m unittest tests.test_side.ReadOnlyOpenSidecarTests tests.test_side.RecheckPositionTests tests.test_side.ChurchGateTripwireTests
```

## Results

- `uv run python -m unittest discover -s tests`: **703 tests, OK** (86.8s). `origin/main` at `0fb4e1c` has 692 (+3 item 1, +6 item 3, +2 item 4). `test_side` + `test_youtube`: 92 (was 81).
- `uv lock --check`: passed (79 packages). `pyproject.toml` and `uv.lock` are identical to `origin/main`.
- Wesley parity: `origin/main` (`0fb4e1c`, `git archive`, using its own `src/`) and this branch were each run with this venv on `/cache/index/wesley.sqlite`. Queries: `"what did Wesley say about worry"`, `"Romans 8:16"`, `"assurance of faith"`, `"the witness of the Spirit"` and `"xyzzy plugh not a sermon"`, each in bm25/dense/hybrid, plus `--side`, `--library spurgeon` and `--library edwards` (bm25, `"assurance of faith"`). stdout, stderr and exit code matched for **18/18** (`/tmp/w3sro/parity.sh`). The `wesley.sqlite` sha256 was `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b` before and after. Every `/cache/index/*.sqlite` (including their existing `-wal`/`-shm`) still opens through `open_readonly`.
- Code head: `1985b56fa01aa88bf4102e163a87dcef45feb634`. The branch head is the commit that adds this report on top of it.

## Open issues and risks

- **Race windows remain (item 2).** The sidecar check in `open_readonly` is by name and runs once, before the connect. A link planted between that check and the first read is still written (the `-shm` index), the same as the `library.py` read-only helpers. On the write path the rechecks narrow the windows, but the 3 probes above show they don't stop SQLite writing first. All of these need a live same-uid writer.
- **`PRAGMA locking_mode=EXCLUSIVE` (optional) not done.** It would remove `-shm` on the write path, but it holds the file lock until close and makes a concurrent reader (a server with the church file open) fail with `database is locked`. It also would not cover the `-wal` window at the WAL switch or any read-only open. That behaviour change should be decided when the church side is wired, not here.
- **Gate scan gaps accepted (item 4):** string lookups (`getattr`, `eval`, `globals()`), a copy of the gate dict mutated elsewhere (a helper, `operator.setitem`, `for`/`with` rebinding), a classic builder (`classic_searcher`) called from church code, and modules other than `app/server.py` and `search/query.py`. Assignment after construction is now refused at runtime. Writing `s._gated` directly, or `object.__setattr__(s, "_gated", False)`, is not. The runtime tests `test_cli_church_searcher_is_gated_on_every_path` and `test_unapproved_church_sermon_is_not_found_through_either_entry_point` still cover the CLI church path.
- Other `open_readonly` callers (`eval/*.py`, `search/build_library.py`, `scripts/smoke_server.py`, `scripts/gate_leak_sweep.py`) now get `UnsafeSidecar` as a traceback rather than a clean error line. They refuse either way.
- Found while writing the `_clear_church_mark` test: `church_shaped` / `church_index_matches` run after `_marked_siblings_not_cleared`. A sidecar link planted on a marked sibling between those two steps leaves that sibling neither cleared nor reported. Its mark stays and nothing is written into it. The only effect is a missing warning, and it needs the same timed race. Not changed.

## Dependencies

None added.
