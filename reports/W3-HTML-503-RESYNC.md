# W3-HTML-503-RESYNC: merge origin/main (1777fb1, #71) into PR #77

Branch `fix/w3-html-503`, started clean at `1d45743`. Merge commit, no rebase, no force-push. `app/server.py` logic untouched (the auto-merge brought #71's changes in; I edited only DEPLOY.md and test_deploy_alerts.py).

## Conflicts and how they were resolved (by editing; no --ours/--theirs)

- `tests/test_deploy_alerts.py`: one hunk, the `CITED` tuple. Kept main's (#71) block in full (single-cache knob side, ONNX pin lines `MISSING_GRAPH_LOG`, `SEARCH_MODE_REASONS`, `:1348-1349`, etc.), then re-pinned the server.py cites at or after main's line 2840 by +79 (the lines #77 adds before them). Cites before 2840 are unchanged.
- `docs/DEPLOY.md`: 11 hunks, all cite shifts plus the tree/sha sentence. Kept main's text and applied the same +79 shift; the sentence is now tree-relative ("the merged tree this file ships in (main with ... the ONNX pin fix and the HTML 503 page)"). The #77 Connections row (HTML 503, `*/*`, `text/*`, q=0 notes) merged without conflict and is kept.

## Cites re-pinned (old on main -> new in merged tree; text read in app/server.py)

| Old | New | Line text |
| --- | --- | --- |
| 2840 | 2919 | `logging.info("listening on http://%s:%s", host, port)` |
| 2844 | 2923 | `app.log_startup_pause()` |
| 2912 | 2991 | `logging.error("church side refused: %s", problem)` |
| 2919 | 2998 | `logging.error("church side refused: %s", exc)` |
| 2930 | 3009 | `logging.error("church side refused: %s", problem)` |
| 2937 | 3016 | `logging.info("church side: %s, read-only, through the publish gate", slug)` |
| 3099 | 3178 | `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")` |
| 3277 | 3356 | `logging.info("stopping")` |
| 3278-3296 | 3357-3375 | `stuck = server.drain()` ... `raise SystemExit(1)` |
| 3282 | 3361 | `"%d handler thread(s) still running after %.0fs; index left open"` |
| 3292 | 3371 | `app.church_connection.close()` |
| 3294 | 3373 | `logging.info("stopped cleanly")` |

All other cited lines (238 ... 2404, library.py, build-bundle.sh, etc.) hold unchanged; `test_every_cited_file_line_holds_its_string` and `test_the_runbook_cites_exactly_the_pinned_lines` pass.

## Audit

`git diff origin/main..HEAD -- docs/DEPLOY.md tests/test_deploy_alerts.py` shows only: the 12 cite shifts above (DEPLOY.md prose and tables), the reworded tree sentence, and the #77 Connections row. No #71 hunk is lost.

## Tests

`PREACHED_REQUIRE_DENO=1 uv run python -m unittest discover -s tests`, all caches (UV_CACHE_DIR, PREACHED_CACHE, PREACHED_ONNX_DIR, HF_HOME, DENO_DIR, XDG_CACHE_HOME) in a temp dir: **Ran 1081 tests, OK (skipped=10)**. No test_shutdown hybrid-load failure was seen.

## Cache safety

`find /cache -xdev -printf '%p\t%s\t%T@\n'` before and after (sorted, 132645 entries each): one difference, the mtime of `/cache/index/cc-speech.sqlite-shm` (1793487200 -> 1793487684). Nothing of mine pointed at /cache, so that is another process using that index.

## Diff stat (origin/main..HEAD)

```
 app/server.py               |  87 +++++++++++++-
 docs/DEPLOY.md              |  38 +++---
 reports/W3-HTML-503-R2.md   | 174 +++++++++++++++++++++++++++
 reports/W3-HTML-503.md      |  94 +++++++++++++++
 tests/test_deploy_alerts.py |  24 ++--
 tests/test_html_503.py      | 287 ++++++++++++++++++++++++++++++++++++++++++++
 6 files changed, 669 insertions(+), 35 deletions(-)
```
Plus this report.

## PR BODY

PR #77: over the connection cap, a browser (`Accept` naming `text/html` with nonzero weight) gets a static HTML 503 page with a 1 s meta refresh; everyone else, including `*/*`, `text/*` and `text/html;q=0`, still gets the JSON body. The accept thread reads only already-buffered bytes and never waits (r2 MF1), q=0 is not acceptable (MF2), and the parser and read paths are tested (S1, 20 tests in `tests/test_html_503.py`).

Resync: merged main `1777fb1` (#71). The conflicts in `docs/DEPLOY.md` and `tests/test_deploy_alerts.py` were resolved by editing, keeping #71 and #77 both; the server.py cites at or after old line 2840 moved +79 and are re-pinned (list in the report); the tree sentence is tree-relative. Full suite with temp caches: 1081 tests OK, 10 skipped. Real /cache listing unchanged except one live `-shm` mtime from another process. `app/server.py` logic not changed by the resync.

Diff stat (origin/main..HEAD): app/server.py, docs/DEPLOY.md, tests/test_deploy_alerts.py, tests/test_html_503.py, reports/W3-HTML-503.md, reports/W3-HTML-503-R2.md, plus reports/W3-HTML-503-RESYNC.md.
