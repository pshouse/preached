# W3-DEPLOY-FIX: CTO #45 r1 must-fixes and should-fixes

Branch `docs/w3-deploy-consolidate`. Head SHA: given in the hand-off (a report cannot name its own commit).
Precondition: head `3ebea1d` was on the branch and on origin. I could not confirm PR #45 is OPEN: `gh` is not installed here. `sandbox.sh` is not installed either; I used plain git in the worktree. Merged `origin/main` (6 commits behind) with a merge commit. No rebase, no force-push, no `src/` change.

Full suite: `PYTHONPATH=src python -m unittest discover -s tests`: **946 tests, OK**. `tests/test_deploy_alerts.py`: 6 tests OK. gitleaks is not installed, so it was not run.

| Item | Result |
| --- | --- |
| MF1 | Removed the literal `198339...63b2`. Step 7 now gives the read command (run in the bundle root, compare to `/healthz`) and says `input index-file`/`index-bundled` are file digests, not `chunks_sha256`. Ran the same query on `/cache/index/wesley.sqlite`: it returns the old value. Script not changed. |
| MF2 | Rule-4 note rewritten to the passive logic CTO stated: `church-paused-stuck` page when `^INFO \S+ \S+ GET /api/side 200$` is logged while still paused; otherwise info notice `church-paused-unverified`. Table row 4 fixed for the no-traffic case. The active probe is labelled an optional manual check. `church-alerts.yaml` is not in the repo, so only CTO's wording is quoted. |
| S1 | Church degradation rows 6-7 (`server.py:853`, `:856`). New "Deploy alerts (OPEN for Infra Ops)" table D1-D6 (`:826`, `:829`, `:1069`, `:1146`, `:3030`, `request failed:` at 7 sites). `INFO listening on http://` (`:2600`) is in the other-lines table. Each string checked against `server.py`; CTO's line numbers all match. D-table severities are my proposal and are marked so. |
| S2 | Per the director correction: kept file:line and added `test_every_cited_file_line_holds_its_string`. It checks each cited line holds its string and that the runbook cites it. Added the new strings to the existing "runbook quotes every line" test. PR #46 must refresh the numbers and the `CITED` table. |
| S3 | Step 3 has the `umask 022; tar -xzf ... -C /srv/preached/<manifest-sha>` command and says the tar has no top-level directory (build uses `-C "$SNAP" .`). |
| S4 | Checklist lists #27 S1 and #33 should-fixes 1-2 (CTO #37 r3) and the #39 tar/bundle gate (#39 r2) as MET. |
| S5 | Part 4 items 5, 6 and 8 are tagged `OPEN:`. |
| S6 | FYI for Infra Ops: the D1-D6 rules do not exist yet, and their severities need their confirmation. Not acted on here. |

Church HC1 text left untouched (#46 rewrites it).

Diff: `git diff <merge-base>..HEAD -- docs/DEPLOY.md tests/test_deploy_alerts.py` on the branch (about +130 lines in DEPLOY.md, +45 in the test).
