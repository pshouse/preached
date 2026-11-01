# W5 main skip census

Report only. One fresh suite run on current `origin/main` with scratch caches, and a census of every skip.

## Base SHA

`44dc5923536e5f8a39f0ba9eeafe5294b3f8ece7` (`origin/main`, merge of PR #80). Branch `qa/w5-main-skip-census`, started from a clean `git status`.

Note: the `9fe33ca` anchor row is on main since #82 (`8e0017d`; `0201049` is an ancestor of main). At `44dc592` it was not yet on main and `docs/SUBMISSION-DRAFT.md` still anchored to `a40706b`. On main now, `docs/SUBMISSION-DRAFT.md` reads "checked at `9fe33ca`" (line 3) and "1081 ran, OK, 10 skipped on `9fe33ca`" (line 42). Section 4 compares against that row.

## Command and env

```
export PREACHED_CACHE PREACHED_ONNX_DIR HF_HOME DENO_DIR XDG_CACHE_HOME UV_CACHE_DIR   # each = fresh mktemp -d
export HF_HUB_OFFLINE=1
uv run python -m unittest discover -s tests -v
```

None of the six pointed at `/cache` or below. `PREACHED_REQUIRE_DENO` was not set. `deno` is at `/usr/bin/deno`, so the deno tests ran.

## Result lines

```
Ran 1105 tests in 250.534s

OK (skipped=12)
```

## Skip census table

Guard lines were re-read on `origin/main` `9690f4f` (R4); the skip reasons are verbatim from the `44dc592` run log (after #84 the embed messages read `... not in PREACHED_CACHE`). Reasons are as printed in the `-v` log.

| # | Test id | Skip reason as printed | Guard (file:line) |
|---|---|---|---|
| **ONNX export** | | | |
| 1 | `test_embed_backend.FdLoadTests.test_load_refuses_a_symlinked_graph` | `granite onnx artifacts are not in /cache` | `tests/test_embed_backend.py:1164` |
| 2 | `test_embed_backend.FdLoadTests.test_real_graph_has_no_external_data` | same | `tests/test_embed_backend.py:1097` |
| 3 | `test_embed_backend.ImportGuardTests.test_youtube_embed_path_does_not_import_torch` | same (the printed line is the docstring "The import embedder is ONNX. ...") | `tests/test_embed_backend.py:660` |
| 4 | `test_embed_backend.RealOnnxTests.test_cached_fp32_and_tokenizer_match_the_pins` | same | `tests/test_embed_backend.py:710` |
| 5 | `test_embed_backend.RealOnnxTests.test_fp32_directory_without_int8_loads` | same | `tests/test_embed_backend.py:717` |
| 6 | `test_embed_backend.RealOnnxTests.test_fp32_query_is_unit_normalized` | same | `tests/test_embed_backend.py:759` |
| 7 | `test_onnx_pin_repro.ExportIsByteIdenticalTests.test_exports_under_any_ambient_seed_are_byte_identical_and_are_the_pin` | `Granite weights are not in PREACHED_CACHE (<scratch>/huggingface/hub/models--ibm-granite--granite-embedding-english-r2/snapshots/47ea694b...)` | `tests/test_onnx_pin_repro.py:774-777` (`skipUnless`, message on :776) |
| 8 | `test_onnx_pin_repro.MutantGraphTests.test_one_flipped_initializer_value_is_refused` | `granite onnx artifacts are not under PREACHED_CACHE (or PREACHED_ONNX_DIR)` | `tests/test_onnx_pin_repro.py:653` |
| **Index / corpus** | | | |
| 9 | `test_eval_leak.TitleLeakTest.test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk` | `needs chunks.jsonl or the index sqlite in PREACHED_CACHE` | `tests/test_eval_leak.py:235` |
| **Deno** | none skipped (deno installed) | | |
| **asr-repro clips** | | | |
| 10 | `test_coverage.CorruptedAsrFixtureTests.test_envelope_matches_the_audio` | `needs the clips in PREACHED_CACHE/asr-repro` | `tests/test_coverage.py:309` (`skipUnless`, helper `_asr_repro_root` :61; an in-body `skipTest` at :313 and a per-clip `skipTest` at :318) |
| **Read-only model mount** | none; the guard no longer exists (see below) | | |
| **Wesley index + pinned ONNX (shutdown)** | | | |
| 11 | `test_shutdown.LoadedSigtermTests.test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` | `needs the Wesley index and the pinned ONNX model under PREACHED_CACHE` | `tests/test_shutdown.py:237-238` (`hybrid_load_ready` check, `skipTest(_HYBRID_SKIP)`) |
| **Infra alerts file** | | | |
| 12 | `test_deploy_regex.DeployRegexTests.test_infra_yaml_matches_when_the_file_is_present` | `infra alerts yaml absent (/workspace/infra-ops/preached/alerts/church-alerts.yaml)` | `tests/test_deploy_regex.py:541` |

Totals by source: ONNX export 8, index/corpus 1, asr-repro 1, shutdown 1, infra file 1, deno 0, read-only mount 0, other 0. That is 12 on the census machine (the count depends on the machine: deno, the infra alerts yaml).

Other guards that did not fire on this machine, unchanged since `9fe33ca` apart from the one-line cache-guard `install()` hook that #84 added near the top of each file: deno `need_deno` at `tests/test_app_js.py:434-439`, used at `:456` and `:637`; `tests/test_mobile_ux.py:320`; `tests/test_privacy_wire_fix.py:250`; `tests/test_privacy_merge.py:219`.

## Changes vs 9fe33ca
(Cites in this section describe the move from `9fe33ca` to `44dc592` and are left as written; the current lines are in R4.)


`git diff 9fe33ca..HEAD --stat` for the skip files: only `tests/test_coverage.py` (+10 lines), `tests/test_embed_backend.py` and `tests/test_shutdown.py` changed. `test_onnx_pin_repro.py`, `test_eval_leak.py`, `test_deploy_regex.py`, `test_app_js.py`, `test_mobile_ux.py`, `test_privacy_wire_fix.py` and `test_privacy_merge.py` are unchanged.

- `tests/test_coverage.py` (#78): the guard was `Path("/cache/asr-repro/c01.wav").exists()` and is now `PREACHED_CACHE/asr-repro/c01.wav`. It also gained a per-clip `skipTest` (:301). The decorator is still at :291. On scratch caches this test now skips; at `9fe33ca` it ran against the hard-coded `/cache`.
- `tests/test_shutdown.py` (#78, with the follow-up in `6935b2d`): `REAL_INDEX` and `ONNX_DIR` follow `PREACHED_CACHE`. The `skipUnless` decorator (:173 at `9fe33ca`) became an in-body `hybrid_load_ready` check, with the skip at :224-225. An empty ONNX directory now skips instead of failing. New tests were added: `test_empty_onnx_dir_skips_hybrid_load` and `test_hybrid_load_ready_follows_the_loader_filenames`. On scratch caches the hybrid test now skips.
- `tests/test_embed_backend.py` (#78): the read-only-mount skip (`if not os.access(source.parent.parent, os.W_OK): skipTest("model mount is read-only...")`, :719 in the draft) was removed. The test now copies the graph under the temp dir. Guard lines moved because of that edit: :740 to :757, :1078 to :1095, :1145 to :1162. :658, :708 and :715 are unchanged.
- #79 (nits batch 5) and #80 (listen backlog) touched no skip guard. At `44dc592` #84 was not on main (no such merge in `git log 9fe33ca..HEAD`; the log had 18 commits, ending at #80); #84 merged later as `9690f4f`.

## Proposed re-anchor wording (text only, not applied)

Compared with the `9fe33ca` row on main since #82 (`8e0017d`; `docs/SUBMISSION-DRAFT.md`, line 3 and line 42). Numbers and cites that change if re-anchored to `44dc592`:

- Line 3: `checked at 9fe33ca` becomes `checked at 44dc592`. Re-run the demo queries or keep the `9fe33ca` note, because the demo dry-run (`reports/W4-DEMO-DRYRUN-2.md`) was not re-run here.
- Test count: `1081 ran` becomes `1105 ran`. The "more than 1,000 tests" headline is unchanged.
- Skips: `10 skipped` becomes `12 skipped` on the census machine (the count depends on the machine: deno, the infra alerts yaml). The two new skips are the `tests/test_coverage.py` envelope test and the `tests/test_shutdown.py` hybrid SIGTERM test. Both now follow `PREACHED_CACHE`, so they skip on scratch caches. The same sha gives `skipped=11` on a machine where the infra alerts yaml is present.
- Run line: `Ran 1081 tests in 256.461s`, `OK (skipped=10)` becomes `Ran 1105 tests in 250.534s`, `OK (skipped=12)`. The evidence cell should cite this report, `reports/W5-MAIN-SKIP-CENSUS.md`.
- Cites that move: `tests/test_embed_backend.py` `:740` to `:759`, `:1078` to `:1097`, `:1145` to `:1164`, `:658` to `:660`, `:708` to `:710`, `:715` to `:717`; `tests/test_onnx_pin_repro.py` `:651` to `:653` and `:774` to `:776`; `tests/test_eval_leak.py:233` to `:235`; `tests/test_deploy_regex.py:539` to `:541` (all lines as on `origin/main` `9690f4f`).
- Move the `tests/test_coverage.py:309` cite and the `tests/test_shutdown.py` cite (`:173` becomes `:238`) out of the "other tests skip only when a source is missing" list and into the scratch-cache skip list. The scratch-cache skip list would then read ONNX export 8, index/corpus 1, asr-repro 1, shutdown 1 = 11. The twelfth skip, the infra alerts yaml (skip at `tests/test_deploy_regex.py:541`), is host-dependent, not a scratch-cache effect: it stays out of that list and is attributed to the host (the default path, overridable by `PREACHED_INFRA_ALERTS` (`tests/test_deploy_regex.py:539`); absent on the census machine). With the yaml present the same sha gives `skipped=11`.
- Delete the read-only model mount sentence (`tests/test_embed_backend.py:719` at `9fe33ca`). That guard no longer exists.
- Drop the sentence "since #78, `tests/test_coverage.py` and `tests/test_shutdown.py` follow `PREACHED_CACHE` ... those last paths were hard-coded at `9fe33ca`, so they did not skip there". It no longer needs a caveat once the anchor is past #78.
- Deno cites are now `tests/test_app_js.py:434-439`, `:456`, `:637`; `tests/test_mobile_ux.py:320`; `tests/test_privacy_wire_fix.py:250`; `tests/test_privacy_merge.py:219`.

Suggested row sentence: "Test suite: more than 1,000 tests; 1105 ran, OK (...). 12 skipped on `44dc592` on the census machine; the count depends on the machine (deno, the infra alerts yaml) as well as the sha. Eleven skips come from private artifacts absent from the scratch caches: the ONNX export (`tests/test_embed_backend.py:660`, `:710`, `:717`, `:759`, `:1097`, `:1164`; `tests/test_onnx_pin_repro.py:653`, `:776`), the chunked corpus or index (`tests/test_eval_leak.py:235`), the `asr-repro` clips (`tests/test_coverage.py:309`), the Wesley index and the pinned ONNX model (`tests/test_shutdown.py:238`). The twelfth is host-dependent, not a scratch-cache effect: the infra alerts yaml is at the default path `/workspace/infra-ops/preached/alerts/church-alerts.yaml` (not in this repo), overridable by `PREACHED_INFRA_ALERTS` (`tests/test_deploy_regex.py:539`); the skip is at `:541`. Deno tests skip only when deno is missing on the machine (none skipped here) (...)."

## /cache before/after diff

Snapshot: `find /cache -maxdepth 2 -printf '%p %s %T@\n' | sort`, 297 entries, before and after the run.

One difference:

```
< /cache/index/cc-speech.sqlite-shm 32768 1793493364.3644106800
> /cache/index/cc-speech.sqlite-shm 32768 1793493661.2717475050
```

Same size, mtime moved by about 297 s. The suite pointed every cache variable at temp dirs. Its cache guard lists `/cache` read-only (`os.walk`/`lstat`: `tests/cache_guard.py:218-256` `snapshot_tree`, `:277-301` `watched_roots`; `tests/test_embed_backend.py:726-727` also checks `/cache`), and as far as I know no test opened a file under it. The likely cause is a concurrent reader of `cc-speech.sqlite`, which rewrites `-shm`; this is unverified. I did not find the writer (`lsof`/`fuser` showed nothing). Cite lines re-read at `origin/main` `9690f4f` (R4). No path was added, removed or resized.

## PR BODY

Report only: a fresh suite run and a skip-source census on current `main` (`44dc592`), so the submission docs can later move off the `9fe33ca` anchor.

- `Ran 1105 tests in 250.534s`, `OK (skipped=12)`, on scratch caches and on the census machine (the count depends on the machine: deno, the infra alerts yaml); the same sha gives `skipped=11` where the infra alerts yaml is present (all six cache env vars on fresh temp dirs, `HF_HUB_OFFLINE=1`).
- The 12 skips on the census machine (the count depends on the machine: deno, the infra alerts yaml): 11 from private artifacts absent from the scratch caches (ONNX export 8, index/corpus 1, asr-repro 1, shutdown hybrid 1) plus 1 host-dependent skip (infra alerts file: the default path, overridable by `PREACHED_INFRA_ALERTS` (`tests/test_deploy_regex.py:539`)). Deno 0, read-only mount 0 (the guard was removed in #78).
- Since `9fe33ca`: `tests/test_coverage.py` and `tests/test_shutdown.py` now follow `PREACHED_CACHE` (two new skips on scratch caches), the read-only-mount skip is gone, and three `tests/test_embed_backend.py` skip lines moved (:740 to :757, :1078 to :1095, :1145 to :1162 from `9fe33ca` to `44dc592`; the same skips are at :759, :1097, :1164 on `9690f4f`/`e434539`).
- The `9fe33ca` row is on main since #82 (`8e0017d`); at `44dc592` it was not. The proposed re-anchor text is in the report. No docs were edited.
- `/cache` snapshot: one mtime change on `/cache/index/cc-speech.sqlite-shm`, observation, likely cause a concurrent reader of `cc-speech.sqlite` rewriting `-shm`; unverified. The suite pointed every cache variable at temp dirs, and its cache guard only lists `/cache` read-only (`os.walk`/`lstat`); as far as I know no test opened a file under it (see report).

PR body stat (`git diff --stat origin/main...HEAD`):

```
 reports/W5-MAIN-SKIP-CENSUS.md | 190 +++++++++++++++++++++++++++++++++++++++++
 1 file changed, 190 insertions(+)
```

## R2 (CTO CONDITIONAL at 4aac742)

Report-only fixes. No tests run; no /cache command was run for R2.

- MF1: the `/cache` paragraph and the PR BODY bullet no longer say no command opened `/cache` or that the mtime change was "not caused by this run's commands". Both now give an observation with a likely cause (concurrent reader of `cc-speech.sqlite` rewriting `-shm`), marked unverified. Cites re-read at `44dc592` with `git show`: `tests/cache_guard.py` `snapshot_tree` is :139-151 (`os.walk` at :151, `_entry` lstat at :117-122), `watched_roots` is :196-220, and `tests/test_embed_backend.py:724-725` is the `/cache` check (the CTO's :724 is the `is_dir()` stat; I added :725).
- MF2: the suggested row sentence no longer says the 12 skips come from artifacts absent from scratch caches. It now reads "12 skipped on `44dc592` on the census machine; the count depends on the machine (deno, the infra alerts yaml) as well as the sha". The infra yaml skip is attributed to the host (the default path, overridable by `PREACHED_INFRA_ALERTS`, per R5 S1), and the deno wording says deno skips depend on the machine.
- S1: if #84 merges first, the re-anchor PR must re-read every cite on its own tree, because most cites move by +2 and the embed skip messages change.
- S2: `tests/test_onnx_pin_repro.py:772-774` and `tests/test_mobile_ux.py:318` are class decorators, so they skip whole classes, not single tests.
- PR BODY: stat line replaced by the final `git diff --stat origin/main...HEAD` (see the PR BODY section).

## R3 (CTO CONDITIONAL at c0bc7cf)

Report-only. No tests run; no /cache command was run for R3.

- MF2-r2: every skip count claim now carries the machine qualifier "on the census machine (the count depends on the machine: deno, the infra alerts yaml)": the totals line ("That is 12"), the re-anchor skips bullet (`10 skipped` becomes `12 skipped`), and PR BODY bullets 1 and 2.
- MF2-r2: the re-anchor count list no longer lumps the host-dependent infra-yaml skip in with the scratch-cache skips. The scratch-cache list is 11; the infra yaml skip is attributed to the host.
- Added a note that the same sha gives `skipped=11` on a machine where the infra alerts yaml is present. The raw output at the Result lines section is verbatim.
- MF1-r2: the PR BODY `/cache` bullet uses the observation wording (mtime change on `-shm`, likely concurrent reader, unverified); there is no "head 4aac742 ... +110" note; the stat line is the current `git diff --stat origin/main...HEAD`.
- R2 section: "No tests run, no cache touched" changed to "No tests run; no /cache command was run for R2".

## R4 (re-anchor cites to post-#84 `origin/main`)

Report-only. Merged `origin/main` (`9690f4ff67fac5ec36dcd3c527301b37fdce84d4`) into this branch with a normal merge; no conflicts. Every cite below was read from the files on that tree (`sed -n`), not computed. No tests run; no /cache command was run. Paths are tree-relative. Counts and findings are unchanged. Cites unchanged at `e434539` (main re-verified in R5). Skip-reason strings in the table are still verbatim from the `44dc592` run log.

Differences from the CTO's expected anchors: `tests/cache_guard.py` `snapshot_tree` is :218-256 (expected :174-186), `_entry` is :196-201 (expected :152), `watched_roots` is :277-301 (expected :233-257). The expected `src/preached/embed_backend.py:726-727` does not exist as a path: the `/cache` check is in `tests/test_embed_backend.py:726-727` (`if Path("/cache").is_dir():` and its `refused.append`), which matches the expected line numbers.

| Cite | old (`44dc592`) | new (`9690f4f`) |
|---|---|---|
| `tests/test_embed_backend.py` ImportGuard skip | :658 | :660 |
| `tests/test_embed_backend.py` cached fp32 pins | :708 | :710 |
| `tests/test_embed_backend.py` fp32 without int8 | :715 | :717 |
| `tests/test_embed_backend.py` unit-normalized | :757 | :759 |
| `tests/test_embed_backend.py` no external data | :1095 | :1097 |
| `tests/test_embed_backend.py` symlinked graph | :1162 | :1164 |
| `tests/test_embed_backend.py` `/cache` check | :724-725 | :726-727 |
| `tests/test_onnx_pin_repro.py` mutant graph | :651 | :653 |
| `tests/test_onnx_pin_repro.py` `skipUnless` | :772-774 (message :774) | :774-777 (message :776) |
| `tests/test_eval_leak.py` | :233 | :235 |
| `tests/test_coverage.py` `skipUnless` | :291-294 | :309 (single line; helper `_asr_repro_root` :61) |
| `tests/test_coverage.py` per-clip `skipTest` | :301 | :318 (new in-body `skipTest` :313) |
| `tests/test_shutdown.py` hybrid skip | :224-225 | :237-238 |
| `tests/test_deploy_regex.py` | :539 | :541 |
| `tests/test_app_js.py` `need_deno` | :432-437 | :434-439 |
| `tests/test_app_js.py` uses | :454, :635 | :456, :637 |
| `tests/test_mobile_ux.py` decorator | :318 | :320 (decorator spans :320-324) |
| `tests/test_privacy_wire_fix.py` | :248 | :250 |
| `tests/test_privacy_merge.py` | :217 | :219 |
| `tests/cache_guard.py` `snapshot_tree` | :139-151 | :218-256 (`os.walk` :230) |
| `tests/cache_guard.py` `_entry` | :117-122 | :196-201 |
| `tests/cache_guard.py` `watched_roots` | :196-220 | :277-301 |

The "Changes vs 9fe33ca" section keeps its historic `9fe33ca`/`44dc592` line numbers on purpose.

The PR BODY stat above is the current `git diff --stat origin/main...HEAD` after R4.

## R5 (CTO CONDITIONAL at 2eec0d7)

Report-only. Merged `origin/main` (`e434539`) into this branch with a normal merge. No tests run; no /cache command was run.

- MF1-r4: the re-anchor cite for the infra yaml skip is `tests/test_deploy_regex.py:541` (the `skipTest`). Checked on `e434539`: :539 is the `path = Path(os.environ["PREACHED_INFRA_ALERTS"]) ... else INFRA_ALERTS` line, :540 is `if not path.is_file():`, :541 is the `skipTest`. So :539 is not `if not path.is_file()` as the review says, but it is the env-override line, which is why S1 cites it.
- MF2-r4: "not on main" claims fixed. The anchor-row note, the "#84" line, the "Compared with" line and the PR BODY bullet now say the `9fe33ca` row is on main since #82 (`8e0017d`) and #84 merged as `9690f4f`; the `44dc592` state is qualified as such. Checked: `0201049` is an ancestor of main; `docs/SUBMISSION-DRAFT.md` on main reads "checked at `9fe33ca`" (:3) and "1081 ran, OK, 10 skipped on `9fe33ca`" (:42).
- S1: "a fixed host path" replaced in the re-anchor cite bullet, the suggested row sentence and PR BODY bullet 2 by "the default path, overridable by `PREACHED_INFRA_ALERTS` (`tests/test_deploy_regex.py:539`)".
- S2: the R4 cites are stated as "unchanged at `e434539`".

PR body stat (`git diff --stat origin/main...HEAD`), current: see the PR BODY section.

## R6 (CTO CONDITIONAL at 42d2193)

Report text only. No tests run; no /cache command was run.

- MF1-r5: PR BODY bullet 3 now names its anchors. Read with `git show <sha>:tests/test_embed_backend.py`: the three `skipTest` lines are :740, :1078, :1145 at `9fe33ca`; :757, :1095, :1162 at `44dc592`; :759, :1097, :1164 at `9690f4f` and at `e434539`. The review's suggested wording put :740/:1078/:1145 at `44dc592`; those are the `9fe33ca` numbers, so the bullet says "from `9fe33ca` to `44dc592`".
- N1: "at `44dc592`" capitalised at the start of the #84 sentence in "Changes vs 9fe33ca".
- N2: the R2 changelog's MF2 "(fixed path)" now reads "the default path, overridable by `PREACHED_INFRA_ALERTS`, per R5 S1".

PR body stat (`git diff --stat origin/main...HEAD`): see the PR BODY section.
