# W4-SUBMIT-REFRESH: demo script and submission draft brought up to date with main

Branch `docs/w4-submit-refresh`, from `origin/main` at `bbdb1ba` (merge of #42). Docs only: `docs/SUBMISSION-DRAFT.md` and `docs/DEMO-SCRIPT.md`. No code, test, dependency, eval or index change. README.md repeated no stale claim (it already describes the wired church side), so it is untouched. Nothing deployed or submitted.

## Changes (old -> new, evidence)

1. **Church column.** `DEMO-SCRIPT.md` shot 4 and `SUBMISSION-DRAFT.md` claims row: "not wired" -> wired through the publish gate since PR #37, needs a named church library, `PREACHED_PRIVACY` and `PREACHED_CHURCH_SIDE=enabled`; **real church data is still not loaded**, only synthetic fixtures have run. Also "Not claimed" bullet, the demo rule line, and "no sample church library is served by main" reworded.
   Evidence (synthetic only; a script in `/tmp` imported the fixtures of `tests/test_church_wire.py`):
   - with the synthetic "sample" church library, `/api/side?q=approvedtoken&mode=bm25`: 200, `library: sample`, `label: Your church`, `sample: true`, `present: true`, `empty: false`, hits `['c-approved']`; classic column identical to the no-church run.
   - with no church library: 200, `present: false`, `empty: true`, `message: "Nothing from your church yet."`, no hits.
   - `/healthz` `church: null` in both.
   - Tests: `test_approved_church_passages_appear_beside_the_classic_side`, `test_without_privacy_config_the_church_side_is_empty_and_wesley_serves`.
   - Live server from main, Wesley only, `/api/side?q=how should a Christian use money`: church `present: false`, message as above, classic top 3 `wesley-050-c0007`, `-c0004`, `wesley-028-c0076`.
2. **Test count.** "738 tests pass on main (cd3ad8f); 6 skip" -> "971 tests pass on main (bbdb1ba), 0 skipped on a machine with the /cache ONNX artifacts; some skip without them". Command: `uv run python -m unittest discover -s tests` -> `Ran 971 tests in 234.586s`, `OK`, no skip line. (Plain `python` lacks numpy; `uv run` is required.) The old "6 skip" figure could not be reproduced here, so it was dropped.
3. **Memory.** Checked against reports: `W3-RSS.md` fix-up 48058ae: 683 MiB after load, 685 after 15 queries, peak (VmHWM) 903 MiB (PR head 908). The 722.7 / ~728 / ~969 MiB figures exist only as the CTO review's, quoted in `W4-DEMO-PREP.md` ("not independently re-measured"); no report measures 969 on the embedder. No number differs from its report; the draft's old text had wrongly attached 969 to the 683 figure. Now: 683 MiB / peak 903 MiB = embedder alone (`W3-RSS.md`); 722.7 MiB / peak about 969 MiB = full server with the Wesley index (CTO review, `W4-DEMO-PREP.md`). Applied in `SUBMISSION-DRAFT.md` CPU row and `DEMO-SCRIPT.md` shot 7 backing. (`W3-RSS.md` also records a live server at 726 MiB after load, consistent with 722.7.) `W4-DEMO-PREP.md` line 31 still has the old 683/969 mix; left alone as a past report.
4. **SHA references.** `cd3ad8f` -> `bbdb1ba` (SUBMISSION line 3, DEMO line 10 and pre-flight). Code changed since `cd3ad8f` (church wire, exposure), so the demo's expected results were re-run live on main: healthz `chunks 8383`, same `index_version`, `onnx`, not fallback; money query top 3 `wesley-050-c0007` 317.48, `-c0004` 211.47, `wesley-028-c0076` 2309.57 (strong); assurance `wesley-011-c0025` 780.35, `wesley-010-c0010` 307.49, `-c0043` 1350.88 (strong); cryptocurrency level `none`, top `wesley-050-c0005`, `wesley-087-c0069`. All unchanged.

## Claims table re-check (each against current main)

| Claim | Result |
| --- | --- |
| No LLM; Whisper, Granite, ranks | OK (`AGENTS.md` sections 1-2) |
| Wesley 143/143, 71.14 h, 0 failures | OK (`W1-A.md:183`) |
| 8,383 chunks | OK (`W1-C.md:192`; live `/healthz` 8383) |
| 98.5% mean / 93.1% min | OK (`W1-C.md:190`) |
| 0.75 s pre-roll | OK (`PREROLL_S = 0.75` in `src/preached/search.py:49` and `app/static/app.js:44`) |
| R@5 0.614, MRR 0.497, nDCG 0.546 | OK (`W3-CPU.md:117`) |
| 0.028 / 0.040; 3 of 28 (0.11) | OK (`EVAL-DELEAK.md:7`, and the blind line cited as `EVAL-GRADE.md:20`) |
| 56 ms p50 / 68 ms p95, 1 thread, 149 MiB venv | OK (`W3-CPU.md:149`, `:153`) |
| cosine 0.99999988; int8 rejected | OK (`W3-CPU.md:93`, `:80`) |
| Low-confidence banner; W3-POLISH section 6 | OK (section 6 exists); "cryptocurrency" re-run live: level `none` |
| Rate limit | OK: 120/60 s default (`app/server.py:248`), 60 via `scripts/serve.sh:93` |
| Serve path, loopback/Tailscale only, no public exposure | OK (`docs/DEPLOY.md` "Going public" exists) |
| YouTube import, CC test clip | OK (`W2-YT.md`, `BGoD6CIpLWQ`) |
| Privacy 635/730 = 0.870 | OK (`W3-PRIV-SKIP.md:67`) |
| Spurgeon 6 / 4.32 h, Edwards 39 / 19.53 h, 12/12 smoke | OK (`W3-LIB.md:11-12,77`) |
| Stacked phone layout not checked | OK (`W3-SIDE.md:70,94`) |
| Eval human review pending | OK (`eval/README.md` "Human review") |
| Church gate row | Fixed (item 1); README citation now `README.md:37` |
| Test count | Fixed (item 2) |

## Numbers

Tests: 971 pass, 0 skipped, on `bbdb1ba`. Description: 245 words (unchanged text; limit 250), counted with `wc -w` over the section.

## Still pending for Patrick (not touched)

Track, tone, tagline, the Tailscale URL placeholder in `DEMO-SCRIPT.md`, and the Gaston permission.

## Risks

The 969 MiB and 722.7 MiB figures are the CTO's and are not re-measured. gitleaks: see commit message / final summary.
