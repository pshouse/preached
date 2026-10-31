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
```
 AGENTS.md                         |  8 +++++++-
 reports/W3-DEPLOY-REGEX-PIN.md    |  2 +-
 reports/W5-BENCH-FAILCLOSED-R2.md |  4 ++--
 reports/W5-NITS-BATCH5.md         | 29 +++++++++++++++++++++++++++++
 search/bench.py                   |  5 +++--
 5 files changed, 42 insertions(+), 6 deletions(-)
```
(The report itself is part of the stat; it is the head commit.)
