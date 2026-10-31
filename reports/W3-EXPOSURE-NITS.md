# W3-EXPOSURE-NITS: CTO #29 r4, #41 and #40 follow-ups

Branch `chore/w3-exposure-nits` from origin/main 6a94caf. Head SHA: see the PR (the report is committed before the SHA exists).

## 1. What was done
- **#29 S1**: `RequestSlotRaceTests.test_slot_is_released_when_sending_the_error_response_fails`. The search raises, the 500 write raises `BrokenPipeError`, and the slot table is empty afterwards; the same key is then served. Mutation check: with the release in `_respond`'s `finally` removed, the test fails (`releases.wait_for(1)` False).
- **#29 S2**: README and `docs/DEPLOY.md` tell API clients (Hark, parallel callers) to honour `Retry-After` on 503/429, and say users behind one IP share its caps.
- **#29 S3**: NOT DONE. See section 4.
- **#41 W1-W3**: DEPLOY bundle text merged into "rerun once; if that fails the same way, report and build off-box"; `tar.gz does not match MANIFEST.sha256` quoted in the investigate list; "attempt N of 3 then exit 0 = success"; "5 of 10" replaced by 8 of 10 (r2).
- **#40 S1**: the 0.42 s / 0.76 s figures removed from `eval/timestamps.py` (METRIC_NOTE), `reports/W1-CLI-timestamps.json` note (edited to equal METRIC_NOTE, checked), `reports/W1-CLI.md` (3 places, labelled withdrawn) and the `src/preached/search.py` comment. The pre-roll is described as a margin, not a measured bound. `docs/SUBMISSION-DRAFT.md:32` already says the figures are dropped.
- **#40 S2**: the in-flight shutdown test asserts `stopping` comes before `GET /api/search 200`.
- **#40 N3**: partly. DEPLOY now says `SuccessExitStatus=143` (SIGTERM dropped as redundant) and that `TimeoutStopSec` expiry means systemd SIGKILLs and reports the stop as failed (`timeout`). Written from general systemd knowledge, not the review text.

## 2. How to run
`uv run python -m unittest tests.test_exposure tests.test_shutdown`; `uv lock --check`.

## 3. Results
Full suite: 842 tests OK (`uv run python -m unittest discover -s tests`). `uv lock --check` OK.

## 4. Open issues
- `/workspace/reports/preached-pr29-review.md`, `preached-pr41-review.md` and `preached-pr40-review.md` do not exist on this machine (no `/workspace`). I worked from TASK.md's verbatim text only. **S3 (docstring nit) is not done** because its text is only in the review file; N3's full text was also unavailable. W1-W3 wording follows TASK.md.
- No `sandbox.sh` or `gh`: worktree used; open the PR by hand from the compare URL.

## 5. Dependencies
None.
