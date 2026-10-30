# W1-CLI: timestamped index + question → exact moment from the command line

Branch `feat/w1-cli`, stacked on `feat/w1-align` (PR #6) at `cb57410`. No W1-C
fix-ups had landed on `origin/feat/w1-align` when I finished, so no merge was
needed. Written 2026-10-30. The model is the recommended **granite-english-r2**
(IBM, `ibm-granite/granite-embedding-english-r2@47ea694b25`); no PRC-developed model is used.

## 1. What was done

1. **Applied `align/index_consumption.patch` as a real commit** (`857e70d`) and
   deleted the patch file. `CHUNKS_JSONL` is still the file `corpus/chunk_sermons.py`
   writes; the index reads `INDEX_CHUNKS_JSONL` (`$PREACHED_CHUNKS`, else
   `chunks_aligned.jsonl`, else `chunks.jsonl`).
2. **Rebuilt the index and re-embedded** (`/cache/index/wesley.sqlite`):
   - 8,383 rows. 0 NULL `start_s`, 0 NULL `audio_url`, 0 NULL `reader`; every row `text_source = canonical`.
   - 8,383 granite-english-r2 vectors, dim 768, fingerprint `13e0ed78bb32d86b` (stored in `meta` under `embeddings:granite-english-r2`).
   - Re-embed took 63.9 s on the RTX 3060 (131 chunks/s, 2.5 GB VRAM peak).
   - Bench of that run: `eval/results/2026-10-30-2.{json,md}` (hybrid RRF recall@5 0.629, MRR@10 0.506, nDCG@10 0.558, sermon@5 0.971). Same text, so the same scores as W1-B's run.
3. **`search/query.py` output** now prints, per hit: sermon title, chunk id and score,
   `h:mm:ss` (and raw `start_s`), the reader, a playable URL, the CCEL page, and the
   canonical quote. The URL is `audio_url#t=<seconds>`, built the way the page does it.
   `app/static/app.js` `mediaUrlAt()` sets `url.hash = "t=" + start_s` on the archive.org MP3,
   and `formatTime()` is floor-to-whole-seconds `h:mm:ss`; `query.py` copies both.
   Example (`uv run search/query.py "Romans 8:16" -k 1`):
   ```
   [1] The Witness of the Spirit, Discourse II  (score 0.0307, wesley-011-c0000)
       at 0:00:32 (start_s=32.81)  read by Tim Cote
       play: https://archive.org/download/sermonsfirstseries_1307_librivox/sermonsfirstseries_11_wesley_64kb.mp3#t=32.81
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

How a hit is judged: the gold span is the first-to-last word time of the eval quote, found in the
canonical word stream and read from W1-C's per-word times (`/cache/aligned/wesley/*.json`).
Every occurrence of the quote counts, in any sermon, matching the text metric, because a sermon
often repeats its text verse. Grade-2 passages only; grade 1 adds nothing (same numbers).

| Criterion | hit@1 | hit@5 |
|---|---|---|
| **Overlap**: hit's `[start_s, end_s]` intersects the gold span, in the same audio file | **14/35 = 0.40** | **23/35 = 0.66** |
| Text metric (`contains_quote`), for comparison | 14/35 | 23/35 |
| Strict: `start_s` falls inside the gold span | 5/35 = 0.14 | 7/35 = 0.20 |

- **Timestamp hits equal text hits exactly**, question by question (after counting every
  occurrence of the quote). So alignment lost nothing: whenever the right passage is retrieved, the
  play position is on it.
- Strict is low by design, not an error: a chunk is ~45 s (median) and the gold quote is a sentence
  or two inside it, so `start_s` is the chunk's start, a little before the quote. Among the 14
  top-1 overlap hits, the quote starts 0 s after `start_s` in 5, ≤ 2 s in 8, and at most 31.7 s
  (sorted: 0, 0, 0, 0, 0, 0.3, 0.6, 2.0, 6.6, 6.6, 14.1, 16.6, 24.2, 31.7). Playing from `start_s`
  reaches the quote in under half a minute every time.
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

- `uv run python -m unittest discover -s tests`: **76 tests, OK** (includes `test_server`, `test_app_js`,
  `test_api_path`, `test_align`; W1-C reported 46 before its patch + 12 align tests; that count was not re-derived).
- `uv run app/server.py` on 127.0.0.1:8000, `GET /api/search?q=what did Wesley say about worry and tomorrow`
  returned real values, e.g. "The Danger of Riches" `start_s` 2211.21, `end_s` 2264.84, reader Larry Wilson,
  `audio_url` the archive.org MP3; "Wandering Thoughts" 197.36–242.17; "Of Former Times" 667.5–712.33.
  The server was then stopped (no process left).

## 4. Open issues and risks

- The test count of 76 is what ran; I did not compare with a pre-patch baseline.
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
