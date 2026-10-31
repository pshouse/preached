# W3-BUNDLE-NITS: CTO #39 r2 optional nits

Branch `chore/w3-bundle-nits`, from origin/main at `5779961` (PR #39 merged). Head SHA: see the PR (this file is committed in the head commit, so it cannot name it).

## 1. What was done
- N1: three new test rows. Each mutant was applied to `scripts/build-bundle.sh`, the test failed, and the script was restored.
  - Manifest `cmp` (`cmp -s "$VERIFY/MANIFEST.sha256" "$OUT/MANIFEST.sha256"` replaced by `true`): killed by `test_archive_manifest_must_equal_the_bundle_manifest` (fake tar reorders the archived manifest lines; hashes and file set still pass).
  - `! -type d` (replaced by `-type f`): killed by `test_archive_with_an_unlisted_symlink_is_not_kept` (fake tar adds a symlink).
  - Version-line `-P` (removed): killed by `test_a_decoy_package_in_the_callers_cwd_is_not_imported`, which now plants `platform.py` in the caller's cwd.
- N2: DEPLOY.md says "rerun, do not investigate" only for `tar failed (tar 1, gzip 0)`. Any other non-zero exit is a real error. If all 3 attempts fail closed: rerun once, report; fallback is building off-box.
- N3: "the Grok Bot box's snapshot daemon" in DEPLOY.md and the script comment.
- N4: the church/YouTube refusal test passes a path in a temp dir instead of `/tmp/does-not-matter`.

## 2. How to run
`.venv/bin/python -m unittest discover -s tests`; `uv lock --check`.

## 3. Results
Full suite: 774 tests, OK. `uv lock --check`: OK (79 packages resolved).

## 4. Open issues
None. The review file `/workspace/reports/preached-pr39-review.md` is not on this machine; the nits were taken verbatim from the task text.

## 5. Dependencies added
None.
