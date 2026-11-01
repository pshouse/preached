# W5-F01 follow-ups (99-XN-F01-FOLLOWUPS-R2)

Branch `fix/w5-f01-followups-2`, cut from `origin/main` `46e4ca2` (PR #96 merged). `git status` was clean before editing. `tests/test_reject_method_slot.py` and `reports/W5-F01-SLOT-RELEASE.md` are both on that main.

## Changes

- **SF1.** `BRANCHES` in `tests/test_reject_method_slot.py` gains `reserved`: the reserved-connection busy branch in `_blocked` (`app/server.py` 2245-2269 on `46e4ca2`: `is_reserved(self.connection)` sets `_reserved`, then a non-`/healthz` path gets 503 + `Retry-After: 1` + `Connection: close` before any slot is taken). The matrix arms it by setting `server.is_reserved` to a function returning True and removes it on disarm. Expected: 501 for OPTIONS/TRACE, 503 with the busy body for every other path, `/healthz` served (200, or 405 for POST/PUT/DELETE/PATCH) and released. For non-`/healthz` paths it also asserts `acquire_slot` was not called. Mutant check: changing `and not health` to `and False` at `app/server.py:2261` (restored after, `git diff app` empty) fails the `reserved` subtests; the unmutated file passes.
- **SF2.** `reports/W5-F01-SLOT-RELEASE.md` now says `reports/W5-HTTP-SECURITY-AUDIT.md` "as merged on main" instead of naming `origin/qa/w5-http-security-audit` (the file is on `46e4ca2`). Its branch list also names `reserved`.
- **N1.** `docs/DEPLOY.md:812` on main reads "tree's `app/server.py`, the copy beside this document." That is the branch wording, kept. Checked by reading: the premise "both sides carried the same fix" does NOT hold. At `8d46f14` (main) line 812 was "tree: the tree this file ships in, in `app/server.py`." and `5244dc9` (the F-01 commit, `git log -S`) is the first commit with the "copy beside this document" wording. `db50587` kept the branch's tree-relative wording over main's, by editing, so no main hunk was dropped except the old phrasing it replaced. Both phrasings are tree-relative. No DEPLOY.md change here.
- **N2.** Skip counts below carry their machine and sha. The skip count in `reports/W5-F01-SLOT-RELEASE.md` (`OK (skipped=12)`, lines 48 and 63) was not labelled there and I left it, since the machine is not recorded; it is out of scope to guess.

`app/server.py` and `docs/DEPLOY.md` untouched, so no DEPLOY cite or `CITED` re-pin. No `git checkout --ours/--theirs`; no conflicts.

## Tests

Machine `preached-sandbox`, tree `46e4ca2` + this diff. Fresh venv from `uv sync --frozen` under a temp dir. `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME` and `UV_PYTHON_INSTALL_DIR` all on fresh `mktemp -d` dirs under `/tmp/f01`, `ORT_DISABLE_TELEMETRY=1`, `HF_HUB_OFFLINE=1`, `PREACHED_REQUIRE_DENO=1`. The ambient env points three of these at `/cache` and the repo `.venv` links to `/cache/uv-python`, so the venv was not used.

- `test_reject_method_slot`: 10 tests OK (preached-sandbox, `46e4ca2`+diff).
- Mutant (reserved branch off): `reserved` subtests FAIL (preached-sandbox).
- Full suite `python -m unittest discover -s tests`: `Ran 1146 tests in 256.980s`, `OK (skipped=12)` (preached-sandbox, `46e4ca2`+diff). Zero `test_every_cited_file_line_holds_its_string` failures.

## /cache snapshot

`find /cache -printf '%p %s %T@\n' | sort` before and after all runs: 132725 lines each, `diff` empty. No difference.

## Stat

```
STAT_PLACEHOLDER
```

## PR BODY

SF1: add the reserved-connection busy branch to the F-01 property matrix (mutant-checked). SF2: F-01 report points at `reports/W5-HTTP-SECURITY-AUDIT.md` as merged. N1: `DEPLOY.md:812` kept the branch's tree-relative wording; note the premise that main carried the same fix is wrong (main had older, also tree-relative wording; `db50587` replaced it). N2: skip counts machine-labelled. Full suite on `preached-sandbox`: 1146 tests, OK (skipped=12). `/cache` listing identical before and after. Tests and reports only; `app/server.py` and `DEPLOY.md` untouched.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
