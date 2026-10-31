# W3-ASR-COVERAGE: ASR coverage gate

Branch `feat/w3-asr-coverage`, rebased on `origin/main` (`3c5526d`). The WIP commit from the stopped run was reviewed, fixed and folded in.

## What was done

1. **Coverage check** (`src/preached/youtube/coverage.py`). Decodes the audio with ffmpeg to 16 kHz mono and finds non-silent stretches by frame energy (30 ms frames, within 30 dB of the file's 98th-percentile level, floor -58 dBFS, breaths under 0.6 s merged, sound under 0.25 s dropped). Transcript words, padded 0.3 s, are subtracted. What is left, merged across short silences and longer than `MAX_UNCOVERED_S = 5.0`, is an uncovered span. Energy was used on purpose: the stack's Silero VAD is the transcriber's own filter, and a check that shares it shares its blind spot. If ffmpeg cannot decode the file, the video's duration counts as speech (fallback to audio length); with neither, the import fails.
2. **Gate.** Both import paths store the spans in `videos.coverage_gaps` (JSON; new column). `approve_review` refuses when the column is NULL (check never ran) or non-empty, and names the spans. Spans also go into the private review file as `field: "coverage"` lines. The YouTube path checks the whole file; a `--windows` entry for the video limits the check to that window (a human has said where the sermon is). `align/asr_chunks.py` (transcript JSON import) takes `--audio-dir` (`<sermon id>.<ext>`) and checks inside `searchable_start..searchable_end`; without audio it stores NULL, so approval is refused.
3. **Cause.** Not reproduced (below). No setting was changed. The WIP's only change to `transcribe.py` was moving the prompt into `INITIAL_PROMPT`; that is kept (same text).
4. `scripts/asr_holes.py`: probe that runs named Whisper settings on one file and prints the uncovered spans.

## Measured holes

Audio: `/cache/w3-asr/clip240.wav` (240 s) and the full `/cache/youtube/cc-speech/BGoD6CIpLWQ.webm` (321.6 s). Model large-v3-turbo (Mobius conversion) unless noted. Language en, word timestamps, VAD on, beam 5, `condition_on_previous_text=False`, the product prompt.

| Device | Settings | Audio | Holes | Uncovered |
|---|---|---|---|---|
| CPU int8 | product | 240 s | 1 (28.2-33.7 s) | 5.5 s |
| CPU int8 | `vad_filter=False` | 240 s | 1 | 5.5 s |
| CPU int8 | looser VAD (thr 0.3, silence 1000 ms, pad 400 ms) | 240 s | 1 | 5.5 s |
| CPU int8 | no_speech 0.9, logprob -2.0, compression 2.8 | 240 s | 1 | 5.5 s |
| CPU int8 | `temperature=0` | 240 s | 1 | 5.5 s |
| CPU int8 | looser VAD and thresholds | 240 s | 1 | 5.5 s |
| CPU float32, 4 threads | product | 240 s | 1 | 5.5 s |
| CPU int8 | product | 321.6 s | 1 | 5.5 s |
| CPU `tiny.en` int8 (the product's CPU fallback) | product / no VAD / loose thresholds | 240 s | 1 each | 5.2 s |
| GPU (3060) int8_float16 | product | 240 s and 321.6 s | 1 | 5.5 s |
| GPU | loose thresholds | 240 s | 1 | 5.5 s |

**The CTO's 22-75 s holes (15-30 s each) did not reproduce** on this audio, on CPU or GPU, with any setting above. "Before" and "after" are therefore the same. The one span, 28-34 s, is not speech: transcribing 20-40 s alone with VAD off and no prior text returns text for 20.6-27.8 s and 34.2-38.8 s and nothing between (no_speech_prob 0). It is music or a sting in the intro. The gate flags it, and a listen clears it (re-import with a `--windows` entry that starts after it). So the gate costs one false positive on this file, and I did not find the cause of the CTO's holes: the CTO's file, thread count or batched pipeline may differ from what I ran. Open item for them: send the file, or the exact command.

GPU shows the same single span and 5 s wall time vs 43-57 s on CPU for turbo (85 s float32).

## Gate behaviour

- Import never fails because of a gap. The sermon lands unpublished with the spans stored and printed (`coverage <id>: no transcript for sound at 28.2-33.7s`).
- `--ack-review` refuses: `ID: 1 stretch(es) of sound have no transcript (28-34s). Listen, then re-import with --redo ...`.
- Music, applause and singing that no word covers also block. There is no "clear this span" command; the clearing step is a re-import with a window. Say if you want a per-span ack instead.
- A hole in the first or last seconds of a sermon is caught on the YouTube path only because the check runs over the whole file when there is no window.

## How to run

```bash
uv run python -m unittest discover -s tests
uv run --extra transcribe python scripts/asr_holes.py AUDIO --device cpu --variant product --variant novad
uv run python align/asr_chunks.py T.json --out o.jsonl --library church --index church.sqlite --audio-dir AUDIO_DIR
```

## Results

- Tests: 503 pass (492 before; 11 new in `tests/test_coverage.py`: synthetic audio with a missed speech stretch is found and blocks approval end to end; a clean file passes and is approved; gap under 5 s, room-tone silence, hole at the end, two holes, undecodable audio, window clipping, unchecked import refused). Existing import tests inject `coverage=lambda *_a, **_k: []` because their audio files are fake.
- `uv lock --check`: passes (`Resolved 79 packages`).
- Head SHA: see the PR head (`git rev-parse HEAD` on the branch).

## Dependencies

None added (numpy and ffmpeg are already needed).

## Risks

- Energy marks any loud non-speech as sound; expect false positives on music and applause.
- Quiet speech more than 30 dB below the file's loud end counts as silence and is never checked.
- The gate is only as good as the `--windows` discipline for clearing.

## Main merge

Merged `origin/main` (e465ad0, after #19 W3-PRIV-SKIP) into this branch with a merge commit (no rebase). Conflicted files:

- `align/asr_chunks.py`: kept both. Each sermon tuple is now `(records, review_sha, base_sha, gaps)`; `index_video` gets `coverage_gaps` and `review_base_sha256`; `main` keeps #19's `private_sermon(..., args.out)` call and #20's `sermon_gaps`.
- `src/preached/youtube/library.py`: kept both schema columns (`review_base_sha256` and `coverage_gaps`) and both `index_video` parameters, written in one UPDATE. `approve_review` no longer exists on main (#19 moved approval to `preached.exclusions.approve`), so it is dropped here.
- `src/preached/youtube/pipeline.py`: kept both imports; the import step runs the coverage check, adds `coverage` review lines to the header, then writes #19's kept-words file and review lines; both columns are stored; the summary line reports excluded stretches and coverage gaps.

Not a textual conflict, but needed: the coverage refusal now lives in `exclusions.approve` (reads `coverage_gaps`, refuses when NULL or non-empty, before any rebuild), so it runs alongside every #19 rule (privacy-config hash, review-file hash, exclude-line-only edits, no narrowing). The reviewer-widening rebuild passes the stored `coverage_gaps` through, so it does not reset to NULL. `youtube/coverage.py` docstring updated.

Tests: #19's tests that import fake audio (`test_priv_skip.py`, `test_priv_skip_fixup.py`, `test_priv_skip_links.py`) now inject `coverage=lambda *_a, **_k: []`. New `test_skip_stretch_and_open_coverage_span_both_gate_approval`: a sermon with skip stretches and an open coverage span is refused (also after a reviewer widens a stretch), and approved after `--redo` with the gap resolved, with skipped markers still absent from the index. The combination is reachable.

- Tests: 540 pass.
- `uv lock --check`: passes (`Resolved 79 packages`).
- Head SHA: stated in the final message (a report cannot contain its own commit's SHA).

## Round-1 fix-up (CTO review of PR #20 at 7b23af1)

This section supersedes the parts above that it contradicts. Points 1 and 2 of "What was done" (30 dB, falling back to the duration on decode failure) and the "Gate behaviour" refusal text no longer apply.

Commits: `47179b8` (all code, tests and fixtures), `3efb3ca` (merge of `origin/main` 9e5c054, #16 W3-SIDE; no conflicts), `7858ba2` (two tests from #16 updated to the new rules), and the commit adding this section.

### Must-fixes

| Item | Change | Tests |
|---|---|---|
| M1 one word covers any length | `coverage.WORD_MAX_COVER_S = 2.0`: a longer word covers 1 s at its start and 1 s at its end, plus the 0.3 s pad. Gaps are now measured by the transcript: the time between two word covers, with pauses included. A gap counts when it is longer than 5 s and at least half of it is sound that no padded word touches. Before the first word and after the last word it is trimmed to sound. | `test_one_long_word_does_not_cover_a_hole`; `CorruptedAsrFixtureTests.test_the_junk_word_hole_needs_the_word_cap` (c03 'eject' is flagged; with the cap off it is not) |
| M2 serve time ignores coverage | `store.visible_sql` also requires `v.coverage_gaps = '[]'`. NULL, a non-empty list, `''` or `'[ ]'` are not served. A file with no `coverage_gaps` column fails closed (`"0"`). `pending_review_count` counts such rows as pending. Every serving path (server, query.py, #16's `library.py`) goes through `visible_sql`. | `test_serving_requires_an_empty_coverage_list` (approved and `[]` is served; each other value hides it and counts as pending) |
| M3 short audio passes | `check_coverage` raises `Unchecked` when the decoded audio plus `LENGTH_TOLERANCE_S = 2.0` is shorter than the last word end or the stated duration. The YouTube path passes the metadata duration. The church path passes `meta.duration_s` when the transcript has one. The length check covers the whole file even when a window is set. | `test_audio_shorter_than_the_transcript_is_unchecked`, `test_download_cut_short_is_unchecked_and_refused` (YouTube download cut to 60 s of 240 s: NULL, refused), `ChurchPathTests.test_short_or_undecodable_audio_stores_null` (20 s of 60 s; shorter than `meta.duration_s`) |
| M4 no end-to-end church test | New `ChurchPathTests` runs `align/asr_chunks.py` with real WAVs and the real `check_coverage` (no stub), then runs `--ack-review`. Removed the test-only `injected` shortcut in `sermon_gaps`: with no audio file the result is NULL, stub or not. Church tests that stub coverage now pass a real `--audio-dir` holding a placeholder file (`tests/coverage_stub.py`). | clean → `[]`, approved, served; hole → refused; no audio → NULL, refused; window clears the intro |

### Should-fixes

| Item | Change | Tests |
|---|---|---|
| S1 | `REL_DB = 40.0`. Noise-floor guard: the threshold is also at least `NOISE_MARGIN_DB = 6` above the 5th-percentile frame level, so a steady hiss inside 40 dB is not counted as sound. | `test_quiet_speech_counts_as_sound` (speech 33 dB down, untranscribed, is flagged), `test_steady_hiss_is_not_sound` |
| S2 | `sparse_spans`: 15 s windows at a 1 s step. A window with at least 7.5 s of sound needs `MIN_WORDS_PER_S = 0.5` words per second of sound. Flagged windows merge, are trimmed to sound, and are unioned with the gaps. | `test_stray_words_over_speech_are_a_sparse_span` (one word every 4.5 s over 40 s: the gap rule alone finds nothing, the density rule finds it) |
| S3 | `sermon_audio`: the stem must equal the sermon id exactly and the suffix must be an audio suffix (`church-1.json`, `church-10.wav` and `church-1.txt` are never taken). Two candidates refuse (`SystemExit`, "keep one") before any file is written. No glob, so ids with glob characters are safe. | `test_audio_is_matched_by_exact_name`, `test_two_audio_files_for_one_sermon_refuse_before_writing` |
| S4 | A decode failure raises `Unchecked`; there is no fallback to the duration. Both paths store NULL and print `coverage ID: NOT checked (...); approval is blocked`. The YouTube review file gets `{"field": "coverage", "unchecked": true}`. | `test_undecodable_audio_is_unchecked`, church undecodable case |
| S5 | `exclusions._rebuild`: `None if coverage_gaps is None else json.loads(...)`. | `test_rebuild_keeps_an_unchecked_coverage_null` (None, `[]` and a span each pass through unchanged) |
| S6 | The refusal names each path's own step (`exclusions.REIMPORT`). YouTube: `--redo`, after re-transcribing or with a `--windows` entry. Church: fix the transcript or set `searchable_start`/`searchable_end`, then re-run `align/asr_chunks.py --index --audio-dir`. The coverage module docstring documents clearing. | `test_hole_in_the_recording_blocks_approval` asserts the church wording; `test_hole_outside_the_searchable_window_needs_no_clearing` |

**Clearing a span** (CTO ruling: re-import for now). Listen to the span first. Then:

- **YouTube:** re-import with `--redo`, after re-transcribing, or with a `--windows` entry that leaves out music before or after the sermon.
- **Church:** fix the transcript, or set `searchable_start`/`searchable_end` around the sermon, and re-run `align/asr_chunks.py --index ... --audio-dir ...`.

The 5.5 s intro-music false positive on `clip240` fails closed and is cleared this way.

**Follow-up, not done (exclude line clears a span).** It does not fit cleanly in this round. A span holds no words, so an `exclude` line over it removes nothing. Clearing would need three things: (a) a stored "cleared" state, since serving checks `coverage_gaps = '[]'`, written only by `approve` and bound to the approved review hash; (b) a rebuild that flags the chunks on both sides of the span, so no link seeks into it (`boundary_flags`); (c) re-import carry-over. That is a separate change with its own tests.

### ASR holes: AMX guard

- `src/preached/cpu_guard.py`: `avoid_amx()` reads the `flags` lines of `/proc/cpuinfo`. On `amx_int8` or `amx_tile`, with `MKL_ENABLE_INSTRUCTIONS` unset, it sets the variable to `AVX512`. If ctranslate2 is already in `sys.modules`, it raises `AmxUnsafe` with the fix instead. A value the operator already set is left alone. No new dependencies.
- Called before ctranslate2 loads in `youtube/transcribe._run`, `ingest/transcribe.Transcriber.__init__` (CUDA, but it loads the same library) and `scripts/asr_holes.py`.
- Tests (`tests/test_cpu_guard.py`, fake cpuinfo): a Xeon with AMX gets AVX512; a tile-only flag counts; a desktop CPU is untouched, even when an `amx_` string appears on a non-flags line; an operator value is kept; refuses when ctranslate2 is loaded; both entrypoints call the guard before importing faster-whisper.
- The coverage gate still checks every transcript: a GPU or production host could corrupt ASR in another way.

### Gate on the CTO's corrupted fixtures

The fixtures are in `tests/fixtures/asr_repro/` (README has the provenance below). Each has the word lists plus the clip's frame level at 0.1 dB, 16 KB each. The spans from the level match the spans from the WAV exactly (`test_envelope_matches_the_audio`, which runs when `/cache/asr-repro` is present).

| Clip | Transcript | Spans flagged | CTO holes > 5 s |
|---|---|---|---|
| c01 | AMX-corrupted | 24.52-30.64, 125.0-159.0 | 24.52-30.64 ✓, 140.42-156.18 ✓ (also 'inflammations' 127.62-140.42) |
| c03 | AMX-corrupted | 24.0-87.0, 95.0-148.0 | 25.58-54.16 ✓, 'eject' 56.92-85.38 ✓, 96.68-115.38 ✓, 116.66-146.66 ✓ |
| c01 / c03 | clean (same model and settings, i9-12900K without AMX, 35-41 s per clip) | none / none | none |

Before this round the gate flagged one of c01's two holes and missed c03's 'eject' hole entirely. c01 24.52-30.64 holds only 4.4 s of speech (with a pause), so a rule based on the extent of the sound alone misses it. Measuring by the transcript's silence catches it.

**False positives on complete transcripts.** I ran all 143 Wesley sermons (GPU batched transcripts in `/cache/transcripts/wesley`, against their mp3s) through the gate. Every flagged span is speech the ASR really dropped:

- the LibriVox disclaimer or outro, which the ingest notes say Whisper routinely drops (most files, in the first ~25 s; 33 files inside `searchable_start..end`);
- three mid-sermon spans where one word is stretched 9-11 s over continuous speech (`wesley-s1-26` 'the' 1289.8-1300.5, `wesley-s2-25` 'sleep' 382.4-391.1, `wesley-s2-51` 'by' 17.7-28.8). This is the M1 pattern on a healthy GPU run.

No flagged span was silence or noise. The Wesley library is public domain and never gated, so this does not change Wesley.

Density margin on unflagged windows: p5 is 1.29 words per second of sound across Wesley, and the single lowest window is 0.52, against the 0.5 threshold. The clean c01/c03 runs are at ≥ 2.2.

**Mutation check.** I applied 20 mutations one at a time and ran the full suite on each. Every mutation made the suite fail:

- M1 cap off; M2 serve check off;
- M3: length check off, duration dropped from it, YouTube path drops the duration, church path drops the duration;
- M4: church stores `[]` on missing audio; church default is a stub;
- S1: 30 dB; noise guard off;
- S2: density off;
- S3: prefix match; ambiguity refusal off;
- S4: decode failure gives `[]`; pipeline turns `Unchecked` into `[]`;
- S5: falsy check;
- approve ignores NULL;
- AMX guard not called in each entrypoint; AMX refusal off.

### Repro provenance

- **Audio:** LibriVox Wesley, archive.org `sermonsfirstseries_1307_librivox`. Clips made with `ffmpeg -ss 60 -t 240 -i sXX.mp3 -ar 16000 -ac 1 cXX.wav`.
- **Checksums:** c01.wav sha256 `7338e033…4a76d`, c03.wav sha256 `ff4e3ed6…15ac` (in full in the fixture README).
- **ASR:** `mobiuslabsgmbh/faster-whisper-large-v3-turbo` @ `0a363e9…`, faster-whisper 1.2.1, ctranslate2 4.8.4, CPU int8.
- **Root cause (CTO's finding):** MKL's AMX int8 kernels on a Xeon VM. With `MKL_ENABLE_INSTRUCTIONS=AVX512` or `AVX2` the output is bit-stable and turbo int8 leaves no holes. This box (i9-12900K) has no AMX, so I could not reproduce it.

### How to run

```bash
uv run python -m unittest discover -s tests
uv run python align/asr_chunks.py T.json --out o.jsonl --library church --index church.sqlite --audio-dir AUDIO_DIR   # AUDIO_DIR/<sermon id>.<ext>
```

### Results

- **Tests:** 595 pass. That is 540 at 7b23af1, plus 25 new here (test_coverage 11 → 29 tests, test_cpu_guard 6, S5 1), plus 30 from #16.
- **Wesley byte-identical vs `origin/main` (9e5c054):** `git archive` extracted to `/tmp`, run with main's `src` forced first on the path.
  - ASR chunks: 143 transcripts, 8,265 chunks, sha256 `5f624dd5…aee720` in both trees.
  - API: 40 eval questions × bm25/dense/hybrid at k=10, plus `sermon()` for all 141 ids, `took_ms` removed: 261 responses, sha256 `38022171…50281d52` in both trees. The dense path was in use: no fallback, `dense_top` present.
- **`uv lock --check`:** passes (79 packages, unchanged).
- **Dependencies:** none added.
- **Head SHA:** given in the final message and on the PR (a report cannot contain its own commit's SHA).

### Risks

- The gate fails closed on music, applause or hymns with no words (by design). The reviewer clears them by re-importing with a window.
- The noise-floor guard uses the 5th-percentile frame level. A recording with no quiet frames at all (continuous music bed) raises the threshold, and quieter speech under the music is then not counted.
- I did not re-run #12's gate-leak benchmark. Serving still goes through the same `visible_sql`, with one more condition.

## Round-2 fix-up (CTO review of PR #20 at b9e3725)

This section supersedes the parts above that it contradicts: the AMX guard no longer keeps any operator value, `REL_DB` is 45, and the church path needs `meta.duration_s`.

Commits on `feat/w3-asr-coverage`: `7091123` (merge of `origin/main` 5358c6e, #22 and #24; no conflicts), `9cf4eec` (N1), `9446396` (N2), `566adb8` (S-a, S-b, S-c, S-f, docs), `553fdae` (S-d), `6db2d34` (S-e), `58b1a6a` (S-g and the coverage sweep script), `6d08e04` (N1 audit: visible-only BM25 and dense, and the gate leak sweep), plus the commit adding this section.

### Must-fixes

| Item | Change | Tests |
|---|---|---|
| N1 signals probe unpublished sermons | `abstain.compute_signals` runs BM25 and dense through the searcher's gate (`searcher._where()`, `Searcher._lexical`, `Searcher._semantic`). `bm25_hits`, `dense_top` and agreement now count only chunks a reader may see. The audit below found that filtering was not enough on its own and fixed that too. | `tests/test_gate_signals.py` (7): two church files that differ only by one unapproved sermon (coverage NULL) give identical `compute_signals`, identical `/api/search` for "righteousness", "grace" and a nonsense word in bm25/dense/hybrid (`took_ms` aside), the same `/healthz` chunk count, and no `/api/sermon` for the hidden id. Before the fix: `bm25_hits` 1 vs 0 for "righteousness", the hidden chunk's cosine 1.0 as `dense_top`, and the level moved between `weak` and `none`. |
| N2 AMX guard accepts unsafe values | On an AMX CPU, `cpu_guard.avoid_amx` keeps `MKL_ENABLE_INSTRUCTIONS` only if it is exactly one of `SAFE_VALUES` = AVX512, AVX512_E1, AVX512_E2, AVX512_E3, AVX2, AVX, SSE4_2 (case-sensitive). Any other non-empty value raises `AmxUnsafe`, naming the value and the allowed list, whether or not ctranslate2 is loaded. An empty value counts as unset and is set to AVX512. A CPU without AMX is not touched. | `tests/test_cpu_guard.py`: every safe value is kept; `AVX512_E4`, `AVX512_E5`, `avx512`, `AVX521`, `" AVX512"`, `"AVX512 "`, `AMX`, `avx2`, `SSE42` raise both before and after ctranslate2 loads, and the environment is left unchanged; empty → AVX512; a desktop CPU keeps `AVX512_E4`. |

### N1 audit: everything a response could take from hidden chunks

| Surface | Finding | Status |
|---|---|---|
| `confidence.signals` (`bm25_hits`, `dense_top`, `agreement`), `abstain`, `confidence.level` | Counted hidden chunks (the CTO's finding). | Fixed (`9cf4eec`). |
| BM25 `score` and **BM25 order** (bm25 mode, the BM25 half of hybrid, agreement) | FTS5 `bm25()` takes its term statistics (row count, document frequency per term, mean length) from every row in `chunks_fts`, hidden ones included. Filtering rows in the `WHERE` clause does not change those statistics. A hidden sermon that uses a word changes the raw score of every visible hit for that word and, for OR queries (5+ terms), the order of the visible hits. The first sweep run (after `9cf4eec` only) found 40+ eval questions whose bm25 and hybrid responses differed. | Fixed (`6d08e04`). A gated `Searcher` keeps an in-memory FTS5 copy of the visible rows only (same tokenizer, read from the file's schema), rebuilt when `PRAGMA data_version`, the gate SQL or the vectors change. Scores are then exactly those of a file that never held the hidden rows. The server's read-only connection is untouched (`query_only` stays on). `test_hidden_rows_do_not_move_the_bm25_order` checks that the raw index puts B first and the searcher puts A first in both files. `test_visible_index_follows_an_approval` checks that an approval written by another process is picked up on the next query. |
| Dense `score` | The cosines did not change, but BLAS rounding of `matrix @ vector` depends on the matrix shape: one score differed by 2e-7 with the hidden rows present. Dense also walked past hidden rows in batches, so its run time depended on how close hidden chunks were to the query. | Fixed (`6d08e04`). A gated file scores only a cached sub-matrix of the visible rows. |
| `took_ms` | With the fixes, a word found only in hidden sermons times the same as a nonsense word (bm25 median 80.5 vs 80.4 µs on the hidden file; 79.1 vs 77.9 µs on the clean file). The first query after a file change rebuilds the visible index: 5.7 ms for 363 rows, about 0.8 s at 50k rows by extrapolation. That shows a write happened, which `pending_review` already discloses. | Fixed, apart from the rebuild time. |
| `/healthz` `chunks` | Already counts visible chunks only (`visible_count`). | No change needed. |
| `/healthz` `pending_review` | A count of sermons awaiting approval, by design (never ids or titles). This is the one intended difference between the two files. | Kept, by design. S-e fixed its value when gate columns are missing. |
| `/api/sermon/<id>` | Gated in SQL and returns 404 for a hidden id. Timing: hidden id 55.0 µs vs absent id 50.4 µs median (2,000 calls each). The ~5 µs is the gate subquery running on the hidden sermon's rows. That is far below network jitter, and all it could show is that an id exists in the file. Ids are YouTube video ids, which are public. | Reported, not fixed. |
| `sermon_flagged`, `touches_flagged` | These read the flags of the hit's own sermon. A hit is only served if its sermon is approved, and the gate is per sermon, so these never consult a hidden sermon. | No change needed. |
| Errors | An FTS syntax error gives the same 500 whether or not hidden rows match. | No change needed. |
| `/api/side` church column | Still the empty side until #12 lands there (W3-SIDE); it reads nothing from the church file. | No change needed. |

**Gate leak sweep** (`scripts/gate_leak_sweep.py`; this re-runs the #12 check). I could not find #12's original sweep script or its results in the repo or `/cache`, so I wrote this one. It builds two church files through the real church path: `align/asr_chunks.py` with Granite ONNX on CPU, the built-in privacy rules, and `--ack-review`. The input is 12 public-domain Wesley transcripts relabelled as church sermons, with made-up sample names spoken twice in each. Coverage is stubbed to `[]`. The `hidden` file holds 6 approved sermons, 3 never approved, 2 approved with coverage NULL, and 1 approved with an open span. The `clean` file holds only the 6 approved sermons. Both files are queried with the 93 eval questions, 60 words that occur only in the hidden sermons, a nonsense word and the 4 sample names, each in bm25, dense and hybrid, plus `/api/sermon` for all 12 ids and `/healthz`.

```
hidden chunks 302, queries 158, responses compared 487
leaks 0   (no hidden chunk or id in any response; every response identical to the clean file
           apart from took_ms; pending_review 0 vs 6 is the intended count)
links served 2,846; 2,199 start after a flagged word of their sermon
link margin (seek minus nearest earlier flagged word end): min 11.45 s, p5 27.84 s, median 226.84 s
           (SEEK_SLACK_S 1.5; no link seeks within it)
```

### Should-fixes

| Item | Change | Tests |
|---|---|---|
| S-a stretched word hides ~5 s | New `coverage.stretched_spans`: a word longer than `LONG_WORD_S = 4.0` s whose middle (the part `WORD_MAX_COVER_S` leaves uncovered) holds at least `MIN_SOUND_S` of sound is a span covering the whole word. `clip_to_window` now keeps a span that lies wholly inside the window at any length; a span the window cuts still needs more than 5 s left. I could not test against c01.tiny.1t-b: that run is not in the repo or in `/cache`. The synthetic case is the same shape: a 7 s word over speech, invisible to both the gap rule and the density rule. | `test_stretched_word_over_speech_is_a_span`; `test_stretched_word_over_silence_or_under_the_limit_passes` (a 7 s word over room tone, or a 4.0 s word, passes); window case in `test_window_clips_and_drops_spans` |
| S-b same-timestamp words inflate density | `sparse_spans` counts distinct start times: one entry per start, ending where its longest word ends. | `test_words_sharing_a_timestamp_count_once` (three words on each stray timestamp used to pass; three distinct starts still pass) |
| S-c no test of the 2 s tolerance | | `test_audio_a_few_seconds_short_is_unchecked`: audio 3, 4 or 5 s shorter than `duration_s` or the last word → `Unchecked`; exactly 2 s short → runs |
| S-d church transcript without `meta.duration_s` passes | `sermon_gaps` stores NULL (unchecked; approval refuses) when `meta.duration_s` is missing, not a number, a bool, not finite, or ≤ 0. Documented in the `align/asr_chunks.py` docstring and `--audio-dir` help. Stubbed church tests get a duration from the last word (`tests/coverage_stub.py`). | `test_no_stated_duration_stores_null` (None, 0, −5, `"60"`, `true`, key absent → NULL, `ack` refuses; with a duration → `[]`) |
| S-e pending 0 without the coverage column | `pending_review_count` agrees with `visible_sql`: when any gate column is missing nothing is served, so every `status = 'ok'` import counts as pending (every row, if there is no `status` column). | `PendingCountTests` |
| S-f hum/music bed | Coverage docstring: speech within about `NOISE_MARGIN_DB` (6 dB) of a steady hum or a music bed cannot be told from it by level, so a hole there is not found and such a recording needs a human listen. | doc |
| S-g 45 dB | `REL_DB = 45.0`, after the Wesley re-run below. | `test_speech_43_db_down_is_sound` (fails at 40) |
| Docs: placeholder words | Coverage docstring, "Clearing a span": never add placeholder words (`...`, `[music]`, made-up text) to a transcript to clear a span. | doc |

The 0.5 words-per-second density floor is unchanged. The coverage gate still runs on every transcript, on every CPU.

### S-g: Wesley false-positive check at 40 and 45 dB

`uv run python scripts/coverage_sweep.py --rel-db 40 45` runs all 143 Wesley GPU transcripts against their mp3s with the round-2 rules. Frame levels are cached in `/cache/w3-asr/levels`.

| | 40 dB | 45 dB |
|---|---|---|
| files flagged | 94 | 94 |
| spans | 98 | 98 |
| spans that touch the searchable window | 85 | 85 |
| density of unflagged windows, p5 / min (words per s of sound) | 2.25 / 0.81 | 2.25 / 0.81 |

The two thresholds flag exactly the same spans because `REL_DB` never decides the threshold on Wesley: the −58 dBFS floor decides it on 135 files and the noise guard on 8. So Wesley stays clean at 45 dB, but it cannot show what 45 dB changes. The change only matters on recordings whose loud end is above about −13 dBFS, where 45 dB counts speech 40-45 dB down as sound. I made the change because the gate fails closed and a missed name costs more than a false flag. Expect somewhat more spans to clear on loud, noisy church audio.

Compared with round 1 (90 spans in 90 files), round 2 flags 8 new spans:

- 3 in LibriVox intros: `wesley-s1-00` 5.5-16.5 s, `wesley-s2-21` 3.7-9.4 and 17.2-23.7 s, where words like "Occasions," and "Several" are stretched 5-7 s over the disclaimer. These are the same class as round 1's disclaimer spans.
- 5 mid-sermon words of 4.1-4.9 s. Re-transcribing each with large-v3 (GPU, fp16, VAD off) shows real dropped speech under every one, so none is a false positive:

| Sermon | Stretched word | Re-run finds |
|---|---|---|
| s1-08 728.4-733.3 | "that" 4.86 s | Greek "hoti dikaio… nomos" |
| s1-10 439.6-443.6 | "hereby" 4.08 s | "first john four verse thirteen" |
| s1-27 62.3-66.4 | "has" 4.10 s | "Matthew 6, 16-18" |
| s2-17 1376.6-1380.9 | "Occasions," 4.32 s | a Latin line |
| s2-26 859.9-864.2 | "attempted" 4.24 s | a Latin line |

The density rule's lowest unflagged window is now 0.81 words per second of sound (round 1: 0.52). Counting distinct start times did not push any clean window toward the 0.5 floor.

### How to run

```bash
uv run python -m unittest discover -s tests
uv run python scripts/coverage_sweep.py --rel-db 40 45 --json /cache/w3-asr/sweep-round2.json   # ~2 min first run, cached after
uv run python scripts/gate_leak_sweep.py --work /cache/w3-asr/gate-sweep                         # ~6.5 min, exits 1 on any leak
uv lock --check
```

### Results

- **Tests:** 619 pass. 601 after merging main (595 at round 1, plus #22/#24's tests), plus 18 new: `test_gate_signals` 7, `test_cpu_guard` 4, `test_coverage` 7.
- **Wesley byte-identical vs `origin/main` (5358c6e):** `git archive` extracted to `/tmp`, each tree run with its own `src` first on the path (checked).
  - ASR chunks: 143 transcripts, 8,265 chunks, sha256 `5f624dd5fd082eaa8a5fcb095f6fe991e5f8555d99ab1aa06aab8e2cc8aee720` in both trees (the same as round 1).
  - API on `/cache/index/wesley.sqlite` with Granite: 93 eval questions × bm25/dense/hybrid at k=10, `/api/sermon` for all 141 ids, and `/healthz`, with `took_ms` removed: 421 responses, sha256 `5bfc028c2d17c20ae00be96d9f4c0fd2bcaedf0896f9badd58a80e124d337fea` in both trees. Dense was in use: all 186 dense and hybrid responses carry `dense_top`. Wesley is not gated, so it never uses the new visible-only index.
- **Gate leak sweep (#12 re-run):** 0 leaks in 487 compared responses; minimum link margin 11.45 s against `SEEK_SLACK_S` 1.5 s (details above).
- **`uv lock --check`:** passes (79 packages, unchanged).
- **Dependencies:** none added.
- **Head SHA:** given in the final message and on the PR (a report cannot contain its own commit's SHA).

### Open issues and risks

- **YouTube path without a duration:** `pipeline` passes `video.duration_s`, which can be None if yt-dlp metadata lacks it. A download cut short after the last word would then pass, the same hole S-d closed on the church path. Not changed here because S-d named only the church path. Recommended follow-up: treat a missing YouTube duration as `Unchecked` too.
- **c01.tiny.1t-b** is not available here. S-a is tested on a synthetic stretched word and on Wesley; please confirm on that run.
- **AMX:** this box has no AMX, so N2 is tested with a fake `/proc/cpuinfo` only. The value list is the CTO's, from MKL verbose output on the AMX box.
- **Visible-index memory:** a gated `Searcher` holds an in-memory FTS5 copy of the visible text plus a copy of the visible vectors. For a church library of a few hundred sermons that is tens of MB.
- **`/api/sermon` timing** (~5 µs for a hidden id versus an absent one): reported above, not fixed.
