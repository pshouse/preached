# W5-NITS-BATCH5

Docs/help nits from CTO reviews of #69, #70, #75, #76. Branch `chore/w5-nits-batch5` from `origin/main` 97537ae. No behaviour change.

| # | Item | File | Status |
|---|---|---|---|
| 1 | Mirror standing rules 4 (extended DEPLOY cites), 5 (cache safety), 6 (merge conflicts) | `AGENTS.md` new "Standing process rules" before section 7 | Done; AGENTS.md had none of them |
| 2 | PREACHED_REQUIRE_DENO sentence | `AGENTS.md:53` | Done. Overstated: the flag is read directly at `tests/test_app_js.py:429` and `tests/test_mobile_ux.py:309`, and via `need_deno` at `tests/test_app_js.py:454`, `:635`, `tests/test_privacy_merge.py:217`, `tests/test_privacy_wire_fix.py:248`. Other deno-using tests do not read it. Reworded to "the deno-backed tests that honor it" and named the four files |
| 3 | Machine-specific "skips" claim | `reports/W3-DEPLOY-REGEX-PIN.md:25` | Done: now "A loosened regex passes wherever the infra yaml is absent." |
| 4 | Diff stat | `reports/W5-BENCH-FAILCLOSED-R2.md:31-34` | Done. `git diff --stat 97537ae^1..97537ae`: README +2, report +36, bench.py +25, test +167, 4 files, 230 insertions. Report had 29 / 223 |
| 5 | Hand-edited abstain.toml rewritten canonically | `search/bench.py` docstring (~l.33) and `--write-calibration` help (~l.951) | Done, text only |
| 6 | PR76 BODY | below | Done |

## Verification
- Full suite (`PREACHED_REQUIRE_DENO=1`, `/cache` bind-mounted read-only in a user namespace, temp `PREACHED_CACHE`, `HF_HOME`, `PREACHED_ONNX_DIR`, `UV_CACHE_DIR`, `XDG_CACHE_HOME`, `TORCH_HOME`): **Ran 1030 tests, OK (skipped=9)**. The skips come from the read-only/temp cache (no ONNX artifacts).
- `uv lock --check`: Resolved 79 packages, OK.
- `/cache` snapshot (`find /cache -printf '%p %s %T@'`) before and after: **0 differing lines**.
- No DEPLOY.md, README.md, app/server.py or tests/test_deploy_alerts.py edits.

## PR76 BODY
Fail closed in `search/bench.py` when a model fails to load or score.

- `bench.py` writes the report, then exits 1 if any selected model has status `error` or `skipped_gated`. `--allow-bm25-only` exits 0 and prints a warning on stderr. Gated failures still fail. Under `--abstain` a gated failure is recorded as plain `error` and still exits 1.
- S2: with `--abstain --write-calibration`, only models that finish `ok` are upserted. A failed model keeps its old `abstain.toml` entry (the file stays byte-identical in the test). A hand-edited file is still rewritten in canonical form.
- Tests: `tests/test_bench_failclosed.py`, 8 tests (counted on main).
- Files: 4 files, +230 (`README.md` +2, `reports/W5-BENCH-FAILCLOSED-R2.md` +36, `search/bench.py` +25, `tests/test_bench_failclosed.py` +167), verified with `git diff --stat 97537ae^1..97537ae`.
- Full suite at the PR head: 1013 tests, OK (skipped=8), per `reports/W5-BENCH-FAILCLOSED-R2.md`; not re-run at that head. Main at 97537ae is now 1030 tests, OK (skipped=9) (read-only cache, temp env).

## Diff stat

`git diff --stat origin/main...HEAD` (this report is part of the head commit):

```
 AGENTS.md                         |   8 ++-
 reports/W3-DEPLOY-REGEX-PIN.md    |   8 +--
 reports/W5-BENCH-FAILCLOSED-R2.md |   4 +-
 reports/W5-NITS-BATCH5.md         | 119 ++++++++++++++++++++++++++++++++++++++
 search/bench.py                   |   5 +-
 5 files changed, 135 insertions(+), 9 deletions(-)
```

## R2

CTO r1 on `54708f3` (PR #79) is CHANGES. `git fetch && git merge origin/main` was already up to date (`97537ae`). No rebase and no force-push. This round edits only `AGENTS.md`, `reports/W3-DEPLOY-REGEX-PIN.md`, and this report.

Head: the commit that adds this section (`git rev-parse HEAD` on `chore/w5-nits-batch5`). A report cannot name its own commit. Parent of this round: `54708f3`. Ahead/behind vs `origin/main`: 3 ahead, 0 behind.

### MF1

`AGENTS.md` cache safety no longer says "for any output" or "the real cache may only be read". Test and mutant runs never point `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, or `HF_HOME` at a real cache (temp dirs only). Reading private data stays possible through an explicit read-only copy or bind mount.

### MF2

Section 7 item 2 no longer prescribes `PREACHED_CACHE=/cache`. The full-suite command is `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=$(mktemp -d) HF_HOME=$(mktemp -d) PREACHED_ONNX_DIR=$(mktemp -d) HF_HUB_OFFLINE=1 uv run python -m unittest discover -s tests`. The only suite run against the real `/cache` is CoS's host verify-merge gate (with its CACHE: CLEAN check); agents must not copy that gate command.

### S1

`reports/W3-DEPLOY-REGEX-PIN.md` lines 29, 35, and 76 no longer state `skipped=1` as a general result. Each says the skip on that run was the infra-yaml check on a machine where the file was absent, and that a loosened regex passes wherever the infra yaml is absent. Line 25 already said that. Line 29 was the same bare `skipped=1` and was fixed with the two the review named.

### S2

The diff stat in the section above is `git diff --stat origin/main...HEAD` after this commit. This round's in-scope diff (`54708f3...HEAD`) is only the three files named above. The branch also carries `reports/W5-BENCH-FAILCLOSED-R2.md` and `search/bench.py` from `ff9ec01`.

In-scope stat for this round (`git diff --stat 54708f3...HEAD`):

```
 AGENTS.md                      |  4 +-
 reports/W3-DEPLOY-REGEX-PIN.md |  6 +--
 reports/W5-NITS-BATCH5.md      | 95 ++++++++++++++++++++++++++++++++++++++----
 3 files changed, 93 insertions(+), 12 deletions(-)
```

### Proof

`uv lock --check`: Resolved 79 packages in 0.54ms. OK.

Full suite, temp caches, `PREACHED_REQUIRE_DENO=1`, `HF_HUB_OFFLINE=1`. Also temp: `UV_CACHE_DIR`, `XDG_CACHE_HOME`, `TORCH_HOME`, `HUGGINGFACE_HUB_CACHE`, `SENTENCE_TRANSFORMERS_HOME`. The process ran under `bwrap` with uid 1000, `/cache` read-only, and `/cache/index` an empty read-only bind, so `serve.sh` did not see uid 0 and the hardcoded Wesley index was not opened. A touch of `/cache/models` inside the sandbox was refused (read-only file system).

Ran 1030 tests in 241.921s. OK (skipped=9). 0 failures, 0 errors.

Skips:

1. `test_deploy_regex.DeployRegexTests.test_infra_yaml_matches_when_the_file_is_present` — infra alerts yaml absent.
2. `test_embed_backend.FdLoadTests.test_load_refuses_a_symlinked_graph` — granite ONNX artifacts not in the temp `PREACHED_ONNX_DIR`.
3. `test_embed_backend.FdLoadTests.test_real_graph_has_no_external_data` — same.
4. `test_embed_backend.ImportGuardTests.test_youtube_embed_path_does_not_import_torch` — same.
5. `test_embed_backend.RealOnnxTests.test_cached_fp32_and_tokenizer_match_the_pins` — same.
6. `test_embed_backend.RealOnnxTests.test_fp32_directory_without_int8_loads` — same.
7. `test_embed_backend.RealOnnxTests.test_fp32_query_is_unit_normalized` — same.
8. `test_eval_leak.TitleLeakTest.test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk` — chunks not in the temp `PREACHED_CACHE`.
9. `test_shutdown.LoadedSigtermTests.test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` — real index not visible and the ONNX dir was empty.

No `test_every_cited_file_line_holds_its_string` failure. `app/server.py` and `docs/DEPLOY.md` were not edited, so no cite re-pin.

### Cache

Snapshots are `find /cache -printf '%p %s %T@'`, sorted. The proof run: before 132629 paths, after 132645. Added 16, removed 0, changed 31 (mtime or size). The sandbox could not write `/cache`. The new paths are `/cache/uv/archive-v0/fRYLND4_rKUqexYe/` (editable `preached` wheel), `/cache/uv/sdists-v10/editable/...`, and five Claude MCP logs under `/cache/xdg/claude-cli-nodejs/-work-preached/`. Size changes also hit `/cache/venvs/demo-main/.../METADATA`, the deno `dep_analysis_cache_v2-wal` and `v8_code_cache_v2-wal`, and directory counts under `uv` and those log dirs. Mtime-only: `/cache/demo-kill`, `/cache/index/wesley.sqlite-shm`, `/cache/uv` and `builds-v0`, several `demo-main` dist-info files, onnxruntime `db-shm`/`db-wal` (wal size stayed 4120032), and deno shm files. Those are other writers on the host during the run. This process's `UV_CACHE_DIR` and `XDG_CACHE_HOME` were temp dirs, and `/cache` was read-only.

An earlier `unshare --map-root-user` attempt was killed because uid 0 makes `serve.sh` refuse to start. Its snapshot (before 132629, after 132629) added nothing. Mtime-only: `cc-speech.sqlite-shm`, the `models` directory, and onnxruntime `db-shm`/`db-wal`.

### Other `PREACHED_CACHE=/cache` test commands

Fixed only the one in `AGENTS.md`. Left as written:

- `docs/DEPLOY.md:284` — `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`
- `docs/SUBMISSION-DRAFT.md:42` — same command, historical 998-test run
- `reports/W3-DEPLOY-REGEX-PIN.md:61` and `:74` — the command that report ran
- `reports/W3-NITS-BATCH.md:68` and `:100`
- `reports/W3-DENO-HARDFAIL-PORTBUSY.md:39`
- `reports/W3-KEEPALIVE-CAP.md:12` (server), `:78` (one module), `:112`, `:164` (suite)
- `reports/W3-DEPLOY-REQUIRE-DENO.md:6` and `:11`
- `reports/14-W3-DEPLOY-AFTER51.md:32`, `:38`, `:83`, `:90`
- `reports/W4-SUBMIT-POST63.md:34` (suite). `:11` is a server, not the suite
- `reports/W4-SUBMIT-FINAL-PASS.md:11` and `:61`
- `reports/W3-SQLITE-DOC-NIT.md:10`
- `reports/W3-LABEL-NITS.md:5` and `:11`
- `reports/W3-CONFIRMATORY.md:25`, `:28`, `:193`, `:200`, `:209`

`reports/W4-FRESH-CLONE-QA.md:11` uses `PREACHED_CACHE=/cache/fresh-clone-qa`, not `/cache`.
