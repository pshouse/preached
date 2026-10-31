# W3-LISTEN-BACKLOG

## What was done
1. `app/server.py`: `LISTEN_BACKLOG = 128` (named constant, with the reason in a comment) and `PreachedServer.request_queue_size = LISTEN_BACKLOG`. socketserver's default was 5. The kernel clamps to `net.core.somaxconn`. No DEPLOY exposure change.
2. `tests/test_listen_backlog.py` (new):
   - burst: 50 connects (10 source IPs x 5, per-client cap 4, global cap 64) made while accept() is held. 3 rounds. Each connect < 0.5 s. After release: exactly 10 over-cap 503s (one per source, JSON body, `Retry-After: 1`) inside 0.5 s, `_conn_by_ip == 4` for every source, `_conn_total == 40`, and the 40 admitted connections get 200.
   - FIN: cap filled, a full POST with a 40000-byte body is sent, the client reads the whole 503, then `recv() == b""` (not `ConnectionResetError`). Two variants: the real close path, and a bare `close()` (see Findings).
3. DEPLOY cites re-pinned (below).

## How to run
`PREACHED_REQUIRE_DENO=1 uv run python -m unittest discover -s tests` with `UV_CACHE_DIR`, `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME` all in one temp dir. Just the new file: `uv run python -m unittest tests.test_listen_backlog -v`.

## Results
Full suite (temp caches): Ran 1085 tests, OK (skipped=11). No `test_every_cited_file_line_holds_its_string` failure. No `test_shutdown` hybrid-load failure (#78) seen.

### Latency / burst, before vs after (50 simultaneous connects, accept held, loopback)
| | backlog 5 (before) | backlog 128 (after) |
|---|---|---|
| connect, max | TimeoutError at 3 s (client 6 in the run; the SYN was dropped, the retry cannot succeed while accept is held; a free accept thread would show the ~1 s retry) | 0-1 ms (3 rounds, 3 runs) |
| over-cap 503 after release, max | not reached | 3-14 ms |
| admitted 200, max | not reached | 0-4 ms |

## Mutants (run on temp caches, each reverted)
- `LISTEN_BACKLOG = 5`: `test_fifty_simultaneous_connects_take_no_syn_retry` RED (connect timed out), `test_backlog_is_bounded` RED. Reverted: green.
- `recv(..., socket.MSG_PEEK)` instead of consume: `test_the_bytes_are_consumed_so_a_bare_close_is_a_fin` RED ("closed with a reset, not a FIN"). Reverted: green.

## Findings
The MSG_PEEK mutant **survives the real close path**. `socketserver.shutdown_request` calls `shutdown(SHUT_WR)` before `close()`, so the FIN is sent first. The RST for unread bytes then lands on a client in CLOSE_WAIT, and Linux still returns the queued 503 and then EOF. I checked this with a bare socket pair: peek + shutdown-then-close gives data then `b""`; peek + bare `close()` gives `ConnectionResetError`. So the consume claim only matters if the close ever loses the half-close. `test_the_bytes_are_consumed_so_a_bare_close_is_a_fin` isolates it by replacing `shutdown_request` with a bare `close()` on the test server; that is what kills the mutant. The real-path test (the one the CTO asked for) passes with either, and is kept as the end-to-end pin.

## DEPLOY cite re-pins (all +11: the constant block is above `class PreachedServer`, one line is added in it; cites before line 2450 do not move)
Each verified by reading `app/server.py` at the new line:
| old -> new | line text |
|---|---|
| 2919 -> 2930 | `logging.info("listening on http://%s:%s", host, port)` |
| 2923 -> 2934 | `app.log_startup_pause()` |
| 2991 -> 3002 | `logging.error("church side refused: %s", problem)` |
| 2998 -> 3009 | `logging.error("church side refused: %s", exc)` |
| 3009 -> 3020 | `logging.error("church side refused: %s", problem)` |
| 3016 -> 3027 | `logging.info("church side: %s, read-only, through the publish gate", slug)` |
| 3178 -> 3189 | `logging.basicConfig(level=logging.INFO, format=...)` |
| 3356 -> 3367 | `logging.info("stopping")` |
| 3357-3375 -> 3368-3386 | `stuck = server.drain()` ... `raise SystemExit(1)` |
| 3361 -> 3372 | `"%d handler thread(s) still running after %.0fs; index left open"` |
| 3371 -> 3382 | `app.church_connection.close()` |
| 3373 -> 3384 | `logging.info("stopped cleanly")` |
Updated in `docs/DEPLOY.md` (26 occurrences) and the `CITED` pins in `tests/test_deploy_alerts.py` (13). The tree sentence is already tree-relative; it now also names the listen backlog.

## Cache safety
All env paths were temp dirs. `/cache` listing (paths, sizes, mtimes, 132661 entries) before vs after: one difference, `/cache/index/cc-speech.sqlite-shm` mtime changed (size same, 32768). My runs never pointed at /cache, so something else on the host touched it (an SQLite reader opening that index). Nothing was added or removed.

## PR BODY
Raise the listen backlog from socketserver's 5 to a named `LISTEN_BACKLOG = 128`, so a burst of simultaneous connects is queued instead of dropped (a dropped SYN costs ~1 s). Adds a burst test (50 connects, no retry, caps and 503 path still hold) and a FIN-not-RST test for the over-cap 503 (CTO #77 S1-r2). Re-pins DEPLOY cites (+11 after line 2450). Finding: the MSG_PEEK mutant survives the real close path because socketserver half-closes first; a bare-close variant kills it.

Full suite: 1085 tests OK (skipped=11).

DIFFSTAT
