# W3-KEEPALIVE-CAP: idle keep-alive holding the per-IP connection cap

Branch `fix/w3-keepalive-cap`, cut from `origin/main` at `b224281`. Nothing was deployed. The repro bound `127.0.0.1` only.

The per-IP cap is `DEFAULT_MAX_CLIENT_CONNECTIONS = 4` (`app/server.py:243` on that tree). The repro server did not set `PREACHED_MAX_CLIENT_CONNECTIONS`.

## Repro

Server, from this worktree before the fix, BM25 only:

```bash
PREACHED_CACHE=/cache uv run python app/server.py --bm25-only --port 8765
```

Log: `INFO BM25 only`, `PREACHED_LISTENING http://127.0.0.1:8765`. Clients were `http.client` keep-alive connections and one raw socket bound to `127.0.0.2`. Same IP means `127.0.0.1`.

| Step | Result |
| --- | --- |
| `GET /api/search?q=grace&k=3` with no holders | 200 in 0.007 s |
| `GET /healthz` with no holders | 200 in 0.003 s |
| Four keep-alive `GET /healthz` from 127.0.0.1 | each 200 in 0.002–0.004 s, `Connection` header absent, `will_close` false |
| Fifth request, same IP, `GET /api/search?q=grace&k=3`, `Connection: close`, 5 s timeout | 503 in 0.00020 s |
| Same search sourced from 127.0.0.2 | 200 in 0.0025 s |
| Fifth same-IP `GET /healthz` | 503 in 0.00016 s |
| `recv` on the first idle holder | empty after 15.002 s (server closed it) |
| Search again while the other three holders were still up | 200 in 0.003 s |
| Six parallel keep-alives (page, css, js, `/favicon.svg`, two `/healthz`) | 200, 200, 200, 404, 503, 503. The two 503s carried `Connection: close` and returned in under 1 ms. `/favicon.svg` is the probe path; the page asks for `/static/favicon.svg` |
| Search while those four 200/404 sockets were still held | 503 in 0.00021 s |
| Retry the search every 0.5 s while four idle keep-alives were held | 503 on tries 1–30, 200 on try 31. Time to 200: 15.019 s |
| One uncontended keep-alive, then `recv` | server closed it after 15.015 s |

Headless Chrome 155.0.8059.84, two `Target.createBrowserContext` (separate socket pools), same server:

- One page load held 2 connections. A second context navigating to `/?q=grace` finished in 0.231 s with status "10 passages." and 20 cards. Two plus two fits in the cap of 4.
- Context A then ran six parallel `fetch('/healthz')`: statuses 200, 200, 200, 200, 503, 503, and the server had 4 connections from that client.
- While those four were held, context B `fetch('/api/search?q=grace')` returned 503 in 2 ms, body `{"error":"unavailable"}`. A direct navigation in a third context got the same JSON in 0.028 s.
- `Page.navigate` of context B to `http://127.0.0.1:8765/?q=grace` while the cap was full: at +0.02 s the URL was that page, `readyState` was `complete`, and the document body was `{"error":"unavailable"}`. Polled for 70 s, the document was still that JSON at 70.007 s. Chrome did not retry the navigation when the idle sockets later closed.

The accept path answers at once with 503. It does not sit for 60 s. What sits is the cap: the first client's idle keep-alives occupy all 4 slots until the header deadline (measured 15.0 s) or until that client closes them. A second client on the same IP is refused for the whole wait. A document that already committed as the 503 body stays that page, which is the hang until the first tab's sockets are gone and the page is loaded again. A phone and a laptop behind one NAT share this cap.

## Cause

On `origin/main` (`app/server.py`):

- HTTP/1.1 leaves the socket open. After the response, `mark_idle` (`2606–2612`) sets `busy` and `reading` false and moves `since` to now. The socket stays in `_conns` and `_conn_by_ip` until the handler leaves `readline`.
- `handle_one_request` (`1949–1958`) waits for the next request line under `HEADER_DEADLINE_S` (15.0, line 240). `scarce_idle_s` (2.0, line 249) applies only when a quarter of the global slots or fewer are free. Four of 32 is not scarce, so the idle socket holds its slot for 15 s. The repro's 15.002 s and 15.015 s closes are that deadline.
- `_acquire_connection` (`2548–2549`) returns false as soon as `held >= max_connections_per_client` for an untrusted peer. There is no per-IP eviction. `_pick_victim` runs only when the global cap is full, and only against a peer holding at least two more than the newcomer (`2498–2523`).
- `process_request` (`2639–2643`) then sends the 503 on the accept thread: `_reject_over_cap` (`2661–2676`) writes `{"error":"unavailable"}`, `Connection: close`, `Retry-After: 1`, and starts no handler thread.

That is why four finished keep-alives from one tab make the next connection from the same IP a 503 until one of them hits the header deadline.

## Fix

Idle sockets still count toward the per-IP cap. A peer already at that cap may take its own oldest socket once the socket has been quiet for `KEEPALIVE_IDLE_S` (1.0 s). The hand-over is the same `shutdown(SHUT_RDWR)` and `refused evict holder->holder` log the global path already uses.

`KEEPALIVE_IDLE_S` is a constant (`app/server.py:260`). No new environment variable. `_takeable_idle` (`2540–2561`) returns the oldest socket of that holder that is not busy, not reading, not reserved, and not closed, and whose `since` is at least 1.0 s ago. `since` is the accept time until `mark_idle` (`2655–2661`) moves it to the end of the last response, so a socket is takeable only after it has actually been sitting. `_acquire_connection` (`2586–2599`) forgets that socket under the lock, decrements the local `held` so the new connection lands on the same per-IP count, and skips global eviction (`elif`). If nothing has been quiet long enough, it returns false and the 503 is unchanged.

Why this and not the other two shapes:

- Dropping idle sockets from the per-IP count would let one address park a keep-alive on every handler thread. `test_one_client_cannot_take_more_than_its_share` requires the extra connection to be refused while those sockets are still held.
- A uniform short read timeout on the next keep-alive wait was tried at 2 s. `test_few_clients_cannot_starve_a_new_one` then closed 5 connections against an assertion of at most 4: the idle close fired during `_is_closed(..., 0.5)` on top of eviction. `test_not_scarce_keeps_the_full_deadline` holds a quiet socket for the header deadline when the server is not scarce. The header deadline and `scarce_idle_s` are unchanged (`handle_one_request`, `1960–1969`).

1.0 s is long enough that a connection opened immediately, while the quiet period is still running, is still refused, and short enough that the new test's bound is 3.0 s.

## Why the #29 protections still hold

- The slot is still released in `Handler.finish` after `super().finish()` flushes the body (`1947–1958`). An interim 100 Continue is not that flush. A slow reader keeps the slot until the body is out. `process_request_thread` (`2700–2704`) still releases as a backstop.
- Inside the quiet second, and whenever every socket of that peer is busy or still reading, `_acquire_connection` returns false. The 503, `Retry-After: 1`, and accept-thread reject are the same (`2688–2693`, `2710–2725`).
- A socket with `reading` set (request line arrived, headers still coming) is not takeable. The single header deadline is unchanged, so a slowloris that has started its headers still holds the slot until that deadline. A different peer still cannot take the socket unless the global cap is full and `_pick_victim`'s "at least two more" rule says so.
- Busy sockets and reserved `/healthz` connections are not takeable. The health reserve still runs only on the global-cap path.
- A trusted proxy still skips the per-IP check. IPv6 `/64` keying, per-key in-flight request slots, and the separate `/healthz` request table are untouched.
- A same-peer hand-over decrements `held` because `_forget` has already dropped that holder's count, then stores `held + 1`, so the per-IP total does not grow. `_conn_total` drops in `_forget` and is incremented again for the newcomer. Global eviction of someone else's socket does not also run.

## Mutant

The at-cap branch was put back to `return False`, and the following check back to `if`, leaving `_takeable_idle` unused. Then restored.

With the hand-over removed, `PREACHED_CACHE=/cache uv run python -m unittest tests.test_keepalive_cap`:

```
test_an_active_flood_still_stops_at_the_cap ... ok
test_idle_keepalive_frees_the_per_ip_slot ... FAIL

AssertionError: 503 != 200 : b'{"error":"unavailable"}'
  File "tests/test_keepalive_cap.py", line 58, in test_idle_keepalive_frees_the_per_ip_slot
    self.assertEqual(status, 200, body)

Ran 2 tests in 3.865s
FAILED (failures=1)
```

The flood test stayed green: two in-flight searches still held the cap past 1 s and the next search was 503. The idle test failed because the header deadline in that test is 30 s, so the quiet socket was still holding the only slot.

Restored, the same command:

```
test_an_active_flood_still_stops_at_the_cap ... ok
test_idle_keepalive_frees_the_per_ip_slot ... ok
  WARNING refused over-cap peer=127.0.0.2
  WARNING refused evict 127.0.0.2->127.0.0.2

Ran 2 tests in 3.866s
OK
```

The idle test refuses the search that arrives inside the quiet second, then after `KEEPALIVE_IDLE_S + 0.4` the next search is 200 in under 1 s and the held socket is the one closed. Wall time of the quiet wait plus that search is asserted under 3.0 s. The flood test sleeps past 1 s with two blocked `q=hold` searches, still gets 503 with `Retry-After: 1` and `{"error":"unavailable"}`, leaves both sockets open, then reads 200 from each after release.

## Tests

```bash
cd /work/preached/.worktrees/fix/w3-keepalive-cap
PREACHED_CACHE=/cache uv run python -m unittest discover -s tests
uv lock --check
```

`uv lock --check`: `Resolved 79 packages in 0.73ms`. No lockfile change.

Full suite: `Ran 1007 tests in 235.550s`, `FAILED (failures=52)`. All 52 are `test_deploy_alerts.RunbookTests.test_every_cited_file_line_holds_its_string` for `app/server.py`. The same 52 cites miss on unmodified `origin/main:app/server.py` (the pin list was written against an older tree; `REQUEST_TIMEOUT_S = 15` is line 234 there, and the cite says 231). Nothing else failed. `tests.test_keepalive_cap` and the #29 suites in `tests/test_exposure.py` (`SlotFairnessTests`, `SlotReleaseTests` including the 100-continue case, `EvictionOrderTests`, `RequestSlotRaceTests`, `ReconnectRetryAfterTests`) and `tests/test_deploy.py` (`test_header_deadline_is_not_per_read`, `test_connection_caps_reject_without_a_handler_slot`) are in that run and are not among the failures.

## Re-pin and CTO round (after main `b2c7b77`)

Merged `origin/main` (`b2c7b77`, which contains PR #73 `docs/w3-deploy-r4-cond`) with a merge commit. No rebase. PR #69 and PR #97 are not on that main, so the early pins did not take an extra +3.

`gh` is not installed here, so PR #72 comments beyond the task file were not read. The findings in the task are applied below.

### Cites

Every `app/server.py` cite in `docs/DEPLOY.md` and every `app/server.py` entry in `CITED` (`tests/test_deploy_alerts.py`) was checked by reading the line, not by adding the shift and stopping. `RunbookTests` then passed: the needle is on that line, and the runbook cites exactly the pinned set. Cites of `src/preached/library.py`, `src/preached/youtube/`, and `scripts/build-bundle.sh` are unchanged.

Relative to main after R4-COND:

| Pins on main | Shift from the hand-over | Read on this tree |
| --- | --- | --- |
| `:234`, `:240` | +3 (module docstring) | `:237` `REQUEST_TIMEOUT_S = 15`, `:243` `DRAIN_TIMEOUT_S = 10.0` |
| 38 pins, `:273`–`:2370` | +11 (`KEEPALIVE_IDLE_S` block) | D1 `:839` → `:850` `logging.exception(MISMATCH_LOG)`; D2b `:1214` → `:1225`; text `:284` `:285` `:286` → `:295` `:296` `:297` |
| 12 pins, `:2765`–`:3219` | +44 from the hand-over code, then +5 from the N2/N3 comments | `listening on` `:2814`; `stopped cleanly` `:3268`; stuck range `:3252–3270` (`stuck = server.drain()` … `raise SystemExit(1)`) |

The hand-over alone would have put `stopped cleanly` at `:3263` (main `:3219` + 44; the pre-R4 cite `:3216` + 47). The two comments below sit above that region and move those twelve pins five lines further. That is the file.

### Guards

Four tests in `tests/test_keepalive_cap.py`. Each was run against its mutant, then with the mutant reverted.

- `test_a_partial_header_socket_is_not_handed_over`. Same peer, request line and one header, quiet for more than 1 s. The newcomer is 503 and the half-sent socket still answers 200. Mutant drops `conn.reading` from `_takeable_idle`: the newcomer got 200. Restored: pass.
- `test_a_busy_peer_cannot_close_another_peers_idle_socket`. Global cap is not full. `127.0.0.3` is at its cap on two busy searches and cannot close `127.0.0.2`'s idle keep-alive. Mutant drops `conn.holder != holder`: the newcomer got 200. Restored: pass.
- `test_hand_over_leaves_the_per_ip_count_at_the_cap`. After the hand-over `_conn_by_ip[peer]` equals the cap, and it is 0 once every socket has closed. Mutant drops `held -= 1`: the count was 2, not 1. Restored: pass.
- `test_a_reserved_healthz_socket_is_never_handed_over`. A `/healthz` socket admitted on the reserve, still waiting for its request, is not taken. Mutant drops `conn.reserved`: the newcomer got 200. Restored: pass.

### Notes

N2: the quiet-period probe must run within 1 s. Commented on the `KEEPALIVE_IDLE_S` check in `_takeable_idle` and on the probe in `test_idle_keepalive_frees_the_per_ip_slot`.

N3: a request that arrives on the idle socket at the moment of the hand-over is dropped. Commented in `_acquire_connection`, and said in the Connections row of `docs/DEPLOY.md`.

S3: that row now describes the same-peer hand-over, and says that clients sharing a NAT or an IPv6 /64 can close each other's idle keep-alives, which is intended.

`church-alerts.yaml` is not on this machine (`/workspace/infra-ops/preached/alerts/church-alerts.yaml` is absent). TODO for CoS: supply the full sha256 of Infra Ops' current yaml (the task names the prefix `42dd7e7c`, 25 rules, all `enabled: false`) and replace the guide's `447cd7e283cba91169e695feb6d39bdf7642522e3d1c587e959f879ef7ea4f29`. The guide is unchanged on that point.

`uv lock --check`: `Resolved 79 packages in 0.61ms`. No lockfile change.

Full suite, from this checkout:

```bash
PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests
```

`Ran 1011 tests in 254.683s`, `OK`. Zero failures. Exit 0.

## Scope

`app/server.py` (hand-over, plus comments only for the quiet-period probe and the dropped request), `tests/test_keepalive_cap.py`, `docs/DEPLOY.md` (cites and the Connections row), `tests/test_deploy_alerts.py` (`CITED` only), this report. No new dependency. `serve.sh` and `README.md` are unchanged.

## Diff stat

`git diff --stat origin/main..HEAD`:

```
 app/server.py               |  55 +++++++++++-
 docs/DEPLOY.md              | 123 +++++++++++++-------------
 reports/W3-KEEPALIVE-CAP.md | 184 ++++++++++++++++++++++++++++++++++++++
 tests/test_deploy_alerts.py |  92 +++++++++----------
 tests/test_keepalive_cap.py | 209 ++++++++++++++++++++++++++++++++++++++++++++
 5 files changed, 552 insertions(+), 111 deletions(-)
```
