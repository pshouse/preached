# W3-LIB: more classic preachers in the built-in library

Branch `feat/w3-lib`, from `origin/main` (9c3e303), with `origin/main` (e2ddbc7) merged in for the fix-up. Written 2026-10-30. The CTO review fix-ups are in sections 9 (round 1) and 10 (round 2).

## 1. What was done

Two hand-picked public-domain archive.org items were added, each as its own library (its own SQLite file, `/cache/index/<slug>.sqlite`). The existing W1-A pipeline (`ingest/`) transcribed them, and the W2-YT library writer indexed them. No parallel pipeline and no new dependency.

| Library slug | Source (archive.org id) | Sermons | Audio | Words | Chunks | Index file |
|---|---|---|---|---|---|---|
| `spurgeon` | `spurgeons_sermons_librivox` | 6 (nos. 191-196) | 4.32 h | 41,859 | 534 | 3.0 MB |
| `edwards` | `select_sermons_edwards_0911_librivox` | 39 tracks (one is the editor's "Advertisement") | 19.53 h | 192,970 | 2,514 | 14.5 MB |

**Edwards finished in full: 39/39 tracks, 19.53 h.**

**Talmage was dropped by Patrick's decision.** A third library, T. De Witt Talmage's 1898 *Sermon on the Mount* disc (`SermonOnTheMountByT.DeWittTalmage1898`), was built in the first pass. It is not in this PR: archive.org gives no licence for it, the clip is 58 s, and the transcript is rough. Its manifest, provenance, source entry, smoke questions and tests were removed, and it is not on the public-domain allow-list. The index file built in the first pass, `/cache/index/talmage.sqlite`, has been deleted with Patrick's OK. Its audio (1.2 MB) and transcript (12 KB) are still under `/cache/{audio,transcripts}/talmage`; the server refuses the slug either way (section 10).

Code changes:
- `src/preached/libraries.py` (new, fix-up): the committed allow-list of public-domain libraries, exactly `spurgeon` and `edwards`. The API is `is_public_domain(slug)` and `provenance_path(slug)`. A slug counts only if it is on the list and its `ingest/manifest/<slug>.provenance.json` is committed. PR #12 can use it to exempt only these slugs from redaction and the approval gate.
- `ingest/classics.py` (new): fixed `SOURCES`. It builds `ingest/manifest/<slug>.jsonl` in the Wesley row schema, joining the LibriVox API for titles, readers and the text source. With `--provenance` it also writes `<slug>.provenance.json`.
- `ingest/run.py`: new `--library <slug>`, which accepts allow-listed slugs only. Without the flag it runs on Wesley as before. The manifest, audio, transcript and log paths are passed explicitly as a `LibraryPaths`; no module globals are rebound. `ingest/fetch.py`: `ensure_audio`/`audio_path` take an optional `audio_dir`.
- `search/build_library.py` (new): takes the transcripts' searchable word window, chunks it (`corpus/chunk_config.json`), embeds with Granite English R2 on CPU and writes `/cache/index/<slug>.sqlite`. It is resumable per sermon and accepts allow-listed slugs only. It refuses a target that is a Wesley-style index or another library's file, and it marks its file with meta `library=<slug>`.
- `src/preached/youtube/library.py`: `index_video` takes optional `reader`, `sermon_number` and `librivox_id`. The defaults keep the YouTube behaviour.
- `search/query.py`: new `--library <slug>`, which cannot be combined with `--index`. Only the Wesley index file gets the Wesley chunk sync. `--index` refuses library files.
- `ingest/manifest.py`: `check_audio_url` now refuses control characters and spaces, and it wraps `urlsplit` errors.
- `app/server.py` serves one library per process: `uv run app/server.py --library spurgeon` (see README). Since round 2 it serves only `wesley` and the allow-listed libraries (section 10).
- `eval/classics_smoke.jsonl` and `scripts/classics_smoke.py` form a **smoke test only** (section 5). Tests are in `tests/test_classics.py` and `tests/test_libraries.py`.

## 2. Sources, licences and text editions (provenance in `ingest/manifest/<slug>.provenance.json`)

Each provenance file records:
- the identifier;
- title, creator and licence from the archive.org metadata;
- the full archive.org file list;
- for each audio file: size and md5 (from archive.org), and sha256 (computed on the downloaded file). `ingest/fetch.py` verifies md5 and size at download.
- a `text_edition` block: the printed text the LibriVox volunteers read from, taken from the LibriVox catalog record (`url_text_source`, `copyright_year`).

Each manifest row also carries that `text_source_url`.

- **Spurgeon** and **Edwards** are LibriVox items. archive.org gives `licenseurl` as `http://creativecommons.org/licenses/publicdomain/`, and LibriVox recordings are dedicated to the public domain. The texts are public domain too: Spurgeon died in 1892 and Edwards in 1758. The voices are volunteer readers (named per section), not the preachers. archive.org lists the Spurgeon creator as "Charles Sturgeon", a typo; the manifest uses Charles Haddon Spurgeon. The audio used is the 64 kbps MP3 derivative, as for Wesley.
- **Spurgeon text edition:** Spurgeon's penny sermons nos. 191-196, preached and published in May 1858. LibriVox gives the text source as the Spurgeon Archive's 1858 index, `https://www.spurgeon.org/index/c04.php`, with text year 1858. That page returned a 404 when I checked it on 2026-10-30, so the exact printing could not be confirmed further.
- **Edwards text edition:** *Select Sermons* of Jonathan Edwards as published by the Christian Classics Ethereal Library. LibriVox gives the text source as `https://www.ccel.org/ccel/edwards/sermons.html`, with text year 1904.
- Nothing was imported by tag. I checked content by reading spots in the transcripts; Spurgeon and Edwards are orthodox Protestant sermons.

## 3. Transcription

The settings match W1-A:
- model: faster-whisper `large-v3-turbo` (`mobiuslabsgmbh/faster-whisper-large-v3-turbo`, revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, OpenAI Whisper lineage);
- decoding: fp16, batch 8, beam 5, Silero VAD, `word_timestamps=True`, `without_timestamps=False`, English;
- prompt: one line, `"<work>, by <author>."`;
- gap fill and loop repair on.

Word timings come from the ASR, not forced alignment (`text_source = asr` on every chunk). No published text was aligned, so the indexed text is what Whisper heard and it contains ASR errors. The readers' audio was not compared with the printed text, and no WER was measured for these libraries.

| Library | Wall time | Speed | VRAM peak | Gap-filled segments | Loop repairs |
|---|---|---|---|---|---|
| spurgeon | 4.2 min | 65 audio-h/wall-h | 3.26 GB | 8 | 1 |
| edwards | 21 min | 55.5 audio-h/wall-h | 3.26 GB | 44 | 1 |

No OOM back-off. The GPU was shared with another tenant at times.

## 4. Quality problems (honest notes)

- Spurgeon and Edwards are modern volunteer readings, so the audio is clean. The transcripts were not checked word for word. Archaic words and Latin/Greek citations are the likely error spots. `ingest/qa.py` reports only on the Wesley folder; I did not extend it.
- Edwards track 10 is the editor's "Advertisement" (4 min) and is indexed as `kind: preface`. Edwards sermons are split across tracks ("pt 1", "pt 2"), so each part has its own `sermon_id`.
- The W1-A window rule keeps the LibriVox intro/outro boilerplate that Whisper transcribed out of the index. Anything Whisper dropped is simply absent.
- No privacy redaction is applied to these two libraries. The sources are 18th-19th century public texts, and the W3-PRIV name list is for church sermons. The allow-list in `src/preached/libraries.py` is what limits this exemption to `spurgeon` and `edwards`.
- There is **no retrieval-quality evaluation** for these libraries. Section 5 is a smoke test.

## 5. Smoke test (not a quality metric)

`scripts/classics_smoke.py` runs `eval/classics_smoke.jsonl` with hybrid search, top 5, Granite English R2. A question passes when an expected sermon is in the top 5 and that hit has a `start_s` and an archive.org play URL with the 0.75 s pre-roll. It shows that each library opens, searches and returns playable hits. **It is not evidence of retrieval quality**, for three reasons:
- an agent wrote the questions and no human reviewed them;
- most questions paraphrase sermon titles;
- Spurgeon has 6 sermons, so a random top 5 contains a given sermon 5/6 (about 83%) of the time.

Result after the fix-up: `smoke: 12/12 passed` (6 Spurgeon, 6 Edwards). The two Talmage questions were removed. I did not listen to the audio at the returned timestamps.

## 6. Tests

`uv run python -m unittest discover -s tests` ran **271 tests, all pass**.
- 247 tests pass after merging `origin/main`, 4 of them W3-LIB's original tests.
- `tests/test_classics.py` now has 6 tests and `tests/test_libraries.py` has 22, both from the fix-up.

`uv lock --check` is clean (75 packages resolved).

## 7. Rerun

```bash
cd /work/preached/.worktrees/feat/w3-lib
uv run ingest/classics.py --provenance                       # manifests + provenance (needs audio for sha256)
for s in spurgeon edwards; do
  uv run --extra transcribe ingest/run.py --library $s --all   # resumable; ~25 min total on an RTX 3060
  uv run search/build_library.py $s                            # -> /cache/index/$s.sqlite
done
uv run search/query.py --library spurgeon "what is the duty of a Sunday school teacher" -k 3
uv run scripts/classics_smoke.py                             # smoke test, 12 questions
uv run app/server.py --library edwards                       # serve one library
uv run python -m unittest discover -s tests && uv lock --check
```

Audio, transcripts and indexes are under `/cache/{audio,transcripts,index}/<slug>`. Only manifests, provenance, code, smoke questions and this report are committed.

## 8. Open issues

- The web page still sends `library=wesley`, and one process serves one library. A library switcher or a side-by-side view needs a server change (W3 follow-up).
- ~~`search/query.py --library` and `app/server.py --library` open any `/cache/index/<slug>.sqlite`.~~ Fixed in round 2 (section 10): both take only allow-listed slugs, and query.py opens non-Wesley targets read-only.
- Calvin (`mostcelebratedsermonsjohncalvin_2104_librivox`) and the other names in BRIEF were out of scope.
- No dependencies were added.

## 9. Fix-up: CTO review of PR #14 (head d69e09f)

First, `origin/main` (e2ddbc7) was merged in with a merge commit: `e97fa65`, no conflicts. History was not rebased or force-pushed.

| Item | Change | Commit | Tests |
|---|---|---|---|
| Must-fix 1: `query.py --index` ran the Wesley sync on a classics file | `--index` and `--library` are mutually exclusive. `--index` refuses a library file, i.e. one with a `videos` table or a meta `library` marker; the file is left unchanged and the message points to `--library <stem>`. The Wesley chunk sync runs only when the target is the Wesley index file (`INDEX_PATH`). Any other `--index` file is searched as it is. Checked by hand on the real `/cache/index/spurgeon.sqlite`: exit 1, and its sha256 is unchanged. | `596c03a` | `tests/test_libraries.py` `QueryIndexTargetTests` (6): mutual exclusion; library file refused and unchanged; meta marker refused; Wesley index synced; other path not synced; `--library` never synced. |
| Must-fix 2: `build_library.py` / `run.py --library` accepted any slug, including wesley | New `src/preached/libraries.py`: allow-list `spurgeon`, `edwards`; `is_public_domain(slug)` (also requires the committed provenance file); `provenance_path(slug)`. `build_library.py` and `ingest/run.py --library` refuse wesley and every other slug (exit 1, clear message). `build_library.py` also refuses a Wesley-style target or another library's file, and writes meta `library=<slug>`. Both existing indexes were re-run to add the marker (+0 sermons). | `2c39d24` | `AllowListTests` (9): list is exactly spurgeon/edwards; provenance committed; **wesley refused** and **unknown slug refused** by both CLIs (also talmage, `../spurgeon`, empty, uppercase); missing provenance is refused. `BuildTargetTests` (3). |
| Patrick decision: Talmage out | Talmage manifest and provenance deleted. Its `SOURCES` entry, special-case code and smoke questions removed. Not on the allow-list. The Talmage-citation should-fix is skipped, as instructed. | `b4cf8fc` | `test_talmage_is_not_shipped`; `test_committed_manifests_validate` expects spurgeon 6 and edwards 39 rows only. |
| Should-fix: text editions for Spurgeon and Edwards | `text_edition` block in each provenance file. `text_source_url` in each manifest row, taken from the LibriVox catalog. Audio sha256s are unchanged. See section 2. | `b4cf8fc` | `test_provenance_records_text_edition` |
| Should-fix: `classics_check.py` is only a smoke test | Renamed `scripts/classics_smoke.py` and `eval/classics_smoke.jsonl`. The docstring, every question row (`"use": "smoke test only..."`) and the summary line say it is not a quality metric. This report no longer presents it as evidence of quality (sections 4-5). | `1483449` | covered by `test_talmage_is_not_shipped` (reads the smoke file); smoke run 12/12 |
| Should-fix: rebinding module globals in `use_library` | `use_library` replaced by `library_paths(slug) -> LibraryPaths` (manifest, audio_dir, transcript_dir, log). Paths are passed to `out_path`, `write_transcript`, `log` and `fetch.ensure_audio(audio_dir=...)`. | `7654432` | `test_library_paths_are_passed_not_rebound` (checks that the module globals are unchanged); `test_transcript_path_stays_inside` updated |
| Should-fix: audio URL check | `check_audio_url` refuses any C0, space, DEL or C1 character. Before, `urlsplit` silently dropped a trailing `\n`, so such a URL passed. `urlsplit`'s own `ValueError` (invalid IPv6 netloc, NFKC-changed host) is now wrapped as `UnsafeRow`. | `763e9e0` | `AudioUrlTests` (4): trailing/embedded newline, CR, tab, NUL, ESC, DEL, NEL, space; IPv6, NFKC and bad-port URLs; all committed manifests still load; `query.play_url` hides these URLs |

Test count: 271, all pass (247 after the merge, minus the 4 original classics tests, plus 6 + 22). `uv lock --check` is clean. No new dependencies, no LLM.

## 10. Fix-up round 2: CTO review of PR #14 (head 18825ef)

First, `origin/main` (4129646, PR #15) was merged in with a merge commit: `67efb03`, no conflicts. No rebase, no force-push. The review file `reports/preached-pr14-review.md` was not in the repo and `gh` is not installed here, so the must-fix list in the task brief was the spec.

| Item | Change | Commit | Tests (`tests/test_libraries.py`) |
|---|---|---|---|
| Must-fix 1: `app/server.py` served any library | `--library` must be `wesley` or pass `is_public_domain`. Then the opened file is checked (`check_servable`). A library file (`videos` table or meta `library`) must carry a `library` marker that names an allow-listed slug equal to `--library`. A YouTube import has no marker, so it is refused. Any other file must look like the Wesley index (has chunks, every `sermon_id` is `wesley-*`) and is served only as `wesley`. Anything else exits 1 with a message: plain SQLite, empty index, other content, not a database, missing. **Church libraries cannot be served until PR #12's redaction/approval gate lands (fail closed).** Checked by hand on `/cache/index`: `wesley`, `spurgeon`, `edwards` and `--index wesley-onnx-fp32.sqlite` serve. `--library cc-speech`, `--library talmage`, `--index cc-speech.sqlite`, `--index spurgeon.sqlite` (without `--library spurgeon`), `--library edwards --index spurgeon.sqlite` and a text file all exit 1. | `85a62e5` | `ServerGateTests` (5): wesley/spurgeon/edwards served (by slug and by `--index`); church (`cc-speech`), `talmage` and unknown slugs refused; `--index` with a church or talmage library file refused; slug/file mismatch refused; plain, empty, non-Wesley, non-SQLite and missing files refused, and the missing file is not created |
| Must-fix 2: `query.py` opened `--library` / non-Wesley `--index` read-write | Every target except the real Wesley index (`INDEX_PATH`) now goes through `open_readonly` (`mode=ro` + `query_only`), as in PR #10's query.py. A missing path is refused, not created, and a file without a `chunks` table is refused. The Wesley index keeps main's `connect` + chunk sync, so the PR #10 merge only has to drop that branch. `--library` now requires `is_public_domain`. The `--index`/`--library` mutual exclusion and the library-file refusal on `--index` are kept. CTO repro by hand: a plain SQLite file keeps the same sha256 and gets no `-wal`; a nonexistent path exits 1 and is not created. `spurgeon.sqlite`, `edwards.sqlite` and `wesley-onnx-int8.sqlite` have the same sha256 after a search. | `085d5d9` | `test_plain_sqlite_index_is_opened_read_only` (bytes unchanged, no `-wal`/`-shm`/`-journal`); `test_nonexistent_index_is_refused_and_not_created` (neither file nor parent dir); `test_library_flag_is_read_only_and_allow_listed` (writes fail, bytes unchanged, church/wesley/talmage refused, an unbuilt allow-listed file is not created) |
| Should-fix: provenance only checked for presence | `load_provenance(slug)` checks that the file parses, `slug` matches, `licenseurl` and `license_note` are present, `text_edition.note` is present, `ia_identifier` is safe and `ia_url` matches it, and `audio_files` is non-empty. Each entry needs a safe `id`/`file_name`, a size > 0, md5, sha256, and must build a valid https archive.org URL (no backslash or control characters). `is_public_domain` is true only when this passes (`BadProvenance` otherwise). | `1351888` | `ProvenanceTests` (8): committed files pass; `{}`, `[]`, empty, bad JSON and `null` refused; slug mismatch or missing; licence missing or blank; text edition missing or blank; empty audio list and bad entries (path names, backslash, size 0/str/bool, bad md5/sha256); bad identifier or ia_url; the committed manifest URLs equal the derived ones |
| Should-fix: backslash host bypass | `check_audio_url` refuses any `\`. `https://evil.com\.archive.org/a.mp3` used to pass (urlsplit host `evil.com\.archive.org`). Control characters are still refused. The server's `public_audio_url` already refused backslashes. | `072abb2` | `test_backslash_host_is_refused`: that exact URL, plus `archive.org\@evil.com` and a backslash in the path; `query.play_url` hides it |
| Should-fix: `build_library.py` checked no sha256 | Each manifest row must match its provenance entry (file name, size, md5, audio URL), or the run stops. Before a sermon is indexed, its audio in `/cache/audio/<slug>` must hash to the recorded sha256. A sermon with missing or different audio is skipped as refused, and the run exits 1. On the real cache, all 6 Spurgeon and 39 Edwards files match. `build_library.py spurgeon` gives "+0 sermons, 0 refused", exit 0. | `d8cddad` | `BuildShaTests` (5): committed manifest matches provenance; md5/size/file_name/URL/id disagreement refused; matching sha passes; same-size different bytes refused; missing audio refused |
| Should-fix: BRIEF Talmage | BRIEF "Demo data" marks Talmage dropped (Patrick's decision, Oct 30). | `3ac27fa` | n/a |

**Wesley output is byte-identical to `origin/main` (4129646).** `origin/main` was exported to `/tmp` and both trees were run on the real `/cache/index/wesley.sqlite`. `search/query.py` output was byte-identical for 3 queries x bm25/hybrid ("what did Wesley say about worry", "Romans 8:16", "assurance of salvation"). The `/api/search` JSON from `app/server.py` (default library) was identical for the same 3 queries x bm25/hybrid/dense, apart from `took_ms`, which is wall-clock timing. In bm25 even `took_ms` matched.

**Tests: 296, all pass** (`uv run python -m unittest discover -s tests`). That is 274 after the merge plus 22 new. **`uv lock --check` is clean** (75 packages). No new dependencies, no LLM.

Notes:
- `README.md` and the W2-YT reports said `app/server.py --library cc-speech` serves a YouTube import. That now exits 1 on purpose. README is updated. The older W2 reports are left as the record of that time.
- A read-only reader of a file that is already in WAL mode (e.g. a built library) may create an empty `-wal` and the `-shm` index. That is SQLite behaviour, and the database bytes do not change. A non-WAL file gets neither (tested).
- The server's Wesley check is about content (every `sermon_id` is `wesley-*`), so the bench variants such as `wesley-onnx-fp32.sqlite` can still be served with `--index`.


## 11. Fix-up round 3: CTO review of PR #14 (head b372646)

`origin/main` had not moved since round 2 (`git log HEAD..origin/main` is empty), so there was nothing to merge. No rebase, no force-push.

| Item | Change | Commit | Tests (`tests/test_libraries.py`) |
|---|---|---|---|
| Must-fix 1: a church import passed as Wesley | The CTO repro was a church import with ids renamed `wesley-*`, the `videos` table dropped, `video_id` kept and no marker. It was served as Wesley. Now `check_servable` also refuses any file whose `chunks` table has `video_id`, `title`, `published` or `flag_end_s`, or any column matching `approv`/`review` (e.g. `review_sha256`, `approved_sha256`). The real Wesley index has none of these columns (checked on `/cache/index/wesley*.sqlite`). The message names the columns. Checked by hand on a real copy of `cc-speech.sqlite` changed the same way: exit 1, "has church-import columns (published, title, video_id)". | `80bd186` | `test_church_import_renamed_wesley_is_refused` (the exact repro); `test_any_church_or_review_column_is_refused_as_wesley` (8 columns, and the plain Wesley schema is still served) |
| Must-fix 2: a forged classics marker at any path | New `libraries.classic_index_problem(slug, path, index_dir=None)`, the one reusable gate for the classics exemption, for PR #12 to call too. The slug must pass `is_public_domain`. Neither the given path nor the canonical `INDEX_DIR/<slug>.sqlite` may be a symlink, and their `realpath`s must be equal. `check_servable` calls it for every non-Wesley `--library`, then requires the matching marker. `query.py --library` calls it too. Checked by hand: `--library spurgeon --index /tmp/.../spurgeon.sqlite` (a real copy, real marker) exits 1, and so does a symlink to `/cache/index/spurgeon.sqlite`. `--library spurgeon` and `--library edwards` still serve. | `80bd186` | `test_forged_classic_marker_elsewhere_is_refused` (the repro: same file name in another directory, plus a church file with a forged marker; the canonical file is still served, also as `dir/./spurgeon.sqlite`); `test_symlinks_to_or_at_the_canonical_path_are_refused` (a link to the canonical file; the canonical path as a link to a forged file); `test_classic_index_problem_is_the_reusable_gate`; `test_index_library_must_match_slug` updated (canonical path with the wrong marker refused) |
| Should-fix: `check_audio_url` passed U+2028 and U+200B | Any non-ASCII character is refused (`UnsafeRow`). The provenance URL check (`libraries._archive_url`) also refuses it. Every committed manifest URL is ASCII and still loads. | `1b409b8` (the `_archive_url` line is in `80bd186`) | `test_non_ascii_is_refused`: U+2028, U+2029, U+200B, U+FEFF, U+00A0, é and U+FF0E in the path, the host and after it; `query.play_url` hides them |
| Should-fix: `query.py` used `connect` for INDEX_PATH | `ensure_chunks(path)` first runs a read-only check, `store.chunks_in_sync`: all schema objects and late columns exist, the file is WAL, and meta `chunks_sha256` equals the chunk file's sha256. Only when that check fails does it open with `connect` and run `sync_chunks`, which is main's behaviour, including creating a missing index. The search then always uses a read-only connection. On the real cache, `wesley.sqlite` is in sync, so `query.py` never opens it read-write (checked with `connect` patched to raise). | `b63ea09` | `WesleySyncReadOnlyTests` (2, sync not mocked): missing index created and synced; second open makes no `connect` call, bytes unchanged, connection refuses writes; changed chunk file re-synced; missing late column re-synced. `test_wesley_search_connection_is_read_only`; `test_wesley_index_is_synced` now checks that the path is passed |
| Nit: manifest vs provenance only at build time | `libraries.check_manifest(slug, provenance)` requires the committed manifest and provenance to have the same ids, each with the same `file_name`, `size`, `md5` and derived `audio_url`. `is_public_domain` runs it, so `query.py`, `app/server.py`, `build_library.py` and `ingest/run.py --library` all check it whenever they run. | `80bd186` | `test_manifest_must_match_provenance_at_runtime`: size, md5, file name, URL, missing row, extra row, duplicate row, non-object row, missing manifest; `test_committed_provenance_passes` now copies the manifest too |

**Wesley output is byte-identical to `origin/main` (4129646).** I compared it the same way as in round 2, on the real `/cache/index/wesley.sqlite`. `search/query.py` output was byte-identical for 3 queries x bm25/hybrid (6/6). The `/api/search` JSON was identical for 3 queries x bm25/hybrid/dense (9/9), apart from `took_ms`. The sha256 of every `/cache/index/*.sqlite` was the same before and after all the manual runs.

**Tests: 306, all pass** (`uv run python -m unittest discover -s tests`). That is 296 + 10 new. **`uv lock --check` is clean** (75 packages). No new dependencies, no LLM.

Notes:
- Behaviour change: `--library spurgeon --index <path>` works only when `<path>` is the canonical file. Copies, symlinks and bench copies of a classic are refused on purpose.
- `check_servable` checks the marker and path of a classic, not its content. Anyone who can write to `/cache/index/<slug>.sqlite` can still put anything in it. That directory is ours (build_library.py writes it), so this is not handled here.
- The check and the open are not atomic: a file swapped between `classic_index_problem` and `open_readonly` would not be caught. The window is at startup only, on a directory only we write to.


## 12. Merge: `origin/main` with PR #10 (W3-CPU, merge `2ad5550`) into PR #14, plus CTO round 4

PR #10 merged first, as the CTO approved. `origin/main` (`2ad5550`) was merged into `feat/w3-lib` (`ad72124`) as a merge commit, `4dd6df0`. No rebase, no force-push. The CTO round-4 gate and should-fixes are a separate commit on top, `e7c78ed`.

### Conflict resolutions (as in the CTO trial merge)

| File | Resolution |
|---|---|
| `app/server.py` (1 hunk, imports) | Kept both: #10's `preached.backends.DEFAULT_EMBED_BACKEND` and #14's `preached.libraries` import. Everything else auto-merged. |
| `search/query.py`, hunk 1 (imports) | #10's imports (`load_embedder`, `check_query_variant`, `open_readonly`), plus #14's `libraries` import and `INDEX_DIR`. Leftover `connect`, `sync_chunks`, `chunks_in_sync`, `StaleChunks`, `index_chunks_jsonl` and the old `embed` imports are gone. |
| `search/query.py`, hunk 2 (helpers) | Kept #14's `is_library_file`, `open_index` and `open_target`. `INDEX_PATH` now goes through `open_target` as well (read-only, no sync), like any other `--index`. `ensure_chunks` is deleted: #10 made `query.py` read-only with no sync, so the read-only `chunks_in_sync` check and its fallback to `connect` had no caller. `store.chunks_in_sync` is deleted too, so `src/preached/store.py` is now the same as on main. |
| `search/query.py`, hunk 3 (arguments) | #14's `--index`/`--library` mutually exclusive group, plus #10's `--embed-backend`, `--onnx-variant`, `--ort-threads` and the torch `--device` help. |
| `search/query.py`, hunk 4 (open) | `open_index(args.index, args.library)` with #10's comment on why the open does not sync. |
| Docstrings and `--help` | `open_index`'s docstring, the `--index`/`--library` help and the library-file refusal message no longer mention a Wesley sync. `--index` help now reads "searched read-only as it is, never synced; library files are refused". |
| `tests/test_libraries.py` | Dropped `test_wesley_index_is_synced` and the whole `WesleySyncReadOnlyTests` class: both tested main's Wesley sync, which #10 removed. Removed the `ensure_chunks` patch from `QueryIndexTargetTests.setUp` and its `assert_not_called` checks. `test_wesley_search_connection_is_read_only` now opens Wesley both by default and by `--index`, and checks the file bytes do not change. |

After the merge commit: **345 tests, all pass**. That matches the CTO trial merge.

### CTO round 4 (`e7c78ed`)

| Item | Change | Tests (`tests/test_libraries.py`) |
|---|---|---|
| **Required gate**: `classic_index_problem` had no owner or mode check | After the existing checks (allow-list, no symlink, realpath equality, file exists), it now also requires the following. INDEX_DIR is not a symlink. INDEX_DIR's parent (`os.stat`), INDEX_DIR (`os.lstat`) and the file (`os.lstat`) are each owned by `os.geteuid()` with no group or world write bit. The file is a regular file with `st_nlink == 1`. Both `app/server.py` and `query.py --library` go through it. On this machine `/cache` (0700), `/cache/index` (0755) and `spurgeon.sqlite`/`edwards.sqlite` (0644, one link) all belong to the server's uid, so both classics are still served. | `ClassicOwnerModeTests`: world-writable and group-writable parent, INDEX_DIR and file are refused through `classic_index_problem`, `server.main` and `query.py` (3 targets x 2 bits); a symlinked INDEX_DIR is refused; a hardlinked file is refused, then passes once the extra link is gone; wrong owner for each of parent, dir and file is simulated by mocking `os.stat`/`os.lstat`, and a different server uid by mocking `os.geteuid`; the private layout passes. |
| Should-fix: church names compared case-sensitively, and `Video_ID` in a side table passed | `CHURCH_COLUMNS`/`REVIEW_COLUMN` are replaced by an allow-list, `WESLEY_SCHEMA`: the exact tables `store.connect` creates (chunks, the five FTS5 tables, embeddings, meta) and each table's columns, compared lower-cased. Any other table or view, or any other column in an allowed table, is refused with its name. SQLite's own `sqlite_*` tables are ignored. A subset is enough, because older bench indexes lack the late columns. The table set used for the `videos`/marker branch is lower-cased too. Wesley ids are matched with `GLOB 'wesley-*'` rather than the case-insensitive `LIKE`. | `WesleyAllowListTests`: `store.connect`'s schema is exactly the allow-list and is served; `Video_ID`, `VIDEO_ID`, `Title`, `Approved_SHA256` and `flag_END_s` in chunks are refused; a side table with `Video_ID`, a `VIDEOS` table, extra columns on meta or embeddings, and a view are refused; `WESLEY-001` is not Wesley. The round-3 tests (`test_church_import_renamed_wesley_is_refused`, 8 columns) still pass. |
| Should-fix: `st_dev`/`st_ino` before and after the open | `main` records `file_identity(index)` (`st_dev`, `st_ino`, following symlinks as the open does) before `open_readonly`. After `check_servable`, it reads it again and refuses on a mismatch ("was replaced while it was being opened or served"). | `test_inode_change_across_the_open_is_refused` (mocked identities); `test_replaced_file_is_refused_on_reload` (a real `os.replace` onto the path). |
| `check_servable` on every Searcher #10's reload builds | `App` takes a `servable(connection)` hook. `main` passes `check_servable` plus the identity check, through `build_app`. `_refresh_if_stale` runs it before `_reload_cached_index` and before the keyword-only fallback after a failed stamp read, so no `Searcher` is built from a reloaded file that has not passed the gate. On failure the app drops its searcher and returns 503 `{"error": "index unavailable"}` for search, health and sermon; the details are logged, not sent. `_status_failed` stays set, so the gate runs again on the next request, and serving resumes once it passes. `sermon()` now refreshes too, so it cannot read a file the gate has started refusing. The hook defaults to None, so apps built directly (tests, #10's YouTube reload test) behave as before. | `test_reload_runs_check_servable_before_any_searcher`: an in-place `ALTER TABLE chunks ADD COLUMN Video_ID` plus a new chunk hash makes search, health and sermon return 503 with no `Searcher` built; dropping the column brings search back. #10's `test_server_reloads_youtube_library_and_falls_back` passes unchanged. |

Test INDEX_DIRs in `QueryIndexTargetTests` and `ServerGateTests` now sit one level under the temp dir (`<tmp>/index`), and the module sets umask 022. Otherwise a shared `/tmp` (root-owned, mode 1777) as INDEX_DIR's parent would trip the new gate.

### Results

- **Tests: 357, all pass** (`uv run python -m unittest discover -s tests`): 345 after the merge, plus 12 new.
- **Wesley is byte-identical to main `2ad5550`.** `git archive 2ad5550` was exported to a temp dir, and both trees were run with the same venv on the real `/cache/index/wesley.sqlite` (onnx fp32 default). `search/query.py` output, stdout plus stderr plus exit code, was byte-identical for 5 queries x bm25/dense/hybrid (15/15). The queries were "what did Wesley say about worry", "Romans 8:16", "assurance of faith", "the witness of the Spirit", and a nonsense query. `/api/search` JSON from `app/server.py` was identical for 5 queries x 3 modes (15/15), apart from `took_ms`. `/healthz` and `/api/sermon/wesley-001` were identical. The sha256 of `/cache/index/wesley.sqlite` was the same before and after the tests and all the runs.
- `check_servable` on the real files: `wesley.sqlite`, `spurgeon.sqlite` and `edwards.sqlite` are served; `cc-speech.sqlite` is still refused.
- **`uv lock --check` is clean** (79 packages, main's lock; `uv.lock` and `pyproject.toml` are identical to main). No new dependencies, no LLM.
- **Head:** `e7c78ed` (code). This report is the commit after it; see `git log -1 origin/feat/w3-lib` for the pushed head.

### Run

```
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_libraries tests.test_youtube
uv lock --check
uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
uv run search/query.py "grace" --mode bm25 --library spurgeon
uv run app/server.py --library edwards --bm25-only
```

### Open issues

- The reload gate runs only when #10's stamp changes (chunk hash, row count, embedding records) or after a failed read. A schema-only change in place that leaves the stamp alone is not rechecked until the next stamp change. The cached rows do not change in that case either.
- The identity check compares the path's inode before the open and after the checks. It cannot see the inode SQLite holds open, so a swap and swap-back inside that window would not be caught. The window is at startup, and the owner/mode gate means only the server's uid can write the classics' directory.
- The owner/mode gate covers the classics only. The Wesley path (`INDEX_PATH`) is gated on content, as before.
- The section 11 row about `ensure_chunks`/`chunks_in_sync` is superseded: both are gone after the merge.
