# W5-F01 follow-ups (99-XN-F01-FOLLOWUPS-R2)

Branch `fix/w5-f01-followups-2`, cut from `origin/main` `46e4ca2` (PR #96 merged). `git status` was clean before editing. `tests/test_reject_method_slot.py` and `reports/W5-F01-SLOT-RELEASE.md` are both on that main.

## Changes

- **SF1.** `BRANCHES` in `tests/test_reject_method_slot.py` gains `reserved`: the reserved-connection busy branch in `_blocked` (`app/server.py` 2245-2269 on `46e4ca2`: `is_reserved(self.connection)` sets `_reserved`, then a non-`/healthz` path gets 503 + `Retry-After: 1` + `Connection: close` before any slot is taken). The matrix arms it by setting `server.is_reserved` to a function returning True and removes it on disarm. Expected: 501 for OPTIONS/TRACE, 503 with the busy body for every other path, `/healthz` served (200, or 405 for POST/PUT/DELETE/PATCH) and released. For non-`/healthz` paths it also asserts no slot was taken (`_Counts.acquired`, which counts successful `acquire_slot` calls, is unchanged). Mutant check: changing `and not health` to `and False` at `app/server.py:2261` (restored after, `git diff app` empty) fails the `reserved` subtests; the unmutated file passes.
- **SF2.** `reports/W5-F01-SLOT-RELEASE.md` now cites `reports/W5-HTTP-SECURITY-AUDIT.md` as "merged on main by PR #91, merge commit `1a0a340`; F-01 at `:62` and `:70`" instead of naming `origin/qa/w5-http-security-audit` (the file is on `46e4ca2`). Its branch list also names `reserved`.
- **N1.** `docs/DEPLOY.md:812` on `46e4ca2` (`:843` on main since #94's merge `5697381`) reads "tree's `app/server.py`, the copy beside this document." That is the branch wording, kept. Checked from git: at the merge base `e434539` line 812 read "the merged tree this file ships in (main plus the listen backlog change)". Main (`8d46f14`) changed it to "tree: the tree this file ships in, in `app/server.py`."; the branch (`5244dc9`) changed it to "tree's `app/server.py`, the copy beside this document." Both removed the stale merged-tree phrase (the same fix in intent, different words), so the line conflicted, and `db50587` kept the branch side verbatim (`git show --cc db50587` has no hunk at :812): a side-pick, not an edit. Main's intent (tree-relative wording) survives. No DEPLOY.md change here.
- **N2.** Skip counts below carry their machine and sha. The two `OK (skipped=12)` counts in `reports/W5-F01-SLOT-RELEASE.md` (lines 48 and 63) now carry "(machine not recorded; tree `8d46f14` + branch)"; the machine was not recorded, so it is not guessed.

`app/server.py` and `docs/DEPLOY.md` untouched, so no DEPLOY cite or `CITED` re-pin. No `git checkout --ours/--theirs`; no conflicts.

## Tests

Machine `preached-sandbox`, tree `46e4ca2` + this diff. Fresh venv from `uv sync --frozen` under a temp dir. `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME` and `UV_PYTHON_INSTALL_DIR` all on fresh `mktemp -d` dirs under `/tmp/f01`, `ORT_DISABLE_TELEMETRY=1`, `HF_HUB_OFFLINE=1`, `PREACHED_REQUIRE_DENO=1`. The ambient env points three of these at `/cache` and the repo `.venv` links to `/cache/uv-python`, so the venv was not used.

- `test_reject_method_slot`: 10 tests OK (preached-sandbox, `46e4ca2`+diff).
- Mutant (reserved branch off): `reserved` subtests FAIL (preached-sandbox).
- Full suite `python -m unittest discover -s tests`: `Ran 1146 tests in 256.980s`, `OK (skipped=12)` (preached-sandbox, `46e4ca2`+diff). Zero `test_every_cited_file_line_holds_its_string` failures.

## /cache snapshot

`find /cache -printf '%p %s %T@\n' | sort` before and after all runs: 132725 lines each, `diff` empty. No difference.

## R2 (CTO r1 CONDITIONAL, docs-only)

- **MF1.** `reports/W5-F01-SLOT-RELEASE.md:3` now cites the audit as "merged on main by PR #91, merge commit `1a0a340`; F-01 at `:62` and `:70`".
- **MF2.** N1 above rewritten from git history: line 812 was a side-pick of the branch wording, not an edit; main's tree-relative intent survives. PR BODY section updated to match.
- **Nits.** 1: SF1 bullet now says no slot was taken (`_Counts.acquired` unchanged). 2: both `OK (skipped=12)` in `reports/W5-F01-SLOT-RELEASE.md` (lines 48, 63) carry "(machine not recorded; tree `8d46f14` + branch)". 3: the Stat block below is labelled with the sha it describes. 4 (count `acquire_slot` calls) not taken; no test change.

Docs-only: `app/server.py`, `docs/DEPLOY.md` and the tests untouched. No merges, no conflicts. Branch is `fix/w5-f01-followups-2` (r1 head `0e67e8e`, R2 head `6ee93c1`); the name `fix/w5-f01-followups` exists only as a stale local branch at `3a93147`, not on origin.

## Stat (`46e4ca2..6ee93c1`)

```
 reports/W5-F01-FOLLOWUPS.md      | 47 ++++++++++++++++++++++++++++++++++++++++
 reports/W5-F01-SLOT-RELEASE.md   |  8 +++----
 tests/test_reject_method_slot.py | 19 ++++++++++++++--
 3 files changed, 68 insertions(+), 6 deletions(-)
```

## PR BODY

SF1: add the reserved-connection busy branch to the F-01 property matrix (mutant-checked). SF2: F-01 report points at `reports/W5-HTTP-SECURITY-AUDIT.md` as merged on main by PR #91 (merge `1a0a340`). N1: `DEPLOY.md:812` kept the branch's tree-relative wording; both sides fixed the stale merged-tree wording in different words; `db50587` kept the branch side (side-pick). N2: skip counts machine-labelled. Full suite on `preached-sandbox`: 1146 tests, OK (skipped=12). `/cache` listing identical before and after. Tests and reports only; `app/server.py` and `DEPLOY.md` untouched.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
