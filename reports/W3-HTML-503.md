# W3-HTML-503: over-cap page navigation retries itself

Branch `fix/w3-html-503`, cut from `origin/main` at `ebffabb`. That tree already contains merged #72 (`f75bbcb`, `fix/w3-keepalive-cap`). Nothing was deployed.

## Problem

A page load within 1 second of the last response is still over the per-IP cap. The accept thread answers `503` with `{"error":"unavailable"}` and starts no handler. Chrome renders that JSON and leaves it on screen. `Retry-After: 1` does not make the browser try the navigation again.

## Fix

`_reject_over_cap` (`app/server.py`, the method that still runs on the accept thread) reads the request headers under one 1-second deadline, then answers.

- If an `Accept` header lists the media type `text/html` (the type token, not a substring), the body is a static HTML page. `Retry-After` is `1`. The page's `<meta http-equiv="refresh" content="1">` uses that same delay, so the browser reloads the current URL on its own. The page is built from constants only. No request byte, path, query, or address is copied into it. No script, no external asset.
- Every other request, including `Accept: application/json` and a request whose headers never arrive, gets the previous JSON message: `Content-Type: application/json; charset=utf-8`, `Retry-After: 1`, `Connection: close`, `Cache-Control: no-store`, body `{"error":"unavailable"}`.

A client that sends nothing cannot hold the accept thread past that one second. The per-key busy `503` is unchanged.

## Tests

`tests/test_html_503.py`. One idle keep-alive holds the only per-IP slot. The next connection is inside the quiet second.

Before this server change, `PREACHED_CACHE` / `PREACHED_ONNX_DIR` / `HF_HOME` pointed at a temp dir:

```
test_api_json_request_keeps_the_json_503 ... ok
test_html_navigation_gets_a_refreshing_page ... FAIL
AssertionError: 'application/json; charset=utf-8' != 'text/html; charset=utf-8'
Ran 2 tests in 1.014s
FAILED (failures=1)
```

The API test passed there because that JSON body is the one this change keeps. Removing the JSON branch (mutant: every over-cap response is the HTML page) fails it:

```
test_api_json_request_keeps_the_json_503 ... FAIL
AssertionError: 'text/html; charset=utf-8' != 'application/json; charset=utf-8'
```

Removing the HTML branch (mutant: `Accept` never counts) fails the navigation test the same way the old server did:

```
test_html_navigation_gets_a_refreshing_page ... FAIL
AssertionError: 'application/json; charset=utf-8' != 'text/html; charset=utf-8'
```

With the change, both tests pass. The navigation check uses Chrome's list (`text/html` among other types) and requires the meta refresh delay to equal `Retry-After`. The page must not contain the query, the peer, a script, or a URL.

## DEPLOY cites

Inserting the helpers and the HTML branch before `logging.info("listening on ...")` moved later `app/server.py` cites. Each new line below was read off the file. `tests/test_deploy_alerts.py` pins only those CITED numbers. The runbook sentence that names where the line numbers hold now says this tree (`app/server.py` as it stands in this checkout).

| Was | Read at | Line holds |
| --- | --- | --- |
| 2817 | 2889 | `logging.info("listening on http://%s:%s", host, port)` |
| 2821 | 2893 | `app.log_startup_pause()` |
| 2889 | 2961 | `logging.error("church side refused: %s", problem)` |
| 2896 | 2968 | `logging.error("church side refused: %s", exc)` |
| 2907 | 2979 | `logging.error("church side refused: %s", problem)` |
| 2914 | 2986 | `logging.info("church side: %s, read-only, through the publish gate", slug)` |
| 3076 | 3148 | `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")` |
| 3254 | 3326 | `logging.info("stopping")` |
| 3255-3273 | 3327-3345 | `stuck = server.drain()` … `raise SystemExit(1)` |
| 3259 | 3331 | `"%d handler thread(s) still running after %.0fs; index left open"` |
| 3269 | 3341 | `app.church_connection.close()` |
| 3271 | 3343 | `logging.info("stopped cleanly")` |

Cites at or before `app/server.py:2381` did not move. The Connections row in `docs/DEPLOY.md` now says a `text/html` navigation gets the static page and every other over-cap request stays JSON.

## Suite and cache

`uv lock --check`: resolved 79 packages, exit 0.

`PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`:

```
Ran 1014 tests in 256.866s
OK
```

Zero failures. `test_every_cited_file_line_holds_its_string` is in that run.

Cache snapshot (path, size, mtime) of `/cache`: 119803 files before any test run here, the same count after. Unit and mutant runs used temp dirs only (`PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME` under `tempfile.gettempdir()`), and that snapshot was unchanged after them. The full suite is the command above, which reads `/cache`. After it, seven SQLite sidecar paths differed (size or mtime). No main database file was in the diff.

| Path | Before size | After size |
| --- | --- | --- |
| `/cache/xdg/deno/dep_analysis_cache_v2-wal` | 1124792 | 1194832 |
| `/cache/xdg/deno/v8_code_cache_v2-wal` | 2113592 | 2307232 |
| `/cache/xdg/deno/node_analysis_cache_v2` | 28672 | 28672 |
| `/cache/index/cc-speech.sqlite-shm` | 32768 | 32768 |
| `/cache/xdg/deno/dep_analysis_cache_v2-shm` | 32768 | 32768 |
| `/cache/xdg/deno/node_analysis_cache_v2-shm` | 32768 | 32768 |
| `/cache/xdg/deno/v8_code_cache_v2-shm` | 32768 | 32768 |

The `-shm` files changed mtime only. The two deno `-wal` files grew. `node_analysis_cache_v2` changed mtime only.
