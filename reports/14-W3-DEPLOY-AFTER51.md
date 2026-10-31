# 14-W3-DEPLOY-AFTER51: #45 follow-up after #51 merged

Branch `docs/w3-deploy-consolidate` (PR #45). Docs and the cite pins only.
No change to `app/`, `src/`, `scripts/`, `pyproject.toml` or `uv.lock`, and
no new deps.

## What was done

Merged `origin/main` (`ad78a75`) into the branch as its own merge commit
(`2973cab`, parents `c7f39a3` and `ad78a75`). Main is past #51 (`87c0395`,
code `8cd3104`) and past `08b8b9b`. No file was changed on both sides.
`app/server.py` is the only cited file that moved. The pin tests check the
cites on this merged tree.

| Item | What changed | Where |
| --- | --- | --- |
| D1 startup | `ERROR stored vectors do not match search/models.toml; serving BM25 only` is `logging.exception(MISMATCH_LOG)` at `app/server.py:836` (text `:281`), with a traceback. | `docs/DEPLOY.md` D1 row |
| D2 startup only | The same class of line for the embedder is `:839` (text `:282`). A reload does not emit it. | `docs/DEPLOY.md` D2 row |
| Reload D1 | The reload path logs D1 once per transition at `:1136` via the call at `:1168`, with no traceback. | `docs/DEPLOY.md` D1 row, MET bullet |
| D2b OPEN | `deploy-index-status-unreadable-bm25`, regex `^ERROR index status unreadable after reload; serving BM25 only$`, PAGE, disabled until the church deploy. Emitted at `:1136` via `:1211` (text `:283`), only when dense search was loaded. Infra Ops drafts it. | `docs/DEPLOY.md` D2b row |
| Paging | D1, D2 and D2b page once per transition, deduped to at most 1 per hour. | Deploy-alerts intro and those three rows |
| Reload fallback | MET. A checkout reload logs D1 or D2b. A frozen bundle still refuses at `:1202` (D4). A server that never loaded weights stays quiet. The stamp traceback is once per outage at `:1088`, then DEBUG. | MET bullet |
| Clean stop | MET. `INFO stopped cleanly` at `app/server.py:3216`, last line of the clean path. The stuck path (D5, `:3204`) does not log it. The INFO rule is OPEN for Infra (no rule id yet). | MET bullet, other-lines table |

CTO cites re-verified on `ad78a75`: startup D1/D2 `:836`/`:839`, reload D1 `:1136` via `:1168`, `stopped cleanly` `:3216`.

Every other `app/server.py` cite in the runbook moved with the same insertions and is pinned in `CITED`. `src/preached/library.py`, `scripts/build-bundle.sh` and the YouTube cites did not move. Infra Ops' yaml is still the 21-rule file pinned to `76990e8` (sha256 `c1841274aed5d778b9fa3b9b417a456c53a38555fb9403cb072deba68b676f0e`, every rule `enabled: false`). This re-pin does not edit that file.

## How to run

```
PREACHED_CACHE=/cache uv run python -m unittest discover -s tests
uv lock --check
```

## Results

- Full suite (`PREACHED_CACHE=/cache`, `uv run python -m unittest discover -s tests`): `Ran 1002 tests in 222.987s`, `OK`. No failures and no skips.
- `tests.test_deploy_alerts.RunbookTests` (inside that run, and re-run after the last wording pass): the cite pins match the merged tree, including `:836`, `:839`, `:1136`, `:1168`, `:1211` and `:3216`.
- `uv lock --check`: OK (79 packages resolved). No dependencies added.

## Open issues

- D2b is not in the yaml. Infra Ops drafts `deploy-index-status-unreadable-bm25` disabled until the church deploy (PAGE, the regex above, once per transition, at most 1 per hour).
- `INFO stopped cleanly` has no rule id. Infra Ops drafts that INFO rule, disabled, with the other deploy rules.
- D7 still has no rule id (unchanged).
- The yaml's D1 and D2 sources predate the reload split. Infra Ops re-pins them against this tree. D2 fires only at startup.
- An idle keep-alive timeout still logs at ERROR (code nit, not this PR).

## Dependencies

None added.

## Scope

This task edited `docs/DEPLOY.md`, `tests/test_deploy_alerts.py` (the `CITED` pins and the quoted alert lines) and this report. No `src/` or `app/` change. `git diff --stat origin/main..HEAD` also lists files already on this branch from earlier #45 rounds. It lists no `src/` or `app/` file.

## R4 condition and post-#63 re-pin

Branch `docs/w3-deploy-r4-cond`, off origin/main `b224281`. Docs and the cite pins only. No change to `app/`, `src/` or `scripts/`. The earlier sections of this file are the #45 record and are unchanged.

On origin/main `b224281`, before these edits, `tests.test_deploy_alerts.RunbookTests.test_every_cited_file_line_holds_its_string` failed: 52 subtests, every one an `app/server.py` pin (`Ran 1 test`, `FAILED (failures=52)`). #63 (`3d59132`) inserted three lines at `app/server.py` 188-190 (`MAX_QUERY`). Every `app/server.py` cite at the old line 188 or later moved by 3. Each needle was read on that new line of current main. The 11 `src/` and `scripts/` pins were not moved; they still hold.

| Item | Now |
| --- | --- |
| D1 / D2 text | `:284` / `:285` |
| D1 startup / D2 startup | `:839` / `:842` |
| Reload D1 | `:1139` via `:1171` |
| D2b | Drafted (no longer OPEN). `:1139` via `:1214` (text `:286`). The runbook now says "disabled until deploy approval", not "disabled until the church deploy". |
| Stamp ticket | `deploy-index-stamp-unreadable` at `:1091` (the `logging.log` of `could not read the index stamp`). TICKET, at most 1 per rolling hour, cap survives restarts, `enabled: false`. With dense search loaded, a stamp failure also fires the D2b page (D4 in a frozen bundle): one page for impact, one ticket for cause. Under `--bm25-only` it is the only alert. |
| D7 | `deploy-abstain-calibration-unusable` at `:1774`. The old pin was `:1771`. `:1774` is that same `logging.exception` line on `b224281`, read from the file. TICKET, at most 1 per hour. |
| Clean stop | `INFO stopped cleanly` at `:3219`. Rule id `deploy-stopped-cleanly`. |
| Paused rows | Rule id `church-paused`. |
| Yaml | `church-alerts.yaml` sha256 `447cd7e283cba91169e695feb6d39bdf7642522e3d1c587e959f879ef7ea4f29`, 25 rules, every one `enabled: false`. Line numbers in `docs/DEPLOY.md` are pinned to main `b224281`. |
| Church gate | Added **OPEN: Patrick's approval** of the church deploy, in writing. A church side is not started until every condition above is met, including the CTO's sign-off on each and Patrick's written approval. |
| gitleaks | The CTO has run gitleaks. It is clean. |

`fix/w3-keepalive-cap` was not on main at this pin.

## How to run

```
PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests
```

## Results

- Baseline on origin/main `b224281`: `test_every_cited_file_line_holds_its_string` FAILED, 52 subtests.
- `tests.test_deploy_alerts` on this tree after the re-pin: `Ran 7 tests`, `OK`, including `test_every_cited_file_line_holds_its_string`.
- Full suite (`PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`) after `git fetch && git merge origin/main` (already up to date at `b224281`): `Ran 1005 tests in 229.274s`, `OK`. No failures. An earlier run of the same command on this tree reported `Ran 1005 tests in 233.409s`, `OK`.

## Open

- Recovery from an unreadable index stamp is silent. `/healthz` shows `"dense": true` when dense search is back, and the server does not log `INFO dense search restored`. Open suggestion for the CTO. That line was not added here.
- An idle keep-alive timeout still logs at ERROR (unchanged code nit).
