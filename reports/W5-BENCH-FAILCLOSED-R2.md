# W5-BENCH-FAILCLOSED-R2

CTO r1 on PR #76 (42f0f83) asked for changes. This round fixes MF1-MF4, S1 and S2.

## What changed
- **MF1** `fail_closed` now prints the `--allow-bm25-only` warning to stderr. Tests assert it is in stderr and absent from stdout.
- **MF2** `test_model_load_failure_exits_nonzero` asserts `r.json` exists and records the model as `error`. The allow test asserts the recorded status is not `ok`.
- **MF3** `test_gated_model_still_fails_closed` raises `OSError("401 gated repo")`. It asserts exit 1, `skipped_gated`, the model key and `--allow-bm25-only` in stderr, and `skipped_gated` in the report.
- **MF4** Abstain tests: failure exits 1 after the report is written, gated is recorded as plain `error` and still exits 1, and `--allow-bm25-only` exits 0 with the warning on stderr.
- **S1** The README and the `bench.py` docstring name both statuses, say gated still fails, and say `--abstain` records gated as plain `error`.
- **S2** Tested: `test_abstain_write_calibration_leaves_failed_model_entry_untouched` seeds a temp `abstain.toml` with an entry for the failing model. After `--abstain --write-calibration` exits 1, the file is byte-identical. Only models that finish `ok` are upserted, so failed models keep their old entries. A hand-edited file is still rewritten in canonical form (comments and ordering normalised), because `abstain.toml` is regenerated from the parsed entries.

## Mutants (temporary, reverted; `git diff` shows only the intended changes)
| Mutant | Result |
|---|---|
| baseline | 8 tests OK |
| MF1 warning back to stdout | killed: `test_allow_bm25_only_proceeds_with_loud_warning`, `test_abstain_allow_bm25_only_warns_on_stderr` |
| M2 `fail_closed` before the writes in `main()` | killed: `test_model_load_failure_exits_nonzero`, `test_gated_model_still_fails_closed` (both error, no `r.json`) |
| M3 `skipped_gated` treated as ok | killed: `test_gated_model_still_fails_closed` |
| M5 `fail_closed` removed from `run_abstain` | killed: 4 abstain tests |

## Verification
- Full suite: `PREACHED_REQUIRE_DENO=1`, `/cache` bind-mounted read-only inside a user namespace, with temp `PREACHED_CACHE`, `HF_HOME`, `PREACHED_ONNX_DIR`, `UV_CACHE_DIR`, `XDG_CACHE_HOME` and `TORCH_HOME`. Result: **Ran 1013 tests, OK (skipped=8)**. No `test_every_cited_file_line_holds_its_string` failures.
- `app/server.py` and the files cited in `docs/DEPLOY.md` are untouched, so no DEPLOY.md re-pin was needed.
- Cache snapshot (`find /cache -printf '%p %s %T@'`) before and after: 32 diff lines, all in files other agents write concurrently. They are `index/cc-speech.sqlite-shm`, the `models` directory mtime, the `xdg/Microsoft/.../onnxruntime.db` `-shm` and `-wal` files (sizes unchanged), and the `xdg/deno/dep_analysis_cache_v2` `-shm` and `-wal` files. My runs mounted `/cache` read-only, so these are not from my runs, and no paths were added or removed by them.
- The new tests only touch temp dirs. The abstain calibration path is patched to a temp file.

## Diff stat (base abdada3..HEAD, in-scope files only)
```
 README.md                         |   2 +
 reports/W5-BENCH-FAILCLOSED-R2.md |  36 ++++++++
 search/bench.py                   |  25 ++++++
 tests/test_bench_failclosed.py    | 167 ++++++++++++++++++++++++++++++++++++++
 4 files changed, 230 insertions(+)
```
Head sha: see the PR (this report is part of the head commit).
