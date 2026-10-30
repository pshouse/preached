# W3-PRIV-NITS: CTO should-fixes from PR #12 round 7 and PR #19 round 4

Branch `feat/w3-priv-nits` from main at e465ad0 (PR #19 merged).

## 1. What was done
| Item | Commit | Test |
|---|---|---|
| `W3-PRIV-WIRE.md` said `t=` rounds up; it rounds down (`int()` in `youtube/listing.py`) | 7aa4af8 | doc only |
| `audio_policy.py` error now says church libraries accept only `none` | 04615a4 | `test_privacy_wire.py` regexes updated |
| `_open_private_dir` EEXIST retries the open exactly once | 9120730 | `test_eexist_retries_the_open_exactly_once` |
| Intermediate path component swapped for a symlink fails closed (create True and False) | 9120730 | `test_intermediate_component_swapped_fails_closed` |
| #19 S1: trunk pages skip `max(64, 8+4*count)` bytes; leaf pages must be fully zero; fixture (512-byte pages, 1500x filler) frees more than one trunk (asserted); `CANARY[:8]` absence check | f5a60d4 | `test_redo_canary_removed_from_db_and_wal` |
| #19 S2: `--out` under a symlinked parent is rewritten at approval, link kept | f5a60d4 | `test_out_under_a_symlinked_parent_is_rewritten_at_approval` |

## 2. How to run
`uv run python -m unittest discover -s tests`; `uv lock --check`.

## 3. Results
531 tests, all pass (528 before, +3). `uv lock --check`: Resolved 79 packages, OK.

## 4. Open issues
None new.

## 5. Dependencies added
None.
