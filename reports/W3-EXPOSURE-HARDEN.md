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
