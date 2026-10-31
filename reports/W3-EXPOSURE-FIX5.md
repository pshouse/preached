# 44-W3-EXPOSURE-FIX5: CTO advance ruling for PR #29 r4

Branch `feat/w3-exposure` (PR #29, open at `f365a63` per the GitHub API; FIX4 report present and not BLOCKED).
`origin/main` is an ancestor of the branch (no new main commits since the FIX4 merge `5808118`), so the branch tree
is the merge tree. No rebase, no force-push, no deploy, no dependencies added. **No production code changed.**

- `2286cb5`: tests for (a) and (b), fix of the formerly flaky test
- `5e119ea`: DEPLOY/README wording for (a)
- `683441c`: tighten the new (b) test (it caught its own same-key window under load, see section 4)
- Head: the commit that adds this report (`git rev-parse origin/feat/w3-exposure`)

## 1. What was done

### Item → commit / test map

| Item | Commit | Test / file |
|---|---|---|
| (a) at-cap reconnect 503 carries `Retry-After: 1` | `2286cb5` | `ReconnectRetryAfterTests.test_at_cap_reconnect_before_release_gets_retry_after` |
| (a) DEPLOY/README: cap N counts in-flight closing responses | `5e119ea` | `docs/DEPLOY.md` (Connections row, Slot fairness row, change list), `README.md` (paragraph after "Then open") |
| (a) no grace period / reserve | none (unchanged on purpose) | the same test requires the 503 while the slot is held (a one-over-cap "grace" mutation fails it) |
| (b) root cause with evidence | none | section 3, "Root cause of (b)" |
| (b) deterministic test (events, not sleeps) | `2286cb5`, `683441c` | `RequestSlotRaceTests.test_slot_is_held_until_after_the_response_is_written` |
| (b) production invariant holds | `2286cb5`, `683441c` | `RequestSlotRaceTests.test_in_flight_never_exceeds_the_cap_and_every_slot_comes_back` |
| (b) the formerly flaky test fixed | `2286cb5` | `SlotFairnessTests.test_trusted_proxy_connections_and_per_client_request_slots` waits on a release counter |

### (a) Retry-After test

`ReconnectRetryAfterTests` sets `max_per_client=1`. A `_Gate` (threading events) wraps `server.closing`, so the
closing handler is held after its body is flushed and before it frees its connection slot. The test reads the full
`Connection: close` 200 and waits for `gate.entered`. It then reconnects from the same peer and requires a 503 with
`Retry-After: 1`, `Connection: close` and `{"error":"unavailable"}`. After that it opens the gate, waits for
`gate.done`, and requires 200. No sleep decides the outcome.

The docs now say that both per-client caps (connections, and requests in flight) count a response until it is
written, including a closing response still being flushed. A client at its cap that reconnects or sends again in
that instant gets 503 with `Retry-After: 1`. No grace period, and why not.

### (b) Root cause, fix, invariant

See section 3 for the evidence. In short, it is a **test-harness timing artifact on correct production behaviour**,
the request-slot twin of (a):

- `acquire_slot` runs in `_blocked`. `release_slot` runs in `Handler._respond`'s `finally`, after `_send` has written
  the response (`wfile` is unbuffered).
- The flaky test sent three `/healthz` requests from the trusted proxy with no `X-Forwarded-For` (`_hold_idle(...,
  3)`). All three share key `127.0.0.9`, and the test's `/healthz` request cap is 1.
- So a client that has read the whole response can send the next same-key request before the old handler runs
  `release_slot`. That request is still in flight, the key is at its cap, and a busy 503 is correct.
- Under CPU load the handler thread is descheduled in that window, and the test got 503 != 200.

Production is not changed. Releasing earlier would let a key go past N while its responses are still being written.
That is the same reasoning the CTO accepted in (a).

- **Deterministic test.** `test_slot_is_held_until_after_the_response_is_written`, for `/healthz` and
  `/api/search`, with `max_requests=1`:
  - A `_Gate` holds the first `release_slot`. Then the test reads the full keep-alive 200, waits for
    `gate.entered`, and requires the slot table to be `{"127.0.0.2": 1}`.
  - A same-key request gets 503 with `Retry-After: 1` and `Connection: close`. A different key gets 200.
  - After `gate.open`, the same key gets 200 on the old keep-alive connection. A `_Releases` counter
    (`threading.Condition`) is then waited on before a new connection also gets 200, and the table must be empty.
- **Invariant test.** `test_in_flight_never_exceeds_the_cap_and_every_slot_comes_back`:
  - 8 client threads start on a `Barrier` and send 120 same-key searches with `max_requests=2`. Counters sit inside
    `acquire_slot` and `release_slot`.
  - Required: peak in flight ≤ 2; every outcome is `(200, no Retry-After)` or `(503, "1")`; releases == acquires;
    tables empty at the end.
  - The assertions hold for any interleaving.
- **Flaky test fixed.** The three proxy `/healthz` requests are now sent one at a time. Before each next one the
  test waits for `_Releases.wait_for(n)`, an event, not a sleep. The end of the test waits for all 8 releases before
  it checks that both tables are empty (it used to poll).

## 2. How to run

```
uv lock --check
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_exposure.RequestSlotRaceTests tests.test_exposure.ReconnectRetryAfterTests
uv run python -m unittest tests.test_exposure.SlotFairnessTests.test_trusted_proxy_connections_and_per_client_request_slots
for i in $(seq 10); do uv run python -m unittest tests.test_exposure; done
for i in $(seq 10); do uv run python -m unittest tests.test_exposure.SlotFairnessTests; done
```

"Under load" means 24 busy-loop shell processes (`while :; do :; done`) on this 24-core box, running for the whole
loop. Each run is `uv run python -X faulthandler -m unittest <target>`. Scripts are in `/tmp/fix5/` (not committed).

## 3. Results

### Root cause of (b), evidence

- **Probe**, `/tmp/fix5/probe.py`: it monkeypatches `PreachedServer.release_slot` to sleep 0.2 s before
  releasing, which widens the write→release window. On the old test (`f365a63`) the formerly flaky test fails at
  exactly the reported step:
  `test_exposure.py line 534 → _hold_idle line 375: AssertionError: 503 != 200`. That is the second same-key
  `/healthz` (log line `refused busy ...`). This matches the HARDEN report's description of the loaded flake
  ("a busy 503 on the per-key /healthz request slot").
- **The same probe on the new head:** `/tmp/fix5/probe2.py` slows both `release_slot` and `closing` by 0.2 s. With
  it, `RequestSlotRaceTests`, `ReconnectRetryAfterTests` and the fixed proxy test all pass. Their outcome no longer
  depends on how long the release takes.
- No other test sends same-key requests back to back at a request cap (grep of `max_requests=`: only this test uses 1).

### Required runs (final tree, `683441c` + this report)

| Run | Result |
|---|---|
| Formerly flaky test x50 **under load** | **50/50** pass |
| `RequestSlotRaceTests` + `ReconnectRetryAfterTests` x50 under load | 50/50 |
| `SlotFairnessTests` x10 under load | 10/10 |
| `tests.test_exposure` x10 quiet (59 tests each) | 10/10 (333 s total) |
| `SlotFairnessTests` x10 quiet | 10/10 |
| Full suite | **817 tests, OK** (141 s), none skipped |
| `uv lock --check` | OK, exit 0 (79 packages) |

Before this change, the formerly flaky test also passed 30/30 and `SlotFairnessTests` 20/20 under the same load on
`f365a63`. So the 50/50 alone does not prove the fix on this box. The probe and the gated test are the proof.

### Mutation checks (each applied to `app/server.py`, run, then reverted; `git diff app/` is empty)

| Mutation | Test | Result |
|---|---|---|
| Accept-time 503 without `Retry-After` | ReconnectRetryAfter | FAIL `KeyError: 'retry-after'` |
| Accept-time `Retry-After: 2` | ReconnectRetryAfter | FAIL `'2' != '1'` |
| Grace: per-peer connection cap `>` instead of `>=` | ReconnectRetryAfter | FAIL `200 != 503` |
| Busy (request-slot) 503 without `Retry-After` | slot_is_held | FAIL `KeyError: 'retry-after'` (both paths) |
| "Fix the race" by releasing the request slot before the response is written (in `_send`) | slot_is_held | FAIL `None != 200` (both paths) |
| Request cap `>` instead of `>=` | in_flight_never_exceeds / slot_is_held | FAIL `3 not less than or equal to 2` / `200 != 503` |
| `release_slot` leaks (no decrement) | in_flight_never_exceeds / slot_is_held | FAIL `{'127.0.0.2': 2} != {}` / `'127.0.0.2' unexpectedly found` |
| Fixed proxy test reverted to back-to-back requests (old test) + 0.2 s slow release | proxy test | FAIL `503 != 200` |

Two first-draft mutations were no-ops and were replaced, not counted. Freeing the connection slot before
`super().finish()` changes nothing because `wfile` is unbuffered. Releasing in `_respond_inner` runs before
`_slot_key` is set.

## 4. Open issues / risks

- **The new test hit the same window during the first loaded run.** That draft asserted that the whole table was
  empty right after the other key's `_get` returned. Under load it failed 4 of the first 7 runs, with
  `{'127.0.0.3': 1} != {}`. It is the same mechanism as (b), seen from another key.
  - `683441c` makes it assert only on the gated key, then wait on the release counter before the next same-key
    request.
  - The invariant test's counter was also changed to wait for the real release to return.
  - The whole loaded and quiet sequence above was rerun from the start on the fixed tree.
- The off-by-one mutation on the invariant test is caught by contention, not by construction: 8 threads against a
  cap of 2 reached a peak of 3. `slot_is_held` catches it deterministically.
- `test_keep_alive_idle_is_bounded_when_scarce` (the other loaded flake from FIX3, scarce timing, not (b)) passed in
  every `SlotFairnessTests` run here and is not changed.
- `sandbox.sh` does not exist anywhere on this machine (as in FIX4). I used plain `git` in the worktree. `gh` is not
  installed: I checked the PR state through the public GitHub API and did not update the PR body or comment.

## 5. Dependencies added

None.
