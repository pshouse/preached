# W3-SIDE-RACE: CTO should-fixes from PR #16 round 3

Branch `feat/w3-side-race`, from `origin/main` at `5a58b6f` (#23). PR #16 merged as `9e5c054`; `src/preached/library.py` on main was unchanged from `dd5fa7d`. Merge commits only, nothing rebased or force-pushed. No new dependencies, no models, no LLM. The church side is **not** wired to the publish gate here: `/api/side`, `/healthz`, and `search/query.py --side` still return the empty church column, as before. No Gaston Community Church data was used.

## What was done

| item | change | tests |
| --- | --- | --- |
| **S1** check-then-write race | Every write path (target mark and sibling clear) now opens through `library._open_checked`. It lists the process's open descriptors (`/dev/fd`), calls `sqlite3.connect`, and `fstat`s each new descriptor. SQLite opens the main database file at connect time; the -wal/-shm files open on the first read, so this happens before any read or write. Each new descriptor must be a regular file with `st_nlink == 1` whose `(st_dev, st_ino)` is not a classic file (`_classic_ids`: `INDEX_PATH`, `INDEX_DIR/wesley.sqlite`, canonical spurgeon/edwards). If there is no new descriptor, the write is also refused (`UnsafeOpen`, a `ValueError`). Then the church shape (`videos`, `chunks.video_id`, no classic `meta.library`) is read again **through that connection** (`_church_shape_problem`). Only after that does the target get `store.migrate` (the old `store.connect` body after `sqlite3.connect`, split out with no change) and the mark. A sibling that fails gets no write and is returned as skipped. | `OpenRaceTests` (4 tests, with subtests for wesley and a church-shaped classic) |
| **S2** inode compare alone | New test where the path differs from the classic by stem, realpath, and #14's canonical paths, with one link, but `_file_id` reports wesley's `(st_dev, st_ino)`. A bind mount does this in practice, and one can't be made without root, so `_file_id` is faked for that path. | `InodeAndLinkTests.test_same_inode_with_one_link_is_the_classic` |
| **S3** hardlinked church | `_protection(path)` returns `"classic"` or `"hardlink"`. Classic checks run first, so a link to a *known* classic still says classic. A church file with more than one link gets `error: X has N hard links, so another name may point at the same file; a church library must have exactly one. It is not marked`, from both `mark_your_church_exclusive` and `classic_church_refusal` (server / `query.py --church-index`). `mark_your_church_exclusive` now returns `[(path, reason)]` for sibling files still marked `role=church` that it did not clear: hardlinked, not church-shaped, or refused once opened. Classic files are still never opened. `import/youtube.py --your-church` prints `warning: <file> is still marked as your church; it <reason>, so the mark was not cleared` to stderr for each one; the exit code is unchanged. | `InodeAndLinkTests.test_hardlinked_church_has_its_own_message_and_its_mark_is_reported`, `ImportTests.test_your_church_reports_sibling_marks_it_did_not_clear` |
| **S4** stub | `SideApiTests.test_classic_side_covers_spurgeon_and_edwards` no longer patches `store.classic_file_problem`. It builds the classic at a temp `INDEX_DIR/<slug>.sqlite` (dir 0755 inside the 0700 temp dir), patches `preached.paths.INDEX_DIR`, and asserts the real `classic_file_problem` returns None before serving. | same test |
| Nit: gate scan | `test_every_searcher_built_near_church_code_passes_the_gate` used to accept any `**x`. Now `**name` passes only when every assignment to `name` in that function is a dict literal (or a conditional of dict literals) with a `"gated"` key. A function parameter (`**kwargs`), a call result, a dict without `gated`, or a reassignment from elsewhere is flagged. A `gated=` keyword still passes. The real code passes as-is. | `ChurchGateTripwireTests.test_source_scan_does_not_take_any_double_star_as_the_gate` |
| Nit: stale text | `search/query.py` help text: `--side` now says the church section is empty and not searched until the gate is wired; `--church-index` / `--church-library` no longer say "Default: the single index marked role=church" (nothing is scanned or opened). Wording now matches `app/server.py`. In `library.classic_church_refusal`, the docstring no longer says the caller "leaves the side empty when the path was only auto-detected" (nothing auto-detects now). It now covers the inode check and the hardlink message. `mark_your_church_exclusive` and `_clear_church_mark` docstrings describe the open-fd check. | n/a |

## Mutation checks

Each line was disabled in turn, then `tests.test_side` and `tests.test_youtube` were run (script at `/tmp/mut.py`, not committed). Every mutation fails at least one test:

| mutation in `library.py` | result |
| --- | --- |
| M1: no fd checks (`for st in []`) | 3 failures, 5 errors (`OpenRaceTests`: target and sibling, wesley and church-shaped classic, plus the one-link inode test) |
| M2: nlink check on the fd off | 4 failures (`test_target_swapped…`, `test_sibling_swapped…`, both classics) |
| M3: classic-inode check on the fd off | 4 errors (`test_classic_inode_with_one_link_once_opened_is_refused`). Before that test was added, M3 survived: a hardlink swap always gives nlink 2. So that test fakes `os.fstat` to report one link on the classic inode, which is the bind-mount case. |
| M4: shape re-read in `_clear_church_mark` off | 1 failure (`test_swap_for_a_wesley_shaped_copy…`: one link, new inode, Wesley-shaped) |
| M5: shape re-read on the target off | 1 failure (same test) |
| M6 (S2): `ident[:2] == other[:2]` in `_protection` off | 2 failures (`test_same_inode_with_one_link_is_the_classic`, `HardlinkTests.test_hardlinks_to_wesley_and_spurgeon…`) |

The S1 tests swap the name inside a wrapper on `sqlite3.connect`, with no sleeps. The wrapper fires on the first non-URI connect to that path, after every by-name check. It `os.link`s the classic to a temp name and `os.replace`s it over the church path. The tests assert the swap fired, then assert the classic's bytes and `st_mtime_ns` are unchanged and that no `-wal`, `-shm`, or `-journal` file appeared.

## How to run it

```bash
cd /work/preached/.worktrees/feat/w3-side-race
uv run python -m unittest discover -s tests
uv lock --check
uv run python -m unittest tests.test_side.OpenRaceTests tests.test_side.InodeAndLinkTests
```

## Results

- `uv run python -m unittest discover -s tests`: **570 tests, OK** (40.3s). Before this branch: 562.
- `uv lock --check`: passed (79 packages); `uv.lock` unchanged.
- Wesley byte-identical: `origin/main` (`5a58b6f`, `git archive`) and this branch were both run with this venv on `/cache/index/wesley.sqlite`: 5 queries × bm25/dense/hybrid (`"what did Wesley say about worry"`, `"Romans 8:16"`, `"assurance of faith"`, `"the witness of the Spirit"`, `"xyzzy plugh not a sermon"`). stdout, stderr, and exit code matched for **15/15**. `wesley.sqlite` sha256 was `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b` before and after. The server's search path is unchanged (`store.connect` behaves the same; only `--help` text changed in `query.py`).
- Code head: `9303905271e2301aed782a97ad765f28d2861309`. The branch head is the commit that adds this report on top of it.

## Open issues and risks

- `_open_checked` uses `/dev/fd` to list descriptors (Linux and macOS have it). If another thread opens a file during the connect, its descriptor is checked too. That can only cause a refusal, never a write. If no new descriptor shows up (for example SQLite reuses a held descriptor for the same inode), the write is refused. The importer closes its own connection before marking, so this does not happen today.
- The window still left: SQLite opens `-journal` / `-wal` by name. Swapping those sidecar names cannot redirect writes into the classic main file, because the main-file writes go to the checked descriptor.
- S2 and the one-link inode test fake file identity (`_file_id`, `os.fstat`). A real same-inode, one-link path needs a bind mount, and that needs root.
- Not done here (by instruction): wiring the church side to #12's publish gate. The TODOs in `app/server.py` (`prepare_church`) and `search/query.py` (`print_side`) still stand.

## Dependencies

None added.
