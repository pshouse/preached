# W2-A: search API, mobile page, and player

## What was done

A read-only web app on top of the W1-B index. The embedder is still `ibm-granite/granite-embedding-english-r2`. Hybrid search is reciprocal rank fusion with k=60 over the top 100 of BM25 and dense, the same call `search/query.py` makes. No new model, no vector database, no generated text.

`app/server.py` is `ThreadingHTTPServer` from the standard library. It binds `127.0.0.1:8000` unless `--host` or `--port` is set. The model loads once, on CPU (`CUDA_VISIBLE_DEVICES` is cleared first so this process does not take the GPU from Whisper). If the model or the Granite vectors fail to load, search continues on BM25 and every search response sets `note` to "Embedding model failed to load; results are BM25 only." `--bm25-only` skips the load on purpose. Asking for hybrid or dense in that mode still returns BM25 and says embeddings are not loaded.

The index is opened `mode=ro` with `PRAGMA query_only`. There are no write routes. `POST`, `PUT`, `PATCH`, and `DELETE` return 405.

`GET /api/search?q=&k=10&mode=hybrid|bm25|dense&library=wesley` returns `{query, mode, took_ms, results, note}`. Each result is `{chunk_id, sermon_id, sermon_number, sermon_title, scripture, text, start_s, end_s, audio_url, reader, text_source, source_url, score}`. `q` is 1–300 characters, `k` is 1–25, `mode` and `library` are allowlists. Bad input is 400 with a fixed JSON error. `start_s`, `end_s`, `audio_url`, `reader`, and `text_source` are optional: a missing column and NULL both become JSON null. The current Wesley index has null timestamps and no audio columns. A later alignment can add them without a server change.

`GET /api/sermon/<sermon_id>` returns title, number, scripture, source URL, and the audio URL and reader when any chunk of that sermon has them. `GET /healthz` reports chunk count, whether dense search is available, and whether the model failed. `GET /` is the page. `GET /static/<name>` serves only `app.js`, `app.css`, and `favicon.svg`.

### Overlap rule

Chunks overlap their neighbors by about 25% (`corpus/chunk_config.json`). The API asks the ranker for up to 100 hits, then keeps `k` of them with `dedupe_adjacent` in `src/preached/search.py`. Higher score wins. A tie keeps the earlier hit. A hit is dropped only when it repeats a hit already kept from the same sermon:

1. A different sermon is never dropped.
2. The same `chunk_id` is dropped.
3. When both chunks have `word_start` and `word_end`, they drop if those ranges overlap. The chunker only overlaps adjacent windows, so this is the 25% neighbor. Ranges that merely touch (`end == next start`) both stay, and a later non-overlapping passage from the same sermon stays.
4. When word offsets are missing and both chunks have timestamps, they drop if the times overlap by at least 0.4 seconds.
5. When those spans are missing too, they drop if the texts are identical or share a boundary run of at least 8 words (a suffix of one is a prefix of the other). A sentence repeated in the middle of another chunk is not a boundary, so it stays.

The excerpt is the winning chunk unchanged. Neighbors are not stitched into a new paragraph.

### Page

Plain HTML, CSS, and JS. No framework, no build, no CDN, no external font. The layout is a single column that fits a 360px-wide screen. System UI for the chrome, Georgia or Palatino for the quotation. The search box has a visible label. A mode select offers words-and-meaning (hybrid), exact words (BM25), or closest in meaning (dense). Four example questions fill the box. Results are an ordered list of cards: sermon number, title, scripture, the excerpt in a `blockquote`, and either a timestamp as `h:mm:ss` plus Play, or the sentence "Audio timing coming soon" and a link to the CCEL `source_url`. Play uses one shared `<audio>` element, sets the URL with a `#t=` media fragment, and sets `currentTime` after metadata. The file is loaded from `audio_url` in the browser. The server does not proxy it. `preload` is `none`. When `start_s` is null there is no play button. A reader on archive.org is labeled "Read by <reader> (LibriVox volunteer)". An archive.org file with no reader name says "Read by a LibriVox volunteer". Any other host is "Read by <reader>" with no LibriVox claim. An ASR chunk says "Wording follows the recording." Zero hits show "Nothing strong found". Result strings are inserted with `textContent`. The footer is: "Results are Wesley's own published words; audio is read by LibriVox volunteers. Preached finds passages; it never writes or paraphrases."

### Security

Every response, including errors, sends `Content-Security-Policy` (`default-src 'self'`, `script-src 'self'`, `style-src 'self'`, `frame-ancestors 'none'`, no `unsafe-inline`, no `unsafe-eval`; `media-src` adds `https://archive.org` and `https://*.archive.org` so the player can stream), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `X-Frame-Options: DENY`. The `Server` header is `Preached`. The Host header must be `127.0.0.1` or `localhost` unless `--hosts` adds more. The request target is limited to 2048 bytes, the body to 4096 bytes, and the socket times out at 15 seconds. Paths outside the static allowlist, including `..` and percent-encoding, are 404. A handler exception returns `{"error":"internal error"}` and the traceback stays on stderr.

## How to run

From `/work/preached/.worktrees/feat/w2-web`:

```bash
uv run app/server.py
```

Open http://127.0.0.1:8000. The index is `/cache/index/wesley.sqlite`. Weights use `HF_HOME=/cache/huggingface`.

```bash
uv run python -m unittest discover -s tests
uv run python scripts/smoke_server.py
uv run python scripts/bench_api.py
```

`smoke_server.py` binds port 0, searches "Christian perfection" with BM25, and prints the first sermon. `--embed` loads Granite. `bench_api.py` loads Granite, warms one eval query, then times all 40.

Checked by hand:

```bash
curl -sS 'http://127.0.0.1:8000/api/search?q=What%20did%20Wesley%20say%20about%20money%3F&k=3&mode=bm25&library=wesley'
```

That returns Wesley's words. The first hit on this index is sermon 50, "The Use of Money", `start_s` null, source `https://ccel.org/ccel/wesley/sermons/sermons.v.l.html`. A headless Chromium pass at 360px wide searched "Christian perfection", showed the excerpt and "Audio timing coming soon", showed "Nothing strong found" for a query with no keyword hit, and on a fixture index played a timed chunk from `0:01:35` through the one audio element without downloading a recording.

## Results

36 tests, `unittest`, all passing. The previous 14 (corpus, FTS, fusion, metrics, the Nomic mask shim) still pass. The new tests cover validation, the result schema, null timestamps, a missing audio column, the overlap rule, static traversal, security headers, a hidden 500, and the BM25 fallback. Tests build a small SQLite file. They do not fetch audio and they do not load Granite.

End-to-end `GET /api/search` on CPU, hybrid, k=10, the 40 eval queries, one warmup excluded, model already loaded:

| | |
| --- | --- |
| p50 | 114 ms |
| p95 | 126 ms |
| min | 101 ms |
| max | 540 ms |
| RSS after model load | 1,580,302,336 bytes (1,507 MiB) |
| RSS after the 40 queries | 1,664,008,192 bytes (1,587 MiB) |
| chunks | 8,383 |
| model | granite-english-r2 |

W1-B measured the same hybrid path at about 115 ms p50 and 135 ms p95 before HTTP. The page adds almost nothing. One query reached 540 ms. The p95 stays at 126 ms, so that spike is a single sample.

BM25 against the same index, no model, was about 58 MiB RSS and a 1 ms `took_ms` for "What did Wesley say about money?". The word "worry" is not in the corpus, so that example is empty in keyword mode. Hybrid is what the page uses by default.

The Granite snapshot on disk is `model.safetensors` at 298,041,696 bytes (284 MiB), plus tokenizer and pooling config. There is no `.onnx` file in that snapshot.

## Open issues

- Text chunks still have null `start_s` and `end_s`, and the index has no `audio_url`, `reader`, or `text_source` columns. The page says timing is coming and links to CCEL. W1-C can fill the columns. The server already reads them.
- The locked torch is `2.15.0+cu132`. The torch package in this venv is 1.08 GiB and the NVIDIA CUDA libraries beside it are 2.96 GiB. A Sprite image that installs this lockfile has to hold that download even though search never uses the GPU. Process RSS after load is 1.5 GiB, not the full wheel size. A CPU-only torch wheel would be the smaller install. This branch does not change the lockfile, because `search/bench.py` still measures the other models on GPU.
- Pillow, torchvision, and einops are still dependencies from W1-B. Granite does not import them. They stay so EmbeddingGemma and Nomic can still load for the benchmark. A Granite-only image can drop those three.
- ONNX is the way off torch. This snapshot does not ship an ONNX file, so it would be an export, then `onnxruntime` on CPU. That runtime wheel is tens of megabytes. It is not added here. The 284 MiB safetensors file is the weight that export would start from. fp32 in memory is larger than that file because the checkpoint is not fp32.
- Neighbors are dropped, not merged. A listener hears the higher-scoring window, not the union of the two overlapping windows.
- Default bind is loopback. `--host 0.0.0.0` plus a Host header of `localhost` would still answer. Keep the bind on `127.0.0.1` until there is a real proxy in front.
- The socket timeout drops a slow client. It does not kill an in-flight torch call. Queries are serialized on one lock because the SQLite connection and the model are not safe to share across threads without it.

## Dependencies added

None. HTTP, JSON, tests, and the smoke and bench scripts are the standard library. The existing lockfile is unchanged: numpy, sentence-transformers, torch, torchvision, pillow, einops. Why those are there is in `reports/W1-B.md`.

## YouTube channel import (not built)

Gaston Community Church's channel is not downloaded, stored, or linked. The pastor's permission is still pending, and this note is not an implementation.

When that permission is confirmed, the records this API already returns are enough:

1. A person submits a channel URL or a list of video ids they have approved. No import by archive.org tag, and no comments, chat, or member names.
2. The video stays on YouTube. `audio_url` is the watch URL. `start_s` and `end_s` come from the sermon-shorts Whisper JSON, which this repo calls and does not copy. `reader` is the pastor's public name. `text_source` is `asr` until a person corrects it. The page already says "Wording follows the recording" for ASR, and it adds "(LibriVox volunteer)" only when the audio host is archive.org.
3. `library` is an allowlist that today accepts only `wesley`. A church library should be a separate SQLite file, or a column filtered in the query, so those sermons are not mixed into an unlabeled Wesley list. Side by side is a later week.
4. Congregant names in stories are stripped before indexing. Until permission, any trial data is sample data.
5. The player seeks. It does not cut, download, or export a clip.
6. The content security policy allows archive.org as media and allows no third-party script. A YouTube iframe would need `frame-src https://www.youtube-nocookie.com`. The IFrame API also wants a script from YouTube, which this policy will not load. The choice, when permission exists, is a link out to the timestamp or an iframe with that frame allowlist and no extra script. Do not open `script-src` to a CDN to get there.
