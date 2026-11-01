# Preached

Search a sermon archive and return the preacher's own words. This repo builds the Wesley text corpus, the eval set, and the retrieval benchmark.

You need uv (the build pin is `uv_build>=0.13.6,<0.14`), Python `>=3.12,<3.14`, a network connection, and disk for the corpus, the index, and the model weights. Importing audio also needs `ffmpeg`.

`PREACHED_CACHE` (default `/cache`) is the one cache knob. The corpus, the SQLite index, the Hugging Face files, and the ONNX graph all live under it. Create that directory before the first command and make sure it is writable. If you cannot write `/cache`, point `PREACHED_CACHE` at a directory you can.

The steps below are text-only. `corpus/chunk_sermons.py` leaves `start_s` empty, so every passage says that audio timing is still coming, links to the CCEL text, and has play `n/a`. Playback is a later step. It is written after the corpus commands, and it needs transcripts this quickstart does not build.

```bash
uv run corpus/fetch_wesley.py
uv run corpus/chunk_sermons.py
uv run python eval/validate.py
uv run --group bench search/bench.py --models granite-english-r2
```

`eval/validate.py` checks every graded quote against every chunk. It prints nothing for about two minutes, then one JSON line. `corpus/fetch_wesley.py` rewrites `corpus/catalog.json` in the clone. If the CCEL text no longer matches that catalog, the fetch stops until you run it again with `--accept-new-text`, after you have re-checked the eval quotes. The bench writes a dated `.json` and `.md` under `eval/results/` in the clone. The catalog and those result files are local outputs. Do not commit them.

The bench line embeds IBM Granite English R2 only. It needs network and disk for the weights. A GPU is recommended. On a GPU it takes a few minutes. A CPU-only bench takes about 9 minutes (541.9 s measured on 8 cores), and a cold weight download is slower still. The same command without `--models` downloads the three enabled models; a GPU is recommended for that run too. `search/bench.py` exits 1 if any selected model fails to load or score (offline, gated, missing weights), after writing the report with that model marked `error` (or `skipped_gated` for a gated repo, which still fails; under `--abstain` gated is recorded as plain `error`). `--allow-bm25-only` accepts the run with a warning on stderr and exits 0. How Granite was chosen is in `reports/W1-B.md`. Labeling notes are in `eval/README.md`.

Hybrid search does not download an ONNX graph. Build it with the bench group. The export then checks the file against the pin `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` in `src/preached/artifacts.py`:

```bash
uv sync --group bench
uv run --group bench python scripts/export_onnx.py
```

Call `scripts/export_onnx.py` as it is. The script forces `ATEN_CPU_CAPABILITY=avx2` before it imports torch and re-executes itself under `PYTHONHASHSEED=1`. An x86-64 host with AVX2 is required. Any other host exits non-zero and says so. The ONNX graph is written under the same `PREACHED_CACHE` knob, at `$PREACHED_CACHE/models/granite-english-r2-onnx/<revision>/`. Before writing, the export deletes that revision directory and rewrites it. When the graph matches the pin, it prints `fp32 sha256 matches the pin` and that digest, then writes `manifest.json`. When it does not match, the export exits non-zero and writes no manifest.

```bash
uv run search/query.py "how should a Christian use money" --mode hybrid -k 5
```

If the graph was never built, that query exits 1 and prints `error: missing ONNX manifest at <path>; build it with: uv run --group bench python scripts/export_onnx.py`. That sentence is what the loader prints. The server still starts and prints `PREACHED_LISTENING http://127.0.0.1:8000`. Its log, in order, is `ERROR embedding model unavailable; serving BM25 only`, then `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only.` and the same missing-manifest sentence, then `WARNING The search model has not been built; results are BM25 only.` `GET /healthz` then has `"fallback": true`, `"dense": false`, `"search_mode": "bm25"`, and `"search_mode_reason": "onnx_graph_not_built"`. A graph that is present but is not the pin is a different refusal: `error: ONNX sha256 for model.fp32.onnx is not the pinned digest`.

The page is a stdlib server. From the clone:

```bash
uv sync
uv run app/server.py
```

`uv sync` installs the runtime only (numpy, onnxruntime, tokenizers) and drops the bench group, including torch. Torch is not in that set. The query embedder defaults to ONNX fp32 with one intra-op thread (`PREACHED_ORT_INTRA_OP_THREADS`, `--ort-threads`). Export and the benchmark need `uv sync --group bench`. Commands and the measured sizes are in `reports/W3-CPU.md`. That file's test count and worktree path are stale. Use this, and do not quote a pass count from it:

```bash
uv run python -m unittest discover -s tests
```

How many tests run or skip depends on the machine (deno, the cache, the ONNX graph). This README states no count.

Then open http://127.0.0.1:8000. Search returns Wesley's published words. Hybrid mode is reciprocal rank fusion with k=60. Adjacent chunks overlap by about 25%, and the API keeps the higher-scoring one so the same words are not listed twice. So `/api/search` does not return the raw top k that `search/query.py` prints: it takes the ranker's top 100 and de-dups down to k (`api_search` in `src/preached/search.py`). `search/bench.py --dedupe` scores that path. In a pre-registered evaluation (58 questions; relevance labels drafted with AI help, a subset confirmed blind by a human), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086). That is the only retrieval figure in this README (`reports/W3-CONFIRMATORY.md`). Excerpts on the page hide CCEL paragraph numbers. The indexed text is unchanged. After the text-only steps above, every passage has no `start_s`: the page says audio timing is still coming and links to the CCEL text. A recording needs the alignment, which reads transcripts at `$PREACHED_CACHE/transcripts/wesley/` (the audio ingest in `reports/W1-C.md`; the commands above do not create them). After `corpus/fetch_wesley.py`:

```bash
uv run align/wesley.py align
uv run align/wesley.py chunks
```

`align` stops if a transcript file is missing. `chunks` writes `$PREACHED_CACHE/corpus/wesley/chunks_aligned.jsonl`, or stops with `not aligned yet` until `align` has finished. Do that before expecting playback. Details are in `reports/W2-A.md`. The timestamp hit@k in `reports/W1-CLI.md` is derived from the alignment: equal to the text metric by construction, not an independent audio-accuracy result. No audio-accuracy measurement is in the repo; the timestamp hit@k is not one (the W1-C spot-check in `reports/W1-C.md` left no measurement data). This README quotes no timing figure, and the 0.75 s pre-roll is a margin, not a measured bound.

Each client gets at most 4 connections and 4 requests in flight (`PREACHED_MAX_CLIENT_CONNECTIONS`, `PREACHED_MAX_CLIENT_REQUESTS`). Both caps count a response until it is written, including a `Connection: close` response that is still being flushed. A client at its cap that reconnects or sends again in that instant gets `503` with `Retry-After: 1`. API clients (Hark, parallel callers) must honour `Retry-After` on a `503` (wait that long, then retry; do not retry at once) and on a `429`. Users behind one IP (a shared office, school or NAT) share that IP's caps: 4 connections, 4 requests in flight and the rate limit. Hardening details are in `docs/DEPLOY.md`.

Another library is a separate SQLite file. One process can open two: the classic library (default `wesley`) and the library marked as your church.

```bash
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library sample --your-church --privacy privacy.example.toml
uv run app/server.py --bm25-only
uv run search/query.py "how should a Christian use money" --mode bm25 --side
```

`https://www.youtube.com/@channel/videos` is not a channel to import, and `privacy.example.toml` is only the shape of a config. Listing that URL exits 1: yt-dlp reports HTTP 404, and nothing is indexed. Pass a real channel URL and a privacy config you have reviewed before anything is indexed.

`--your-church` sets `meta.role` to `church` on that file after a successful import and clears the mark on any other church import in the index directory. `wesley`, `spurgeon`, and `edwards` stay the classic libraries, and no file that is one of them (by name, path, or hardlink) is ever marked or cleared. The slug `sample` is labelled sample data. With `--church-library <slug>` or `--church-index <file>` (and `$PREACHED_PRIVACY` set; the server also needs `PREACHED_CHURCH_SIDE=enabled`, the deploy switch in `docs/DEPLOY.md`'s church gate), the server's `/api/side` church column, `/api/search?library=<slug>`, and `search/query.py --side` search that file read-only, only through the publish gate: a sermon appears only when it is approved (`--ack-review`), its import status is `ok`, and its ASR coverage check found nothing open. Flagged passages get no play link. Church confidence is unrated. Any problem with the church file (no deploy switch, no privacy config, missing, a symlink, hardlinked, owned by another user, in WAL mode, unsafe `-wal`/`-shm`/`-journal`, not a church import, group- or world-writable, replaced after start) is one logged `church side refused:` line and the empty church column; the classic side keeps serving. `/healthz` keeps `"church": null` either way. With no church named, every response matches a process that never had one. The page's Side by side view still calls `/api/side`. The page keeps asking for `library=wesley`.

`--library SLUG` opens `$PREACHED_CACHE/index/SLUG.sqlite` (`PREACHED_CACHE` defaults to `/cache`). Pass `library=SLUG` on `/api/search`. Without a privacy config, only Wesley (built in, on its own pipeline) and the public-domain libraries listed in `src/preached/libraries.py` (Spurgeon and Edwards) are served. A classic is served only from its own owner-only `$PREACHED_CACHE/index/SLUG.sqlite`. A church library (a YouTube or ASR import) is served only with `$PREACHED_PRIVACY` set, and always behind the publish gate: a sermon appears only after `--ack-review`. Passages with a redacted name get no link, and such a sermon loses its untimed links (see `reports/W3-PRIV-WIRE.md`). Details of the side view are in `reports/W3-SIDE.md`.

### Reading a search result

Each `/api/search` result (and each result in an `/api/side` column) has `score` and `why`; the response has `confidence`.

- `score` is the ranker's own number, unchanged. In hybrid mode it is a reciprocal rank fusion sum: `1/(60 + rank)` for each list the passage is in, BM25 and dense, each cut at its top 100. `1/61 = 0.0164` is first in one list only; `2/61 = 0.0328` is first in both. In `bm25` mode it is the BM25 score (higher is better) and in `dense` mode the cosine. It only orders one result list; it is not a probability and does not compare across queries.
- `why` says how the passage was found, read off the same candidate lists the ranker fused for this query (`Why` and `Searcher._pack` in `src/preached/search.py`): `keyword_rank` and `meaning_rank` are its 1-based places in the BM25 and dense top 100 (null when it is not in that list, or the mode did not run it: `bm25` mode has no meaning fields, `dense` mode no keyword fields); `similarity` is its dense cosine from that list, rounded to 3 places (null when not in the dense list), on the model's own scale: it is not a percentage or a chance of being right, and even unrelated passages score fairly high; `found_by` is `both`, `keyword` or `meaning`. The lists are the publish-gated ones, so on a church library a hidden or unpublished sermon never moves a visible passage's rank. A result built some other way carries `"why": null`. The page shows it as one line under each card, such as "Found by both keyword (#3) and meaning (#1) search · similarity 0.81".
- `confidence` (`src/preached/abstain.py`) reads two signals: `agreement` (some shown passage is in both the BM25 and the dense top 100) and `dense_top` (the best dense cosine) against a floor calibrated per model, backend and variant in `search/abstain.toml`. `strong`: agreement and `dense_top` above the floor. `weak`: one of the two fails. `none` (the page's "low confidence", `abstain` true): both fail; the passages are still returned. `unrated`: a search with results but no dense signal (BM25-only search), or a church library with results, whose cosines the Wesley floor does not fit. A search with no results is `none` ("nothing found") in every mode, BM25-only and church included. The floor is a heuristic fitted on very few questions (five unanswerable ones; see `reports/W3-POLISH.md`); the page explains the levels under "What the confidence notes mean".

## Credits

- Text: John Wesley, *Sermons on Several Occasions* (public domain), via the [Christian Classics Ethereal Library (CCEL)](https://ccel.org/ccel/wesley/sermons).
- Recordings: [LibriVox](https://librivox.org/) volunteers (public domain in the US), streamed from the [Internet Archive](https://archive.org/).

## License

The Preached code is licensed under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE). Copyright 2026 Patrick Shouse.

This does not relicense third-party data. Sermon texts and audio keep their own licences, as recorded in `ingest/manifest/{wesley,spurgeon,edwards}.provenance.json`: the Wesley, Spurgeon, and Edwards texts (via CCEL or the Spurgeon Archive) are public domain. The Wesley First Series audio is marked CC0 1.0 (worldwide); the Wesley Second and Third-Fifth Series audio is marked Public Domain Mark 1.0; the Spurgeon and Edwards recordings carry the retired CC "Copyright-Only Dedication (based on United States law) or Public Domain Certification" (retired 2010-10-11; `creativecommons.org/licenses/publicdomain/`); LibriVox states its recordings are public domain in the US. Check your own jurisdiction before redistributing the audio. Embedding model weights are downloaded separately and keep their own licences (see `search/models.toml`).

## YouTube channel import

Paste a channel (or one watch URL) and build a library the search server can read. Audio is downloaded only as a working file under `$PREACHED_CACHE/youtube/SLUG/` and deleted after the video is indexed. `--keep-audio` leaves the file. The index stores the transcript excerpt and the exact start and end seconds. The watch URL's `t=` starts 0.75 s before that start (never below 0) and is truncated to a whole second. The video stays on YouTube. `text_source` is `asr`. `reader` is left empty.

`SLUG` is a lowercase slug (letters, digits, and hyphens). `privacy.toml` is a privacy config you have reviewed. The quotes are there so pasting the block reaches Python. `@channel` is not a real channel.

```bash
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library "SLUG" --privacy "privacy.toml" --dry-run
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library "SLUG" --privacy "privacy.toml" --limit 5 --since 2024-01-01
uv run --extra youtube --extra transcribe import/youtube.py "https://www.youtube.com/watch?v=VIDEO" --library "SLUG" --privacy "privacy.toml" --require-cc
```

A privacy config is required (`--privacy "privacy.toml"` or `$PREACHED_PRIVACY`, see `privacy.example.toml`); without one the import exits 2 before listing anything. Names are redacted, every sermon gets a private review file and lands unpublished until `--ack-review <id>`. Passages that hold a name get no play link (Patrick's decision). Announcements, prayer requests and testimonies are proposed as excluded stretches in the review file and never indexed; the passages either side of one get no play link. **Before `--ack-review`, the reviewer must listen through the whole recording**, start to end, and add an `exclude` line for anything the rules missed (CTO ruling, 2026-10-30): the rules caught 0.870 of the words on an LLM-written synthetic test set, so they are not enough alone and the human check is the real control (`reports/W3-PRIV-SKIP.md`). `wesley`, `spurgeon` and `edwards` are refused as import slugs. Wesley is built in. `src/preached/libraries.py` lists Spurgeon and Edwards, the public-domain libraries exempt from redaction and the publish gate. Church audio must never land in them. Details: `reports/W3-PRIV-WIRE.md`.

`--dry-run` prints `id`, `title`, `YYYY-MM-DD`, and duration in seconds, and writes nothing. A second run skips video ids already imported. One bad video does not stop the rest. `--require-cc` skips a video unless yt-dlp's `license` field names Creative Commons. That flag is for a public test clip, not for a church that has given permission.

Sermon windows: by default the longest spoken stretch is indexed, and a long repeated chorus is left out. To override that for one video, copy `import/sermon_windows.example.toml` and pass `--windows`. Details and the speech-span rule are in `reports/W2-YT.md`.

Transcription uses faster-whisper (`uv sync --extra transcribe`). If the GPU already holds more than 6 GB, the run uses CPU and the small English model. Gaston Community Church is refused until the pastor's permission is confirmed.
