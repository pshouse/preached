# W3-DEPLOY-REQUIRE-DENO

Base: `origin/main` b89103f (PR #45 merged). Task 94 (`fix/w3-deno-hardfail`, 701751c) is **not merged**; it exists only on origin. At b89103f the flag is honored only by `tests/test_mobile_ux.py:308-326`, so the docs say "the deno-backed tests that honor it".

## What changed
- `docs/DEPLOY.md:281-294` ("Local smoke test"): pre-deploy full-suite command with `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache`, plus one paragraph on why. `docs/DEPLOY.md` (Stop and exit codes, shutdown gate) gets a one-line note that the real-index shutdown run does not need deno.
- `AGENTS.md:53` (section 7, "How to run it"): same command for reviewers. This is the only reviewer run instruction in the repo.
- README.md untouched. Task 17 should add the flag to any full-suite line there; `grep -n "unittest discover" README.md` found none at b89103f.
- Other mentions (`docs/SUBMISSION-DRAFT.md:42` quotes the command without the flag; `docs/research/embeddings.md:377`) are left alone, out of scope.

## Runs (deno at /usr/bin/deno, PREACHED_CACHE=/cache)
- Full documented command, deno present: `Ran 1005 tests in 224.608s`, `FAILED (failures=52)`. All 52 are `tests/test_deploy_alerts.py` `test_every_cited_file_line_holds_its_string` subtests (cited `app/server.py` lines are stale). **Pre-existing:** the same 52 fail on a clean b89103f worktree (`Ran 7 tests`, `failures=52`). Not caused by this change and not fixed here (out of scope). No deno failures; no skip line printed.
- Deno-backed files, deno present, flag on: test_mobile_ux 9 OK, test_app_js 8 OK, test_privacy_wire_fix 21 OK, test_privacy_merge 9 OK, no skips.
- Deno hidden (PATH with only uv/python3/git), flag on: test_mobile_ux **fails** (2 failures: `RequireDenoTests.test_deno_present_when_required`, `PhonePageBehaviourTests.test_cards_player_and_scroll`, "PREACHED_REQUIRE_DENO=1 but deno is not installed"). test_app_js `OK (skipped=6)`, test_privacy_wire_fix `OK (skipped=1)`, test_privacy_merge `OK (skipped=1)`: these still skip silently until task 94 merges.

## Open
- The "passes with 0 skips" claim only holds after #94 merges; until then the flag protects test_mobile_ux alone.
- The 52 stale-cite failures on main need their own fix.
