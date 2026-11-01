# W5 main skip census

Report only. One fresh suite run on current `origin/main` with scratch caches, and a census of every skip.

## Base SHA

`44dc5923536e5f8a39f0ba9eeafe5294b3f8ece7` (`origin/main`, merge of PR #80). Branch `qa/w5-main-skip-census`, started from a clean `git status`.

Note: the `9fe33ca` anchor row is **not on main**. `docs/SUBMISSION-DRAFT.md` on `main` still anchors to `a40706b` (998 tests, 0 skipped). The `9fe33ca` row is on branch `docs/w4-submit-dryrun2` (commit `0201049`, line 42). Section 4 compares against that row.

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

Guard lines were read on `44dc592`. Reasons are as printed in the `-v` log.

| # | Test id | Skip reason as printed | Guard (file:line) |
|---|---|---|---|
| **ONNX export** | | | |
| 1 | `test_embed_backend.FdLoadTests.test_load_refuses_a_symlinked_graph` | `granite onnx artifacts are not in /cache` | `tests/test_embed_backend.py:1162` |
| 2 | `test_embed_backend.FdLoadTests.test_real_graph_has_no_external_data` | same | `tests/test_embed_backend.py:1095` |
| 3 | `test_embed_backend.ImportGuardTests.test_youtube_embed_path_does_not_import_torch` | same (the printed line is the docstring "The import embedder is ONNX. ...") | `tests/test_embed_backend.py:658` |
| 4 | `test_embed_backend.RealOnnxTests.test_cached_fp32_and_tokenizer_match_the_pins` | same | `tests/test_embed_backend.py:708` |
| 5 | `test_embed_backend.RealOnnxTests.test_fp32_directory_without_int8_loads` | same | `tests/test_embed_backend.py:715` |
| 6 | `test_embed_backend.RealOnnxTests.test_fp32_query_is_unit_normalized` | same | `tests/test_embed_backend.py:757` |
| 7 | `test_onnx_pin_repro.ExportIsByteIdenticalTests.test_exports_under_any_ambient_seed_are_byte_identical_and_are_the_pin` | `Granite weights are not in PREACHED_CACHE (<scratch>/huggingface/hub/models--ibm-granite--granite-embedding-english-r2/snapshots/47ea694b...)` | `tests/test_onnx_pin_repro.py:772-774` (`skipUnless`, message on :774) |
| 8 | `test_onnx_pin_repro.MutantGraphTests.test_one_flipped_initializer_value_is_refused` | `granite onnx artifacts are not under PREACHED_CACHE (or PREACHED_ONNX_DIR)` | `tests/test_onnx_pin_repro.py:651` |
| **Index / corpus** | | | |
| 9 | `test_eval_leak.TitleLeakTest.test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk` | `needs chunks.jsonl or the index sqlite in PREACHED_CACHE` | `tests/test_eval_leak.py:233` |
| **Deno** | none skipped (deno installed) | | |
| **asr-repro clips** | | | |
| 10 | `test_coverage.CorruptedAsrFixtureTests.test_envelope_matches_the_audio` | `needs the clips in PREACHED_CACHE/asr-repro` | `tests/test_coverage.py:291-294` (`skipUnless`; a per-clip `skipTest` is at :301) |
| **Read-only model mount** | none; the guard no longer exists (see below) | | |
| **Wesley index + pinned ONNX (shutdown)** | | | |
| 11 | `test_shutdown.LoadedSigtermTests.test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` | `needs the Wesley index and the pinned ONNX model under PREACHED_CACHE` | `tests/test_shutdown.py:224-225` (`hybrid_load_ready` check, `skipTest(_HYBRID_SKIP)`) |
| **Infra alerts file** | | | |
| 12 | `test_deploy_regex.DeployRegexTests.test_infra_yaml_matches_when_the_file_is_present` | `infra alerts yaml absent (/workspace/infra-ops/preached/alerts/church-alerts.yaml)` | `tests/test_deploy_regex.py:539` |

Totals by source: ONNX export 8, index/corpus 1, asr-repro 1, shutdown 1, infra file 1, deno 0, read-only mount 0, other 0. That is 12.

Other guards that did not fire on this machine, unchanged since `9fe33ca` (files have an empty `git diff 9fe33ca..HEAD`): deno `need_deno` at `tests/test_app_js.py:432-437`, used at `:454` and `:635`; `tests/test_mobile_ux.py:318`; `tests/test_privacy_wire_fix.py:248`; `tests/test_privacy_merge.py:217`.

## Changes vs 9fe33ca

`git diff 9fe33ca..HEAD --stat` for the skip files: only `tests/test_coverage.py` (+10 lines), `tests/test_embed_backend.py` and `tests/test_shutdown.py` changed. `test_onnx_pin_repro.py`, `test_eval_leak.py`, `test_deploy_regex.py`, `test_app_js.py`, `test_mobile_ux.py`, `test_privacy_wire_fix.py` and `test_privacy_merge.py` are unchanged.

- `tests/test_coverage.py` (#78): the guard was `Path("/cache/asr-repro/c01.wav").exists()` and is now `PREACHED_CACHE/asr-repro/c01.wav`. It also gained a per-clip `skipTest` (:301). The decorator is still at :291. On scratch caches this test now skips; at `9fe33ca` it ran against the hard-coded `/cache`.
- `tests/test_shutdown.py` (#78, with the follow-up in `6935b2d`): `REAL_INDEX` and `ONNX_DIR` follow `PREACHED_CACHE`. The `skipUnless` decorator (:173 at `9fe33ca`) became an in-body `hybrid_load_ready` check, with the skip at :224-225. An empty ONNX directory now skips instead of failing. New tests were added: `test_empty_onnx_dir_skips_hybrid_load` and `test_hybrid_load_ready_follows_the_loader_filenames`. On scratch caches the hybrid test now skips.
- `tests/test_embed_backend.py` (#78): the read-only-mount skip (`if not os.access(source.parent.parent, os.W_OK): skipTest("model mount is read-only...")`, :719 in the draft) was removed. The test now copies the graph under the temp dir. Guard lines moved because of that edit: :740 to :757, :1078 to :1095, :1145 to :1162. :658, :708 and :715 are unchanged.
- #79 (nits batch 5) and #80 (listen backlog) touched no skip guard. #84 is not on main (no such merge in `git log 9fe33ca..HEAD`; the log has 18 commits, ending at #80).

## Proposed re-anchor wording (text only, not applied)

Compared with the `9fe33ca` row on `docs/w4-submit-dryrun2` (`0201049:docs/SUBMISSION-DRAFT.md`, line 3 and line 42). Numbers and cites that change if re-anchored to `44dc592`:

- Line 3: `checked at 9fe33ca` becomes `checked at 44dc592`. Re-run the demo queries or keep the `9fe33ca` note, because the demo dry-run (`reports/W4-DEMO-DRYRUN-2.md`) was not re-run here.
- Test count: `1081 ran` becomes `1105 ran`. The "more than 1,000 tests" headline is unchanged.
- Skips: `10 skipped` becomes `12 skipped`. The two new skips are the `tests/test_coverage.py` envelope test and the `tests/test_shutdown.py` hybrid SIGTERM test. Both now follow `PREACHED_CACHE`, so they skip on scratch caches.
- Run line: `Ran 1081 tests in 256.461s`, `OK (skipped=10)` becomes `Ran 1105 tests in 250.534s`, `OK (skipped=12)`. The evidence cell should cite this report, `reports/W5-MAIN-SKIP-CENSUS.md`.
- Cites that move: `tests/test_embed_backend.py` `:740` to `:757`, `:1078` to `:1095`, `:1145` to `:1162`. Unchanged: `:658`, `:708`, `:715`, `tests/test_onnx_pin_repro.py:651`/`:774`, `tests/test_eval_leak.py:233`, `tests/test_deploy_regex.py:539`.
- Move the `tests/test_coverage.py:291` cite and the `tests/test_shutdown.py` cite (`:173` becomes `:225`) out of the "other tests skip only when a source is missing" list and into the scratch-cache skip list. The count list would then read ONNX export 8, index/corpus 1, asr-repro 1, shutdown 1, infra file 1 = 12.
- Delete the read-only model mount sentence (`tests/test_embed_backend.py:719`). That guard no longer exists.
- Drop the sentence "since #78, `tests/test_coverage.py` and `tests/test_shutdown.py` follow `PREACHED_CACHE` ... those last paths were hard-coded at `9fe33ca`, so they did not skip there". It no longer needs a caveat once the anchor is past #78.
- Deno cites (`tests/test_app_js.py:432-437`, `:454`, `:635`; `tests/test_mobile_ux.py:318`; `tests/test_privacy_wire_fix.py:248`; `tests/test_privacy_merge.py:217`) are unchanged.

Suggested row sentence: "Test suite: more than 1,000 tests; 1105 ran, OK, 12 skipped on `44dc592` with scratch caches (...). The 12 skips come from private artifacts absent from those scratch caches: the ONNX export (`tests/test_embed_backend.py:658`, `:708`, `:715`, `:757`, `:1095`, `:1162`; `tests/test_onnx_pin_repro.py:651`, `:774`), the chunked corpus or index (`tests/test_eval_leak.py:233`), the `asr-repro` clips (`tests/test_coverage.py:291`), the Wesley index and the pinned ONNX model (`tests/test_shutdown.py:225`), and an infra alerts file that is not in this repo (`tests/test_deploy_regex.py:539`). Deno tests skip only when deno is missing (...)."

## /cache before/after diff

Snapshot: `find /cache -maxdepth 2 -printf '%p %s %T@\n' | sort`, 297 entries, before and after the run.

One difference:

```
< /cache/index/cc-speech.sqlite-shm 32768 1793493364.3644106800
> /cache/index/cc-speech.sqlite-shm 32768 1793493661.2717475050
```

Same size, mtime moved by about 297 s. The suite ran on scratch caches only, and no test or command in this run opened `/cache`. This is an SQLite shared-memory file, which a live reader of `cc-speech.sqlite` on this host updates on its own. I did not find the writer (`lsof`/`fuser` showed nothing). I am reporting it, not claiming it is unrelated with certainty. No path was added, removed or resized.

## PR BODY

Report only: a fresh suite run and a skip-source census on current `main` (`44dc592`), so the submission docs can later move off the `9fe33ca` anchor.

- `Ran 1105 tests in 250.534s`, `OK (skipped=12)`, on scratch caches (all six cache env vars on fresh temp dirs, `HF_HUB_OFFLINE=1`).
- The 12 skips: ONNX export 8, index/corpus 1, asr-repro 1, shutdown hybrid 1, infra alerts file 1. Deno 0, read-only mount 0 (the guard was removed in #78).
- Since `9fe33ca`: `tests/test_coverage.py` and `tests/test_shutdown.py` now follow `PREACHED_CACHE` (two new skips on scratch caches), the read-only-mount skip is gone, and three `tests/test_embed_backend.py` cites moved (:740 to :757, :1078 to :1095, :1145 to :1162).
- The `9fe33ca` row is on `docs/w4-submit-dryrun2`, not main. The proposed re-anchor text is in the report. No docs were edited.
- `/cache` snapshot: one mtime change on `/cache/index/cc-speech.sqlite-shm`, not caused by this run's commands (see report).

```
 reports/W5-MAIN-SKIP-CENSUS.md | 109 +++++++++++++++++++++++++++++++++++++++++
 1 file changed, 109 insertions(+)
```
