# W3-HTML-503-R2: CTO r1 on PR #77 (MF1 accept-thread wait, MF2 q=0, S1 parser tests)

Branch `fix/w3-html-503` (PR #77). These commits come after r1 at `58f5ae5`. Only merges and new commits, no rebase or force-push. Nothing was deployed.

- Merged `origin/main` at `97537ae` (#69, #75, #76) in `bcadd00`. The merge was clean with no conflicts. It changed none of `app/server.py`, `tests/test_deploy_alerts.py` or the DEPLOY.md cite rows.
- Code head: `906b03a`. This report is the commit on top of it. The final head sha and the ahead/behind counts are in the PR BODY section.
- I could not find the full review file (`/workspace/reports/preached-pr77-review.md`) on this box (`/workspace` does not exist). I worked from the verbatim must-fixes in the task.

## What changed

### MF1: the accept thread never waits

`_read_over_cap_headers` (`app/server.py`) is now a single non-blocking `recv` of the bytes already buffered, up to the same bound as before (`65536 + MAX_HEADER_BYTES`). The socket is set non-blocking first. A Python socket with a timeout would poll for that timeout before the recv, even with `MSG_DONTWAIT`. If no complete header block with an acceptable `text/html` is buffered, the reply is the plain JSON 503. Every over-cap socket still gets `Retry-After: 1` and is closed at once (`shutdown_request`, unchanged).

There is one deviation from the letter of fix (a): the bytes are consumed with a plain recv rather than peeked with `MSG_PEEK`. The wait is the same: zero. The bound is the same. The difference: closing a socket whose receive queue still holds unread bytes makes Linux send a RST. Consuming them keeps the close a plain FIN. On loopback, a client still read the 503 in both variants (checked by hand), so this is defensive, not a fix for a failure I observed.

Documented consequence: a browser whose request headers had not all arrived when the connection was accepted (sent late, or split across packets) gets the JSON 503, not the page. The task accepts this. It is tested (`test_headers_not_yet_arrived_get_json`, `test_a_split_header_reads_only_the_first_part`) and stated in the DEPLOY.md Connections row.

### MF2: q=0 is not acceptable

`_accept_includes_html` splits each media range on `;`. When the type is `text/html` and any parameter matches `q=0` (regex `\s*q\s*=\s*0(\.0*)?\s*`, case-insensitive, so `0`, `0.`, `0.0` through `0.000`, `Q=0` and ` q = 0 ` all match), that range is skipped. A later `text/html` with a nonzero q still counts. `qs=0` is not `q`.

### S1: parser and read tests; */* pinned

`tests/test_html_503.py`. The file had 2 tests in r1 and has 20 now.

- `AcceptParserTests` (9): case; whitespace and tabs; several `Accept` lines in either order; near-misses (`text/htmlx`, `xtext/html`, `text/html5`, `application/xhtml+xml`, `Accept-Language`, `X-Accept`, `text/html-fragment`); a folded continuation line; the wildcards `*/*`, `text/*`, `*/*;q=0.8` stay JSON (pinned); q=0 variants; nonzero q; an incomplete block (split header) is JSON.
- `OverCapReadTests` (5, socketpair): a silent socket returns `b""` in under 50 ms; buffered bytes are returned; a split header returns only its first part, without waiting; the read is bounded (`2 * bound` bytes sent, at most `bound` read); a closed peer reads as JSON.
- `OverCapHtmlTests` (4, live server): the r1 HTML-page test and the r1 JSON test, plus `q=0` / `q=0.000` / `Q=0` get JSON, and `*/*` gets JSON. A browser sends its request right after the handshake, and whether those bytes arrive before `accept()` returns is a race. These tests wrap the server's `get_request` so it waits until the socket is readable, which makes that ordering fixed. The server code under test is unchanged.
- `OverCapNoWaitTests` (2, live server): headers not yet arrived get the JSON 503 (the documented case). **The MF1 test**: 20 silent over-cap sockets, then a request from a below-cap peer, which must be answered in under 100 ms. Each silent socket must have received the 503 with `Retry-After: 1` followed by EOF. The test raises the listen backlog to 128 so that only the accept thread can add delay (see Open issues).

The MF1 test and the live HTML tests passed 30 out of 30 runs in a loop.

DEPLOY.md, Connections row: the page now needs `text/html` with a nonzero weight. `text/html;q=0`, `*/*` and `text/*` get JSON (pinned in `tests/test_html_503.py`). The row also states the read-only-what-is-buffered rule and the late or split header case.

## Latency table (MF1)

This is legit-request latency behind K silent over-cap sockets. Setup: `max_per_client=1`, one held keep-alive from 127.0.0.2, K connects from 127.0.0.2 fired non-blocking and never sending, then a timed `/healthz` from 127.0.0.3 (connect through full response). The server keeps its default listen backlog. Each cell is the median of 3 runs (ms), and each tree used its own `tests/test_exposure._Served`. Script: `/tmp/html503/scripts/latency.py TREE 5 20 50` (not committed).

| K silent | main `97537ae` | r1 `58f5ae5` | head `906b03a` |
| --- | --- | --- | --- |
| 5 | 0.8 | 3003.7 | 0.8 |
| 20 | 0.8 | 4007.2 | 0.7 |
| 50 | 0.7 | 4006.1 | 0.8 |

Raw runs: main 0.8,0.8,0.8 / 0.8,1.0,0.7 / 0.7,0.8,0.7; r1 3003.6,3005.6,3003.7 / 4007.2,4007.2,4007.8 / 4006.1,4006.3,4006.1; head 0.9,0.7,0.8 / 0.7,0.9,0.7 / 0.8,0.7,1020.2.

The 1020 ms head run at K=50 is not this change. I ran main and head interleaved, 4 rounds of 10 runs each at K=50. Runs over 100 ms: main 4/40, head 5/40, all about 1 s. That is the kernel dropping a handshake when 50 connects in a burst overflow the default listen backlog of 5, then the SYN being retried after 1 s. It happens on main too. r1 stays near 3 to 4 s and not K seconds for the same reason: the backlog overflows and the client's own SYN retries set the timing.

## Mutants

These ran under read-only `/cache` (`unshare -rm` with an ro bind, nested userns back to uid 1000) with scratch caches. `app/server.py` was restored from a saved copy after each, and `cmp` confirmed it matched.

1. Put back the r1 blocking read (1 s deadline loop). Failures:
   ```
   FAIL: test_silent_over_cap_sockets_do_not_delay_the_next_client
   AssertionError: None != 200 : no response within 5 s
   FAIL: test_a_silent_socket_returns_at_once
   AssertionError: 1.0010754039976746 not less than 0.05
   FAIL: test_a_split_header_reads_only_the_first_part
   AssertionError: 1.0003829420020338 not less than 0.05
   Ran 20 tests in 10.536s
   FAILED (failures=3)
   ```
2. Drop the q=0 check. Failures:
   ```
   FAIL: test_q_zero_is_not_acceptable
   AssertionError: True is not false : Accept: text/html;q=0
   FAIL: test_q_zero_html_gets_json
   AssertionError: 'text/html; charset=utf-8' != 'application/json; charset=utf-8'
   Ran 20 tests in 2.030s
   FAILED (failures=2)
   ```

## DEPLOY cites (rule 4)

Pins were checked against the merged tree. The 2-line growth of the `PreachedServer` docstring and the helper rewrite moved every `app/server.py` cite at or after `listening on` by +7, relative to the r1 pins. Pins before line 2430 did not move: a script that finds each needle nearest its old line reported no other changes. I read each new line off the file:

| Was | Now | Line holds |
| --- | --- | --- |
| 2889 | 2896 | `logging.info("listening on http://%s:%s", host, port)` |
| 2893 | 2900 | `app.log_startup_pause()` |
| 2961 | 2968 | `logging.error("church side refused: %s", problem)` |
| 2968 | 2975 | `logging.error("church side refused: %s", exc)` |
| 2979 | 2986 | `logging.error("church side refused: %s", problem)` |
| 2986 | 2993 | `logging.info("church side: %s, read-only, through the publish gate", slug)` |
| 3148 | 3155 | `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")` |
| 3326 | 3333 | `logging.info("stopping")` |
| 3327-3345 | 3334-3352 | `stuck = server.drain()` ... `raise SystemExit(1)` |
| 3331 | 3338 | `"%d handler thread(s) still running after %.0fs; index left open"` |
| 3341 | 3348 | `app.church_connection.close()` |
| 3343 | 3350 | `logging.info("stopped cleanly")` |

The replacement was one regex pass, so no number was shifted twice (2961→2968 and 2968→2975 overlap). It touched every occurrence in DEPLOY.md and in `CITED` only. The sentence about where the line numbers hold is already tree-relative ("this tree (`app/server.py` as it stands in this checkout)"), so it is unchanged. `tests.test_deploy_alerts` and `tests.test_deploy_regex`: OK. The one skip is the infra alerts YAML, which is absent on this box (`/workspace/infra-ops/...`).

## How to run

```
S=$(mktemp -d)
PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=$S/cache HF_HOME=$S/hf DENO_DIR=$S/deno XDG_CACHE_HOME=$S/xdg \
  PREACHED_ONNX_DIR=$S/onnx TORCH_HOME=$S/torch uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_html_503 tests.test_deploy_alerts tests.test_deploy_regex
uv lock --check
```

## Results

Full suite, `PREACHED_REQUIRE_DENO=1`, with scratch `PREACHED_CACHE`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `PREACHED_ONNX_DIR`, `TORCH_HOME` and `UV_CACHE_DIR`, under read-only `/cache`. Two runs (plain and `-v`) gave the same result:

```
Ran 1050 tests in 228.735s
FAILED (failures=1, skipped=8)
```

- **1 failure, environmental, not this change:** `test_shutdown.LoadedSigtermTests.test_sigterm_under_hybrid_load_exits_zero_and_cleans_up`. Its skip guard checks only that `PREACHED_ONNX_DIR` is a directory. The scratch dir exists but is empty, so the test runs, the server logs `embedding model unavailable` with a traceback, and the test's `"Traceback" in err` check fails 3/3 runs (rc 0, 26 OK responses, nothing leaked). Main (`97537ae`) fails the same way, 3/3 runs, under the same scratch environment. On this branch, with `PREACHED_ONNX_DIR` unset (the real ONNX dir, read only, `/cache` mounted ro), `tests.test_shutdown.LoadedSigtermTests` gives `Ran 2 tests ... OK`.
- **8 skips:** 1 `test_deploy_regex` infra YAML (`/workspace/infra-ops/...` absent); 6 `test_embed_backend` (`granite onnx artifacts are not in /cache`, because of the scratch ONNX dir); 1 `test_eval_leak` (`needs chunks.jsonl or the index sqlite in PREACHED_CACHE`, scratch). No deno-backed test skipped.
- Zero `test_every_cited_file_line_holds_its_string` failures.

`uv lock --check`: `Resolved 79 packages`, OK.

Cache snapshot (rule 5): `find /cache -xdev -printf '%p\t%s\t%T@\n'` before any run (132614 entries) and after (132629 entries).

- Lines in the diff: 21 added (`>`) and 6 removed (`<`), all under `/cache/uv`, plus the mtime of `/cache` itself. The entries are 15 new files and dirs and 6 changed directory or interpreter entries. **This is mine:** my first two plain `uv run` calls (18:25:51 and 18:25:59 local), which created this worktree's `.venv`, ran before I overrode `UV_CACHE_DIR`. This shell's environment sets it to `/cache/uv`. uv wrote the editable `preached` wheel (`sdists-v10/editable/e19ed657bfbc770d/...`, `archive-v0/psBa8UznJZRCVtfJ/...`) and one interpreter msgpack into the shared uv cache. These are additions only. No existing file was removed or resized.
- `/cache` top-level mtime moved to 18:29:48 with no entry added or removed directly under it. I cannot attribute that: my mutant and suite runs had `/cache` read-only, and other agents write `/cache` concurrently.
- Nothing changed under `/cache/models`, `/cache/huggingface`, `/cache/index`, `/cache/xdg` or any other non-uv path. Every later run used scratch caches including `UV_CACHE_DIR`.

## Open issues

- A navigation whose headers arrive after `accept()` gets the JSON 503 (accepted by the CTO, documented, tested). How often this happens in production behind the proxy is not measured.
- `PreachedServer` keeps socketserver's default `request_queue_size = 5`. A burst of more than about 6 connects can lose a handshake to a 1 s SYN retry, on main as well as here. This is out of scope. It is a possible follow-up if bursts matter.
- The full CTO review file was not on this box. Only the must-fixes and should-fixes quoted in the task were addressed.

## Dependencies

None added.

## PR BODY

Head: see the latest commit on `fix/w3-html-503`. It is the report commit; the code is at `906b03a`. Ahead/behind `origin/main` (`97537ae`): **4 ahead, 0 behind**, counting the report commit (3 before it: r1 `58f5ae5`, merge `bcadd00`, fix `906b03a`).

`git diff --stat origin/main..HEAD` (all in scope):

```
 app/server.py               |  87 +++++++++++++-
 docs/DEPLOY.md              |  37 +++---
 reports/W3-HTML-503-R2.md   | (this report)
 reports/W3-HTML-503.md      |  94 +++++++++++++++
 tests/test_deploy_alerts.py |  24 ++--
 tests/test_html_503.py      | 287 ++++++++++++++++++++++++++++++++++++++++++++
```

### r2: CTO r1 must-fixes

- **MF1 (accept-thread wait):** the over-cap path does one non-blocking recv of the bytes already buffered (bounded at `65536 + MAX_HEADER_BYTES`) and never waits. Headers not yet arrived get the JSON 503. Over-cap sockets still close at once with `Retry-After: 1`. The bytes are consumed, not peeked, so close is a FIN and not a RST. New test: 20 silent over-cap sockets, then a below-cap request answered in under 100 ms.
- **MF2 (q=0):** `text/html` with `q=0` (`0`, `0.`, `0.0` through `0.000`, any whitespace, `Q`) is skipped and gets JSON. Tests cover `q=0`, `q=0.000` and `;Q=0`, both at the parser and on the live server.
- **S1:** parser and read unit tests: case, whitespace, multiple Accept lines, near-misses, folded line, split header (JSON, documented), read bound. `*/*` and `text/*` stay JSON; this is pinned and documented in DEPLOY.md.

Legit-request latency behind K silent over-cap sockets (median of 3, ms):

| K | main | r1 `58f5ae5` | head |
| --- | --- | --- | --- |
| 5 | 0.8 | 3003.7 | 0.8 |
| 20 | 0.8 | 4007.2 | 0.7 |
| 50 | 0.7 | 4006.1 | 0.8 |

Mutants: putting back the blocking read fails the latency test (no response within 5 s) and 2 read tests (1.0 s ≥ 0.05 s). Dropping the q=0 check fails both q=0 tests. Both were reverted.

DEPLOY cites: 12 `app/server.py` pins moved +7 (2889→2896 … 3343→3350, range 3327-3345→3334-3352). Each was read off the merged tree and updated in DEPLOY.md and `CITED`. `test_deploy_alerts` and `test_deploy_regex` pass.

Full suite (`PREACHED_REQUIRE_DENO=1`, scratch caches, ro `/cache`): 1050 tests, 1 failure, 8 skips. The failure is `test_shutdown` hybrid-load, caused by the empty scratch ONNX dir. It fails the same way on main and passes on this branch with the real ONNX dir read-only. `uv lock --check` OK. Cache: only `/cache/uv` additions from my first `uv run` before I overrode `UV_CACHE_DIR` (details in `reports/W3-HTML-503-R2.md`).

No dependencies added.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
