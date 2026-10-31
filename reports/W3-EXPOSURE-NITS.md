# W3-EXPOSURE-NITS: CTO #29 r4, #41 and #40 follow-ups

Branch `chore/w3-exposure-nits` from origin/main 6a94caf, origin/main later merged in (c428e50). Final head 88a8e6e. **PR #44 merged** (f1de31e). Every item below is done.

(Updated in place by 56-W3-DEPLOY-CONSOLIDATE, CTO #44 review S2: §1, §3 and §4 were stale.)

## 1. What was done
- **#29 S1**: `RequestSlotRaceTests.test_slot_is_released_when_sending_the_error_response_fails`. The search raises, the 500 write raises `BrokenPipeError`, and the slot table is empty afterwards; the same key is then served. Mutation check: with the release in `_respond`'s `finally` removed, the test fails (`releases.wait_for(1)` False).
- **#29 S2**: README and `docs/DEPLOY.md` tell API clients (Hark, parallel callers) to honour `Retry-After` on 503/429, and say users behind one IP share its caps.
- **#29 S3**: done in the fix round (88a8e6e, below): the invariant test's docstring states its limits. (Its off-by-one wording was corrected again in 56-W3-DEPLOY-CONSOLIDATE, CTO #44 N1: the invariant test also catches an off-by-one; `slot_is_held` is the deterministic guard, not the only one.)
- **#41 W1-W3**: DEPLOY bundle text merged into "rerun once; if that fails the same way, report and build off-box"; `tar.gz does not match MANIFEST.sha256` quoted in the investigate list; "attempt N of 3 then exit 0 = success"; "5 of 10" replaced by 8 of 10 (r2).
- **#40 S1**: the 0.42 s / 0.76 s figures removed from `eval/timestamps.py` (METRIC_NOTE), `reports/W1-CLI-timestamps.json` note (edited to equal METRIC_NOTE, checked), `reports/W1-CLI.md` (3 places, labelled withdrawn) and the `src/preached/search.py` comment. The pre-roll is described as a margin, not a measured bound. `docs/SUBMISSION-DRAFT.md:32` already says the figures are dropped.
- **#40 S2**: the in-flight shutdown test asserts `stopping` comes before `GET /api/search 200`.
- **#40 N3**: done. DEPLOY says `SuccessExitStatus=143` (SIGTERM dropped as redundant) and that `TimeoutStopSec` expiry means systemd SIGKILLs and reports the stop as failed (`timeout`). The recommended value (`TimeoutStopSec=30`, above `DRAIN_TIMEOUT_S` 10 s and `REQUEST_TIMEOUT_S` 15 s) was added in 56-W3-DEPLOY-CONSOLIDATE (CTO #44 S3).

## 2. How to run
`uv run python -m unittest tests.test_exposure tests.test_shutdown`; `uv lock --check`.

## 3. Results
Full suite at the final head 88a8e6e: 934 tests OK (`uv run python -m unittest discover -s tests`). `uv lock --check` OK. (The first version of this section said 842; that was before the fix round and the merge of origin/main.)

## 4. Open issues
- None left open from #29 r4, #41 or #40. The review files (`/workspace/reports/preached-pr29-review.md`, `preached-pr41-review.md`, `preached-pr40-review.md`) are not on this machine. The CTO reviewed every item in #44 before it was merged.
- No `sandbox.sh` or `gh`: worktree used; open the PR by hand from the compare URL.

## 5. Dependencies
None.

## Fix round: W3-EXPOSURE-NITS-FIX (CTO #29 r4 S3, #40 S2)

Previous head: e091ac0 (origin/main merged in with a merge commit, no rebase). Tests/docstrings only.

- `tests/test_exposure.py`: the docstring of `test_in_flight_never_exceeds_the_cap_and_every_slot_comes_back` now says it catches a non-atomic acquire only through contention (mutant killed 5/5 with a 2 ms window) and that `slot_is_held` is the deterministic guard for off-by-one, not atomicity.
- `tests/test_shutdown.py` `InFlightTests`: the order assert now matches the whole `INFO stopping` line (`\nINFO stopping\n`) instead of `err.index("stopping")`, and requires it before `GET /api/search 200`.
- Mutation: joining the held search before SIGTERM (not in flight at the stop) makes the test FAIL; reverted afterwards.
- Full suite OK (934 tests); `uv lock --check` OK.
