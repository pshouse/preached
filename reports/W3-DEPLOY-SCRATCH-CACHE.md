# W3-DEPLOY-SCRATCH-CACHE

Branch `docs/w3-deploy-scratch-cache` from `origin/main` `44dc592` (PR #80). Clean tree before the edit. Historical reports are unchanged. No `app/` change.

## What was done

1. `docs/DEPLOY.md` local smoke test no longer runs the suite with `PREACHED_CACHE=/cache`. The documented command is `PREACHED_REQUIRE_DENO=1` and `HF_HUB_OFFLINE=1`, with `mktemp -d` directories for `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME` and `UV_CACHE_DIR`. One sentence: only the host verify-merge gate runs the suite against the real `/cache`; when a test needs real data, use a read-only copy or a read-only bind mount.
2. One paragraph in the Index section (the read-only index text that was at lines 347-350): serving the WAL-mode `/cache` index straight from a checkout on a read-only mount is unsupported; use `copy_index` (it copies the index with the SQLite backup API and switches the copy to rollback-journal (`DELETE`) mode, so it can be served from a read-only directory; the source is opened read-only and is not checkpointed) for that. Never use `immutable=1` (it gives silent stale reads and missed reloads). Step 4 (lines 128-130) still says a DELETE-mode bundle index may be mounted read-only. That sentence is not repeated there.

`copy_index` (`scripts/bundle_manifest.py`) opens the source with `open_readonly` (`mode=ro`), copies with the backup API, and sets `journal_mode=DELETE` on the copy. A temp WAL source with `wal_autocheckpoint=0` kept its `-wal` size and mtime; the copy was `delete`, had no `-wal`, and held the row that existed only in the source WAL. The live file is not rewritten.

## DEPLOY cites (rule 4)

No cited file changed (`app/server.py`, `scripts/build-bundle.sh`, `src/preached/library.py`, `src/preached/youtube/library.py`, `src/preached/youtube/pipeline.py`). No `file:line` cite in `docs/DEPLOY.md` moved, and this edit adds none, so no `CITED` pin in `tests/test_deploy_alerts.py` moved. The tree sentence is already tree-relative and was left as written. Read at `docs/DEPLOY.md` after the edit: "The line numbers below are this tree: the merged tree this file ships in (main plus the listen backlog change), in `app/server.py`. Each `app/server.py` cite was read off that file." Those line numbers are `app/server.py` lines. This PR does not edit that file, so they still hold on the tree the sentence names.

`tests.test_deploy_alerts` reads each pinned line: `Ran 7 tests in 0.273s`, `OK`, including `test_every_cited_file_line_holds_its_string` and `test_the_runbook_cites_exactly_the_pinned_lines`. The full suite below includes that test again. Zero `test_every_cited_file_line_holds_its_string` failures.

## How to run

```bash
PREACHED_REQUIRE_DENO=1 \
HF_HUB_OFFLINE=1 \
PREACHED_CACHE=$(mktemp -d) \
PREACHED_ONNX_DIR=$(mktemp -d) \
HF_HOME=$(mktemp -d) \
DENO_DIR=$(mktemp -d) \
XDG_CACHE_HOME=$(mktemp -d) \
UV_CACHE_DIR=$(mktemp -d) \
uv run python -m unittest discover -s tests
```

The run below used one scratch directory under `tempfile.gettempdir()` (`/tmp/w3scratch-suite.QMrowE`) and pointed those six variables, plus `HUGGINGFACE_HUB_CACHE`, `SENTENCE_TRANSFORMERS_HOME` and `TORCH_HOME`, at subdirectories of it. Each path was resolved and checked to sit under `/tmp` and not under `/cache`. The ambient shell has `HF_HOME=/cache/huggingface`, `UV_CACHE_DIR=/cache/uv` and `XDG_CACHE_HOME=/cache/xdg`; the command overrides them. `UV_PYTHON_INSTALL_DIR` stayed `/cache/uv-python` (the interpreter install, not a suite cache).

## Results

`PREACHED_REQUIRE_DENO=1 uv run python -m unittest discover -s tests` with the caches above and `HF_HUB_OFFLINE=1`:

**Ran 1105 tests in 253.258s, OK (skipped=12).** 0 failures, 0 errors. 0 `test_every_cited_file_line_holds_its_string` failures.

## Cache safety

Snapshot: `find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`, before any test command and after the full suite.

| | lines |
|---|---|
| before | 132722 |
| after | 132732 |

Paths only before: 0. Paths only after: 10. Paths whose size or mtime changed: 11.

The 10 new paths and 10 of the changes are Claude CLI MCP logs under `/cache/xdg/claude-cli-nodejs/-work-preached/mcp-logs-claude-ai-*` (new `2026-11-01T00-44-*.jsonl` files, and the `2026-11-01T00-40-41-576Z.jsonl` files plus their directories grew). This suite set `XDG_CACHE_HOME` to `/tmp/w3scratch-suite.QMrowE/xdg`. The new and grown files are Claude CLI MCP logs from before the lockout (the CLI's ambient XDG_CACHE_HOME), not from the suite, which used a scratch XDG_CACHE_HOME.

The other change is `/cache/index/cc-speech.sqlite-shm`: size stayed 32768, mtime `1793493661.2717475050` to `1793494112.2371121840`. That mtime-only change is benign. Nothing under `/cache/uv`, `/cache/huggingface`, or the other index files changed. This run never set a cache variable to `/cache` and did not open that index on purpose. The same shm mtime moved in the listen-backlog report while that suite also used temp caches.

No destructive call was made against `/cache`.

## PR BODY

Document the suite on scratch caches, and say a WAL-mode `/cache` index is not served straight from a checkout on a read-only mount.

- The pre-deploy suite command uses `mktemp -d` for `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME` and `UV_CACHE_DIR`, plus `HF_HUB_OFFLINE=1` and `PREACHED_REQUIRE_DENO=1`. Only the host verify-merge gate runs the suite against the real `/cache`. A test that needs real data uses a read-only copy or a read-only bind mount.
- The Index section: that WAL checkout on a read-only mount is unsupported. Use `copy_index` (backup API, copy converted to `journal_mode=DELETE`). Never use `immutable=1` (silent stale reads and missed reloads).
- No cited source line moved. `CITED` pins and the tree sentence stay. The tree sentence is already tree-relative ("the merged tree this file ships in").

Full suite on temp caches: **Ran 1105 tests in 253.258s, OK (skipped=12)**. 0 `test_every_cited_file_line_holds_its_string` failures. `/cache` listing: 132722 lines before, 132732 after. The new and grown files are Claude CLI MCP logs from before the lockout (the CLI's ambient XDG_CACHE_HOME), not from the suite, which used a scratch XDG_CACHE_HOME. The `/cache/index/cc-speech.sqlite-shm` mtime-only change (size unchanged) is benign.

```
 docs/DEPLOY.md                     | 25 +++++++++--
 reports/W3-DEPLOY-SCRATCH-CACHE.md | 89 ++++++++++++++++++++++++++++++++++++++
 2 files changed, 110 insertions(+), 4 deletions(-)
```

## R2 (CTO CHANGES at b8db842)

CTO review of PR #87 at `b8db842` asked for these doc changes. No code change. No tests were run.

| Item | Change |
|---|---|
| MF1 | `docs/DEPLOY.md` no longer says `copy_index` checkpoints. The parenthetical is: it copies the index with the SQLite backup API and switches the copy to rollback-journal (`DELETE`) mode, so it can be served from a read-only directory; the source is opened read-only and is not checkpointed. The same wording replaces the checkpoint claim in "What was done" item 2. Re-read on this tree: `copy_index` is `scripts/bundle_manifest.py:53`; `scripts/build-bundle.sh:155` calls it. The function opens the source with `open_readonly_or_exit` (`mode=ro`, `query_only` via `open_readonly`), copies with `Connection.backup`, and sets `PRAGMA journal_mode=DELETE` on the copy. `scripts/bundle_manifest.py:70-72` says the backup cannot checkpoint or write the live index. `wal_autocheckpoint=0` in the probe note is the source setup, not a claim that `copy_index` checkpoints. |
| Rule 4 | No cited source file changed. No `file:line` cite in `docs/DEPLOY.md` moved, and this edit adds none, so no `CITED` pin in `tests/test_deploy_alerts.py` moved. The tree sentence stays: "the merged tree this file ships in (main plus the listen backlog change), in `app/server.py`." Those numbers are `app/server.py` lines. This PR does not edit that file. |
| MF2 | Deleted "Those logs are another process on the host" and every "another process" attribution in this report. The cache-diff paragraph and the PR-body suite line now say the new and grown files are Claude CLI MCP logs from before the lockout (the CLI's ambient XDG_CACHE_HOME), not from the suite, which used a scratch XDG_CACHE_HOME. The `/cache/index/cc-speech.sqlite-shm` change is mtime only and is benign. |

`git diff --stat origin/main...HEAD` (also the block under PR BODY, refreshed to this output):

```
 docs/DEPLOY.md                     | 25 +++++++++--
 reports/W3-DEPLOY-SCRATCH-CACHE.md | 89 ++++++++++++++++++++++++++++++++++++++
 2 files changed, 110 insertions(+), 4 deletions(-)
```
