# W3-ONNX-NITS: CTO #26 r2 + r3 follow-ups

Branch `chore/w3-onnx-nits`, from origin/main (eb4d48a; includes #26, #31, #32, #33). PR #26 was merged, so the precondition holds.

## Item map

| Item | Change | Test |
|---|---|---|
| 1 FunctionProto attribute defaults | `onnx_embed.py`: `"function": {7: "node", 11: "attribute"}` | `test_external_data_in_a_function_is_refused` (field 7 and field 11, plus a clean field-11 tensor accepted) |
| 2 five untested refusals | tests only | `test_missing_proc_self_fd_is_refused`, `test_nesting_past_the_limit_is_refused`, `test_external_data_in_a_function_is_refused` (field 25), `test_external_data_in_a_sparse_initializer_is_refused` (field 15; values and indices), `test_trailing_partial_field_is_refused` |
| 3 FIFO test hang | daemon thread, `join(timeout=5)`, fail if alive (releases the blocked open first) | `test_fifo_at_the_graph_path_is_refused_without_hanging` |
| 4 read-only model mount | skip when `source.parent.parent` is not writable | `test_fp32_directory_without_int8_loads` |
| 5 DEPLOY.md owner/mode note | docs/DEPLOY.md: root-or-service-uid, 0755 or stricter, else BM25 only; pre-cutover check is `/healthz` `dense: true` | docs only |
| S1 sentinel digest | load test wraps `_open_hashed_graph` to return a sentinel; asserts `model_sha256 == sentinel` | `test_load_reports_the_sha256_of_the_graph_it_loaded` |
| S2 `VerifiedArtifacts.digests` | dropped (nothing read it) from `artifacts.py` | existing manifest tests |
| S3 wrong umask example | DEPLOY.md now names an rsync/cp of a checkout made under umask 002, and says build-bundle.sh tars are unaffected | docs only |
| S4 build-bundle "file changed as we read it" | No change needed: main already tars a private full-copy snapshot (commit 56ffbf7, `scripts/build-bundle.sh`). | none |

## Mutation results (item 2, plus 1, 3, S1)

Each check removed or broken in `onnx_embed.py`, full `tests.test_embed_backend` run, then restored.

| Mutation | Result |
|---|---|
| remove `/proc/self/fd` check | FAIL: `test_missing_proc_self_fd_is_refused` |
| remove nesting limit | FAIL: `test_nesting_past_the_limit_is_refused` |
| drop `25: "function"` | FAIL: both field subtests of the function test |
| drop `15: "sparse"` | FAIL: both field subtests of the sparse test |
| remove trailing `pos != end` check | FAIL: `test_trailing_partial_field_is_refused` |
| item 1: drop `11: "attribute"` | FAIL: function test, `attribute_proto` subtest |
| item 3: drop `O_NONBLOCK` | FAIL after 5 s (no hang) |
| S1: report the manifest digest as `model_sha256` | FAIL |

## Verification

- `tests/test_embed_backend.py`: 55 tests, OK (was 49 on the reviewed head; +5 new, +1 from main).
- Full suite (`unittest discover -s tests`): 733 tests, OK.
- `uv lock --check`: passes (79 packages resolved, no new deps).
- Head SHA of the code commit: bea4ad2626fecc617fa1b18c0e73299898d26cc6 (the report is committed on top).

## PR

`gh` is not installed in this sandbox, so the branch is pushed and the PR is not opened. Title to use: "W3: ONNX loader follow-ups (CTO #26 r2+r3)".
