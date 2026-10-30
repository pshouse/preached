# W3-SIDE: classic library beside your church

Branch `feat/w3-side`. Merged `origin/main` at `2ad5550` (PR #10, ONNX fp32) in `0f0eeef`. PR #14 and PR #12 were not on main at that fetch, so this fix does not call `check_servable` and does not add a second check. No new dependencies. No new models. Gaston Community Church was not imported, stored, or shown. The church column in tests is fixture text, and a library whose slug is `sample` (or whose meta `sample` is `1`) is labelled sample data.

## What was done

One question, two libraries. Each library is still its own SQLite file under `/cache/index/<slug>.sqlite`. A search reads one connection, so a hit from the other file cannot appear in that list.

The church mark is one row in the `meta` table that file already has: `role` = `church`. `import/youtube.py --your-church` sets it only when the import returns 0 (every selected video imported or skipped on purpose). `--dry-run` writes nothing. A failed or partial import leaves the mark unset and leaves a sibling mark in place. The slug `sample` also writes `sample` = `1`.

Clearing a sibling uses a plain `sqlite3` connection: no schema migration and no `journal_mode=WAL`. `wesley`, `spurgeon`, `edwards`, and the canonical classic paths (`INDEX_PATH` and `/cache/index/<slug>.sqlite` for those slugs) are skipped, including a copy whose file stem is one of those names. Marking one of those files raises `ValueError` and leaves its bytes as they were.

The server still has one classic library (`--library`, default `wesley`). Until PR #12's publish gate is on main, it does not open or search a church file. `prepare_church` resolves the path so a bad name can be refused, then the process serves only the classic index. An explicit `--church-library` or `--church-index` of wesley, spurgeon, or edwards (including `Wesley.sqlite`, and including a missing file with that stem) is `SystemExit`. A classic file that only showed up because it was marked `role=church` is ignored, so that mark does not stop the classic server. Several marks are logged and the side stays empty.

`GET /api/search?library=<slug>` searches the classic library. Any other slug, including a church slug, is a 400 (`library must be wesley`). Omitting `library` still searches the classic file. That search still reloads when the classic index stamp changes (PR #10).

`GET /api/side` searches the classic library once and returns the church column a process with no church file returns:

```json
{
  "library": null,
  "label": "Your church",
  "sample": false,
  "present": false,
  "empty": true,
  "message": "Nothing from your church yet.",
  "mode": null,
  "results": [],
  "note": null,
  "abstain": false,
  "confidence": null
}
```

The key `present` stays `false`, which is the body the page already uses for a missing church. The response does not include a church hit, a timed YouTube link, or a church `source_url`. `/healthz` keeps `"church": null`. A process started with `--church-library sample` returns the same `/api/side`, `/api/search`, and `/healthz` JSON as a process with no church file (`took_ms` aside).

`search/query.py --side` prints the classic section, then `## Your church` and `Nothing from your church yet.` It does not open the church file. `--church-library wesley` (or spurgeon, or edwards) exits before the index is opened. The CLI still prints the ranker's raw top `-k` (default 5). The API still de-dupes.

Church confidence, for the search the gate will turn on later, is `abstain.church_confidence`: `unrated` when there are passages, and `none` with `calibrated` false and no floor when the list is empty. The Wesley floor in `search/abstain.toml` is not applied. While serving is off, the HTTP church object keeps `confidence: null`, same as the missing-church body.

The page's View control is unchanged. Side by side still calls `/api/side?k=5`. The single-library view still calls `/api/search?library=wesley&k=10`. On a phone the columns stack. At 800px and wider they sit next to each other. CSP is unchanged.

## How to run it

From `/work/preached/.worktrees/feat/w3-side`:

```bash
uv run python -m unittest discover -s tests
uv lock --check
uv run search/query.py "what did Wesley say about worry" --mode bm25 --side
uv run app/server.py
```

Open http://127.0.0.1:8000 and choose View → Side by side. The church column says nothing is there yet.

Mark a fixture library (this does not fetch Gaston Community Church; that channel is still refused before yt-dlp). The mark is stored. The server still leaves that column empty:

```bash
uv run --extra youtube import/youtube.py "https://www.youtube.com/watch?v=VIDEO" --library sample --your-church
uv run app/server.py --church-library sample
uv run search/query.py "mercy" --mode bm25 --side --church-library sample
```

`GET /api/side?q=mercy&mode=bm25&k=5` returns the classic hits and the empty church column. `GET /api/search?q=mercy&library=sample&mode=bm25` is a 400, `library must be wesley`.

## Results

`uv run python -m unittest discover -s tests` after this fix-up: **304 tests, all passing** (19.5s). `uv lock --check` passed. The lock was not regenerated. No dependency was added.

Deno is installed; the page test still runs the card renderer, the watch link, the archive player, the empty church sentence, the sample-data heading, and the per-side low-confidence toggle. Those fixtures are page inputs. The API does not send them. There is no browser in this environment, so the stacked phone layout was not clicked through in a real viewport. That check is still open and is not this job. The CSS test checks that two columns appear only inside the `min-width: 800px` rule.

## Fix-up (CTO review of `6443b40`)

`origin/main` was `2ad5550` (PR #10). PR #14 was not on main, so the church side is refused here by leaving it empty, not by adding a parallel of `check_servable`.

| item | commit | test |
| --- | --- | --- |
| Church side stays empty until PR #12. `/api/side`, `/api/search?library=sample`, `/healthz`, and `search/query.py --side` match a process with no church file. `present` stays false. `/healthz` `"church"` stays null. No church hit, watch URL, or church `source_url`. | `f2f02d8` | `SideApiTests.test_search_stays_inside_one_library`, `test_side_by_side_abstains_per_side_and_labels_sample_data`, `test_configured_church_matches_the_no_church_responses`, `test_low_confidence_is_per_side`, `test_missing_church_is_an_empty_side_not_an_error`, `test_church_without_vectors_does_not_drop_the_classic_side`, `SideCliTests.test_side_flag_prints_both_columns` |
| `mark_your_church_exclusive` skips wesley, spurgeon, edwards, and canonical classic paths. A sibling mark is cleared with a plain `sqlite3` connection (no migration, no WAL). A wesley copy's bytes stay identical. | `b4395de` (clear/skip); test in `f2f02d8` | `MarkTests.test_classic_copy_bytes_are_unchanged_and_a_sibling_is_cleared_without_wal` |
| Church confidence is `unrated` when there are hits, and `none` / uncalibrated / no floor when there are none. The Wesley abstain floor is not applied. HTTP stays `confidence: null` while the side is empty. | `f2f02d8` | `SideCliTests.test_church_confidence_is_unrated_not_the_wesley_floor` |
| Explicit wesley, spurgeon, or edwards as the church is `SystemExit` (server and `search/query.py`), including a missing file and `Wesley.sqlite`. An auto-detected classic mark does not stop the server. `import/youtube.py --your-church` returns 2 for those slugs and writes no file. | `b4395de` (importer); `f2f02d8` (server and CLI) | `ChurchRefusalTests.test_explicit_classic_slug_is_refused_and_a_marked_copy_is_not_opened`, `SideCliTests.test_classic_church_slug_is_refused`, `ImportTests.test_classic_slugs_are_refused_as_your_church` |
| The church mark is written only when the import returns 0, the run is not a dry-run, and the sqlite file exists. A failed import does not mark that file and does not clear a sibling. | `b4395de` | `ImportTests.test_failed_import_does_not_mark_the_church`, `ImportTests.test_your_church_mark_is_exclusive_and_dry_run_writes_nothing` |

Full suite after both commits: 304 tests, 0 failures. `uv lock --check` passed (79 packages). The health stub in `SchemaTests.test_health_keeps_existing_keys` accepts the label read added when the classic column title is resolved (`f2f02d8`).

## Open issues

- **TODO (after PR #12 is on main):** turn the church searcher back on. It gets #12's gate and per-request `visible_sql`, audio withheld on flagged passages, and the `source_url` rule covering hits, plus #10's index-stamp reload on that file. Confidence stays `abstain.church_confidence` (unrated) until a floor is fitted on a church library. `load_church_searcher` is still in `app/server.py` and is unused. If #14 is on main by then, a church file passed as `--library` is refused with #14's `check_servable`. Do not add a parallel check. The classic searcher already reloads.
- If more than one non-classic file is marked `church` and the process is not given `--church-library` or `--church-index`, the church side is empty. The server logs the slugs. It does not guess.
- The single-library page still sends `library=wesley`. A server started with `--library` set to something else will reject that request, as it did before.
- The page asks for 5 hits per side. The API default remains 10, matching `/api/search`.
- The CLI list is not de-duplicated. The API list is. That split is the one `README.md` already describes for a single search.
- No congregation archive is connected. Do not point `--church-library` at Gaston Community Church audio until the pastor's permission is confirmed. The importer still refuses that channel before any fetch.
- A real-browser pass of the stacked phone layout was not run. That check is still open and is not this job.

## Dependencies

None. `uv lock --check` passed; `uv.lock` was not changed. The standard library, the existing SQLite file per library, and the existing Deno test (skipped when `deno` is missing). No model was added.
