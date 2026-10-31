# W3-DEPLOY-CONSOLIDATE: DEPLOY.md end to end, one runbook

Branch `docs/w3-deploy-consolidate` from origin/main `f1de31e` (PR #44 merge; contains #37 `2b7ac93` and #40 `6a94caf`). Precondition met. Docs only, plus one new test file that pins alert strings and one test docstring (no test logic changed). No code changed. Nothing deployed. Head SHA: see the PR (this report is committed before the SHA exists).

## 1. What was done

### DEPLOY.md, read end to end and rewritten as one runbook

`docs/DEPLOY.md` now has four parts:

1. **The runbook**, in order: build (including how to read the tar flake), check, upload and extract, owner and modes, venv, start (with the systemd unit settings), go-live checks, roll back, rotate a secret.
2. **Reference**: what may be served, what the server needs, what the bundle holds, the start-up bundle check, what `serve.sh` sets, direct-start guarantees, stop and exit codes, `.venv`, reproducing a hash, the Hardening table (unchanged), notes for the host.
3. **The church side (not deployed)**: the hard-conditions checklist (all OPEN), the interim rule, the approval rule, how the gate works, what is logged, and the Infra Ops alert table with file:line sources.
4. **Going public (not part of this deploy)**: the draft threat model, then the one gate list ("Remaining go-public gate items"). Release notes follow.

Heading levels and the headings `### What a direct start does and does not guarantee`, `` ### `.venv` is a trust boundary ``, `### Reproducing a bundle hash`, `## Threat model (DRAFT, not final)` (as a substring of the `###` heading), `### Remaining go-public gate items` and `## Release notes` were kept so that the existing doc pins in `tests/test_deploy.py` and `tests/test_exposure.py` still pass unchanged.

Contradictions and duplicates removed:

| Was | Now |
| --- | --- |
| Two go-public lists (13 items under "Going public", 12 under "Remaining go-public gate items") with different numbering. The Hardening notes said "gate item 5", which was retention in the first list and scoped credentials in the second. | One 14-item list. "Part 4, item 5" is retention. Item 11 is new: the CTO's end-to-end read of DEPLOY.md. |
| M2 and M4 "in code on `feat/w3-exposure`". | In code on main since PR #29 was merged. Each closes when the CTO accepts it. |
| Threat-model gap "the audit log records the socket peer, not the client, until M2". This contradicted the Hardening table, which says the log has the client key. | Replaced by the gap that is still true: with `PREACHED_TRUSTED_PROXIES` empty behind `tailscale serve`, the log and the limits key on the socket peer, not the client. The history ("every proxied request was logged as `127.0.0.1`") moved to the #29 release notes. |
| "Public exposure goes only through Tailscale" said twice. | Once. |
| Church: "logs one `ERROR church side refused: <why>` line" (CTO nit). | The searcher-build path is called out: one `refused` line, then the Python traceback (`logging.exception`, `app/server.py:1633`). |
| Gate item 3: "checked at start and before every church search. Any failure drops the church side until restart." | At start it is a refusal; while serving it is a drop. Both last until restart. |
| Gate item 4: "While `--ack-review` is writing … each church search is skipped …, and the side is not dropped." That is only true after start. | At start, a writer lock or a WAL-mode file is a refusal until restart (CTO r3). The interim rule: never start the server while `--ack-review` runs. |
| "`INFO church side resumed` when church results come back". | Logged only after the next church search completes. With no church traffic, no `resumed` line. |
| Build section gave `uv sync` as "the install recipe", and so did Update step 4. Update step 1 repeated the build section. | `uv sync` is in step 5 only. Build is step 1 only. |
| Hardening notes pointed at "step 5 exits 126" and "check step 6" of "Update the Sprite". | Steps renumbered to the single runbook (step 6 exits 126; step 7 is the go-live check). |
| Systemd notes (`SuccessExitStatus=143`, `TimeoutStopSec=`) were inside a bullet of "what a direct start guarantees". | Step 6 (unit settings) and "Stop and exit codes". |
| The kill file was described in the table, under roll back, and in the gate. | Table (reference), step 7 (check), step 8 (use). |
| "From this worktree", "On this machine that is CPython 3.12.16". | "From a clean checkout", "on the build machine". |

### CTO additions folded in

- **#37 r3, hard condition 1**: the runbook line is in the hard-conditions checklist, with only the "DEPLOY must say" wording changed: "A writer lock at startup drops the church side until restart. Treat a busy startup as paused and retry the open later. Until fixed, never start the server while `--ack-review` runs, and Infra Ops alerts on `church side refused: the church file is locked by a writer`." It is repeated as an operator step below the checklist.
- **#37 r3, checklist**: "Church deploy hard conditions" lists pastor permission, CTO church-deploy approval, an operator-chosen unguessable slug, Infra Ops alerts on the exact strings, the writer-lock fix or the interim rule, and the church-on integration test under #29's caps (health buckets, refusal-log flush, SIGTERM, stuck path). Every item is marked **OPEN**. None is marked met.
- **Alert rules (06:31)**: DEPLOY cites `/workspace/infra-ops/preached/alerts/church-alerts.yaml` (ops box, not readable from here). It has a five-row rule table with each rule's file:line, the log format and anchoring, and "every church rule stays DISABLED until the church deploy is approved".
- **#44 S3**: step 6 recommends `TimeoutStopSec=30`, above `DRAIN_TIMEOUT_S` (10.0, `app/server.py:235`) and `REQUEST_TIMEOUT_S` (15, `app/server.py:229`), both checked in code. It also says a stuck drain leaves the church index open too (`app/server.py:3026-3043`; the church connection is closed only on the clean path, `:3039-3040`, inside the CTO's cited `3029-3040`).
- **#44 S1**: `reports/W1-CLI.md:59-60` and `:75-76` now say "No audio-accuracy measurement is in the repo; the timestamp hit@k is not one." The README sentence that called the W1-C spot-check "audio accuracy" says the same. Other hits are in §4.
- **#44 S2**: `reports/W3-EXPOSURE-NITS.md` updated in place: header (final head 88a8e6e, PR #44 merged as f1de31e), §1 (#29 S3 done, #40 N3 done), §3 (934 tests at 88a8e6e), §4 (nothing open).
- **#44 N1**: `tests/test_exposure.py` docstring of `test_in_flight_never_exceeds_the_cap_and_every_slot_comes_back` now says the invariant test also catches an off-by-one (peak 3 against a cap of 2, W3-EXPOSURE-FIX5), so `slot_is_held` is the deterministic guard, not the only one. Docstring only. A grep of `docs/`, `reports/`, `tests/`, `app/` and `src/` found no other place that calls it the only guard. `reports/W3-EXPOSURE-FIX5.md:141` was already right.

### New test: `tests/test_deploy_alerts.py`

It pins the strings the runbook tells Infra Ops to match:

- A real writer lock (`BEGIN EXCLUSIVE`) at `open_church` logs exactly `ERROR:root:church side refused: the church file is locked by a writer (database is locked); it is not opened`.
- A failing church search logs `church search failed; that side is empty` followed by a traceback.
- A searcher that cannot be built logs `church side refused: its searcher could not be built` followed by a traceback.
- `app/server.py` still configures `format="%(levelname)s %(message)s"`.
- DEPLOY.md quotes each of these, plus the `dropped`, `paused` and `resumed` prefixes and the tar-flake line.

## 2. How to run

```bash
uv run python -m unittest tests.test_deploy_alerts -v
uv run python -m unittest discover -s tests
uv lock --check
# the grep checks behind the tables below
grep -n 'church side\|church search failed\|levelname' app/server.py
grep -n 'locked by a writer\|cannot be opened (\|it is not opened"\|cannot be read ({exc})\|is in WAL journal mode' src/preached/library.py
grep -n 'attempt .* of 3\|tar failed\|does not match MANIFEST' scripts/build-bundle.sh
```

## 3. Results

Tests: 940 OK at base `f1de31e`. 945 OK on this branch (940 plus the 5 in `tests/test_deploy_alerts.py`). The existing DEPLOY doc pins (`tests/test_deploy.py`, `tests/test_exposure.py` `DocAndScriptTests`) pass without changes. 934 OK re-run at `88a8e6e`, which confirms the S2 figure. `uv lock --check` OK.

### Alert rules: Infra Ops sources (against 2b7ac93) re-checked on f1de31e

| Rule | Infra Ops source | On f1de31e | Match |
| --- | --- | --- | --- |
| PAGE writer lock at startup | `server.py:2668`, text `library.py:468` + `:865`, ends `(database is locked); it is not opened` | `2668 logging.error("church side refused: %s", exc)`; `468 raise ChurchPaused(f"the church file is locked by a writer ({exc})")`; `865 problem = f"{exc}; it is not opened"`. Full line reproduced by the new test. | yes |
| other startup lock forms | `library.py:848` `cannot be opened (database is locked)`, `:869` `cannot be read` | `848 … cannot be opened ({exc})`, `869 … cannot be read ({exc})` | yes (text only; see §4) |
| PAGE `ERROR church side refused:` | `server.py:983, 988, 1633, 2663, 2668, 2679` | all six lines log `church side refused: …` | yes |
| PAGE `ERROR church side dropped:` | `server.py:1351` | `1351` | yes |
| INFO/pause `INFO church side paused:` | (no line given) | `1359` | n/a |
| `INFO church side resumed` | `server.py:1418` | `1418`, inside `_church_search` after a search ran | yes |
| TICKET `ERROR church search failed; that side is empty` | `server.py:1421` | `1421` (`logging.exception`) | yes |
| Log format | `server.py:2848` | `2848 logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")` | yes |

### Every alert or log string the runbook names, with where the code emits it (grep-verified on f1de31e)

| String | File:line |
| --- | --- |
| `ERROR church side refused: <why>` | `app/server.py:983`, `:988`, `:1633`, `:2663`, `:2668`, `:2679` |
| `ERROR church side refused: the church file is locked by a writer (database is locked); it is not opened` | `app/server.py:2668`; `src/preached/library.py:468`, `:865` |
| `ERROR church side refused: <file> is in WAL journal mode; run --ack-review (it leaves DELETE mode) before serving it` | `app/server.py:2668`; `src/preached/library.py:839` |
| `ERROR church side refused: its searcher could not be built` + traceback | `app/server.py:1633` |
| `ERROR church side refused: PREACHED_CHURCH_SIDE is not 'enabled'; …` | `app/server.py:2663`, text `:2615` |
| `ERROR church side dropped: <why>` | `app/server.py:1351` |
| `INFO church side paused: <why>` | `app/server.py:1359` (called from `:1345` and `:1426`); texts `library.py:468`, `:907`, `server.py:1426` |
| `INFO church side resumed` | `app/server.py:1418` |
| `ERROR church search failed; that side is empty` + traceback | `app/server.py:1421` |
| `INFO church side: <slug>, read-only, through the publish gate` | `app/server.py:2686` |
| `warning: the church file is still in wal journal mode (…)` | `src/preached/youtube/pipeline.py:333`, text `src/preached/youtube/library.py:157` |
| `INFO stopping` | `app/server.py:3025` |
| `ERROR <n> handler thread(s) still running after 10s; index left open` | `app/server.py:3030` |
| `WARNING refused <class> <detail> suppressed=N` | `app/server.py:469` |
| `WARNING refused <class> flush suppressed=N` | `app/server.py:481` |
| `tar exited 1 (file changed as we read it?); attempt N of 3` (tar flake) | `scripts/build-bundle.sh:239` |
| `tar failed (tar 1, gzip 0); no archive written` (tar flake, after three attempts) | `scripts/build-bundle.sh:243` |
| `tar.gz does not match MANIFEST.sha256; no archive written` | `scripts/build-bundle.sh:247` |
| `Log format %(levelname)s %(message)s` | `app/server.py:2848` |

Every string DEPLOY names was found in code. "file changed as we read it" is GNU tar's own message, and "Suppressed N messages" is journald's. Neither is emitted by this repo, and DEPLOY says whose each one is.

## 4. Open issues, risks, exclusions

**Mismatches for Infra Ops and the CTO.** No code was changed for any of these.

1. **`/api/side` has no "paused" state.** The pause rule pages "only if GET /api/side still shows the side paused". It never shows that. A paused, dropped or refused side, and a server with no church side, all give `"church": {"present": false, …}`, and `/healthz` gives `"church": null` in every case. A `GET /api/side?q=…` is also itself a church search, so it ends a pause (and logs `resumed`) if the lock is gone. DEPLOY documents a workable check: one probe after 15 minutes; `present: true` means resumed; `present: false` with no `dropped` line since the `paused` line means still paused, so page. Infra Ops should change the rule.
2. **A start-up form missing from the PAGE writer-lock rule.** A start while `--ack-review` has the file in WAL mode logs `ERROR church side refused: <file> is in WAL journal mode; run --ack-review …` (`library.py:839`). It is the same "busy startup" and the same until-restart outcome. The generic `refused:` PAGE rule catches it, but not as the first-checked lock rule.
3. **`library.py:848` and `:869` with `(database is locked)`**: the text is grep-verified, but these forms were not reproduced. A `BEGIN EXCLUSIVE` writer gives the `:865` form, which the new test pins.
4. **`resumed` can be absent.** If the side is dropped during a pause, `_drop_church` clears the flag and no `resumed` line comes; the `dropped` PAGE covers that. With no church traffic, no `resumed` line comes either.
5. **Observation (code, not changed)**: when the church searcher cannot be built (`app/server.py:1633`), `build_app` does not hand the church connection to `App`, and `serve_until_stopped` closes only `app.church_connection`. That connection stays open until the process exits. It is harmless for reads but worth a look in the writer-lock fix.

**Audio-accuracy grep (S1)** of `docs/`, `reports/`, `README.md`, `eval/`, `src/`, `app/`, `tests/`:

- Fixed: `reports/W1-CLI.md:59-60`, `:75-76`, and `README.md:25`.
- Already correct, unchanged: `eval/timestamps.py:42` (`METRIC_NOTE`) and `reports/W1-CLI-timestamps.json:2` both say no audio-accuracy figure is claimed. `docs/SUBMISSION-DRAFT.md:32` says no measured offset is claimed.
- Listed, not changed:
  - `reports/W1-HARDEN.md:13` is a historical change log row. It says "the audio evidence is the W1-C spot-check (median 0.42 s, max 0.76 s …)". Those figures were withdrawn later (#40 S1). I left the record as written; the CTO may want a "[superseded]" note.
  - `reports/W1-C.md:387-388` says "The accuracy of Whisper's own word times was measured independently in W1-A: median 0.01 s, p90 0.05 s against a sequential decode." It does not call this audio-accuracy evidence. It compares one decode against another, not against the audio, so it should not be read as audio accuracy either.

**Other notes:**

- Every church hard condition and every go-public item is OPEN. The CTO's own read-through of DEPLOY.md is go-public item 11, and it gates any deploy.
- The Hardening table, the threat-model text, the release notes and every number in DEPLOY were carried over as they were. They were not re-measured.
- `sandbox.sh` and `gh` are not on this machine. I used a git worktree from origin/main; the PR has to be opened by hand from the compare URL.

## 5. Dependencies added

None.
