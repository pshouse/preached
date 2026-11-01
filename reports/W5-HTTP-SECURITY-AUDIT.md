# W5 HTTP security audit

Reviewed `origin/main` at `d8a096693f82e8b00933451cb1060a71efafd80a` (this branch started there; main had not moved). Scope is this report. No file under `app/`, `src/`, `tests/`, or `docs/` was edited. Findings that need code are recommendations.

The process on main is a stdlib `ThreadingHTTPServer` (`app/server.py`). It serves GET and HEAD only. It sets no cookie and no CORS header. There is no application credential. The bind address is the authorization boundary.

## How this was probed

Two processes, both `python app/server.py --bm25-only --host 127.0.0.1` on a free high port, with a one-chunk synthetic Wesley index under `/tmp`. `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, and `TORCH_HOME` were fresh directories under `/tmp/w5-audit/`. The live process environ was read and matched those paths. `PREACHED_RATE_LIMIT`, `PREACHED_TRUSTED_PROXIES`, and `PREACHED_DISABLED` were unset, so the numbers below are the code defaults, not the tighter `scripts/serve.sh` values. The embedding model was not loaded (log: `BM25 only; the embedding model was not loaded`). The church side was not started.

`ss` showed `LISTEN` backlog 128 on `127.0.0.1` (`Send-Q` 128), which is `LISTEN_BACKLOG` at `app/server.py:2457`. Each process was stopped by its exact PID. Captures cited below are from those processes (ports 51623 and 55287). `curl` folds dot segments, so traversal and the HTTP/2 preface were sent on raw sockets.

## Routes and methods

Every successful route is GET or HEAD. HEAD uses the same handler with an empty body (`do_HEAD` at `app/server.py:2392`).

| Request | Result | Where |
| --- | --- | --- |
| `GET /` and `HEAD /` | `index.html`, `text/html; charset=utf-8` | `_route` `app/server.py:2304`, `_send_page` `2332` |
| `GET /healthz` and `HEAD /healthz` | health JSON, 200 or 503 | `_route` `2307` |
| `GET /api/search` and `HEAD` | search JSON | `_route` `2311` |
| `GET /api/side` and `HEAD` | both columns | `_route` `2311` |
| `GET /api/sermon/<id>` and `HEAD` | sermon JSON, or 404 | `_route` `2324`, `_send_sermon` `2352` |
| `GET /static/app.js`, `app.css`, `favicon.svg` | those three files | `_route` `2327`, `static_name` `615`, `STATIC_TYPES` `199` |
| any other path | 404 `{"error": "not found"}` | `_route` `2330` |
| `POST`, `PUT`, `DELETE`, `PATCH` | 405 `{"error": "method not allowed"}`, `Allow: GET, HEAD`, connection closed | `do_POST` `2420`, `do_PUT` `2423`, `do_DELETE` `2426`, `do_PATCH` `2429`, `_reject_method` `2395` |
| any other method (`OPTIONS`, `TRACE`, …) | 501 `{"error": "bad request"}`, connection closed | `_handle_parsed` `2073`–`2076` |
| connection accepted over the cap | 503 on the accept thread, no handler | `process_request` `2727`, `_reject_over_cap` `2752` |

`/disable` and `/resume` are not routes. On the first probe process both returned `404` `{"error": "not found"}`. No route reads a body (`docs/DEPLOY.md` entry-points list: every method other than GET and HEAD is 405, and no route reads a body).

## Limits, headers, and the switch

Checked in code and, where a live response is named, on the probe.

| Control | Code | Live result |
| --- | --- | --- |
| Query length | `MAX_QUERY = 300` (`193`). `parse_search_args` (`637`–`680`) strips, rejects code points `< 32` or `127`, and requires 1–300 code points. | Missing `q`: 400 `q is required`. Empty `q` and a 301-character `q`: 400 `q must be 1 to 300 characters`. 300 `c`s with `mode=bm25&k=1`: 200. `q` containing `%0A`: 400 `q has unsupported characters`. |
| `k` | Digits only, then 1–25 (`656`–`665`). Default 10. | `0`, `26`, `-1`, `foo`, `1e2`: 400 `k must be an integer from 1 to 25`. |
| `mode` | `hybrid`, `bm25`, `dense` (`222`, `668`–`670`). | `mode=SQL`: 400 `mode must be hybrid, bm25, or dense`. |
| `library` | Must be a library this process has open. The error names only the classic slug (`672`–`679`). | `library=../etc`: 400 `library must be wesley`. |
| Query field count | `parse_qs(..., max_num_fields=32)` (`2313`). | 33 fields: 414 `{"error": "request too large"}`. |
| Target, headers, body | `MAX_TARGET = 2048` (`227`), `MAX_HEADER_BYTES = 8192` (`232`), `MAX_BODY = 4096` (`228`). A body over the cap is 413 (`2220`–`2222`). | `Content-Length: 99999` on `/healthz`: 413. |
| Framing | Chunked and duplicate `Content-Length` are refused before the route (`2063`–`2070`). | `Transfer-Encoding: chunked`: 501 `{"error": "bad request"}` with the handler security headers and `Connection: close`. Two `Content-Length` lines: 400, same body. |
| Host | Exactly one `Host`, and `host_allowed` (`2223`–`2225`, `1281`). Default allowlist `127.0.0.1,localhost` (`3209`–`3210`). | `Host: evil.example`: 421 `{"error": "host not allowed"}`. `Host: localhost`: 200. Two raw `Host` lines (`127.0.0.1:55287` and `evil.example`): 421 `{"error": "host not allowed"}`. |
| Connections | 32 global, 4 per socket peer (`246`–`247`). In-flight 4 per client key, with a separate table for `/healthz` (`250`, `2708`–`2716`). | See F-01 and F-04. |
| Rate | Code default 120/60s per key and 1200 global (`263`–`266`). `/healthz` is 60 and 600 (`268`–`269`). `serve.sh` passes 60 and 600 (`scripts/serve.sh:93`–`95`). | From `127.0.0.4`, favicon GETs 1–120 were 200. 121 and 122 were 429 `{"error": "too many requests"}`, `Retry-After: 60`, with the handler security headers. Log: `WARNING refused 429-client 127.0.0.4 127.0.0.4 /static/favicon.svg`. The next `/healthz` from `.4` was 200. The next `/api/search` from `.4` was 429. The global cap of 1200 was not flooded. |
| Listen backlog | `LISTEN_BACKLOG = 128` (`2457`). | `ss` Send-Q 128 on the probe listener. |
| Security headers on the handler | CSP (`206`–`220`, includes `frame-ancestors 'none'`; no `unsafe-inline` or `unsafe-eval`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` (`2160`–`2164`). `Cache-Control: no-store` (`2182`, `2154`). `Server: Preached` (`2135`–`2136`). | Present on 200, 400, 404, 405, 413, 414, 421, 429, 501, and the handler 503. |
| CORS and cookies | No `Access-Control-*` and no `Set-Cookie` anywhere in `app/server.py`. | `OPTIONS /api/search` with `Origin: https://evil.example` returned 501 and no CORS header. `GET /healthz` with that `Origin` returned 200 and no CORS header. No captured response contained `Set-Cookie`. |
| Bind | `--host` default `127.0.0.1` (`3191`). | The probe listener was `127.0.0.1` only. |
| Kill switch | Not an HTTP route. `App.disabled` (`1284`–`1307`) reads `PREACHED_DISABLED` from this process's environment and `kill_file_engaged` (`381`–`395`). A regular file is on. A missing file in a normal directory is off. A directory, a symlink, or an unreadable parent is on. Contents are never read and the path is never returned. | With `PREACHED_KILL_FILE` set: file present → `/healthz` 503 `{"ok": false, "disabled": true}`, `/api/search` and `/` 503 `{"error": "unavailable"}`. File removed → `/healthz` 200 `disabled: false`. A symlink to a missing target, and a directory at the path, each stayed on. After the directory was removed, `/healthz` was 200. The log has no engage or resume line. |

`_positive_int` (`346`–`351`) accepts any integer ≥ 1. Rate limits and `PREACHED_HEALTH_RESERVED_CONNECTIONS` (default 1, `279`) have no ceiling.

## Findings

### F-01 — High — a 405 holds an in-flight search slot until the process exits

`_reject_method` (`2395`) calls `_blocked` (`2230`). When the size, host, kill-switch, and rate checks pass, `_blocked` calls `acquire_slot` and stores the key on `self._slot_key` (`2274`–`2287`). The matching `release_slot` runs only in `_respond`'s `finally` (`2362`–`2370`). `do_GET` and `do_HEAD` call `_respond`. `do_POST`, `do_PUT`, `do_DELETE`, and `do_PATCH` call `_reject_method` and do not. The 405 closes the connection (`2409`) and the in-flight count stays at 4.

`DEFAULT_MAX_CLIENT_REQUESTS` is 4 (`250`). Four calls through `_reject_method` fill the search table for that client key. The probe sent one POST, one PUT, one DELETE, and one PATCH. Four of any one of those methods take the same path. The next request from that key hits the busy branch (`2276`–`2285`) and returns 503 `{"error": "unavailable"}` with `Retry-After: 1`. That branch runs before `_route` chooses a path, so `/`, `/api/search`, `/api/side`, `/api/sermon/…`, and `/static/…` all take it. The probe measured `/api/search`, `/`, and `/static/favicon.svg`. Nothing on the 405 path decrements the counter, and the counter has no timer. The GET that followed the fourth 405, in the same second, was already 503. `/healthz` uses `_health_slots_by_key` (`2708`–`2710`) and still returns 200.

Raw requests from `127.0.0.5` to the second probe, in order, each with `Connection: close`:

1. `GET /api/search?q=grace&mode=bm25&k=1` → `HTTP/1.1 200 OK`, search JSON.
2. `POST /api/search?q=grace` → `HTTP/1.1 405 Method Not Allowed`, `{"error": "method not allowed"}`.
3. `PUT` the same target → 405, same body.
4. `DELETE` the same target → 405, same body.
5. `PATCH` the same target → 405, same body.
6. `GET /api/search?q=grace&mode=bm25&k=1` → `HTTP/1.1 503 Service Unavailable`, `Retry-After: 1`, `{"error": "unavailable"}`.
7. `GET /` → 503, same body.
8. `GET /static/favicon.svg` → 503, same body.
9. `GET /healthz` → `HTTP/1.1 200 OK`, `"ok": true`.

A following `GET /api/search?q=grace&mode=bm25&k=1` from `127.0.0.1` was 200. The leak is per client key. The log line was `WARNING refused busy 127.0.0.5 127.0.0.5 /api/search suppressed=0`.

`scripts/serve.sh` passes `PREACHED_TRUSTED_PROXIES` only when it is set (`137`–`138`). The default is empty, which `docs/DEPLOY.md` already records: behind `tailscale serve`, every client is the socket peer `127.0.0.1` and shares one bucket (known gap, "With `PREACHED_TRUSTED_PROXIES` left empty"). On that deploy, four POSTs from anyone who can open the port stick search, the page, and static files for the whole process, while `/healthz` stays green. This probe did not run Tailscale. The per-key behavior was measured; the process-wide reading is that measurement plus the documented shared peer.

`OPTIONS` and `TRACE` return 501 from `_handle_parsed` before `_blocked`, so they do not take a slot. A request that fails the size or host check raises `BadRequest` inside `_reject_method` before `acquire_slot`.

Recommendation: release the slot before `_reject_method` returns (the same `finally` as `_respond`), or send the 405 through `_respond`. Add a test that sends four 405s from one peer and then asserts `GET /api/search` is 200 and the slot table is empty.

Covered today: `tests/test_server.py::ServerTests.test_methods_host_and_body_limits` sends one POST and expects 405. `tests/test_exposure.py` `SlotReleaseTests` and `RequestSlotRaceTests` cover `release_slot` on the GET path. Neither sends four 405s and then a GET.

### F-02 — Medium — a failed church search logs the question

The classic handler logs the exception type only. `_respond_inner` says so and does it (`2381`–`2383`): `logging.error("request failed: %s", type(exc).__name__)`. `docs/DEPLOY.md` states the same rule in the Logs row of the hardening table: "A failed request logs the exception type, not the message."

The church side does the other thing. `App._church_search` (`1600`–`1602`) calls `logging.exception("church search failed; that side is empty")` for any failure that `is_busy` does not swallow. `store.bm25_search` raises `RuntimeError(f"FTS5 query failed for MATCH {match!r}: {exc}")` (`src/preached/store.py:369`–`371`). `match` is `to_fts_query(query)` (`src/preached/fts.py:143`–`152`), the quoted tokens of the question. `logging.exception` writes that message and the traceback. A congregant name in a question that FTS rejects would land in the church-side log.

The successful classic search does not do this. A probe query `What did Jane CongregantUniqueNameZZZ ask about baptism?` returned 200 with that string in the JSON body. Both probe logs were searched for `Congregant`; it is absent. Access lines are `peer key GET /api/search status`, because `log_request` drops the query string (`2119`–`2123`) and `log_message` drops it too (`2090`–`2098`).

The church side was not started on the probe (no private index, and `serve.sh` passes no `--church-library` or `--church-index`). This finding is the code path, not a captured church log line. `docs/DEPLOY.md` Part 3 still says the church side is not deployed.

`tests/test_deploy_alerts.py` pins the current call (`app/server.py:1602`, `logging.exception("church search failed; that side is empty")`). That pin records the call. It does not assert that the query is absent. `tests/test_church_harden.py::assert_church_clean` asserts a startup log lacks the failure string. No test asserts that a failed church search omits the MATCH text.

Recommendation: log `type(exc).__name__` only, the same way `_respond_inner` does. The PR that does that has to move the deploy-alert pin and any DEPLOY.md sentence that cites the line. Keep the client body as the empty church side; that part already hides the error.

### F-03 — Medium — a public bind needs no acknowledgement, and the Host list does not stop it

`--host` defaults to `127.0.0.1` (`3191`). The probe bound that address and nothing else. `--hosts` defaults to `127.0.0.1,localhost` (`3209`–`3210`).

`main` adds the bound address to the Host allowlist only when it is not `0.0.0.0`, `::`, or empty (`3312`–`3315`). It still calls `make_server(app, args.host, args.port)` (`3343`) for those values. There is no extra flag. A process started with `--host 0.0.0.0` or `--host ::` listens on every interface, and the allowlist is still the default plus whatever `--hosts` names. A remote client that sends `Host: 127.0.0.1` or `Host: localhost` passes `host_allowed`. This was read from `main`. The probe did not bind a public address.

There is no application login. Anyone who can open the port can search and can read sermon reader, title, and text. `docs/DEPLOY.md` already says the deploy is loopback or Tailscale, "Do not bind `0.0.0.0`", and that going public is the Part 4 gate (items still open, including the threat-model sign-off and the serve-versus-funnel decision).

Recommendation: refuse `--host 0.0.0.0` and `--host ::` unless the operator passes an explicit acknowledgement flag. Leave a Tailscale address usable. Do not add an account system in that PR. Public exposure stays the go-public gate: Tailscale ACL, and no funnel until that gate is signed.

No current test refuses a public bind. `test_methods_host_and_body_limits` covers a bad `Host` header (421) on a loopback server.

### F-04 — Low — the accept-thread 503 omits the handler security headers

Handler responses go through `_security_headers`. The accept-thread 503 is a raw byte string (`2752`–`2772`): status, `Content-Type`, `Content-Length`, `Connection: close`, `Retry-After: 1`, `Cache-Control: no-store`, and the body. It does not send CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Server`, or `Date`.

A fifth connection from `127.0.0.6` received:

```http
HTTP/1.1 503 Service Unavailable
Content-Type: application/json; charset=utf-8
Content-Length: 23
Connection: close
Retry-After: 1
Cache-Control: no-store

{"error":"unavailable"}
```

The same peer with `Accept: text/html` received the constant 176-byte page (`2859`–`2864`), `Content-Type: text/html; charset=utf-8`, and the same header set. The page is built from constants. The probe body contained no request bytes. The log was `WARNING refused over-cap peer=127.0.0.6 suppressed=0`.

The hardening table's Headers row lists CSP, nosniff, no-referrer, `X-Frame-Options: DENY`, and `Server: Preached` for the process. This path is outside that set. The HTML form has no CSP. It also has no attacker-controlled bytes.

`tests/test_html_503.py` pins status, content type, `Retry-After`, `Connection`, `Cache-Control`, and that the page does not echo the query. It does not require the handler security headers.

Recommendation: send the same four security headers and `Server: Preached` on both over-cap bodies. Keep the body a constant. Extend `test_html_503` rather than only the handler's `assert_secure`.

Handler responses also omit `Permissions-Policy`, `Cross-Origin-Opener-Policy`, and `Cross-Origin-Resource-Policy`. Those are worth adding on the handler path in the same small PR. Leave HSTS off while the process speaks plain HTTP (`docs/DEPLOY.md`: TLS comes from the proxy or Tailscale).

### F-05 — Low — the kill switch is silent, and a direct start has no default path

The switch works, and it is filesystem-only. The probe above engaged a regular file, a dangling symlink, and a directory, and serving resumed when a regular file or that directory was removed. `/healthz` reports `disabled: true` and does not report the path. `GET /disable` and `GET /resume` are 404.

`main`'s `build_app` call (`3316`–`3330`) does not pass `kill_file`. `disabled` then uses `PREACHED_KILL_FILE` if that variable is set, and otherwise stays off (`1301`–`1306`). `scripts/serve.sh:92` defaults `PREACHED_KILL_FILE` to `$ROOT/KILL` and passes it. A direct `python app/server.py` or `uv run`, with the variable unset, has no kill file to touch.

Nothing logs the transition. The probe log shows the 503 access lines and no line that says the switch engaged or cleared. `PREACHED_DISABLED` is this process's environment (`1288`–`1291`). Another shell cannot flip it. That part matches the hardening table.

Recommendation: when `main` starts with no kill path, default the same `$ROOT/KILL` path `serve.sh` uses, and log one info line when the switch goes on and one when it goes off. Keep contents and the path out of the client body. Do not add an HTTP disable route; the 404 is the right answer for a listener that may be reachable past loopback.

Behavior of an engaged file is covered by the server tests around `disabled` and by the hardening table. A direct-start default and a transition line are not.

### F-06 — Low — an HTTP/2 preface is answered with a body and no status line

Sending the bytes `PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n` produced exactly `{"error": "bad request"}` (24 bytes) and then a close. There was no status line and no header. The log, from the same connection, was:

```text
INFO 127.0.0.1 code 505
INFO 127.0.0.1 127.0.0.1 - / 505
```

The method and path in that access line are the placeholders `-` and `/`. Command and path were still unset.

CPython 3.12.16 `http.server.BaseHTTPRequestHandler.parse_request` sets `request_version` to the default `HTTP/0.9` (`http/server.py:283`), and on `version_number >= (2, 0)` it calls `send_error(505)` (`319`–`323`) before it assigns the client's version (`324`) and before it assigns command and path (`339`). The app overrides `send_error` (`app/server.py:2138`) and still writes the JSON body (`2157`–`2158`). Codes other than 413, 414, and 431 use the text `bad request` (`2145`–`2148`), so the logged 505 and the body disagree. `send_response_only`, `send_header`, and `end_headers` skip the status line and the header block when `request_version == 'HTTP/0.9'` (stdlib `512`, `526`, `540`). The body write is outside that condition. `Connection: close` still sets `close_connection` because that assignment in `send_header` is outside the version check (`532`–`534`).

The app's own early rejects already avoid this. A too-long or control-character request line sets `request_version = ""` before `send_error` (`2003`–`2006`, `2020`–`2024`). The 505 path is inside stdlib `parse_request`, which those assignments do not wrap.

The body is the fixed JSON string. It does not echo the preface. Severity stays low: a client that sends an HTTP/2 preface, and any proxy that frames on a status line.

Recommendation: before calling `parse_request`, if the request line's version is HTTP/2 or newer, set `request_version` to `HTTP/1.1` and send a normal headered 505 (or 400) through the app's `send_error`, then close. Add a socket test that the first bytes are `HTTP/1.1 505` and that the body is the fixed JSON.

No current test sends an HTTP/2 preface.

### F-07 — Low — rate and reserve env values have no ceiling, and static files spend the search budget

`_positive_int` (`346`–`351`) returns the parsed integer whenever it is ≥ 1. `PREACHED_RATE_LIMIT`, `PREACHED_GLOBAL_RATE_LIMIT`, the two health rate limits, and `PREACHED_HEALTH_RESERVED_CONNECTIONS` all go through that helper. An operator can set the search budget or the health reserve to an unbounded count. `serve.sh` itself passes finite defaults (60, 600, and the reserve it already documents).

The limiter that is configured does run. The favicon series above hit 429 at request 121 with `Retry-After: 60` and full handler headers. `/healthz` from the same peer stayed 200, which is the separate health bucket (`docs/DEPLOY.md` `/healthz` bucket row, and `tests/test_exposure.py::HealthBucketTests`).

`/`, `/static/*`, and `/api/search` share the search bucket (`2264`–`2272` uses `health=False` for every path other than `/healthz`). One hundred twenty favicon GETs, at the code default, made the next search 429 for the rest of the window. `serve.sh`'s cap is 60, so the same pattern is a shorter flood. `docs/DEPLOY.md` already says clients behind one NAT share that IP's rate limit. It is worth a line in the same place that a static flood spends the search budget.

Recommendation: give each of those env values a documented ceiling in `_positive_int`'s callers, and reject a value above it at startup. Leave the shared search bucket as it is unless a later change gives static files their own small budget. Cite `HealthBucketTests` so a new ceiling does not merge the health bucket back into search.

`tests/test_exposure.py::DocAndScriptTests.test_serve_sh_passes_the_new_settings` checks that `serve.sh` passes the settings. It does not cap a huge value.

## Checked, and already holding

These were probed or read so the audit would cover them. They are not new findings.

- Path traversal. `static_name` (`615`–`627`) rejects `/`, `\`, NUL, `..`, and `%`, then requires a name in `STATIC_TYPES`. `_send_static` resolves the file and requires the parent to be the static directory (`2345`–`2348`). Sermon ids must match `SERMON_ID` (`291`) and `_send_sermon` also rejects `/`, `\`, `%`, and `..` (`2352`–`2354`). Raw requests for `GET /static/./app.js`, `GET /static/../pyproject.toml`, and `GET /api/sermon/../pyproject.toml` each returned 404 `{"error": "not found"}` with the handler security headers and no file bytes. `tests/test_server.py::test_static_allowlist_and_traversal` covers the allowlist.
- Absolute-form request line. `GET http://example.com/api/search?q=grace&mode=bm25&k=1` with `Host: 127.0.0.1:55287` returned the local search JSON (200, 745 bytes). The process did not fetch `example.com`. The access log recorded `GET http://example.com/api/search 200` (the query string was still removed).
- `Content-Length` with surrounding whitespace. `Content-Length:  0 `, `Content-Length:  1`, and a tab before `0` each returned `HTTP/1.1 200` for `/healthz` with the handler security headers. The value is stripped before the limit check. This is not a traceback leak.
- Error bodies are fixed JSON. Captured 400, 404, 405, 413, 414, 421, 429, 501, and 503 bodies are the short `error` strings above. No body contained `Traceback`, a filesystem path, or an environment value. `tests/test_server.py::test_internal_error_hides_the_exception` covers the handler 500.
- XSS surface of the page. `app/static/index.html` loads `/static/app.js` and sets `<meta name="referrer" content="no-referrer">`. It has no inline script. `app/static/app.js` puts result text in `textContent` (lines 3 and 11) and allows URLs only through `safeUrl` (https, or the page's own origin, with userinfo rejected, lines 25–37). A search for `innerHTML` in `app/static` found none. `favicon.svg` has no script. A fixture title `Salvation by Faith <script>alert(1)</script>` came back inside the JSON string. `Content-Type` is JSON and `X-Content-Type-Options` is `nosniff`. The page does not interpret that title as HTML.
- Query privacy on the classic path. The access log dropped `CongregantUniqueNameZZZ`. The JSON body echoed `query`, which is what the page needs. A proxy in front of this process must not log the request target: `q` is on the wire because search is GET (`app/static/app.js` builds `/api/search` or `/api/side` with `URLSearchParams`, and it auto-runs when the page URL already has `?q=`). Retention of proxy logs is go-public gate item 5 in `docs/DEPLOY.md`.
- `X-Forwarded-For` is ignored when the peer is not trusted. `X-Forwarded-For: 198.51.100.7, 203.0.113.9` on `/healthz` returned 200, and neither address appears in the probe log. The key stayed `127.0.0.1`. Covered by `tests/test_exposure.py::ClientKeyTests.test_untrusted_peer_ignores_forwarded_for` and `ForwardedForTests.test_spoofed_forwarded_for_with_no_trusted_proxies`.
- Dependency surface, read from `pyproject.toml` and `uv.lock`. Runtime dependencies are `numpy` 2.5.4, `onnxruntime` 1.31.1, and `tokenizers` 0.23.3 (declared floors `numpy>=2.1`, `onnxruntime>=1.20`, `tokenizers>=0.21`). Optional `transcribe` and `youtube`, and the `bench` group (torch), are not default. `default-groups = []`. The probe used `--bm25-only`, so the ONNX graph was not loaded. `.venv` is the trust boundary `docs/DEPLOY.md` already names. No CI dependency scan is go-public gate item 8 (the repo has no `.github/`). That item is open there; it is not a new gap.

## Already fixed on main (not re-opened)

`reports/W3-EXPOSURE-HARDEN.md`, `reports/W3-EXPOSURE-NITS.md` (open issues: none), `reports/W3-EXPOSURE-FIX5.md`, and `tests/test_exposure.py` already cover, and this audit treated as holding:

- Client key from the socket peer unless the peer is in `PREACHED_TRUSTED_PROXIES`; then the right-most untrusted `X-Forwarded-For` hop. IPv6 keyed by /64, Tailscale `fd7a:115c:a1e0::/48` per address. Tests: `ClientKeyTests`, `Ipv6KeyTests`.
- Spoofed `X-Forwarded-For` from an untrusted peer. Tests: `ForwardedForTests`.
- `/healthz` rate and in-flight buckets separate from search. Tests: `HealthBucketTests`, `RefundAndHealthSlotTests`.
- Slot fairness, idle eviction, header deadline, and scarce idle timeout. Tests: `SlotFairnessTests`, `EvictionOrderTests`.
- `Expect: 100-continue` does not bypass the in-flight slot, and a finished GET releases its slot. Tests: `SlotReleaseTests`, `RequestSlotRaceTests`.
- Query string removed from the access log; refusal lines rate-limited. Tests: `AuditLogTests`.
- Listen backlog 128. `reports/W3-LISTEN-BACKLOG.md` and `tests/test_listen_backlog.py`.

`docs/DEPLOY.md` "Known gaps" (thread per connection, health reserve is best-effort, the 32-address lockout, trusted-proxy forgery by any local `127.0.0.1` process, one shared bucket when `PREACHED_TRUSTED_PROXIES` is empty behind `tailscale serve`, no TLS in the process, a garbage forwarded hop keys on the proxy) stay as written there. The go-public gate items are still the list in Part 4. F-01 is the new item on top of the shared-peer gap: the shared key can now be stuck, not only rate-limited, and `/healthz` will not show it.

## Prioritized fixes

Small PRs, in this order:

1. Release the in-flight slot on 405 (F-01). Test: four 405s, then `GET /api/search` is 200 and the slot table is empty.
2. Log a church search failure as the exception type only (F-02). Move the `tests/test_deploy_alerts.py` pin in that same PR.
3. Add the handler security headers to the accept-thread 503, and `Permissions-Policy`, `Cross-Origin-Opener-Policy`, and `Cross-Origin-Resource-Policy` on handler responses (F-04). Leave HSTS off on plain HTTP.
4. Default the kill-file path in `main` the way `serve.sh` does, and log one line when it engages and one when it clears (F-05).
5. Refuse `--host 0.0.0.0` and `--host ::` without an explicit acknowledgement (F-03). Leave public exposure to the go-public gate.
6. Clamp the rate-limit and health-reserve env values at startup (F-07).
7. Answer an HTTP/2 preface with a headered 505 and a close (F-06).
8. Note in the hardening table that static and page GETs spend the search rate budget (F-07). That is a docs sentence, not a second limiter.

## Cache snapshot

`find /cache -maxdepth 3 -printf '%p %s %T@\n' | sort` was taken before the first probe process and after the last probe process had been stopped by PID.

One line differs. `/cache/index/wesley.sqlite-shm` stayed 32768 bytes. Its mtime moved from `1793496003.2430169390` to `1793498230.8235476600` (`2026-10-31 21:57:10 -0400`). `/cache/index/wesley.sqlite` and `/cache/index/wesley.sqlite-wal` were unchanged, and the wal file was still 0 bytes. At the after snapshot no process had the real index open.

This audit's server was started with `--index` on a file under `/tmp/w5-audit/` and with all seven cache variables under `/tmp/w5-audit/`. That environ was read from the live process. The shm mtime is the only difference, and it is a reader timestamp on the shared index, not a size change from this audit.
