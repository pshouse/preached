# W3-DENO-HARDFAIL-PORTBUSY (#63 r2 S2 + N2, #66 N1-N3)

Branch `fix/w3-deno-hardfail`, merged with origin/main 0559b02 (R4-COND, #73) in 54ec03b.

## What changed

- `tests/test_app_js.py` (new shared helper): `REQUIRE_DENO` (`PREACHED_REQUIRE_DENO=1`) and `need_deno(case)`. With deno it returns; without deno it fails if the env var is set, else skips as before. `PageStateTests` and `AppJsTests` (the old `skipUnless` decorators at :439 and :618) now call it in `setUp`.
- `tests/test_privacy_wire_fix.py` `test_page_shows_text_only_for_withheld_audio`: decorator replaced by `need_deno(self)` (imported from `test_app_js`, as `PRELUDE` already is elsewhere).
- `tests/test_privacy_merge.py` `ServedTests.run_page`: `skipTest` replaced by `need_deno(self)`.
- `tests/test_mobile_ux.py` is untouched (out of scope); it keeps its own equivalent.
- `app/server.py` `PreachedServer.server_close`: `refusals = getattr(self, "refusals", None)`; flush only if set. `self.refusals` is created after bind, so a failed bind used to raise AttributeError from `server_close` and hide the real OSError.
- `tests/test_port_busy.py` (new, 1 test): holds a listening socket, constructs `PreachedServer` on that port, asserts OSError with `errno.EADDRINUSE`.
- `reports/W3-NITS-BATCH.md`: #42 N1 landed without `connect()` and the CTO accepted it; #40 N1 optional creator-vs-author check not taken; test count corrected to 998 on main 1793b06, now 999.

## Hard-fail proof

Deno present: `test_app_js.py` 8 tests OK. With deno hidden from PATH (PATH holds only a `uv` symlink):

| File | `PREACHED_REQUIRE_DENO` unset | `=1` |
|---|---|---|
| test_app_js (6 deno tests) | skipped=6, OK | failures=6 |
| test_privacy_wire_fix (1) | skipped=1, OK | failures=1 |
| test_privacy_merge (1, `test_page_renders_no_link_under_none`) | skipped=1, OK | failures=1 |

## Mutant proof

With the `server_close` guard removed, `test_port_busy` errors: `AttributeError: 'PreachedServer' object has no attribute 'refusals'` (FAILED errors=1). With the guard restored: OK.
(The mutant was made by stashing `app/server.py`; I used `git stash`, found the single entry by SHA, applied it and dropped it. The stash list is empty.)

## Round 2 (CTO C1 + nits)

- C1: #69's `server_close` guard (+3 lines in `app/server.py`) shifts the 12 cites at or above old :2762. Re-pinned in `docs/DEPLOY.md` and `CITED` (`tests/test_deploy_alerts.py`), each checked by reading `app/server.py` at this head: 2765->2768, 2769->2772, 2837->2840, 2844->2847, 2855->2858, 2862->2865, 3024->3027, 3202->3205, 3203-3221->3206-3224 (`stuck = server.drain()` to `raise SystemExit(1)`), 3207->3210, 3217->3220, 3219->3222.
- N1: totals for the PR body (replace the earlier 999): full suite on this head is Ran 1006 tests, OK, 0 failures (`PREACHED_REQUIRE_DENO=1`, deno present). The "off 1793b06" base in the body is stale; base is now 0559b02.
- N2: removed unused `import shutil` from `tests/test_privacy_merge.py` and `tests/test_privacy_wire_fix.py`.
- N3: `test_port_busy` skips on win32; the no-op `assertNotIsInstance` is now `assertIsNone(ctx.exception.__context__)`.

## Results

- `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`: Ran 1006 tests, OK, zero failures.
- `uv lock --check`: Resolved 79 packages, clean.
