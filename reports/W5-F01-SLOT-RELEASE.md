# W5-F01: 405 releases the in-flight slot

Branch `fix/w5-405-slot-release`, cut from `origin/main` at `e434539`, resynced onto `origin/main` `8d46f14` (see the last section). Audit F-01 (High) in `reports/W5-HTTP-SECURITY-AUDIT.md` on `origin/qa/w5-http-security-audit`. Cause checked on that main before the edit.

## Cause

`do_POST`, `do_PUT`, `do_DELETE` and `do_PATCH` called `_reject_method`, which called `_blocked`. A successful `acquire_slot` incremented `_slots_by_key` or `_health_slots_by_key` and stored the key on the handler. `release_slot` ran only in `_respond`'s `finally`, and `_reject_method` never entered `_respond`. The cap is `DEFAULT_MAX_CLIENT_REQUESTS` (4). Four 405s from one client key left that key's table at 4 for the life of the process, so later requests on the same table returned 503. `/healthz` uses the other table, so it stayed 200 while search was stuck, and the reverse for a `/healthz` 405.

Disabled, rate-limit, reserved-busy and a failed acquire all return before `_slot_key` is set. OPTIONS and TRACE are answered with 501 before `_blocked`, so they never take a slot. The leak was the successful acquire followed by the 405 write.

## Fix

`_reject_method` calls `_respond(True, reject_method=True)`. The 405 write stays in its own try, with the same `BadRequest` and `Exception` handling and the same `logging.error("request failed: %s", ...)` line. GET, HEAD and the 405 methods share one `finally`, which releases the slot once after the response is written. A handler is reused for keep-alive, so the flag is a keyword argument on that call, not a field left on the handler.

`/healthz`, when `app.health()` reports `ok`, adds `slots_stuck`: how many keys are still at an in-flight cap for more than `PREACHED_SLOT_CAP_STUCK_S` seconds. The code default is 30 (`DEFAULT_SLOT_CAP_STUCK_S`). `0`, a negative number, a non-numeric value and an empty value keep 30. `scripts/serve.sh` does not pass the variable. The search table and the `/healthz` table are counted separately, so one key at both caps counts as two. The field is that count. It does not carry a client key or an address. The kill-switch body stays `{"ok": false, "disabled": true}` because `_blocked` sends it before `_route`. The 405 body stays `{"error":"method not allowed"}` with `Allow: GET, HEAD`.

## Tests

`tests/test_reject_method_slot.py`, raw sockets, BM25-only, synthetic temp index. Loopback sources are separate client keys.

RED on `e434539`'s `app/server.py` (the fix file swapped out for that run, then restored). Both burst tests fail on the four-POST half, so the eight-POST half is not reached:

```
FAIL: test_four_then_eight_posts_to_healthz_then_get_is_200
AssertionError: (False, 503) != (True, 200) : tables search={} health={'127.0.0.5': 4} body=b'{"error": "unavailable"}'

FAIL: test_four_then_eight_posts_to_search_then_get_is_200
AssertionError: (False, 503) != (True, 200) : tables search={'127.0.0.5': 4} health={} body=b'{"error": "unavailable"}'

Ran 2 tests in 7.184s
FAILED (failures=2)
```

GREEN on this branch: the same module, 10 tests, OK in 7.984s. That includes four then eight POSTs to `/api/search` and to `/healthz`, then a GET that is 200 with both tables and both cap clocks empty. A gated `release_slot` shows the 405 body is readable while the slot is still held, and the table is empty once the gate opens. The cap clock counts only when the key has sat at the cap for more than N seconds (exactly N stays 0). `/healthz` shows the count and the body contains no client address.

The property test covers every method in GET, HEAD, POST, PUT, DELETE, PATCH, OPTIONS and TRACE, every path in `/`, `/healthz`, `/api/search`, `/api/side`, `/api/sermon/wesley-001`, `/static/favicon.svg` and `/no/such`, and every branch in handled, disabled, busy, 429, bad request and exception. After each request both `_slots_by_key` and `_health_slots_by_key` are `{}`, and both cap clocks are empty.

## DEPLOY cites

`app/server.py` line numbers moved, so every `app/server.py` cite in `docs/DEPLOY.md` and every matching pin in `tests/test_deploy_alerts.py` was re-read on this tree. The sentence above the alert table says the line numbers are this tree's `app/server.py`, the copy beside the document. The slot-fairness row and the "W5 405 in-flight slot" release note document the release and `slots_stuck`. `scripts/serve.sh` is unchanged.

## Verification

Full suite, with `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR` and `TORCH_HOME` each on a fresh directory under `/tmp`:

```
Ran 1130 tests in 275.341s
OK (skipped=12)
```

`test_every_cited_file_line_holds_its_string` is in that run. The suite exited 0, so that test has no failure from this change.

`find /cache -maxdepth 3 -printf '%p %s %T@\n' | sort` before the first `uv run` and after the suite: 1640 lines, byte-identical. No path, size or mtime changed.

## Resync with origin/main (99-XG-F01-RESYNC)

`origin/main` merged into this branch with a normal merge commit (no rebase). The branch was based on `e434539`; the merge base with `origin/main` (`8d46f14`) is the new base. Main changed `app/server.py` by two lines since `e434539` (the `why` field: `"why"` in the hit field list and `"why": hit.why.as_dict() ...` in the hit dict). Both are present after the merge, and no F-01 hunk was touched: the diff of `app/server.py` against `origin/main` is the same set of added and removed lines as this branch's own diff against `e434539`. The `why` field's responses are not changed by the merge.

Conflicts were in `docs/DEPLOY.md` (cites) and `tests/test_deploy_alerts.py` (CITED pins) only. They were resolved by editing, not by picking a side: main's text kept, then every `app/server.py` cite and pin re-derived against the merged `app/server.py` by finding each pinned string, then the cites read by `test_every_cited_file_line_holds_its_string` and `test_the_runbook_cites_exactly_the_pinned_lines`. The slot-fairness row, the "W5 405 in-flight slot" note and the tree-relative sentence ("this tree's `app/server.py`, the copy beside this document") are kept.

Burst tests on the merged branch: RED with `app/server.py` swapped for `origin/main`'s copy (restored after), both four-POST halves fail with `(False, 503) != (True, 200)` and `body=b'{"error": "unavailable"}'`; GREEN on the merged tree, `test_reject_method_slot` 10 tests OK.

Full suite on temp caches (all seven variables on fresh `mktemp -d` dirs): `Ran 1146 tests in 253.312s`, `OK (skipped=12)`. No `test_every_cited_file_line_holds_its_string` failure. `/cache` listing (`find /cache -maxdepth 3 -printf '%p %s %T@\n' | sort`, 1640 lines) is identical before and after.
