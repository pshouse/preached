# 40-W3-CHURCH-GATE-WIRE: serve the church side, only through #12's publish gate

**Depends on #33; do not merge before #33.**

Branch `feat/w3-church-wire`, from `origin/main` at `af06a44` (#32). `origin/fix/w3-sidecar-readonly` (#33, `45657d6`) is merged in with a merge commit (`8d720af`), so this branch builds on #33's sidecar-checked `store.open_readonly` and read-only `Searcher.gated` / `gate_on()`. History uses merge commits only. Nothing was rebased or force-pushed, and nothing was pushed to `fix/w3-sidecar-readonly` or any other existing branch. No new dependencies or models, and no LLM. Nothing was deployed, and Tailscale and the Sprite were not touched. **Only synthetic church fixtures were used.** No real church audio or transcripts were downloaded, imported or committed; there is no pastor permission yet.

## What was done (design summary)

When a church library is named with `--church-library <slug>` or `--church-index <file>`, and only then, the church column of `/api/side`, `/api/search?library=<church slug>`, and `search/query.py --side` show church passages. Those passages come only from a `Searcher` built with the publish gate on.

- **One open path:** `library.open_church_readonly(path, classic=...)` (new). It refuses, in this order:
  - no privacy config (`privacy.required_config`)
  - a missing file
  - a classic or hardlinked file (`classic_church_refusal`)
  - the classic index itself (same inode)
  - an unsafe `-wal`/`-shm`/`-journal` (#33's `store.open_readonly`, which raises `UnsafeSidecar`)
  - a file that is not a church import (`_church_shape_problem`)
  - a file without the publish-gate columns (`visible_sql(gated=True) == "0"`)
  - a file replaced during the open

  Each refusal raises `ChurchRefused`. The open is `mode=ro` plus `query_only`, so nothing is written from the serving path. The post-open checks run before the first SQL read.
- **Server (`app/server.py`):**
  - `open_church` wraps that open and adds the classic side's `writable_problem` (no group- or world-writable file or directory).
  - On any refusal it logs one `ERROR church side refused: <why>` line and the process serves Wesley exactly as without a church. `prepare_church` is unchanged: an explicit wesley/spurgeon/edwards as the church still exits at start, because that is a configuration error.
  - `build_app` builds the church searcher only through `load_church_searcher` (literal `gated=True, library=None`), with the classic side's query embedder. Stored vectors must match the model fingerprint and be fp32 (`check_query_variant`); otherwise that side is BM25 with a note.
  - `App.__init__` keeps a church searcher only when the searcher, its connection and a non-classic slug arrive together. It calls `gate_on()`, clears the searcher's slug so the public-domain exemption can't apply, and refuses the side if `gated` is still not `True`.
  - Before every church search, `church_check` (`writable_problem` + `library.church_file_problem`) re-checks the file: same inode, one link, not a classic, safe sidecars, still church-shaped. A problem, or any exception in church search, is logged, drops the church side until restart, and returns the no-church column. The classic side is never affected.
- **Church cards:**
  - Visibility: `store.visible_sql` per call. A sermon must be approved (`approved_sha256 == review_sha256`), have `status = 'ok'`, and have `coverage_gaps = '[]'` from #20. A NULL coverage result (never checked) is hidden, and so is a NULL `video_id`.
  - Links: the same `hit_dict` flagged-audio and `source_url` rules as the classic side, with `touches_flagged` and `sermon_flagged` read from the church file.
  - Confidence: `abstain.church_confidence` (unrated). Wesley's floor is not applied.
- **`/healthz`:** keeps `"church": null`, now as a constant with or without a church. It does not reveal the church slug or whether a church is open. Nothing new is reported, since no CTO approval was given for more.
- **Church column when served:**
  - `library` = the slug; `label` = meta label or "Your church"; `sample` comes from `is_sample_library` (the page adds "(sample data)").
  - `present: true`, `mode` = the church side's effective mode, `note` (BM25 fallback), `confidence` (unrated, or none when empty).
  - Refused, or no church: the exact constant column from main.
- **CLI (`search/query.py --side`):** opens the church through the same `open_church_readonly` and searches it only through `search_index(..., church=True)` (`church_searcher`, literal `gated=True`). Cards use the flagged-audio policy against the church connection. A refusal prints one `church side refused:` line on stderr and the same empty section as before. In the church path, missing church vectors (`RuntimeError`) fall back to BM25 the same way as `EmbeddingMismatch`. With no church named, the output is unchanged.
- README paragraph updated.

## Item map

| item | what | commit | tests |
| --- | --- | --- | --- |
| 1 | Removed `del church_*` in `App.__init__` and `build_app`, the constant church column in `side()` (now used only for no church or a refused one), and the `print_side` TODO. Church searcher built only via the gate; fail closed with a logged refusal | `c8194c8` | `test_church_wire`: `ChurchServedTests`, `ChurchRefusalAtOpenTests` (10), `ChurchRefusalWhileServingTests` (7), `ServerMainTests` (6) |
| 2 | Church files opened read-only only through `open_church_readonly` → #33's sidecar-checked `open_readonly`. No writes from the serving path | `c8194c8` | `test_serving_writes_nothing_to_the_church_file`, `test_a_good_church_file_opens_read_only` (an UPDATE fails), `test_hardlinked_sidecar_to_wesley` (-wal/-shm/-journal, Wesley sha unchanged), `ServerMainTests.test_unsafe_church_sidecar_does_not_stop_wesley` |
| 3 | The #16 "church must be empty" tests are replaced. `SideApiTests` now has a church file with nothing approved: the church side is open and shows nothing, the classic column equals the no-church one, `/healthz` is equal. New tests cover approved+visible passages appearing, and unapproved, stale-review, coverage-gap, unchecked-coverage, failed-import, orphan, flagged and eval-only content never appearing. They cover API, side and CLI in bm25/dense/hybrid. Gate-off mutations fail the tests. `/healthz` stays `"church": null` | `c8194c8`, `8f91da7`, `171d4c5` | `ChurchServedTests` (9), `GateOffMutationTests` (4), `CliSideTests` (4), `SideApiTests.test_church_with_nothing_approved_adds_no_church_payload`, `test_healthz_says_nothing_about_the_church` |
| 4 | `ChurchGateTripwireTests` kept. The recorders now require `gated` passed by name and the literal `True` (`assertIs`; dict equality alone took `gated=1`). The source scan already required the constant `True` (`550eeaa`, #27) | `c8194c8` | `ChurchGateTripwireTests.assert_gate`, used by `test_server_church_searcher_is_gated_on_every_path` and `test_cli_church_searcher_is_gated_on_every_path`. Mutation M16 (`gated: 1`) fails both |
| 5 (2) | inode-only test: **already on main** (#27, `InodeAndLinkTests.test_same_inode_with_one_link_is_the_classic`) | n/a | n/a |
| 5 (3) | hardlinked church file has its own error, and skipped siblings are reported: **already on main** (#27, `InodeAndLinkTests.test_hardlinked_church_has_its_own_message_and_its_mark_is_reported`, `ImportTests.test_your_church_reports_sibling_marks_it_did_not_clear`). The new serving path reuses that message (`ChurchRefusalAtOpenTests.test_hardlinked_church_file`) | n/a | n/a |
| 5 (4) | temp `INDEX_DIR` instead of the `classic_file_problem` stub: **already on main** (#27, `SideApiTests.test_classic_side_covers_spurgeon_and_edwards`) | n/a | n/a |
| 6 | Synthetic fixtures only (`tests/test_church_wire.build_church`: made-up tokens, titles and `churchvidNN` ids) | all | n/a |
| 7 | No new deps; full suite; parity; `uv lock --check`; gitleaks | n/a | see Results |

"Eval-only content": the repo has no eval-only church data. Its eval-only concept is `eval_only` models (`search/models.toml`, e.g. `arctic-embed-l`). The test is that church vectors stored only under an eval-only model are never used: `load_church_searcher` with that key, or with a runtime key whose vectors aren't there, gives a gated BM25 searcher with the stale note. The server already refuses an eval-only `--model`. If CTO meant something else by "eval-only", that test needs adding.

## Mutation results (gate)

Each mutation was applied on its own to the real code. Then `tests.test_side` and `tests.test_church_wire` were run with the script `/tmp/w3cw/mut.py` (not committed). Every mutation fails at least one test.

| mutation | result | tests that fail (sample) |
| --- | --- | --- |
| M1 `load_church_searcher` gate `{"gated": False}` | 3 fail | `test_server_church_searcher_is_gated_on_every_path`, `test_every_searcher_passes_the_gate…`, `test_eval_only_vectors…` |
| M2 `App` does not call `church_searcher.gate_on()` | 47 fail, 2 errors | every served-church test: App then refuses the ungated searcher |
| M3 `store.visible_sql` always None (gate off) | 76 fail | `test_unapproved_flagged_coverage_gap…`, CLI leak test, `test_unmutated_does_not_leak` |
| M4 coverage condition removed from `visible_sql` | 59 fail | `test_unapproved_flagged_coverage_gap…`, `test_approval_while_running…` |
| M5 approval condition removed | 56 fail | same family |
| M6 per-request `church_check` skipped | 3 fail | `test_file_replaced_after_start`, `test_sidecar_planted_after_start`, `test_check_that_raises_is_a_refusal` |
| M7 privacy config not required for the church | 6 fail | `test_no_privacy_config`, `test_without_privacy_config…`, CLI refusal |
| M8 `open_readonly` sidecar check off | 12 fail, 1 error | #33's `ReadOnlyOpenSidecarTests`. The church-open tests still refuse, because `church_file_problem` re-checks sidecars before the first read |
| M9 church cards ignore the flagged-audio policy | 1 fails | `test_flagged_passage_has_no_audio…` |
| M10 church shape not checked at open | 1 fails | `test_not_a_church_import` |
| M11 `/healthz` reports the church slug | 5 fail | `test_healthz_says_nothing_about_the_church` and others |
| M12 CLI `church_searcher` `gated=False` | 3 fail | `test_cli_church_searcher_is_gated_on_every_path` and others |
| M13 App keeps the church searcher's slug | 1 fails (test added in `171d4c5`; it was not caught before) | `test_app_clears_a_slug_on_the_church_searcher` |
| M14 a church search exception propagates | 1 error | `test_church_search_exception_leaves_the_classic_side` |
| M15 group- or world-writable church file accepted | 1 fails | `test_world_writable_church_file` |
| M16 `gated: 1` instead of `True` | 2 fail | both tripwire recorders (item 4) |

In-suite gate-off checks (`GateOffMutationTests`) patch `visible_sql` off, strip the coverage clause, and make `gate_on` a no-op. They show that the leak assertions fire, or that App refuses the side.

## Parity (no church configured)

There is no `compare_responses` tool in the repo. As in the earlier reports, `origin/main` (`af06a44`) was exported with `git archive` (with `git init` so the server accepts it as a checkout). Both trees were run with this worktree's venv on `/cache/index/wesley.sqlite` (ONNX fp32, the default) by `/tmp/w3cw/parity.py`, which is not committed.

- **CLI:** 5 queries ("what did Wesley say about worry", "Romans 8:16", "assurance of faith", "the witness of the Spirit", "xyzzy plugh not a sermon") × bm25/dense/hybrid, `--side` × 3 modes, and `--library spurgeon` / `edwards`. stdout, stderr and exit code matched **20/20**.
- **HTTP:** `/api/search` (15, plus 15 with `library=wesley&k=10`), `/api/side` (15), `/api/sermon/wesley-001`, `/healthz`, the 400s for `library=sample` on `/api/search` and `/api/side`, `/`, and `/static/app.js`. Status and body bytes matched **51/51** (`took_ms` masked). Startup log lines also matched.
- **With a refused church** (`--church-index` on a synthetic file, no `$PREACHED_PRIVACY`): HTTP still matched 51/51, and CLI stdout and exit code matched 20/20. The only differences are one `church side refused:` line in the server log and on CLI stderr for the 3 `--side` runs.
- **Wesley sha256:** `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b` before and after every run.

**Live probe** (synthetic church served, `PREACHED_PRIVACY=privacy.example.toml`, real Wesley index):
- Approved passages (`c-shared`, `c-approved`) appear with their timed watch links.
- The flagged card has no audio and no source link.
- All 6 hidden tokens return 0 hits on `/api/search?library=mychurch` in hybrid mode.
- `/healthz` has `"church": null`.
- The church file's sha256 is unchanged.
- The fixture's vectors are for the `fixture` model, so that side said BM25 with the stale-vector note.

## How to run it

```bash
cd /work/preached/.worktrees/feat/w3-church-wire
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_side tests.test_church_wire
uv lock --check
# Synthetic church only:
PREACHED_PRIVACY=privacy.example.toml uv run app/server.py --church-index /path/to/synthetic.sqlite
PREACHED_PRIVACY=privacy.example.toml uv run search/query.py "mercy" --mode bm25 --side --church-index /path/to/synthetic.sqlite
```

## Results

- `uv run python -m unittest discover -s tests`: **748 tests, OK** (88.3s). The merge base `8d720af` has 710; this branch adds 38 (`tests/test_church_wire.py`). `test_side` stays at 51, with its tests rewritten.
- `uv lock --check`: passed (79 packages). `pyproject.toml` and `uv.lock` are identical to `origin/main`.
- gitleaks: **NOT run**; it is not installed in this sandbox. A grep of the added lines for key, token and private-key patterns found nothing.
- Code head before this report: `171d4c5`. The branch head is the commit that adds this report.

## Open issues and risks

- **`/healthz`** keeps `"church": null` as a constant. It does not show whether a church side is open or refused. If operators want that, CTO has to approve a field first.
- **`-wal`/`-shm` beside a WAL-mode church file.** A read-only open of a WAL-mode church file makes SQLite create its `-wal`/`-shm` files next to it, the same as #33's `open_readonly`. The database file's bytes are not written (sha256 unchanged in the tests and the live probe). `immutable=1` would stop that, but it would also stop approvals made while the server runs from showing on the next request, so it was not used.
- **Same-uid race windows** from #33 remain: a sidecar planted between a name check and SQLite's open. `church_file_problem` runs before the first read on open and before every request, which narrows that window but doesn't close it.
- **A dropped church side stays dropped until restart.** This is deliberate (fail closed), but a transient problem, for example a briefly unreadable directory, needs a restart.
- **The church side shares the classic side's lock and query embedder.** The side view encodes the query twice, about one extra ONNX query encode per `/api/side`.
- **`/api/sermon/<id>` serves only the classic library.** The page does not call it for church cards.
- **Real church data:** none was used, and the importer still refuses Gaston Community Church. Do not point `--church-library` at real church sermons until the pastor's permission is confirmed and approvals are done.
- **No PR was opened:** `gh` is not available in this sandbox.

## Dependencies

None added.
