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

## Hard conditions (CTO #33)

Task 41-W3-CHURCH-HARDCOND. CTO ruled should-fixes 1 and 2 from the #33 review hard conditions on church wiring; 3–5 were optional. All five are done. `origin/main` (with #33 merged as `eb4d48a`) was merged into this branch first (merge commit `724a671`). Merge commits only, nothing rebased or force-pushed, no other branch pushed. No new dependencies, nothing deployed, synthetic fixtures only. The review file `/workspace/reports/preached-pr33-review.md` does not exist in this sandbox, so this section works from the CTO ruling as quoted in the task.

### Item → commit / test

| CTO item | Commit | Test (`tests/test_hard_conditions.py`) |
| --- | --- | --- |
| 1. Raw read-only connects bypass the sidecar check | `8c2a5a5` | `ScriptReadOnlyOpenTests` (one test per script; `measure_parity` has one subtest per open), `test_the_same_scripts_read_an_index_with_safe_sidecars`, `RawConnectGuardTests` |
| 2. Realpath half of `_sidecar_problem` untested | `9f80703` (test only) | `RealpathSidecarTests.test_a_symlinked_name_whose_real_shm_links_to_wesley_is_refused` (+ safe-sidecar control) |
| 3. `App.gated` writable | `566120f` | `AppGatedReadOnlyTests` |
| 4. Traceback instead of an error line on `UnsafeSidecar` | `8c2a5a5` | `ErrorLineTests` (`open_readonly_or_exit`; `review_sheet`, `smoke_server`, `eval/pool.py` as subprocesses; `build_library.check_target`) |
| 5. `_clear_church_mark` sibling passed over silently | `2b3cbba` | `SiblingSidecarSkippedTests` |

- **Item 1:** new `store.open_readonly_or_exit` (`open_readonly`, but a missing index or an `UnsafeSidecar` becomes `SystemExit` with one error line). Now used by:
  - `check_dedupe.py:75`
  - `check_nl_questions.py:46`
  - `review_sheet.py:57`
  - `measure_parity.py` (`load_rows`, `load_torch_docs`, `step_spotcheck`'s shipped-index open, `_copy_index`)
  - `bundle_manifest.copy_index` (the deploy backup of the live index)
  - `eval/apply_grades.py`. The CTO list missed this one; the repo-wide grep found it.

  `copy_index` imports `preached.store` lazily, so the manifest part stays stdlib-only. `build-bundle.sh` now puts `src` on `PYTHONPATH` for that call (the same `$PY` already imports `preached.store` for `check_servable`). `measure_parity._connect` was an unused writer and was deleted.
- **Item 3:** `App.gated` is now a property over `_gated`, set once from the slug in `__init__`. `app.gated = …`, `setattr` and `del` raise `AttributeError`, the same convention as `Searcher.gated`. `app._gated` can still be assigned directly, the same accepted residual as `Searcher._gated`. `App.library` is still a plain attribute. With the gate on it only matters through `public_domain_file`, which checks the file's own marker, so a church file cannot earn the exemption by renaming the slug.
- **Item 4:** `eval/pool.py`, `eval/timestamps.py`, `scripts/gate_leak_sweep.py`, `scripts/smoke_server.py` and `search/build_library.check_target` print `error: <index> has a -shm file with 2 hard links; it is not opened` and exit non-zero. Before, they printed a traceback (and still refused). `pool.py` keeps its own missing-index message.
- **Item 5:** in `mark_your_church_exclusive`'s clearing loop, a candidate whose sidecar is unsafe now is reported in `skipped` as `<problem> (not opened)` (no duplicate if the first scan already listed it). Before, `church_shaped` returned False for it and the loop moved on with a bare `continue`. That only happens when the sidecar turns unsafe between the scans and the loop, because both earlier scans already list or exclude it.

### Repo-wide grep (`sqlite3.connect(` / `mode=ro` / `immutable`, outside `tests/`)

No `immutable` anywhere. Every `mode=ro` is in `store.open_readonly` or a docstring. `RawConnectGuardTests` checks, by AST, that exactly these raw `sqlite3.connect` calls remain:

| Where | Why it is not `open_readonly` |
| --- | --- |
| `src/preached/store.py` `connect()` | the writer (ingest/migrate) |
| `src/preached/store.py` `open_readonly()` | the checked open itself |
| `src/preached/library.py` `_Checked` | church writes: `mode=rw`, sidecars and the opened descriptor checked (#27/#33) |
| `src/preached/search.py` | `":memory:"` |
| `scripts/bundle_manifest.py` `copy_index` `dst` | the new bundle copy; its name and sidecars were just unlinked |
| `scripts/measure_parity.py` `_copy_index` `dst` | a new copy under `/cache/w3-cpu`; refuses the shipped path |
| `scripts/gate_leak_sweep.py` writer | the synthetic temp index the sweep just built |

The `sqlite3.connect` calls in `tests/` are fixture builders and probes on temp files.

### Planted -shm probe (item 1)

Setup: a synthetic `wesley.sqlite`, plus a WAL-mode synthetic index with no sidecars whose `-shm` name is a hardlink to Wesley. Each script then runs against that index, in-process (models stubbed, a stub `torch` for `measure_parity`, `measure_parity`'s path constants pointed at the temp files). The probe compares Wesley's sha256 before and after. The base is the merge commit `724a671`, extracted with `git archive`; the fix is this branch.

| Script / open | merge base `724a671` | this branch |
| --- | --- | --- |
| `check_dedupe` | **CHANGED** | unchanged, refused |
| `check_nl_questions` | **CHANGED** | unchanged, refused |
| `review_sheet` | **CHANGED** | unchanged, refused |
| `apply_grades.load_chunks` | **CHANGED** | unchanged, refused |
| `bundle_manifest.copy_index` | **CHANGED** | unchanged, refused |
| `measure_parity.load_rows` (69) | **CHANGED** | unchanged, refused |
| `measure_parity.load_torch_docs` (81) | **CHANGED** | unchanged, refused |
| `measure_parity.step_spotcheck` shipped open (148) | **CHANGED** | unchanged, refused |
| `measure_parity._copy_index` (318) | **CHANGED** | unchanged, refused |

Every refusal on this branch was `SystemExit: error: target.sqlite has a -shm file with 2 hard links; it is not opened`. `ScriptReadOnlyOpenTests` runs the same probe in the suite.

### Mutation checks

Each mutation was applied to the working tree, the named tests were run, and the files were restored with `git checkout`.

| Mutation | Result |
| --- | --- |
| M-A: `_sidecar_problem` without the realpath half (`bases = [abspath]`) | `RealpathSidecarTests` fails. Across `test_side`, `test_youtube`, `test_church_wire` and `test_hard_conditions` (147 tests), exactly 1 fails: the new realpath test. Before this task, all side+youtube tests passed with the half dropped. |
| M-B: each of `check_dedupe`, `check_nl_questions`, `review_sheet`, `apply_grades`, `bundle_manifest`, `measure_parity` reverted to its `724a671` version | `ScriptReadOnlyOpenTests` fails for each (measure_parity: 4 of 4 subtests) |
| M-C: `App.gated` back to a plain attribute | `AppGatedReadOnlyTests` fails (2) |
| M-D: item 5 sidecar check removed from the clearing loop | `SiblingSidecarSkippedTests` fails |
| M-E: `open_readonly_or_exit` lets `UnsafeSidecar` through | `ErrorLineTests` fails (2 failures, 2 errors) |

### Results

- `uv run python -m unittest discover -s tests`: **782 tests, OK** (89.8s). That is 766 after the `origin/main` merge, plus 16 in `tests/test_hard_conditions.py`.
- `uv lock --check`: passed (79 packages). No dependency changes.
- No PR body was updated: `gh` is not installed in this sandbox, so the branch was only pushed. The PR body should get this section's item table.
- Code head before this section: `9f80703`. The commit that adds this section is `bc0969c`; the branch head is the follow-up commit that records this SHA (report text only).

## CTO r1 fixes (PR #37)

Task 44-W3-CHURCH-FIX. CTO r1 on PR #37 (`a1cb055`) returned CHANGES. `origin/main` at `1498182` (it includes `1215761`) was merged in first, with merge commit `4ab867a`. Merge commits only, nothing rebased or force-pushed, and no other branch pushed. No new dependencies, nothing deployed, and only synthetic church fixtures were used. `scripts/build-bundle.sh` was not touched; should-fix 5 belongs to 44-W3-BUNDLE-TAR. The review file `/workspace/reports/preached-pr37-review.md` is not in this sandbox, so this section works from the CTO text quoted in the task.

### Item → commit / test

| CTO item | Commit | Tests |
| --- | --- | --- |
| MF1: textual conflict with #25 in `build_app` | `4ab867a` (merge) | #37's docstring kept, then #25's `RUNTIME_MODELS` guard. Full suite, parity, e2e |
| MF2 + SF7: a symlink bypasses the writable-dir rule; owner not checked | `1cfb8d9`, `a3db9c0` | `ChurchRefusalAtOpenTests`: `test_symlink_into_a_world_writable_directory_is_refused` (the CTO case; it shows that the old `writable_problem(link)` returned None), `test_symlink_to_a_safe_church_file_is_refused_too`, `test_real_directory_behind_a_symlinked_parent_is_checked`, `test_church_file_owned_by_another_user_is_refused`, `test_church_directory_owned_by_another_user_is_refused`, `test_symlink_owner_and_wal_are_refused_before_any_connect`. `ChurchRefusalWhileServingTests`: `test_name_swapped_for_a_symlink_to_the_same_file_after_start`, `test_owner_change_after_start` |
| SF1: the raw-connect tripwire misses import forms and `store.connect` reads | `f48f89f` | `RawConnectGuardTests` (3): repo scan of every sqlite3 import, repo scan of writer `store.connect` uses, and `test_every_bypass_form_is_seen` (17 source snippets) |
| SF2: no adjacent-chunk test for church audio withholding | `1cfb8d9` | fixture rows `c-near-flag` (name ends at 209.8 s) and `c-adjacent` (starts at 210 s). `ChurchServedTests.test_the_chunk_right_after_a_flagged_name_has_no_audio` (side + search API), `CliSideTests.test_the_chunk_right_after_a_flagged_name_prints_without_audio` |
| SF3: the 400 text reveals the church | `1cfb8d9`, `a3db9c0` | `test_400_text_is_the_same_with_without_and_after_a_dropped_church` (covers no church, served, paused and dropped). Updated asserts in `test_side` / `test_church_wire` |
| SF4: no deploy hold in code; DEPLOY silent on the church | `1cfb8d9` | `ServerMainTests.test_without_the_deploy_switch_the_church_is_not_opened_and_wesley_serves` (6 values × both flags; the file is never opened), `test_the_deploy_switch_is_not_passed_by_serve_sh`. New `docs/DEPLOY.md` section "The church gate" |
| SF6: publish should leave DELETE mode; refuse WAL | `9534d58`, `1cfb8d9` | `ApprovalTests.test_approval_leaves_the_church_file_in_delete_mode`, `test_approval_with_another_wal_reader_warns_and_the_server_refuses_the_file`. `ChurchRefusalAtOpenTests.test_wal_mode_church_file_is_refused_and_no_sidecar_appears`, `test_delete_mode_church_file_opens_with_no_sidecar`. `ChurchRefusalWhileServingTests.test_wal_mode_while_serving_skips_the_request_without_dropping` |
| Nit: cached corrupt pages | docs only | Accepted gap, listed in DEPLOY's church gate. I found no cheap fix: an in-place edit that keeps the inode and the change counter is served from SQLite's page cache until it misses |
| Nit: `bundle_manifest.py:75` dangling symlink | `f0bf886` | `test_copy_index_replaces_a_dangling_symlink_without_creating_its_target` |

### What changed

- **MF2 (`library.church_path_problem`)** runs in `open_church_readonly` before any connect, and in `church_file_problem` before every church search. It refuses:
  - a church name that is a symlink. This matches DEPLOY's rule for the classic library.
  - a real file or real parent directory not owned by the serving euid or root.
  - a real file or real parent directory that is group- or world-writable.

  This covers the CLI too, which never had `writable_problem`. The server keeps `writable_problem` as well.
- **SF1:** `RawConnectGuardTests` parses every `.py` outside `tests/`. Only the files in `RAW_CONNECTS` may import sqlite3, in any form: `import`, alias, `dbapi2`, `from sqlite3 import`, or a `"sqlite3"` string for `__import__`/`import_module`. Each file has a count of raw opens: `connect`/`dbapi2` references, `Connection(...)` calls, `getattr` on the module, and non-safe from-imports. A sqlite3 attribute outside the safe list fails until it is reviewed. `WRITER_CONNECTS` lists the four users of the writer `store.connect`: `build_index`, `bench`, `measure_parity` and `youtube.library.open_library`.
- **SF3:** both 400 sites now say `library must be <classic slug>`. That is byte-identical to main's no-church text and does not change when a church is open, paused or dropped. I chose this over a new generic string so the no-church parity stays identical. It does mean the text does not list a church slug even when one is accepted.
- **SF4:** `open_church` refuses first unless `PREACHED_CHURCH_SIDE` is exactly `enabled`, from a checkout or a bundle. The refusal is one `church side refused:` line, and the file is not opened. `serve.sh` does not pass this variable (its `env -i` allow-list) and passes no `--church-*`, so a `serve.sh` start can never enable the church side. The switch is not in the privacy TOML: that file's sha256 is pinned at import, so editing it would refuse every later approval. The CLI (`query.py --side`) is not gated by the switch because it is not a deploy path. DEPLOY.md's new section lists the gate: deploy switch, privacy config, permissions, owner, DELETE mode, publish gate, and the known gaps. The pastor-permission and church-deploy holds are stated first.
- **SF6:**
  - `pipeline.acknowledge` ends with `youtube.library.leave_delete_mode`: a checked checkpoint, then `journal_mode=DELETE`, then a check of the result.
  - Another open WAL reader can block the switch. In that case the approvals stand, the command prints `warning: the church file is still in wal journal mode …`, and the exit status does not change.
  - `open_church_readonly` reads the SQLite header (bytes 18/19, no connect) and refuses a WAL-mode file.
  - While serving, `church_file_problem` raises `ChurchPaused` before its first read when the file is in WAL mode, which is the case while `--ack-review` is writing. `App._church_ready` skips the church side for that request only (INFO line, no drop) and reads nothing. That is why the server never joins the WAL and the switch back to DELETE succeeds with the server running.

### Mutation results

The script `/tmp/cwfix/mut.py` (not committed) applied each mutation on its own and ran `test_side`, `test_church_wire`, `test_hard_conditions` and `test_coverage`, then restored the file. Every mutation fails at least one test. The first full pass found three survivors: MF2-e, SF6-a, and SF3 at the `App.search` site. MF2-e and SF6-a were refused only after a connect, by the post-open check. For SF3, the mutated text matched after a drop. `a3db9c0` added a "refused before any connect" test and a paused-400 check, and the final pass below has no survivors.

| Mutation | Fails |
| --- | --- |
| MF2-a symlink refusal off | 4 (`test_symlink_into_a_world_writable_directory_is_refused`, `…safe_church_file…`, `…swapped_for_a_symlink…`, `…before_any_connect`) |
| MF2-b real directory not checked | 2 (`…symlinked_parent_is_checked`, `…directory_owned_by_another_user…`) |
| MF2-c owner not checked | 4 (file owner, dir owner, owner change after start, before-any-connect) |
| MF2-d path check skipped per request | 3 |
| MF2-e path check skipped at open | 1 test, 2 failing subtests (`…before_any_connect`) |
| SF2-a server church cards ignore adjacent flags | 1 (`test_the_chunk_right_after_a_flagged_name_has_no_audio`) |
| SF2-b CLI cards ignore adjacent flags | 1 (`…prints_without_audio`) |
| SF3 `App.search` 400 lists open libraries | 1 (`test_400_text_is_the_same…`) |
| SF3b `parse_search_args` 400 lists open libraries | 5 |
| SF4 deploy switch off | 1 test, 6 failing subtests |
| SF6-a WAL file opened at start | 1 (`…before_any_connect`) |
| SF6-b WAL not paused while serving | 2 |
| SF6-c `--ack-review` does not leave DELETE mode | 2 |
| Nit: `exists()` instead of `lexists()` in `copy_index` | 1 |
| SF1: `from sqlite3 import connect` added to `query.py` | 1 |
| SF1: `store.connect` imported into `check_dedupe.py` | 1 |

### Parity and e2e

- **No-church parity:** `origin/main` `1498182` vs this branch, using `/tmp/cwfix/parity.py` (not committed). Same venv, `/cache/index/wesley.sqlite`, ONNX fp32.
  - CLI (5 queries × 3 modes, `--side` × 3, spurgeon, edwards): stdout, stderr and exit **20/20**.
  - HTTP: **52/52** status and body (`took_ms` masked). This includes the `library=sample` 400 on both endpoints and the `library=mychurch` 400.
  - Startup log equal apart from the `PREACHED_RSS_BYTES` number.
- **With a refused church** (`--church-index` on a synthetic file, no switch, no privacy config):
  - HTTP **52/52**.
  - CLI stdout and exit 20/20.
  - The only differences are the expected `church side refused:` lines: one in the server log (deploy switch) and one on CLI stderr for the 3 `--side` runs (privacy config). Main does not wire a church, so it prints none.
- **Wesley sha256** `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b` was unchanged.
- **E2E over real HTTP** (`/tmp/cwfix/e2e.py`, synthetic church, `PREACHED_PRIVACY=privacy.example.toml`, `PREACHED_CHURCH_SIDE=enabled`): **17/17**.
  - The approved passage is served with a timed watch link.
  - The adjacent-to-flag card has no audio or source link.
  - The 6 hidden tokens get 0 hits in all 3 modes, and `/healthz` says `"church": null`.
  - The 400 text is the same while served, paused and dropped.
  - No `-wal`/`-shm` appeared, and the church sha256 did not change from serving.
  - In WAL mode the church side is skipped with nothing read; back in DELETE mode it is served again; after a chmod 666 it is dropped.
  - Each of these start refusals is logged with the same 400: no switch, a symlink into a 0777 directory, a WAL file (no `-shm` created).

### Results

- `uv run python -m unittest discover -s tests`: **818 tests, OK** (90.9 s). The merge of main gave 797. This round adds 21: 2 in `RawConnectGuardTests`, 1 for the dangling symlink, 2 in `ApprovalTests`, and 16 in `test_church_wire`.
- `uv lock --check`: passed (79 packages). `pyproject.toml` and `uv.lock` are unchanged.
- gitleaks: NOT run (not installed in this sandbox).
- **PR body: NOT updated.** `gh` is not installed in this sandbox. The branch is pushed. The PR body should get this section's item table.
- Code head before this section: `a3db9c0`. The branch head is the commit that adds this section.

### Open issues

- **Same-uid races remain (#33).** The symlink, owner and mode checks are by name. A WAL flip between the pause check and the read can still make the server join the WAL. If that happens, `--ack-review` warns and a restart refuses the file until `--ack-review` is re-run with no reader.
- **A paused request** gives an empty church column, and `library=<church>` gets a 400 for that request.
- **Any write tool opens WAL again** (`open_library` → `store.connect`). Examples: an import, or `--redo`. The file stays in WAL mode, and is refused at start or paused while serving, until the next `--ack-review` returns it to DELETE mode.
- **Holds:** the pastor-permission and church-deploy holds stand. Do not set `PREACHED_CHURCH_SIDE` on any deploy.
