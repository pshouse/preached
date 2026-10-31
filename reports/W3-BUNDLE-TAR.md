# W3-BUNDLE-TAR: CTO follow-ups from #38 (S2 deploy gate, S1, N1-N3) and #37 r1 should-fix 5

Branch `fix/w3-bundle-tar`, from origin/main 1498182. No new dependencies.

## 1. Item -> commit / test map

| Item | Commit | Test(s) |
|---|---|---|
| S2 tar exit 1 leaves a complete-looking tar.gz (deploy gate) | ae33617 `scripts/build-bundle.sh`: tar to `<out>.tar.gz.partial.$$`, retry once on tar exit 1, `gzip -t`, extract and `sha256sum --check --strict MANIFEST.sha256`, file set must equal the manifest's plus the manifest, then `mv`. Any failure exits 1 and leaves no tar. An older `<out>.tar.gz` is removed before the attempt. | `test_tar_exit_1_leaves_no_archive_and_fails` (fake tar on PATH, always exit 1: non-zero exit, no `.tar.gz`, no `.partial`), `test_failed_rebuild_removes_an_older_archive`, `test_tar_exit_1_once_is_retried_and_the_archive_verifies`, `test_tar_exit_2_is_not_retried`, `test_archive_that_disagrees_with_the_manifest_is_not_kept` (tar exits 0 but adds an unlisted file), `test_success_archive_verifies_against_the_manifest` |
| S2 report line | this branch | `reports/W3-ONNX-NITS.md` S4 row corrected: "no change needed" was wrong |
| #37 r1 should-fix 5 (`python -c` imports from caller's cwd) | ae33617: `-P` on all five inline `python` runs (the stdin check, strip_int8, copy_index, stamp, version line). The `-I` runs and the script-file runs already did not put cwd first. | `test_a_decoy_package_in_the_callers_cwd_is_not_imported` (decoy `preached/`, `app/`, `scripts/` in cwd; marker file must not appear; build succeeds) |
| S1 7 untested walker entries | 6fd31e8 | `test_external_data_under_every_walker_entry_is_refused`, one subTest row each: training_info.initialization (20/1), training_info.algorithm (20/2), attribute.tensors (10), attribute.graphs (11), attribute.sparse_tensor (22), attribute.sparse_tensors (23). Each row is a TensorProto with `data_location=1` reached only through that entry. |
| N1 FIFO release can raise ENXIO | 6fd31e8 | `test_fifo_at_the_graph_path_is_refused_without_hanging`: release open now retries on ENXIO until the worker ends or 5 s pass, then fails the test. |
| N2 `cp -r` is 0775 only under umask 002 | a54138f `docs/DEPLOY.md` | docs; recommends `cp -a` / `rsync -a` from a 0755 tree, or the chmod lines |
| N3 doc names `model/`, loader checks `model/<rev>/` | a54138f `docs/DEPLOY.md` | docs; says the loader checks `model/<revision>/` only and why that is safe (files pinned by hash) |

Behavior note for Infra Ops: a successful build prints the same lines as before. On a tar exit 1 the script prints `retrying once` to stderr. If `<out>.tar.gz` exists, the build succeeded and the archive was checked.

## 2. Mutation checks (S1)

Each walker-table entry removed from `_ONNX_SUBMESSAGES` in `src/preached/onnx_embed.py`, `tests.test_embed_backend` run, file restored (`git diff src` empty afterwards).

| Mutation | Failing subTest |
|---|---|
| drop `20: "training"` from model | training_info.initialization and .algorithm |
| `training` loses `1` | training_info.initialization |
| `training` loses `2` | training_info.algorithm |
| attribute loses `10` | attribute.tensors |
| attribute loses `11` | attribute.graphs |
| attribute loses `22` | attribute.sparse_tensor |
| attribute loses `23` | attribute.sparse_tensors |

All 7 entries are caught, each by its own row only. The S2 and decoy tests were also run against the old `build-bundle.sh` from main: 6 of the 7 new BundleTests tests fail there (decoy, mismatch, stale-tar removal, exit 1, retry, exit 2); the seventh, the success-path archive check, passes on both.

## 3. Real build runs

The model artifacts and `/cache/index/wesley.sqlite` are in the sandbox, so these are real builds of the Wesley bundle (about 2 minutes each, 4.5 GB of output for 10).

- 10 builds completed; 10 exit 0, 10 left a `.tar.gz`, 0 `.partial` files left behind.
- 0 of 10 hit the tar exit 1 retry path. The flake did not show up in this run, so these counts say the happy path is stable; the fake-tar tests are what show the fail-safe works.
- The tars had the same sha256 (`9e9ad053...ddd8c`): all 8 of builds 1-8 matched when compared, and builds 5-10 (6 tars) matched at the end. Builds 1-4 were deleted after that first comparison to free disk.
- One extra loop iteration (the 9th of the first loop) was killed by the sandbox's 10-minute limit mid-build. It left no tar and no `.partial`, which is the intended interrupted-build behavior. It is not counted in the 10; builds 9 and 10 above were rerun.

## 4. Numbers

- Full suite: 751 tests, OK (`uv run python -m unittest discover tests`). New tests: 1 in `test_embed_backend.py` (6 subTests), 7 in `test_deploy.py`.
- `uv lock --check`: ok.

## 5. Open issues

- The cause of the tar exit 1 on a static snapshot is still unknown. The script now handles the symptom (one retry, then fail with no tar). If a build hits the retry, the stderr line is the evidence to chase.
- The retry reuses the same private snapshot; it does not re-copy.
- A tar with a different failure mode that still verifies against the manifest is accepted by design: the manifest check is the contract.
- The reference review file `/workspace/reports/preached-pr38-review.md` is not present in this sandbox; I worked from the task text.

Head SHA: the commit that adds this file is the head of `fix/w3-bundle-tar` (`git rev-parse --short HEAD` after checkout; also shown on the PR).
