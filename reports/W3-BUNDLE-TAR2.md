# W3-BUNDLE-TAR2: CTO round 1 on PR #39

Branch `fix/w3-bundle-tar`, origin/main f9f7551 merged in with a merge commit (no rebase). No new dependencies. `uv lock --check` OK. Full suite: 772 tests OK.

## Item -> commit / test map (all in e0fced8)

| Item | Change | Test(s) |
|---|---|---|
| M1 stale tar after failed build | `TAR` set and `rm -f -- "$TAR"` right after the usage check; later rm dropped | `test_failures_before_the_tar_step_remove_a_stale_archive` (subTests: missing index, non-SQLite index, ONNX pin mismatch, non-empty output dir) |
| S2 three tar attempts | loop on tar exit 1 (gzip 0), max 3, each gated by verify_tar; DEPLOY.md documents the snapshot-daemon cause and "rerun on `tar failed`" | `test_tar_exit_1_twice_then_success_passes`, `test_tar_exit_1_three_times_fails_closed_after_three_attempts` (exactly 3 calls, no tar, no partial); once-retry test now expects "attempt 2 of 3" |
| S1 sha256sum --check untested | fake tar changes a listed file's bytes before tarring | `test_archive_with_a_changed_listed_file_is_not_kept` |
| Nit: stale .partial.<pid> | `rm -f -- "$TAR".partial.[0-9]*` at start | `test_leftover_partial_files_from_killed_builds_are_removed` (non-pid and other-name files kept) |
| Nit: `! -type d` in set check | done | covered by existing set-check test |
| Nit: compare extracted MANIFEST.sha256 with $OUT's | `cmp -s` in verify_tar | build tests that reach verify |
| Nit: trailing slash on OUT | rejected, exit 2 | `test_out_dir_with_a_trailing_slash_is_rejected` |
| Nit: version line in decoy test | asserts `input python X.Y.Z sqlite N` in stdout | `test_a_decoy_package_in_the_callers_cwd_is_not_imported` |

## Mutation checks
- M1: moved the rm back to just before the tar step: `test_failures_before_the_tar_step_remove_a_stale_archive` fails on all 4 subTests. Restored.
- Attempt bound: changed `-lt 3` to `-lt 4`: `test_tar_exit_1_three_times_fails_closed_after_three_attempts` fails. Restored.

## Process notes
- `sandbox.sh` and `gh` are not on this machine and `/workspace/reports/preached-pr39-review.md` does not exist. I used plain git (remote head was 8ff11e5, as expected) and the review items as quoted in TASK.md. PR #39 open state could not be confirmed with gh.
- Not run: any deploy or shipping bundle build; the real-box snapshot-daemon cause is from the CTO's note, not reproduced here.
