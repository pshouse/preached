# W3-EXPOSURE-HARDEN: server hardening before anything goes public

Branch `feat/w3-exposure`, cut from `origin/feat/w3-deploy-prep` at `2eebe78` (PR #18, not merged). PR base: `feat/w3-deploy-prep`. Nothing was deployed or exposed. The bind stays on loopback or Tailscale. This work did not contact the Sprite or read any credential.

Merges, both as merge commits, no rebase, no force-push. `origin/feat/w3-deploy-prep` was still at `2eebe78`, so that merge was already up to date. `origin/main` at `ef4d4eb` (#23, #24) was merged as `34345b3` with no conflicts.

## What was done

| CTO item | What changed | Commit | Tests (raw socket unless noted) |
| --- | --- | --- | --- |
| 1a. Trusted-proxy `X-Forwarded-For` keying | `PREACHED_TRUSTED_PROXIES` takes comma-separated addresses or networks and defaults to empty. A malformed entry, or one with host bits set, stops start-up. XFF is read only when the socket peer is in that list. Hops are read right to left and trusted hops are skipped. The first untrusted hop is the key. Hops to its left are never read. A hop that does not parse keys on the nearest trusted address. IPv4-mapped IPv6 is folded to IPv4. At most 32 hops are read. `Forwarded` (RFC 7239) is ignored. | `1966c70` | `test_spoofed_forwarded_for_from_an_untrusted_peer_is_ignored` (127.0.0.2 sends a different fake XFF on each request and still gets 429 on the third), `test_spoofed_forwarded_for_with_no_trusted_proxies`, `test_trusted_proxy_keys_on_the_right_most_untrusted_hop` (a client-prepended hop and a chain of trusted hops are both handled), plus unit tests `ClientKeyTests` (7) |
| 1b. Global backstop | One window over all clients. Search: `PREACHED_GLOBAL_RATE_LIMIT`, 1200 per 60 s in code and 600 in `serve.sh`. The per-client bucket is checked first, so a client already over its own cap does not spend the backstop. | `1966c70` | `test_global_backstop_caps_many_clients`, `test_a_client_over_its_own_cap_does_not_spend_the_backstop`, `test_backstop_counts_proxied_clients` |
| 2. Per-client slot fairness | (a) When all slots are taken, a newcomer gets the slot of the longest-idle connection belonging to the peer that holds the most. That peer must hold at least 2 more connections than the newcomer. "Idle" means between requests or still sending headers. A request being handled is never closed. The victim gets `shutdown(SHUT_RDWR)`, and its slot moves to the newcomer under the lock. (b) Once a quarter of the slots or fewer are free (8 of 32), a connection waiting for its next request gets `PREACHED_SCARCE_IDLE_S` (2 s) instead of the 15 s header deadline. (c) In-flight requests are capped per client key (`PREACHED_MAX_CLIENT_REQUESTS`, 4). Over the cap: 503, `Retry-After: 1`, `Connection: close`. (d) A trusted proxy is exempt from the per-peer connection cap, because its clients are only distinguishable after the headers arrive. | `1966c70`, `2dd2189` | `test_few_clients_cannot_starve_a_new_one` (4 peers × 2 keep-alive connections fill 8 slots, and 4 newcomers each get 200), `test_slow_header_senders_are_closed_for_a_newcomer`, `test_requests_in_flight_are_never_closed`, `test_no_churn_between_equal_clients`, `test_one_client_cannot_take_more_than_its_share`, `test_keep_alive_idle_is_bounded_when_scarce`, `test_not_scarce_keeps_the_full_deadline`, `test_trusted_proxy_connections_and_per_client_request_slots` (includes a spoofed left hop that still hits the cap), `test_direct_peer_request_slots` |
| 3. `/healthz` in its own bucket | A separate per-client table (`PREACHED_HEALTH_RATE_LIMIT`, 60 per 60 s) and a separate global backstop (`PREACHED_HEALTH_GLOBAL_RATE_LIMIT`, 600). It uses the same client key as search. | `1966c70` | `test_search_flood_does_not_starve_healthz` (per-client and global search budgets spent, healthz still 200), `test_healthz_flood_does_not_spend_the_search_budget`, `test_healthz_has_a_global_backstop_of_its_own`, `test_healthz_bucket_follows_the_trusted_proxy_key` |
| Threat model draft (docs only) | `docs/DEPLOY.md` has a new "Threat model (DRAFT, not final)" section: assets, attackers, entry points, controls, known gaps, and the remaining gate (CTO sign-off, then Patrick's approval, then a kill-switch drill). The Hardening table, the Tailscale proxy note, and the release notes were updated. | `8069c2f` | `test_threat_model_draft_lists_the_gate`, `test_serve_sh_passes_the_new_settings` (not socket tests) |

`scripts/serve.sh` passes the six new variables through `env -i`. It sets `PREACHED_GLOBAL_RATE_LIMIT` to 600 by default and never sets `PREACHED_TRUSTED_PROXIES`.

Changed existing tests, both in `tests/test_deploy.py`:
- `test_healthz_uses_the_same_bucket` is now `test_healthz_has_its_own_bucket`, because item 3 reverses that contract.
- `test_per_ip_limit_ignores_forwarded_for` spends its budget on searches instead of `/healthz`. It still asserts that XFF from an untrusted peer is ignored.

Mutation checks. Each mutation was applied by hand, run, then reverted. Every one failed at least one test:
- eviction off: 6 failures
- trust every peer: 6
- left-most hop: 6
- `/healthz` back in the search bucket: 4
- scarce bound off: 1
- global backstop off: 4
- request slots off: 2
- busy connections evictable: 1

Byte identity: `scripts/compare_responses.py` starts the base tree (`feat/w3-deploy-prep` `2eebe78`) and this tree with `--bm25-only` on the real Wesley index. It sends the same raw requests to both. The paths cover search (200 and three 400s), side, sermon (two 200s and two 404s), the page, `app.js`, and a 404. Result: **13/13 identical** after masking `Date`, `took_ms`, and `Content-Length`. `Content-Length` changes only when `took_ms` changes width.

## How to run

```bash
cd /work/preached/.worktrees/feat/w3-exposure
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_exposure
uv lock --check
python3 -I scripts/compare_responses.py /work/preached/.worktrees/feat/w3-deploy-prep "$PWD"
# Behind a local proxy only (example):
PREACHED_TRUSTED_PROXIES=127.0.0.1 scripts/serve.sh
```

## Results and numbers

- `uv run python -m unittest discover -s tests`, after both merges: **634 tests, 79.9 s, OK**. `tests/test_exposure.py` adds 28 of them. `test_exposure` alone passed 5 runs out of 5 (about 14.6 s each).
- `uv lock --check`: clean (79 packages resolved). No lockfile change.
- Head SHA: the commit that adds this report. `git rev-parse HEAD` on `feat/w3-exposure` gives it. The last code and merge commit before the report is `34345b3`.

## Open issues, risks, exclusions

- Not deployed and not public. The go-public gate is still open: the threat model is a draft, and CTO sign-off, Patrick's approval, and the kill-switch drill have not happened.
- The connection caps run at accept time, before the path is known, so `/healthz` has no reserved connection slot. Eviction of idle connections is what keeps a slot free. If 32 requests are all busy, healthz gets 503.
- Eviction closes an idle keep-alive connection without a response. That is normal HTTP keep-alive behaviour, and clients retry idempotent GETs. A request that arrives just as its connection is closed is dropped. `mark_busy` stops a request whose connection was already handed away.
- IPv6 clients are keyed per full address, not per /64. Many addresses still meet the global backstop.
- A trusted proxy that writes a garbage hop puts those clients in the proxy's bucket (fails closed).
- `tailscale serve` was not tested as a proxy here. DEPLOY tells the operator to check that it appends XFF before listing `127.0.0.1`.
- The PR could not be opened from this machine because the `gh` CLI is not installed. The branch is pushed. See the PR section below.
- No RSS or latency re-run. The change adds a lock and some dictionary work per connection and per request.

## Dependencies added and why

None. `ipaddress` and `socket` are stdlib. No LLM, no new model.

## Fix-up: CTO round 1 of PR #29 (32-W3-EXPOSURE-FIX)

Review of `6217aa4`: CHANGES. Nothing was deployed, nothing was bound to a public interface, and the Sprite was not contacted. No new dependencies.

Merge: `origin/feat/w3-deploy-prep` is at `06bd034`, which includes 30-W3-DEPLOY-FIX5's bytecode fix (`7623d48`). FIX5 had been pushed, and this branch already merged it at `34f3880` (a merge commit). `git merge --no-ff origin/feat/w3-deploy-prep` therefore reported "Already up to date", so there is no new merge commit. No rebase, no force-push.

| Item | What changed | Commit | Tests |
| --- | --- | --- | --- |
| **M1, eviction closed a half-sent request.** | `_Connection.reading`. `mark_reading(request)` sets `reading=True, since=now`. `handle_one_request` calls it once `rfile.readline` returns a non-empty request line. `_pick_victim` runs two passes. The first takes only connections that are not busy, not reading and not reserved. The second, which also takes reading connections, runs only when no eligible peer has an idle one. `mark_idle` and `mark_busy` clear `reading`. | `e594d74` | (a) `test_half_sent_request_gets_a_response`: the CTO's pD scenario. 4 slots; 127.0.0.5 holds 3 and 127.0.0.6 holds 1. .5 half-sends on its oldest connection, and a newcomer from .9 gets 200. .5 finishes its headers and **gets 200**. Its oldest *idle* connection is the one closed, and the others still answer. (b) `test_the_oldest_idle_connection_is_the_one_closed`. (c) `test_mark_busy_is_false_after_a_hand_over`, plus `test_reading_is_taken_only_when_no_idle_one_is_left` (the fallback, and `mark_idle` clearing the flag). |
| **M2, audit log.** | `log_request` writes `peer key method path status`, with both addresses escaped like the peer. The key is the request's rate key, or is worked out from the headers for errors raised before routing. It is reset for every request, because a proxy can carry several clients on one keep-alive connection. `RefusalLog` writes `refused <class> <detail> suppressed=N` as a warning, at most once per class per second. The classes are `over-cap` (accept-time 503), `evict` (`holder->newcomer`), `busy` (per-key in-flight 503, or a non-healthz request on the reserve), and `429-client`, `429-global`, `429-health` and `429-health-global` (`RateLimiter.name`). | `e594d74` | `test_proxied_request_logs_the_forwarded_key` (the line ends `127.0.0.9 198.51.100.7 GET /healthz 200`, and the query is dropped), `test_direct_request_logs_peer_twice_and_ipv6_keys_by_64`, `test_each_429_class_is_logged` (all four classes), `test_over_cap_and_eviction_are_logged`, `test_refusal_lines_are_rate_limited_with_a_count` |
| **M3, DEPLOY go-public gate.** | Before CTO sign-off, in both "Going public" and "Remaining go-public gate items": the RSS fix (#26; still 1.62 GB with dense on), audit logging (M2), an end-to-end test through real `tailscale serve`/`funnel`, and per-/64 IPv6 keying (M4). DEPLOY now states that public exposure goes only through Tailscale with `PREACHED_TRUSTED_PROXIES=127.0.0.1`, and that eviction matters only for a direct bind. Known gaps adds the 32-address lockout (65/65 503s; #18 behaves the same), a local process on the Sprite acting as the trusted proxy and forging keys, and the peer-only log before M2. The stale "IPv6 per address" and "no reserved healthz slot" gaps were replaced. The Logs row, Hardening, the proxy note and the release notes were updated. | `7ac9b0e` | `test_go_public_gate_has_the_round_one_items_before_sign_off`, `test_serve_sh_passes_the_health_reserve` |
| **M4, IPv6 by /64.** | `address_key()`: an IPv6 address is keyed by its `/64` network, and IPv4 and IPv4-mapped addresses stay per address. It is used for every key `client_key` returns (direct peer and forwarded hop) and for the connection holder. The trusted-proxy check still uses the full address. | `e594d74` | `Ipv6KeyTests`: key unit cases (direct and through a proxy), a shared rate bucket for addresses in one /64, and a shared per-peer connection cap. `test_mapped_ipv6_and_ipv6` was updated to expect `2001:db8:1::/64`. |
| Should 1: the backstop spent the client's bucket. | `RateLimiter.refund(key)`. `App.allow` refunds the client hit when the global (or health-global) limiter refuses. | `e594d74` | `test_a_global_refusal_does_not_spend_the_client_bucket` (search and healthz) |
| Should 2: reserve a /healthz slot. | When the cap is reached and nothing can be evicted, up to `PREACHED_HEALTH_RESERVED_CONNECTIONS` more connections are admitted (default 1, 0 turns it off; `serve.sh` passes it). A reserved connection is never an eviction victim. It serves one `/healthz` with `Connection: close`. Any other path on it gets 503 `unavailable` and a close. | `e594d74` | `test_reserved_connection_serves_healthz_once_and_only_healthz`. `test_requests_in_flight_are_never_closed` now expects a search to get 503 and `/healthz` to get 200 from the reserve. |
| Should 3: own /healthz behind own searches. | `acquire_slot`/`release_slot(key, health=)`: `/healthz` uses its own per-key in-flight table. | `e594d74` | `test_own_healthz_while_own_searches_fill_the_request_slots` |
| Should 4: compare_responses coverage. | Three server pairs (default, `PREACHED_RATE_LIMIT=2`, `PREACHED_MAX_CLIENT_CONNECTIONS=1`) on `--port 0`. The `PREACHED_*` environment is scrubbed, and `PREACHED_CACHE` is set explicitly (default `/cache`). The cases add `/healthz`, five HEADs, two keep-alive pairs, an untrusted XFF, the 429 path (including rotated XFF and HEAD), and the accept-time 503. | `b0067a1` | run below |

Changed existing tests. To keep the eviction tests meaningful now that a reserve exists, four newcomer requests are searches instead of `/healthz`: `test_few_clients_cannot_starve_a_new_one`, `test_slow_header_senders_are_closed_for_a_newcomer`, `test_no_churn_between_equal_clients` and `test_requests_in_flight_are_never_closed`. A `/healthz` newcomer would otherwise get 200 from the reserve even with eviction broken.

### Mutation checks (re-run)

Each mutant was applied by hand and run against `tests.test_exposure` and `tests.test_deploy` (93 tests), then reverted. `cmp` confirmed the file was restored.

- `conn.since < best[0]` → `>`: **4 failures** (`test_half_sent_request_gets_a_response`, `test_the_oldest_idle_connection_is_the_one_closed`, `test_mark_busy_is_false_after_a_hand_over`, `test_reading_is_taken_only_when_no_idle_one_is_left`). In round 0 this mutant survived.
- `mark_busy` ignores `closed`: **1 failure** (`test_mark_busy_is_false_after_a_hand_over`). In round 0 this mutant survived.

### Numbers

- `uv run python -m unittest discover -s tests` at `b0067a1`: **659 tests, 103.6 s, OK**. That is 25 more than round 0's 634. `tests.test_exposure` now has 45 tests and passed 5 of 5 runs (about 20 s each).
- `uv lock --check`: clean, 79 packages resolved. The lockfile did not change.
- Byte identity: `python3 -I scripts/compare_responses.py /work/preached/.worktrees/feat/w3-deploy-prep "$PWD"` (base `06bd034`, real Wesley index, `--bm25-only`) gives **28/28 identical**, with Date, `took_ms` and Content-Length masked.
- Head SHA: the commit that adds this section (`git rev-parse HEAD` on `feat/w3-exposure`). The last code commit is `b0067a1`.

### Notes and limits

- `mark_reading` starts at the request line. A client that drips the request line itself (no newline yet) still counts as idle. A client that sends a request line and then drips headers is protected until its peer's idle connections are gone. The header deadline still bounds both: 15 s, or 2 s when slots are scarce.
- One client can hold the single reserve for up to the scarce header deadline and then reconnect, so the reserve is a best effort. DEPLOY lists this under Known gaps.
- The 32-address lockout is documented, not fixed. On a direct bind it would need a different victim rule; behind Tailscale there is one peer and eviction never runs.
- The access log has one more field. Anything that parses it by position needs updating, and the release notes say so.
- Behind a trusted proxy, addresses in that proxy's own /64 share its holder count. The intended proxy is `127.0.0.1`, so this does not come up in practice.
- `tailscale serve`/`funnel` was still not tested as a proxy. It is now a gate item.

## Round 2 fixes: CTO round 2 of PR #29 (42-W3-EXPOSURE-FIX2)

Review of `9fa2451`: CHANGES. Nothing was deployed, nothing was bound to a public interface, and the Sprite was not contacted. No new dependencies. The task named `reports/W3-EXPOSURE.md`; that file does not exist, so this section is appended to the PR's report, `reports/W3-EXPOSURE-HARDEN.md`. The review file `/workspace/reports/preached-pr29-review.md` is not on this machine, so the items below follow the review text in the task.

Merge: `git merge origin/main` (main at `efdf8ab`, which includes `eb4d48a`) made merge commit `5f14714`. The only conflict was the `app/server.py` import block (#32 moved `import signal` to the top). Resolved as the CTO did: the hunk keeps only `import socket  # noqa: E402`; `import ipaddress` sits outside the hunk. No rebase, no force-push.

| Item | What changed | Commit | Tests |
| --- | --- | --- | --- |
| **M1, import conflict with main.** | Merged main and resolved as above. | `5f14714` | Full suite on the merge alone: 774 tests, OK. |
| **M2, flaky `test_requests_in_flight_are_never_closed` and the SIGSEGV.** | (1) `PreachedServer.shutdown_request` calls `_release_connection` before `super().shutdown_request` (`_forget` is idempotent; the call in `process_request_thread` stays). (2) `_Served._serve` sets `daemon_threads = False` and `block_on_close = True` on the test server, so `server_close` joins every handler thread before cleanup closes the sqlite connection. (3) **The prescribed fix did not remove the flake on its own** (see below). The client reads the whole `Connection: close` response (it has a Content-Length) and reconnects before the handler thread reaches `shutdown_request`. So the handler's `end_headers` now calls `server.closing(request)` when `close_connection` is set, which frees the slot before any byte of the last response goes out. Every body is built before `end_headers`, so nothing is still working when the slot is handed on. | `13a2208` | New `test_slot_is_free_once_a_closing_response_is_read` (healthz, search, 404): it holds each handler for 0.3 s between write and close, then checks the slot is already free and the same peer, at its cap of 1, gets straight back in. Without the `end_headers` release it fails 5/5 runs, all three subtests. `test_requests_in_flight_are_never_closed` now also asserts `_reserved_total == 0` straight after the reserve's 503. |
| **M3, go-public gate (docs only).** | Both "Going public" and "Remaining go-public gate items" now list, before CTO sign-off: #26 go-live checks on the Sprite (`/healthz` `dense: true`, `fallback: false`, `model_sha256` equal to the pin, `model/` not group- or world-writable; `umask 002` silently serves BM25 only) in place of the stale "1.62 GB" line (now 721 MiB); a #18 stale-bytecode drill and never `python -m app.server`; access-log retention and journald limits; least-privilege, scoped credentials (Sprite; tagged Tailscale node whose ACL allows only serve/funnel to the port; auth keys with expiry and rotation, by 1Password path only); fuzzing for the HTTP parser and `client_key`/XFF parsing; dependency and secret scanning in CI (no CI exists). The Tailscale e2e test is still listed as open. The threat model's "no query is stored" line now says client IP, path and time are stored. Left open for Patrick, listed as such: the retention period, serve vs funnel, and which CI. No CI workflow was added. | `5045deb` | `test_go_public_gate_has_the_round_one_items_before_sign_off` now checks each new item comes before CTO sign-off in both lists, that "1.62 GB" is gone, and that the stored-IP line is there. |
| Should: Tailscale IPv6 shares one /64. | `address_key` keys `fd7a:115c:a1e0::/48` (`TAILSCALE_IPV6`) per address. Every other IPv6 address is still keyed by /64. | `0b91810` | `test_tailscale_addresses_are_keyed_per_address` (direct, forwarded, the edge of the /48, separate rate buckets), `test_tailscale_nodes_do_not_share_the_connection_cap` |
| Should: sibling in the trusted proxy's /64. | Test only; code already trusts by the configured network. | `0b91810` | `test_a_sibling_in_the_proxys_64_is_not_trusted`: a sibling peer's XFF is ignored, and a sibling hop behind the real proxy is the client. |
| Should: deterministic `_pick_victim` test for the reserve. | Test only. | `0b91810` | `test_a_reserved_healthz_connection_is_never_taken`: `_FakeRequest`s, no sockets. A busy and a reserved connection from a peer holding 2 more than the newcomer: `_pick_victim(0)` is None, the newcomer gets the second reserve, the next is refused, nothing is shut. |
| Should: flush the suppressed refusal count. | `RefusalLog.flush()` logs `refused <class> flush suppressed=N` for each class with a pending count, then clears it. `PreachedServer.server_close` calls it, and `main()`'s `finally` already calls `server_close`. At shutdown, not on a timer. | `0b91810` | `test_suppressed_counts_are_flushed_at_shutdown` |
| Should: journald docs. | DEPLOY's host section documents journald rate limiting (`RateLimitIntervalSec=`/`RateLimitBurst=`, or `LogRateLimit*` per unit), the "Suppressed N messages" loss under a flood, and rotation (`SystemMaxUse=`, `SystemMaxFileSize=`, `MaxRetentionSec=`). No values chosen. | `5045deb` | docs |
| Should: #18 `main()` `finally` closes sqlite under live handlers. | **Not changed; follow-up.** PR #36 (`chore/w3-deploy-sigterm-nits`) is not merged. Its diff to `main()` widens the `except` to `(KeyboardInterrupt, SystemExit)` but keeps `server.server_close(); connection.close()` with `daemon_threads = True`, so `server_close` does not join handlers and a SIGTERM during a search can still close the connection under `Searcher.bm25`. A fix for main after #36: join handlers (non-daemon threads with a bounded join, or a drain counter) before `connection.close()`. That branch was not touched. | none | none |

### Mutation checks (round 2)

Each mutant was applied by a script that restored the file afterwards (it checked the content matched), and was run against `tests.test_exposure` (50 tests):

- trust widened to the proxy's /64: **1 failure** (`test_a_sibling_in_the_proxys_64_is_not_trusted`). The CTO noted this mutant survived all 45 round-1 tests.
- `_pick_victim` may take reserved connections: **1 failure** (`test_a_reserved_healthz_connection_is_never_taken`).
- no Tailscale exception in `address_key`: **2 failures** (both Tailscale tests).
- `server_close` does not flush: **1 failure** (`test_suppressed_counts_are_flushed_at_shutdown`).
- no release in `end_headers` (`shutdown_request` release kept): `test_slot_is_free_once_a_closing_response_is_read` fails **5/5**.

### Flake runs

On a quiet machine this box does not reproduce the flake: `9fa2451` passed 20/20 alone, and so did the tree without the `end_headers` release. Under CPU load (24 busy-loop processes on 24 cores) it does:

| Tree | Runs of `SlotFairnessTests.test_requests_in_flight_are_never_closed` alone | Failed |
| --- | --- | --- |
| `9fa2451` (round-1 head), loaded | 20 | **4** (all `503 != 200` on `/healthz`, the CTO's failure) |
| `shutdown_request` release + thread join only (CTO's fix as written), loaded | 50 | **6** |
| final head, quiet (`-X faulthandler`) | 50 | **0** |
| final head, loaded | 50 | **0** |

`SlotFairnessTests` on the final head, `-X faulthandler`: **0/10 failed** quiet and **0/10 failed** loaded, every exit code 0 (no 139). Script: `/tmp/m2scripts/flake.sh` (not committed). It is a loop of `uv run python -X faulthandler -m unittest tests.test_exposure.SlotFairnessTests.test_requests_in_flight_are_never_closed` (50×), then `tests.test_exposure.SlotFairnessTests` (10×).

### Numbers

- `uv run python -m unittest discover -s tests` on the final code (`5045deb`): **780 tests, 109.1 s, OK**. That is 774 from main plus round 1, plus 6 new tests in `tests.test_exposure`, which now has 51.
- `uv lock --check`: clean, 79 packages resolved. The lockfile did not change.
- Byte identity: `python3 -I scripts/compare_responses.py <origin/main worktree> "$PWD"` gives **28/28 identical** (Date, `took_ms` and Content-Length masked).
- Head SHA: the commit that adds this section (`git rev-parse HEAD` on `feat/w3-exposure`). The last code commit is `0b91810`, and the last docs commit is `5045deb`.

### Notes and limits

- The per-key in-flight request slot (`acquire_slot`) is still released after the response is written, in `_respond`'s `finally`. A client that fires a new search on another connection the instant it reads a response could get a spurious `busy` 503. That is the same race class as M2, but not one the review raised. It is not changed here.
- Releasing the connection slot in `end_headers` means a closing connection stops counting toward the caps while its last response is still being written, up to the 15 s socket timeout for a slow reader. That is at most one response per connection, after which the handler exits.
- The `gh` CLI is not installed here, so the PR body could not be updated from this machine.
