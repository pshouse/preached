# W3-DEPLOY-REGEX-PIN

`tests/test_deploy_regex.py` pins every backticked `^...$` in `docs/DEPLOY.md` to a line the app emits. Round 2 addresses the CTO review on `86e4ef8`. `origin/main` (including #72) is merged as `2ca1206`. No rebase.

## Anchors (MF1)

Table rows are keyed by the alert id in the first cell (`D2b`, `stamp`). Prose is keyed by a marker beside the pattern, not by a line number. The side-access line in `docs/DEPLOY.md` is:

`^INFO \S+ \S+ GET /api/side 200$` `<!-- regex: side-access -->`

The marker is on that same line, so no later line moved. No `app/server.py` cite moved, and no CITED pin in `tests/test_deploy_alerts.py` changed. `test_every_cited_file_line_holds_its_string` and `test_the_runbook_cites_exactly_the_pinned_lines` passed in the full suite. Unknown anchors still fail with `no producer`.

`ERROR ONNX GRAPH NOT BUILT` is not a `^...$` pattern on `origin/main`. No producer was added for it.

## Logging capture (MF2, MF3)

`capture_root_formatter()` runs the real `logging.basicConfig`, then stops. It reads the formatter on the one root `StreamHandler` (format, style, datefmt) and rejects any other handler. Records are rendered with `logging.Formatter.format`, so asctime is filled when the format uses it; the alert comparison uses the first line only. `os.environ` is wrapped in `patch.dict`. `CUDA_VISIBLE_DEVICES=""` does not leak. `HF_HOME`, `PREACHED_CACHE`, `PREACHED_ONNX_DIR` and `TMPDIR` for that call are a temp directory. Startup names (`parse_args`, `App.__init__`, `open_readonly`, `build_app`, `make_server`, and the other index/model/port calls) raise `basicConfig not reached first` if `main()` reaches them.

Nit, accepted: `side_access_line` sets `_client_key`, so `log_request` takes `_log_key()`'s early return and does not read `X-Forwarded-For`. The line is still the real `log_request` format.

## Parser (MF4)

Paragraph lines are joined before backtick matching, so a wrapped `^...$` is one pattern. A backtick token that starts with `^` and has no `$` is a failure, not a skip. The expected names are exactly `D2b`, `stamp`, `side-access`.

Infra check: `test_infra_yaml_matches_when_the_file_is_present` compares those regexes to `pattern` / `evidence_pattern` when `church-alerts.yaml` is present (`PREACHED_INFRA_ALERTS` or `/workspace/infra-ops/preached/alerts/church-alerts.yaml`). A loosened regex passes wherever the infra yaml is absent.

## Proofs

Trial-merge of `86e4ef8` with `origin/fix/w3-keepalive-cap` (#72), scratch tree `5788f83`, not this branch. Clean merge. The side pattern is on line 821. With the marker and this test file, `tests.test_deploy_regex`: Ran 10 tests, OK (skipped=1; the infra-yaml check on a machine where the file is absent). A loosened regex passes wherever the infra yaml is absent.

The previous test, pointed at #72's `DEPLOY.md`, fails:

`no producer for DEPLOY.md pattern DEPLOY.md:821: add one, do not skip it`

Blank line inserted at the top of a scratch copy of that merged `DEPLOY.md`: Ran 10 tests, OK (skipped=1; the infra-yaml check on a machine where the file is absent). A loosened regex passes wherever the infra yaml is absent. Names stay `side-access`, `D2b`, `stamp`.

Marker removed from a scratch copy:

`no producer for DEPLOY.md pattern '^INFO \S+ \S+ GET /api/side 200$': prose ^...$ has no <!-- regex: name --> anchor; add one, do not skip it`

D9, a wrapped extra pattern. The old per-line scanner still sees 3 patterns (the wrap is invisible). This test fails:

`no producer for DEPLOY.md pattern wrapped-d9: add one, do not skip it`

and the pinned set gains `wrapped-d9`.

D10, a backtick `` `^INFO no dollar` ``. The old scanner still sees 3 patterns. This test fails:

`backticked pattern starts with ^ but has no $: '^INFO no dollar'`

S11, a root `StreamHandler` with `%(levelname)s: %(message)s` added before `basicConfig`:

`logging setup mismatch: format '%(levelname)s: %(message)s' != basicConfig format '%(levelname)s %(message)s'`

Reorder mutant: `logging.basicConfig` moved to just after `open_readonly` inside `main`. The test fails with `basicConfig not reached first`. The real `open_readonly` was not called.

Checked lines: `side-access` <- `'INFO 203.0.113.9 203.0.113.9 GET /api/side 200'`; `D2b` <- `'ERROR index status unreadable after reload; serving BM25 only'`; `stamp` <- `'ERROR could not read the index stamp'`.

## Cache

Snapshots are path, size, mtime. Regex and mutant runs set `PREACHED_CACHE`, `PREACHED_ONNX_DIR` and `HF_HOME` to temp dirs (`HF_HUB_OFFLINE=1`, `PYTHONDONTWRITEBYTECODE=1`). The full suite is the required command, which sets `PREACHED_CACHE=/cache`.

Across that suite (before 132572 entries, after 132572): no path added or removed. Changes:

- `/cache/index/cc-speech.sqlite-shm` mtime only (size 32768). `cc-speech.sqlite` itself was unchanged.
- `/cache/models` directory mtime only. No child path was added, removed, or resized.
- `/cache/xdg/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db-shm` and `onnxruntime.db-wal` mtimes only (wal size stayed 4120032).
- `/cache/xdg/deno/` analysis and v8 code-cache shm/wal mtimes; `dep_analysis_cache_v2-wal` 997072 -> 1124792 bytes; `v8_code_cache_v2-wal` 1713952 -> 2113592 bytes. `PREACHED_REQUIRE_DENO=1` runs deno, and `XDG` cache on this machine is under `/cache/xdg`.

Earlier in the session, before the suite, the same shm files and Claude MCP logs under `/cache/xdg/claude-cli-nodejs` moved. Those logs are not written by this test file.

## Full suite

`PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`

Ran 1021 tests in 262.657s. OK. 0 failures, 0 errors. The skipped=1 on that run is `test_infra_yaml_matches_when_the_file_is_present`, on a machine where the infra yaml is absent. A loosened regex passes wherever the infra yaml is absent.

## Diff vs origin/main

`git diff --stat origin/main...HEAD`

```
 docs/DEPLOY.md                 |   2 +-
 reports/W3-DEPLOY-REGEX-PIN.md |  87 +++++++
 tests/test_deploy_regex.py     | 535 +++++++++++++++++++++++++++++++++++++++++
 3 files changed, 623 insertions(+), 1 deletion(-)
```
