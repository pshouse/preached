# W3-SIDE-RACE: CTO should-fixes from PR #16 round 3

The round-1 fix-up for PR #27 is at the end: [CTO round 1 on PR #27](#fix-up-cto-round-1-on-pr-27).

Branch `feat/w3-side-race`, from `origin/main` at `5a58b6f` (#23). PR #16 merged as `9e5c054`; `src/preached/library.py` on main was unchanged from `dd5fa7d`. Merge commits only, nothing rebased or force-pushed. No new dependencies, no models, no LLM. The church side is **not** wired to the publish gate here: `/api/side`, `/healthz`, and `search/query.py --side` still return the empty church column, as before. No Gaston Community Church data was used.

## What was done

| item | change | tests |
| --- | --- | --- |
| **S1** check-then-write race | (Round 1 on #27 replaced `_open_checked` with `_Checked` and added the sidecar checks; see the fix-up section below.) Every write path (target mark and sibling clear) now opens through `library._open_checked`. It lists the process's open descriptors (`/dev/fd`), calls `sqlite3.connect`, and `fstat`s each new descriptor. SQLite opens the main database file at connect time; the -wal/-shm files open on the first read, so this happens before any read or write. Each new descriptor must be a regular file with `st_nlink == 1` whose `(st_dev, st_ino)` is not a classic file (`_classic_ids`: `INDEX_PATH`, `INDEX_DIR/wesley.sqlite`, canonical spurgeon/edwards). If there is no new descriptor, the write is also refused (`UnsafeOpen`, a `ValueError`). Then the church shape (`videos`, `chunks.video_id`, no classic `meta.library`) is read again **through that connection** (`_church_shape_problem`). Only after that does the target get `store.migrate` (the old `store.connect` body after `sqlite3.connect`, split out with no change) and the mark. A sibling that fails gets no write and is returned as skipped. | `OpenRaceTests` (4 tests, with subtests for wesley and a church-shaped classic) |
| **S2** inode compare alone | New test where the path differs from the classic by stem, realpath, and #14's canonical paths, with one link, but `_file_id` reports wesley's `(st_dev, st_ino)`. A bind mount does this in practice, and one can't be made without root, so `_file_id` is faked for that path. | `InodeAndLinkTests.test_same_inode_with_one_link_is_the_classic` |
| **S3** hardlinked church | `_protection(path)` returns `"classic"` or `"hardlink"`. Classic checks run first, so a link to a *known* classic still says classic. A church file with more than one link gets `error: X has N hard links, so another name may point at the same file; a church library must have exactly one. It is not marked`, from both `mark_your_church_exclusive` and `classic_church_refusal` (server / `query.py --church-index`). `mark_your_church_exclusive` now returns `[(path, reason)]` for sibling files still marked `role=church` that it did not clear: hardlinked, not church-shaped, or refused once opened. Classic files are still never opened. `import/youtube.py --your-church` prints `warning: <file> may still be marked as your church; it <reason>, so the mark was not cleared` ("may" since round 1 on #27: a file with an unsafe sidecar is not opened, so its mark is not known) to stderr for each one; the exit code is unchanged. | `InodeAndLinkTests.test_hardlinked_church_has_its_own_message_and_its_mark_is_reported`, `ImportTests.test_your_church_reports_sibling_marks_it_did_not_clear` |
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
- ~~Swapping those sidecar names cannot redirect writes into the classic main file.~~ **This was false** (CTO round 1 on #27). SQLite opens `-wal`, `-shm` and `-journal` by name after the descriptor check, so a sidecar name hardlinked to wesley.sqlite made SQLite write the WAL or the shm index into Wesley, with no race needed, even from read-only opens. Fixed in the fix-up section below.
- S2 and the one-link inode test fake file identity (`_file_id`, `os.fstat`). A real same-inode, one-link path needs a bind mount, and that needs root.
- Not done here (by instruction): wiring the church side to #12's publish gate. The TODOs in `app/server.py` (`prepare_church`) and `search/query.py` (`print_side`) still stand.

## Dependencies

None added.

## Fix-up: CTO round 1 on PR #27

Round 1 on `d30b3eb` (code `9303905`) came back CHANGES. `origin/main` was merged in first (`37d2820`, a merge commit at `a2fd33e`, #20). Nothing was rebased or force-pushed. No new dependencies, no models, no LLM. The church side is still not wired to the publish gate.

### Item → commit → test

| item | change | commit | tests |
| --- | --- | --- | --- |
| **MUST-FIX 1** sidecars into a classic | New `library._sidecar_problem(path)`. Before any open of a church candidate it `os.lstat`s each of `libraries.SIDECAR_SUFFIXES` next to the given path and next to its realpath. Each one that exists must be a regular file, not a symlink, with `st_nlink == 1`, and its `(st_dev, st_ino)` must not be in `_classic_ids()`. On failure the **target** raises `UnsafeOpen` (`error: sample.sqlite has a -wal file with 2 hard links; it is not written`). A **sibling** is not opened at all, even read-only: it is returned as skipped with `has a -wal file with 2 hard links (not opened)`. **`church_shaped`** and **`_is_church_file`** return False without opening it, so it is never in `church_index_matches` or `find_church_index`. `_open_checked` became `_Checked`, which runs one read after the connect (in WAL mode that opens -wal and -shm, and a hot journal replays) and then calls `recheck()`. `recheck()` checks the sidecar names again and `fstat`s every descriptor opened since the last snapshot (one link, not a classic). The target calls `recheck()` again after `PRAGMA journal_mode=WAL` plus a read, and once more before the commit. `_clear_church_mark` calls it before the delete. The false claim in "Open issues" (old line 50) is struck through and corrected. | `108b98b`, `1c3aea5` | `SidecarTests` (6 tests, 16 subtests): hardlinked `-wal`, `-shm`, `-journal` on the target, a rollback-mode sibling, a WAL-mode sibling (journal mode asserted), and the read-only helpers on a WAL-mode church file. Each asserts Wesley's sha256, size and mtime are unchanged. Also: symlink / directory / one-link-classic-inode sidecars; a -wal link planted after the connect (target and sibling); the descriptor recheck on its own (`test_the_descriptor_recheck_refuses_a_sidecar_the_name_check_misses`) |
| **SF1** descriptor reuse | `_descriptors()` returns `{fd: fstat}`. `_new_files(before)` counts a descriptor as new when its number is new **or** its `(st_dev, st_ino)` changed (a closed and reused number). After the connect, exactly one new regular file is required (0 gives `no new descriptor`, 2+ gives `N new files, not 1`), and it must be the inode `os.stat(path)` names after the connect (`is not the file SQLite opened (the name changed)`). | `108b98b` | `DescriptorTests.test_a_reused_descriptor_number_counts_as_new` (SQLite gets a number that was open before, verified, and a benign file opens next), `test_the_opened_file_must_be_the_one_the_name_points_at_after_the_connect` |
| **SF2** `O_CREAT` | Writes open `file:<abspath>?mode=rw` with `uri=True` (`_rw_uri`), so SQLite never creates the file. A failed open is `UnsafeOpen("could not be opened for writing (...)")`. `_SwapOnConnect` now matches that URI and has `how="link" \| "copy" \| "symlink"`. | `108b98b` | `DescriptorTests.test_a_dangling_symlink_swap_creates_no_file`: target and sibling are swapped for a symlink to a missing `index/spurgeon.sqlite`; asserts nothing exists there afterwards |
| **SF3** gate scan | `_ungated_searchers` now checks **every** `Searcher` use in `app/server.py` and `search/query.py`, not only functions with "church" in a name. A `Searcher` is the bare name, `<mod>.Searcher`, an `import ... as` alias, or a name assigned from one. A call passes only with the constant `True`: `gated=True`, a fourth positional `True`, `**{"gated": True}`, or `**name` where `name` is not a parameter, is never mutated (`.method()`, `name[...] =`, augmented assign, `del`), and every assignment to it is a dict literal whose `"gated"` is the constant True. A bare reference (`partial(Searcher, ...)`) is flagged; annotations are not. The only exceptions are `CLASSIC_BUILDERS` (`default_loader`, `load_search`, `App._searcher`, `query.classic_searcher`), and one of those that mentions church is flagged. `search/query.py` now builds every searcher through `church_searcher` (literal `gated=True, library=None`) or `classic_searcher`, so the church path has a literal True. Its behaviour is unchanged (parity below). | `550eeaa` | `ChurchGateTripwireTests.test_source_scan_requires_the_constant_true` (17 bypasses flagged, including every one the CTO listed, plus 5 passing forms). The old assertion that a `gated: False` branch passes is gone. `test_every_searcher_passes_the_gate_or_is_a_named_classic_builder` on the real code |
| **SF4** order | `mark_your_church_exclusive`: by-name checks on the target (including sidecars), then `_Checked(target)` plus the shape read through it. The target is **held open** while the siblings are cleared, then migrated and marked. A target that fails changes no sibling. | `108b98b` | `DescriptorTests.test_a_target_that_fails_once_opened_clears_no_sibling` |

The CLI warning for siblings now reads `warning: X may still be marked as your church; it <reason>, so the mark was not cleared`, because a sibling with an unsafe sidecar is not opened and its mark is unknown. `tests/test_youtube.py` was updated to match.

### Reproduction (before the fix)

Using `/tmp/w3sr/repro.py` (not committed) on the merged tree before `108b98b`, a Wesley-shaped `wesley.sqlite` started at sha256 `30aa22b4adb8…`, the same start as the CTO's run. With a hardlinked `-wal`, the target, the rollback sibling and the WAL sibling each returned `[]` (success) and changed Wesley's hash, after which Wesley's nlink was back to 1. With a hardlinked `-shm`, the target, the WAL sibling and read-only `church_shaped()` each changed Wesley. `-journal` left Wesley intact. After the fix, all 12 cases leave Wesley at `30aa22b4adb8`.

### Mutation checks (round 1 on #27)

Each change was turned off in turn, then `tests.test_side` and `tests.test_youtube` were run (script `/tmp/w3sr/mut.py`, not committed). Every mutation fails at least one test:

| mutation in `library.py` | tests that fail |
| --- | --- |
| sidecar name check off | the target, sibling, read-only and symlink/classic sidecar tests (5 failures, 9 errors) |
| classic-inode check on sidecars off | `test_symlinked_or_classic_sidecars_are_refused` |
| `recheck()` off | both planted-after-connect subtests, and the descriptor recheck test |
| only the fd half of `recheck()` off | `test_the_descriptor_recheck_refuses_a_sidecar_the_name_check_misses` |
| fd-number diff only (no inode compare) | `test_a_reused_descriptor_number_counts_as_new` |
| "exactly one new file" off | `test_a_reused_descriptor_number_counts_as_new` |
| fd inode vs `os.stat(path)` off | `test_the_opened_file_must_be_the_one_the_name_points_at_after_the_connect` |
| `mode=rw` → `mode=rwc` | `test_a_dangling_symlink_swap_creates_no_file`. The other 14 failures happen because `_SwapOnConnect` only fires on `mode=rw` |
| siblings cleared before the target is checked | `test_a_target_that_fails_once_opened_clears_no_sibling` |

The gate scan was also run on mutated copies of the real sources (`/tmp/w3sr/mut_scan.py`). Each of these is flagged: `gated: False` in `load_church_searcher`, an added `gate.update(gated=False)`, `gated=False` or `gated=church` in `query.church_searcher`, and a church mention inside the `load_search` classic builder.

### How to run it

```bash
cd /work/preached/.worktrees/feat/w3-side-race
uv run python -m unittest discover -s tests
uv lock --check
uv run python -m unittest tests.test_side.SidecarTests tests.test_side.DescriptorTests tests.test_side.OpenRaceTests tests.test_side.ChurchGateTripwireTests
```

### Results

- `uv run python -m unittest discover -s tests`: **637 tests, OK** (43.7s). At the main merge `37d2820`: 627 (+10).
- `uv lock --check`: passed (79 packages). `uv.lock` and `pyproject.toml` are identical to `origin/main`.
- Wesley parity: `origin/main` (`a2fd33e`, `git archive`) and this branch were each run with this venv on `/cache/index/wesley.sqlite`. That covered the same 5 queries × bm25/dense/hybrid, plus `--side`, `--library spurgeon` and `--library edwards` (bm25, `"assurance of faith"`), which exercise the `classic_searcher` refactor. stdout, stderr and exit code matched for **18/18**. The `wesley.sqlite` sha256 was `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b` before and after.
- Code head: `1c3aea53f0487aec854238f2f898215cf0ba4a57`. The branch head is the commit that adds this section on top of it.

### Open issues and risks (round 1 on #27)

- ~~Each sidecar is still checked by name and then opened by SQLite, so a narrow window is left. For the read-write path, the descriptor recheck after the first read, after the WAL switch and before the commit catches a link planted in that window before anything is written. The exception is a `-journal` opened by the first write in rollback mode, which no recheck sees before that write. The CTO saw a hardlinked `-journal` leave Wesley intact on 3.53.1, and the pre-fix reproduction here agrees (all 4 `-journal` cases). For read-only opens (`church_shaped`, `_is_church_file`), the `-shm` is written during the first read, so a link planted between the lstat and that read is not caught. That race needs write access to the index dir, timed to the open.~~
  **This overclaimed** (CTO round 2 on #27). The rechecks refuse the link, but not always before SQLite has written to it. Measured on SQLite 3.53.1 (`reports/W3-SIDECAR-READONLY.md`, item 2), 3 of the 6 probed windows change Wesley's bytes before the refusal, after which Wesley reads back as `file is not a database`. They are: a `-shm` link planted after the connect (the first read writes the shm index into it), and a `-wal` or a `-shm` link planted between the recheck before the WAL switch and the switch (`PRAGMA journal_mode=WAL` and the read after it open both files and write to them). A `-wal` link planted after the connect on a WAL-mode target, and a `-journal` link in either window, leave Wesley intact. Every one of these windows needs a live writer with the same uid, timed to the open. Round 1 accepted that as residual risk, and it still stands. The rechecks narrow the window and stop the mark and the commit. They do not guarantee that nothing is written. Read-only opens are the same: the name check runs once, before the connect.
- ~~`store.open_readonly` itself does not check sidecars. Only the church opens in `library.py` do. The server's classic open is unchanged: for spurgeon/edwards, `classic_index_problem` already checks the sidecars. **When the church side is wired to the server (post-#12), it must call `_sidecar_problem` (or the same checks) before `open_readonly` on the church file.**~~
  **Fixed in W3-SIDECAR-READONLY** (CTO round 2 on #27, item 1): `store.open_readonly` now runs `library._sidecar_problem` before every connect, so `search/query.py` (`open_index`, `is_library_file`) and `app/server.py` (`--library <church slug>`, `--index`) refuse a church file with an unsafe sidecar.
- A read-only open of a WAL-mode church file leaves an empty `-wal` and a `-shm` behind (as before). They are regular files with one link, so they pass the check.
- The gate scan is a tripwire, not a proof. A classic builder called from church code (for example `classic_searcher` inside `search_index`'s church branch) is not flagged by the scan. The runtime tests `test_cli_church_searcher_is_gated_on_every_path` and `test_unapproved_church_sermon_is_not_found_through_either_entry_point` cover that path.
- The one-link classic-inode sidecar case fakes `os.lstat`, since a bind mount needs root. The same applies to the S2 / one-link descriptor tests above.

### Dependencies

None added.
