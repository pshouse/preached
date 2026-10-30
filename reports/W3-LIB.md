# W3-LIB: more classic preachers in the built-in library

Branch `feat/w3-lib`, from `origin/main` (9c3e303), with `origin/main` (e2ddbc7) merged in for the fix-up. Written 2026-10-30. The CTO review fix-up is in section 9.

## 1. What was done

Two hand-picked public-domain archive.org items were added, each as its own library (its own SQLite file, `/cache/index/<slug>.sqlite`). The existing W1-A pipeline (`ingest/`) transcribed them, and the W2-YT library writer indexed them. No parallel pipeline and no new dependency.

| Library slug | Source (archive.org id) | Sermons | Audio | Words | Chunks | Index file |
|---|---|---|---|---|---|---|
| `spurgeon` | `spurgeons_sermons_librivox` | 6 (nos. 191-196) | 4.32 h | 41,859 | 534 | 3.0 MB |
| `edwards` | `select_sermons_edwards_0911_librivox` | 39 tracks (one is the editor's "Advertisement") | 19.53 h | 192,970 | 2,514 | 14.5 MB |

**Edwards finished in full: 39/39 tracks, 19.53 h.**

**Talmage was dropped by Patrick's decision.** A third library, T. De Witt Talmage's 1898 *Sermon on the Mount* disc (`SermonOnTheMountByT.DeWittTalmage1898`), was built in the first pass. It is not in this PR: archive.org gives no licence for it, the clip is 58 s, and the transcript is rough. Its manifest, provenance, source entry, smoke questions and tests were removed, and it is not on the public-domain allow-list. The index file built in the first pass is still at `/cache/index/talmage.sqlite` (cache only, never committed). Delete it if it should not be served by accident.

Code changes:
- `src/preached/libraries.py` (new, fix-up): the committed allow-list of public-domain libraries, exactly `spurgeon` and `edwards`. The API is `is_public_domain(slug)` and `provenance_path(slug)`. A slug counts only if it is on the list and its `ingest/manifest/<slug>.provenance.json` is committed. PR #12 can use it to exempt only these slugs from redaction and the approval gate.
- `ingest/classics.py` (new): fixed `SOURCES`. It builds `ingest/manifest/<slug>.jsonl` in the Wesley row schema, joining the LibriVox API for titles, readers and the text source. With `--provenance` it also writes `<slug>.provenance.json`.
- `ingest/run.py`: new `--library <slug>`, which accepts allow-listed slugs only. Without the flag it runs on Wesley as before. The manifest, audio, transcript and log paths are passed explicitly as a `LibraryPaths`; no module globals are rebound. `ingest/fetch.py`: `ensure_audio`/`audio_path` take an optional `audio_dir`.
- `search/build_library.py` (new): takes the transcripts' searchable word window, chunks it (`corpus/chunk_config.json`), embeds with Granite English R2 on CPU and writes `/cache/index/<slug>.sqlite`. It is resumable per sermon and accepts allow-listed slugs only. It refuses a target that is a Wesley-style index or another library's file, and it marks its file with meta `library=<slug>`.
- `src/preached/youtube/library.py`: `index_video` takes optional `reader`, `sermon_number` and `librivox_id`. The defaults keep the YouTube behaviour.
- `search/query.py`: new `--library <slug>`, which cannot be combined with `--index`. Only the Wesley index file gets the Wesley chunk sync. `--index` refuses library files.
- `ingest/manifest.py`: `check_audio_url` now refuses control characters and spaces, and it wraps `urlsplit` errors.
- The server already serves one library per process: `uv run app/server.py --library spurgeon` (see README). No server change was needed.
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
- `search/query.py --library` and `app/server.py --library` open any `/cache/index/<slug>.sqlite`, including church libraries and the leftover `talmage.sqlite`. The allow-list gates ingest and build, not search.
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
