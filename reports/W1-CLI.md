# W1-CLI: timestamped index + question → exact moment from the command line

Branch `feat/w1-cli` (PR #7). Started on `feat/w1-align` (PR #6) at `cb57410`; after #5 and #6
merged, `origin/main` (`b57a623`) was merged in (no rebase) and the PR retargeted to `main`.
Written 2026-10-30; §6 lists the PR #6 review should-fixes applied afterwards. The model is the recommended **granite-english-r2**
(IBM, `ibm-granite/granite-embedding-english-r2@47ea694b25`); no PRC-developed model is used.

## 1. What was done

1. **Applied `align/index_consumption.patch` as a real commit** (`857e70d`) and
   deleted the patch file. `CHUNKS_JSONL` is still the file `corpus/chunk_sermons.py`
   writes; the index reads `paths.index_chunks_jsonl()` (`$PREACHED_CHUNKS`, else
   `chunks_aligned.jsonl` if it still matches `chunks.jsonl`, else `chunks.jsonl`; see §6).
2. **Rebuilt the index and re-embedded** (`/cache/index/wesley.sqlite`):
   - 8,383 rows. 0 NULL `start_s`, 0 NULL `audio_url`, 0 NULL `reader`; every row `text_source = canonical`.
   - 8,383 granite-english-r2 vectors, dim 768, fingerprint `13e0ed78bb32d86b` (stored in `meta` under `embeddings:granite-english-r2`).
   - Re-embed took 63.9 s on the RTX 3060 (131 chunks/s, 2.5 GB VRAM peak).
   - Bench of that run: `eval/results/2026-10-30-2.{json,md}` (hybrid RRF recall@5 0.629, MRR@10 0.506, nDCG@10 0.558, sermon@5 0.971). Same text, so the same scores as W1-B's run.
3. **`search/query.py` output** now prints, per hit: sermon title, chunk id and score,
   `h:mm:ss` (and raw `start_s`), the reader, a playable URL, the CCEL page, and the
   canonical quote. The URL is `audio_url#t=<seek>` with `seek = max(0, start_s − 0.75)`, built
   the way the page does it: `app/static/app.js` `playStart()` applies the same 0.75 s pre-roll and
   `mediaUrlAt()` sets `url.hash = "t=" + seek`; `formatTime()` is floor-to-whole-seconds `h:mm:ss`
   of the exact `start_s`. `query.py` copies all three (`preached.search.PREROLL_S`/`play_start`).
   Example (`uv run search/query.py "Romans 8:16" -k 1`):
   ```
   [1] The Witness of the Spirit, Discourse II  (score 0.0307, wesley-011-c0000)
       at 0:00:32 (start_s=32.81)  read by Tim Cote
       play: https://archive.org/download/sermonsfirstseries_1307_librivox/sermonsfirstseries_11_wesley_64kb.mp3#t=32.06  (0.75 s pre-roll)
       text: https://ccel.org/ccel/wesley/sermons/sermons.v.xi.html
       "The Spirit itself beareth witness with our spirit, ..."
   ```
4. **Timestamp eval** `eval/timestamps.py` (new): runs the 40 questions through the same hybrid
   call as `query.py` (top 5), and judges each hit's `[start_s, end_s]` against the gold quote's
   aligned time span.
5. **Tests and server**: see §3.

## 2. How to run

```bash
cd /work/preached/.worktrees/feat/w1-cli
uv run search/build_index.py                         # loads chunks_aligned.jsonl, prints 8383
uv run search/bench.py --models granite-english-r2   # re-embed (~64 s GPU)
uv run search/query.py "what did Wesley say about worry and tomorrow" -k 3
uv run eval/timestamps.py                            # writes reports/W1-CLI-timestamps.json
uv run python -m unittest discover -s tests
uv run app/server.py                                 # http://127.0.0.1:8000/api/search?q=...
```

## 3. Results

### Timestamps, 35 answerable questions (5 unanswerable are excluded)

> **How to read this table (W1-HARDEN relabel).** These hit@k numbers are *derived from the
> alignment*: the gold span and each chunk's `start_s`/`end_s` both come from the same W1-C per-word
> alignment, so a chunk that contains the quote text overlaps the quote's span by construction.
> They are therefore **equal to the text metric by construction (14/23 vs 14/23) and are not an
> independent audio-accuracy result.** They show that timings and text agree, not that the timings
> match the audio. The audio-accuracy evidence is the **W1-C spot-check**: `start_s` against the
> audio, |delta| median 0.42 s, max 0.76 s, covered by the 0.75 s pre-roll. Do not present the
> timestamp hit@k to judges as a separate result.

How a hit is judged: the gold span is the first-to-last word time of the eval quote, found in the
canonical word stream and read from W1-C's per-word times (`/cache/aligned/wesley/*.json`).
Every occurrence of the quote counts, in any sermon, matching the text metric, because a sermon
often repeats its text verse. Grade-2 passages only; grade 1 adds nothing (same numbers).

| Criterion | hit@1 | hit@5 |
|---|---|---|
| **Overlap** (derived from the alignment, not an audio measurement): hit's `[start_s, end_s]` intersects the gold span, in the same audio file | **14/35 = 0.40** | **23/35 = 0.66** |
| Text metric (`contains_quote`); the overlap row equals it by construction | 14/35 | 23/35 |
| Strict: `start_s` falls inside the gold span | 5/35 = 0.14 | 7/35 = 0.20 |

- **Timestamp hits equal text hits exactly** (by construction, see the note above), question by question (after counting every
  occurrence of the quote). So alignment lost nothing: whenever the right passage is retrieved, the
  play position is on it.
- Strict is low by design, not an error: a chunk is ~45 s (median) and the gold quote is a sentence
  or two inside it, so `start_s` is the chunk's start, a little before the quote. Among the 14
  top-1 overlap hits, the quote starts 0 s after `start_s` in 5, ≤ 2 s in 8, and at most 31.7 s
  (sorted: 0, 0, 0, 0, 0, 0.3, 0.6, 2.0, 6.6, 6.6, 14.1, 16.6, 24.2, 31.7). Playing from `start_s`
  reaches the quote in under half a minute every time.
- **Pre-roll.** These numbers judge the stored `[start_s, end_s]`, which stay the exact first-word
  onset (data unchanged by §6). The player and the CLI link now seek 0.75 s earlier, so in playback
  each lead above is 0.75 s longer and no top-1 hit starts after its first word (W1-C's worst
  measured late start is 0.76 s). Re-run after §6: `eval/timestamps.py` gives identical results,
  question by question (hit@1 14, hit@5 23, strict 5/7).
- Retrieval itself is the limit (hit@5 0.66 is W1-B's recall@5 0.629 counted per question, with
  unanswerable excluded). Misses are retrieval misses (the wrong sermon or passage), not timing.
- Per-question detail: `reports/W1-CLI-timestamps.json` (`g2_overlap_first_rank`, `g2_inside_first_rank`, `top1_lead_s`).

### Spot check: 5 random top-1 hits vs the W1-A Whisper words (seed 20261030)

Chunk text normalized with `align/textnorm`, compared as a bag of words with the Whisper words in
`[start_s − 0.3, end_s + 0.3]` of that chunk's audio file.

| question | chunk | start–end s | chunk words in Whisper window | Whisper words in chunk |
|---|---|---|---|---|
| k-luke-22-19 | wesley-101-c0000 | 27.91–68.06 | 99.1% | 99.1% |
| q-justification | wesley-011-c0028 | 882.22–928.40 | 98.3% | 98.3% |
| q-self-denial | wesley-048-c0028 | 816.18–860.84 | 99.2% | 100% |
| k-christian-perfection | wesley-040-c0023 | 788.44–849.72 | 93.9% | 100% |
| q-money | wesley-028-c0076 | 2309.57–2352.50 | 98.5% | 97.8% |

Mean 97.8% / 99.0%. The window's first words match the chunk's first words in all five
(e.g. "Do this in remembrance of me. Luke 22, 19."). The 93.9% case is the Christian Perfection file,
whose unread bracketed Scripture references W1-C already flags (§4 of W1-C). I could not listen to
audio, so this is text against ASR words, not an ear check.

### Tests and server

- `uv run python -m unittest discover -s tests`: **120 tests, OK** after merging `main` and §6
  (`main` alone: 101; 76 before the merge). Deno is on the sandbox PATH, so the `app.js` tests ran.
- `uv run app/server.py` on 127.0.0.1:8000, `GET /api/search?q=what did Wesley say about worry and tomorrow`
  returned real values, e.g. "The Danger of Riches" `start_s` 2211.21, `end_s` 2264.84, reader Larry Wilson,
  `audio_url` the archive.org MP3; "Wandering Thoughts" 197.36–242.17; "Of Former Times" 667.5–712.33.
  The server was then stopped (no process left).

## 4. Open issues and risks

- Strict `start_s`-inside-span is 5/35. If the product wants the play button to land closer to the
  quote, the options are a sentence-level `start_s` for the best sentence in the chunk, or a small
  lead-in. I did not change it: the card shows the chunk's range, and the text it plays is the chunk.
- The CLI example "what did Wesley say about worry and tomorrow" is not an eval question. The
  eval's own worry question (`q-worry`) is a miss in the top 5: the right passage is not retrieved,
  so there is no timing to judge. That is the ranking, not alignment.
- The labels in `eval/questions.jsonl` are LLM-made and still pending Patrick's review (see `eval/README.md`); these timestamp numbers inherit that.
- Text and times come from the alignment; the reader's voice is a LibriVox volunteer, not Wesley's.
  The page already labels this.

## 5. Dependencies added

None. `eval/timestamps.py` uses the repo's own modules and the stdlib.

## 6. PR #6 review should-fixes (applied on this branch)

1. **Timing-only change keeps vectors** (`store.sync_chunks`). When the hash changes but the chunk ids
   and the embedding inputs (`EMBED_KEY_COLUMNS` = chunk_id, sermon_title, scripture, text) match row
   for row in order, only the other columns (start_s, end_s, audio_url, reader, spans, ...) are
   `UPDATE`d in place; rowids, vectors and `embeddings:*` fingerprints stay. Anything else still
   rebuilds and drops vectors. The same rule covers a legacy hashless index, so timing still lands
   there (PR #2's fix) and now without a re-embed. On a scratch copy of the real index, a
   timing-only resync of 8,383 chunks took 0.6 s and kept all granite vectors and their meta.
   Tests: `InPlaceMetadataTests` (in place, text change, title/scripture change, reorder,
   duplicate ids) and the updated legacy test in `tests/test_store.py`.
2. **Stale aligned file is refused** (`paths.index_chunks_jsonl()`, resolved at call time, replacing
   the import-time `INDEX_CHUNKS_JSONL`). `align/wesley.py chunks` now writes
   `chunks_aligned.source.json` with the sha256 of `chunks.jsonl` and `chunk_config.json`. Before
   using `chunks_aligned.jsonl`, the hashes are checked; if they differ or there is no record, the
   canonical chunk ids and text are compared with `chunks.jsonl` in order; a mismatch raises
   `StaleChunks` and `build_index.py`, `query.py`, `bench.py` exit with a re-run hint.
   `$PREACHED_CHUNKS` still overrides. The current `/cache` file passed the content check and its
   record was written (`hash` path from now on). Tests: `tests/test_preroll_paths.py`.
3. **ASR chunk ids are namespaced** (`align/asr_chunks.py`): `asr:{sermon_id}-cNNNN`. Canonical ids
   never contain a colon. `sync_chunks` also refuses duplicate chunk ids up front
   (`DuplicateChunkId`) before writing anything. Tests in `tests/test_align.py` (a church sermon
   reusing `wesley-001` indexes alongside the CCEL chunks) and `tests/test_store.py`.
4. **Player pre-roll** in the player, not the data: `app.js` `playStart()` and
   `preached.search.play_start()` both give `max(0, start_s − 0.75)` (2 decimals); `query.py`'s play
   link uses it; labels and `start_s` stay exact. Tests: Deno checks in `tests/test_app_js.py`,
   a Python/JS parity check, and `query.play_url` tests.
5. **Manifest default** (`align/wesley.py`): `--source-manifest` defaults to
   `ingest/manifest/wesley.jsonl` in this tree (#5 is merged). Test in `tests/test_align.py`.

Nothing in §6 changes `chunks_aligned.jsonl`, the index rows or the vectors, so the W1-CLI eval
numbers stand; the re-run above confirms it.
