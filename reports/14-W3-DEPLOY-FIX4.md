# 14-W3-DEPLOY-FIX4: CTO #45 round 3

Branch `docs/w3-deploy-consolidate` (PR #45). Docs and tests only. No change
to `app/`, `src/`, `scripts/`, `pyproject.toml` or `uv.lock`, and no new deps.

## What was done

First merged `origin/main` (`47da348`) into the branch as its own merge
commit (`bc40ab9`, parents `25af181` and `47da348`). Merge-base with the
branch tip was `76990e8`. No file was changed on both sides, so nothing was
resolved by dropping either side. `app/server.py` is not in that diff, so
every runbook `file:line` is the same number as on the `76990e8` pin. The
pin test checks them on this merged tree.

| Item | What changed | Where |
| --- | --- | --- |
| MF1 | `FdLoadTests` counts fds only after `gc.collect()`, so a cyclic collection cannot free leaked fds between the two readings. The two tests that build an App (`church_app`, `build_app`) close its sqlite connections in `addCleanup`, including the gated searcher's in-memory FTS connection. | `tests/test_embed_backend.py:788`, `tests/test_deploy_alerts.py:135`, `:181`, `:210` |
| S1 | `INFO church side pause ended: refused` (`app/server.py:1431`) moved out of the "Other lines" table into the "Paused at start" bullet, next to "no `resumed` line". It follows any refusal of a retry while paused (rows 1-3), not only `:1424`. The refusal line precedes it. Not an alert. | `docs/DEPLOY.md:722-727` |
| S2 | D7 stays TICKET, at most 1 per hour, and is OPEN: Infra Ops drafts it disabled at the re-pin. The deploy-alerts intro no longer says every rule is drafted. D1-D6 are the drafted, disabled rules. | `docs/DEPLOY.md:843-847`, `:857` |
| S3 | The silent reload BM25-fallback hard condition applies to any deploy that can reach the reload paths (a checkout deploy and the church site). A frozen bundle refuses first at `app/server.py:1184` (D4), so it is covered there. The plain "lines 1150 and 1190" are now pinned cites (`:1150` `STALE_NOTE`, `:1190` `INDEX_READ_NOTE`) in `CITED`, so a later refresh fails if they move. | `docs/DEPLOY.md:861-868`, `tests/test_deploy_alerts.py:77-80` |
| S4 | Dropped "that is acceptable" from the late page on a start-time pause. The sentence still says the page can come late. | `docs/DEPLOY.md` row 5 |

## How to run

```
uv run python -m unittest discover -s tests -p 'test_[a-e]*.py'
uv run python -m unittest discover -s tests
uv lock --check
```

## Results

- `tests/test_[a-e]*.py` (`discover -s tests -p 'test_[a-e]*.py'`), 8 runs after the fix, each `Ran 456 tests` and `OK`:
  - 159.049s, 157.706s, 154.979s, 155.120s, 156.308s, 156.565s, 158.284s, 157.936s.
- `tests.test_deploy_alerts` (inside those runs and the full suite): the cite pins, including `:1150` and `:1190`, match the merged tree.
- Full suite: `Ran 994 tests in 219.401s`, `OK`. No failures and no skips.
- `uv lock --check`: OK (79 packages resolved). No dependencies added.

## Open issues

- D7 has no rule id yet. Infra Ops drafts it disabled at the re-pin (TICKET, at most 1 per hour).
- The silent reload BM25 fallback is still a hard condition (W3-OBS-GAPS). Scope is a checkout deploy and the church site. A frozen bundle is covered by D4 at `:1184`.
- Infra Ops' yaml is still the file pinned to `76990e8`. This merge did not move the cited lines.
- An idle keep-alive timeout still logs at ERROR (code nit, not this PR).

## Dependencies

None added.
