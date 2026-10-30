# W3-LIB: more classic preachers in the built-in library

Branch `feat/w3-lib`, from `origin/main` (9c3e303). Written 2026-10-30.

## 1. What was done

Three hand-picked archive.org items were added, each as its own library (its own SQLite file, `/cache/index/<slug>.sqlite`). The existing W1-A pipeline (`ingest/`) transcribed them, and the W2-YT library writer indexed them. No parallel pipeline and no new dependency.

| Library slug | Source (archive.org id) | Sermons | Audio | Words | Chunks | Index file |
|---|---|---|---|---|---|---|
| `talmage` | `SermonOnTheMountByT.DeWittTalmage1898` | 1 | 58 s (0.02 h) | 114 | 1 | 52 KB |
| `spurgeon` | `spurgeons_sermons_librivox` | 6 (nos. 191-196) | 4.32 h | 41,859 | 534 | 3.0 MB |
| `edwards` | `select_sermons_edwards_0911_librivox` | 39 tracks (one is the editor's "Advertisement") | 19.53 h | 192,970 | 2,514 | 14.5 MB |

**Edwards finished in full: 39/39 tracks, 19.53 h.**

Code changes (all small):
- `ingest/classics.py` (new): fixed `SOURCES`, builds `ingest/manifest/<slug>.jsonl` in the Wesley row schema (LibriVox API joined for titles and readers) and, with `--provenance`, `<slug>.provenance.json`.
- `ingest/run.py`: new `--library <slug>` (default `wesley`) that points the manifest, audio and transcript folders at that library. Metadata keys fall back to `None`, and the voice note names the right author. Wesley behaviour is unchanged.
- `search/build_library.py` (new): transcripts to the searchable word window, to chunks (`corpus/chunk_config.json`), to Granite English R2 on CPU, into `/cache/index/<slug>.sqlite`. Resumable per sermon.
- `src/preached/youtube/library.py`: `index_video` takes optional `reader`, `sermon_number` and `librivox_id` (defaults keep the YouTube behaviour).
- `search/query.py`: new `--library <slug>`. It skips the Wesley chunk sync, which would otherwise write Wesley chunks into another library's file.
- The server already serves one library per process: `uv run app/server.py --library spurgeon` (see README). No server change.
- `eval/classics_questions.jsonl` and `scripts/classics_check.py`; `tests/test_classics.py` (4 tests).

## 2. Sources and licences (provenance in `ingest/manifest/<slug>.provenance.json`)

Each file has the identifier, title/creator/licence from archive.org metadata, the full archive.org file list, and per audio file: size, md5 (from archive.org) and sha256 (computed on the downloaded file; md5 and size are verified at download by `ingest/fetch.py`).

- **Spurgeon** and **Edwards**: LibriVox items. archive.org `licenseurl` is `http://creativecommons.org/licenses/publicdomain/`; LibriVox recordings are dedicated to the public domain. Spurgeon (d. 1892) and Edwards (d. 1758) texts are public domain. The voices are volunteer readers (named per section), not the preachers. archive.org lists the Spurgeon creator as "Charles Sturgeon", a typo; the manifest uses Charles Haddon Spurgeon. Audio used: the 64 kbps MP3 derivative, as for Wesley.
- **Talmage**: an 1898 disc recording in archive.org's `78rpm` collection. **It has no `licenseurl` field.** My basis for calling it public domain is that it was fixed in 1898 (before 1923) and Talmage died in 1902; that is my reading, not a rights opinion, and a human should confirm it before anything is published. Audio used: the original upload `SermonOnTheMount1898.mp3` (VBR, 1.1 MB), not the 64 kbps copy, because the source is already poor. The recording is only 58 s long, so this library holds one short clip, not a sermon archive. This is Talmage's own voice.
- Nothing was imported by tag. Content was checked by transcript spot reads (Spurgeon, Edwards are orthodox Protestant sermons; Talmage reads the Beatitudes).

## 3. Transcription

Same as W1-A: faster-whisper `large-v3-turbo` (`mobiuslabsgmbh/faster-whisper-large-v3-turbo`, revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, OpenAI Whisper lineage), fp16, batch 8, beam 5, Silero VAD, `word_timestamps=True`, `without_timestamps=False`, English, one-line prompt `"<work>, by <author>."`, gap fill and loop repair on. Word timings are **ASR word timings, not forced alignment** (`text_source = asr` on every chunk). No published text was aligned: the indexed text is what Whisper heard, so it contains ASR errors (the readers' text and the printed text were not compared; no WER was measured for these three).

| Library | Wall time | Speed | VRAM peak | Gap-filled segments | Loop repairs |
|---|---|---|---|---|---|
| talmage | 2.9 s | n/a (58 s file) | 2.3 GB | 0 | 0 |
| spurgeon | 4.2 min | 65 audio-h/wall-h | 3.26 GB | 8 | 1 |
| edwards | 21 min | 55.5 audio-h/wall-h | 3.26 GB | 44 | 1 |

No OOM back-off. The GPU was shared with another tenant at times.

## 4. Quality problems (honest notes)

- **Talmage 1898.** Only 114 words, from a 58 s disc. Whisper heard the Beatitudes (Matt 5:3-12) with obvious errors: "they shall be comfortless" (for "comforted"), "for they shall be killed" (for "filled"), and the passage ends at "...falsely for men." Whisper's idea of the text leans on the very familiar Bible passage, so I cannot say which words were really on the disc without a human listening. The end is cut off in the transcript (searchable window 1.49-55.03 s). Timestamps are coarse: one 45 s chunk. Do not quote this transcript as what Talmage said.
- **Spurgeon / Edwards.** Modern volunteer readings, so audio is clean. Not checked word for word. Archaic words and Latin/Greek citations are the likely error spots. `ingest/qa.py` reports only for the Wesley folder; I did not extend it.
- Edwards track 10 is the editor's "Advertisement" (4 min) and is indexed as `kind: preface`. Edwards sermons are split across tracks ("pt 1", "pt 2"), so each part is its own `sermon_id`.
- LibriVox intro/outro boilerplate that Whisper transcribed is left out of the index by the W1-A window rule; what Whisper dropped is simply absent.
- No privacy redaction was applied: the sources are 18th-19th century public texts. The W3-PRIV name list is for church sermons.
- Question set is tiny and written by me; it shows the pipeline works, not retrieval quality.

## 5. Test questions and results

Written by the agent (Claude), **not human-reviewed**. Hybrid search, top 5, Granite English R2. A pass needs an expected sermon in the top 5, a `start_s`, and an archive.org play URL with the 0.75 s pre-roll (`eval/classics_questions.jsonl`).

| Library | Question | Rank | Hit |
|---|---|---|---|
| talmage | blessed are the peacemakers | 1 | talmage-1898-01 @ 0:00:01 |
| talmage | blessed are those who are persecuted for righteousness | 1 | talmage-1898-01 @ 0:00:01 |
| spurgeon | who is the builder and the foundation of the church | 1 | 191 @ 0:20:03 |
| spurgeon | what is the duty of a Sunday school teacher | 1 | 192 @ 0:25:05 |
| spurgeon | these men have turned the world upside down | 1 | 193 @ 0:23:04 |
| spurgeon | is man responsible for his sin if God is sovereign | 3 | 194 @ 0:18:57 |
| spurgeon | look unto me and be ye saved | 1 | 195 @ 0:46:23 |
| spurgeon | religion that helps us now, not only after death | 1 | 196 @ 0:10:54 |
| edwards | sinners held over the pit of hell like a spider | 1 | edwards-02 @ 0:06:32 |
| edwards | a spiritual light from God that is different from natural knowledge | 1 | edwards-03 @ 0:04:53 |
| edwards | God chooses whom to save by his sovereign will | 1 | edwards-08 @ 0:06:00 |
| edwards | Christ is both a lion and a lamb | 1 | edwards-17 @ 0:25:09 |
| edwards | in my Father's house are many mansions | 1 | edwards-39 @ 0:00:00 |
| edwards | is it just for God to condemn sinners to hell | 4 | edwards-27 @ 0:30:34 |

**14/14 pass.** I did not listen to the audio at these timestamps; the timestamps come from ASR word starts. (The first Edwards question lands in part 2 of "Sinners in the Hands of an Angry God", which is the part containing the spider image.)

## 6. Tests

`uv run python -m unittest discover -s tests`: **207 tests, all pass** (203 before, plus 4 in `tests/test_classics.py`: manifests validate, title cleaning, `--library` path switching and slug refusal, searchable window and chunking). `uv lock --check`: clean.

## 7. Rerun

```bash
cd /work/preached/.worktrees/feat/w3-lib
uv run ingest/classics.py --provenance                       # manifests + provenance (needs audio for sha256)
for s in talmage spurgeon edwards; do
  uv run --extra transcribe ingest/run.py --library $s --all   # resumable; ~30 min total on an RTX 3060
  uv run search/build_library.py $s                            # -> /cache/index/$s.sqlite
done
uv run search/query.py --library spurgeon "what is the duty of a Sunday school teacher" -k 3
uv run scripts/classics_check.py                             # 14 questions
uv run app/server.py --library edwards                       # serve one library
uv run python -m unittest discover -s tests && uv lock --check
```

Audio, transcripts and indexes are under `/cache/{audio,transcripts,index}/<slug>`; only manifests, provenance, code, eval questions and this report are committed.

## 8. Open issues

- Talmage licence needs human confirmation (section 2).
- The web page still sends `library=wesley`; one process serves one library, so a library switcher or a side-by-side view needs a server change (W3 follow-up).
- Calvin (`mostcelebratedsermonsjohncalvin_2104_librivox`) and the other BRIEF names were out of scope.
- Dependencies added: none.
