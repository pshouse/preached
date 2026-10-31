# W3-DENO-HARDFAIL-PORTBUSY (#63 r2 S2 + N2, #66 N1-N3)

Branch `fix/w3-deno-hardfail` off origin/main 1793b06.

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

## Results

- `PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`: Ran 999 tests, OK.
- `uv lock --check`: Resolved 79 packages, clean.
