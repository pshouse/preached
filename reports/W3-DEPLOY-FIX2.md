# W3-DEPLOY-FIX2: CTO #45 round 2 fixes

Branch `docs/w3-deploy-consolidate` (PR #45). Docs and tests only. No change
to `app/`, `src/`, `scripts/`, `pyproject.toml` or `uv.lock`, and no new deps.

## What was done

First merged `origin/main` (`0f2b553`, #49) into the branch. The merge was
clean, with no edits to main's content. #49 changes no file the runbook
cites. I re-checked every cited `file:line` by hand on the merged tree. The
test below now checks them all.

| Item | What changed | Where |
| --- | --- | --- |
| Must-fix 1 | A failed retry of a paused start now logs one `ERROR church side refused: <why>` line, the same line a start logs: `:2787`/`:2794`/`:2805` (`open_church`), `:886` (searcher), `:1381`/`:1386` (install). `:1419` is only for an unexpected exception. The retries end and the pause clears (`:1423`, `:1425`) with no `resumed` line. Also documented: a retry that finds the file busy again keeps the pause with no new line. Row 1 now reads "Any refusal, at start or on a retry of a paused start". Row 3 now covers only the unexpected-exception case. | `docs/DEPLOY.md:710-724`, `:772`, `:774` |
| Must-fix 2 | Row 5 and its note now describe the yaml: candidates are `/api/side 200` lines logged after the 15-minute window while still paused. The page fires only on a second candidate at least `confirm_after: 30s` after the first. A `resumed`, refused or dropped line, or the restart marker, clears the pause. A revert is the one `confirm_after` value. Row 1 now says "(row 5)". | `docs/DEPLOY.md:776`, `:783-806`, `:772` |
| S1 | `CITED` now pins every `file:line` the runbook cites (53 cites: the alert rows, the "Other lines" table, the gate bullets and the unit bullets), with fuller needles. A range pins its first and last line. A new test parses the runbook per table row, bullet or paragraph, so a bare `:n` binds to the file named earlier in its own row. It fails if the doc cites anything unpinned or the test pins anything the doc doesn't cite (this covers the optional nit). | `tests/test_deploy_alerts.py:56-141`, `:209-224` |
| S2 | D6 note: the four client-caused types are named. Proposed: a ticket only for other types (deduped, 1/h), with the client types at INFO. That needs a server change, so not in this PR. | `docs/DEPLOY.md:845` |
| S3 | Rows 7-8 are marked OPEN for Infra Ops, with "none yet (OPEN)" as the rule id. Rows 1-6 got a Rule id column (`church-refused`, `church-dropped`, `church-paused` -> `church-paused-stuck` / `-unverified`, `church-search-failed`). | `docs/DEPLOY.md:770-777`, `:817-829` |
| S4 | The sources line now says the yaml is sourced at `96195be` and was verified on the tree merged with `0f2b553`. The "Other lines" header got the same update. | `docs/DEPLOY.md:766-768`, `:848` |
| S5 | HC2 now reads "added in #46, pending CTO verification" (`tests/test_church_harden.py`, `b9833d8`) and stays OPEN. | `docs/DEPLOY.md:640-643` |
| S6 | The lock-form row adds `app/server.py:883` (searcher build) and `library.py:915` (the start's own `church_file_problem` pause, so `:468` and `:962` can also happen at start). The WAL row and the "Paused at start" bullet got the same. Optional row added: D7 TICKET `ERROR abstain calibration unusable; abstain floor disabled` (`app/server.py:1730`), also added to `DOCUMENTED`. | `docs/DEPLOY.md:853-854`, `:703-708`, `:846` |
| Severities | No severity was changed. Added "severity pending CTO ruling (reviewer recommends ...)" to row 4 (TICKET), row 5's `church-paused-stuck` (TICKET) and D6 (the split). | `docs/DEPLOY.md:775`, `:776`, `:845` |

## How to run

```
uv run python -m unittest tests.test_deploy_alerts
uv run python -m unittest discover -s tests && uv lock --check
```

## Results

- `tests.test_deploy_alerts`: 7 tests, OK.
- Mutation proof. Each mutation was applied, the test run, and the mutation reverted (the tree is clean apart from this PR's files):
  - A blank line inserted at `src/preached/library.py:400`: 6 failures (`:468`, `:883-884`, `:895-896`, `:915`, `:921-922`, `:962`).
  - In-place text edits at `app/server.py:2812`, `:3151`, `:1530` and `src/preached/library.py:884`: each fails on its own cite.
  - Doc edits: D6 `:2325` changed to `:2326`, and a bare `:3166` moved to a bullet that names no file. Each fails the cites-exactly test.
  - Known limit: the check works on the set of (file, line) pairs, so deleting one of several identical cites (for example `:915`, which appears in three rows) passes.
- Full suite: 972 tests, OK on three runs in a row. The first run, before those three, had `FAILED (failures=1)`. The failure never came back, and I didn't save that run's output, so I can't say which test it was. It was most likely a timing flake in a server test. Nothing outside the docs and tests changed.
- `uv lock --check`: OK (79 packages resolved).

## Open issues

- The yaml is not readable from this repo. Row 5's logic is taken from the CTO's description (sha256 `569fa58c2275a0a48f4ed06cf2237e3990b673ecdbf5f378d77e9550ca38b344`). The 30 s rationale in the note is my reading: a paused start retries only after its wait (at most `CHURCH_RETRY_MAX_S`).
- The severities for row 4, `church-paused-stuck` and D6 are pending a CTO ruling.
- The D6 client-type split needs a server change (a later PR).
- HC1 and HC2 stay OPEN, pending CTO verification. HD1 is still OPEN.

## Dependencies

None added.

## Severity rulings (70-W3-DEPLOY-SEVERITIES)

CTO's final rulings (10:16 ET), applied to docs/DEPLOY.md; every "severity pending CTO ruling" line is gone. Yaml: `church-alerts.yaml` sha256 `c1841274aed5d778b9fa3b9b417a456c53a38555fb9403cb072deba68b676f0e` (21 rules, all `enabled: false`, pinned to `76990e8`; supersedes `fdbf36ff`).

| Row | Line | Rule id | Final severity |
| --- | --- | --- | --- |
| 1 | church side refused | `church-refused` | PAGE |
| 2 | refused: searcher could not be built | `church-refused` | PAGE |
| 3 | refused: file could not be opened | `church-refused` | PAGE |
| 4 | church side dropped | `church-dropped` | PAGE (same effect as refused) |
| 5 | paused -> stuck (30 s confirm) | `church-paused-stuck` | PAGE |
| 5 | paused, no church traffic | `church-paused-unverified` | INFO |
| 5 | paused (start), resumed, `pause ended: refused` (new, `:1431`) | `church-paused` | INFO |
| 6 | church search failed | `church-search-failed` | TICKET (max 1/hour) |
| 7 | church vectors mismatch, BM25 | `church-vectors-mismatch-bm25` | TICKET |
| 8 | church vectors unavailable, BM25 | `church-vectors-unavailable-bm25` | TICKET |
| D1 | stored vectors mismatch, BM25 | `deploy-stored-vectors-mismatch-bm25` | PAGE |
| D2 | embedding model unavailable, BM25 | `deploy-embedding-unavailable-bm25` | PAGE |
| D3 | refusing to serve after reload | `deploy-refusing-after-reload` | PAGE |
| D4 | refusing to serve (frozen bundle) | `deploy-refusing-frozen-bundle` | PAGE |
| D5 | stuck stop | `deploy-stuck-stop` | PAGE |
| D6 | request failed, server-side types | `deploy-request-failed-server` | TICKET (max 1 per rolling hour) |
| D6 | request failed: TimeoutError, ConnectionResetError, BrokenPipeError, ConnectionAbortedError | `deploy-request-failed-client` | INFO |
| D7 | abstain calibration unusable | (none) | TICKET (unchanged) |
| - | listening on / stopping / church opened / refusal warning and flush / tar flake | `process-restart`, `deploy-stopping`, `church-opened`, `deploy-refusal-warning`, `deploy-refusal-flush`, `build-tar-flake-retry`, `build-tar-flake-exhausted` | INFO |

Rows 7-8 and D1-D6: rule drafted, disabled (Infra Ops). OPEN in DEPLOY.md: an idle keep-alive timeout should not log at ERROR (code nit, later). Known gaps: silent BM25 fallback on reload is a HARD CONDITION before any public exposure (W3-OBS-GAPS); no clean-stop exit line is a should-fix until W3-OBS-GAPS lands. HD1 is MET (fixed in #48).

### Post-#48 refresh

Merged origin/main `76990e8` into this branch (merge commit, no conflicts). Every `app/server.py` citation in DEPLOY.md and `CITED` in `tests/test_deploy_alerts.py` was re-pinned against the merged tree, with `:1431`, `:1482` and `:2745` added. A final re-pin follows 71-W3-OBS-GAPS.

### Full suite, 3 runs (outputs in `cache/full-suite-run{1,2,3}.txt`)

- Run 1: 978 tests, 1 failure: `test_embed_backend.FdLoadTests.test_graph_owned_by_another_uid_is_refused` (`AssertionError: 19 != 34`, an open-fd count). Not touched by this change.
- Run 2: OK. Run 3: OK.
- `uv lock --check`: OK. No dependencies added.
