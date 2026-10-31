# Preached

Search a sermon archive and return the preacher's own words. This branch builds the Wesley text corpus, the eval set, and the retrieval benchmark.

```bash
uv run corpus/fetch_wesley.py
uv run corpus/chunk_sermons.py
uv run python eval/validate.py
uv run --group bench search/bench.py
uv run --group bench search/bench.py --models granite-english-r2 --dedupe
uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
```

Corpus text and the SQLite index stay under `/cache`. Weights use `HF_HOME=/cache/huggingface`. The default embedder is IBM Granite English R2, hybrid RRF. How that was chosen is in `reports/W1-B.md`. Labeling notes are in `eval/README.md`.

The page is a stdlib server. From this worktree:

```bash
uv sync
uv run app/server.py
```

`uv sync` installs the runtime only (numpy, onnxruntime, tokenizers). Torch is not in that set. The query embedder defaults to ONNX fp32 with one intra-op thread (`PREACHED_ORT_INTRA_OP_THREADS`, `--ort-threads`). Export and the benchmark need `uv sync --group bench`. Commands and the measured sizes are in `reports/W3-CPU.md`.

Then open http://127.0.0.1:8000. Search returns Wesley's published words. Hybrid mode is reciprocal rank fusion with k=60. Adjacent chunks overlap by about 25%, and the API keeps the higher-scoring one so the same words are not listed twice. So `/api/search` does not return the raw top k that `search/query.py` prints: it takes the ranker's top 100 and de-dups down to k (`api_search` in `src/preached/search.py`). `search/bench.py --dedupe` scores that path. For Granite hybrid it gives R@5 0.614, MRR@10 0.497 and nDCG@10 0.546, against 0.629, 0.506 and 0.558 for the raw top 10. Excerpts on the page hide CCEL paragraph numbers. The indexed text is unchanged. Passages with no `start_s` say that audio timing is still coming and link to the CCEL text. Details are in `reports/W2-A.md`. The timestamp hit@k in `reports/W1-CLI.md` is derived from the alignment: equal to the text metric by construction, not an independent audio-accuracy result. Audio accuracy is the W1-C spot-check (`reports/W1-C.md`); this README quotes no timing figure, and the 0.75 s pre-roll is a margin, not a measured bound.

Each client gets at most 4 connections and 4 requests in flight (`PREACHED_MAX_CLIENT_CONNECTIONS`, `PREACHED_MAX_CLIENT_REQUESTS`). Both caps count a response until it is written, including a `Connection: close` response that is still being flushed. A client at its cap that reconnects or sends again in that instant gets `503` with `Retry-After: 1`. Hardening details are in `docs/DEPLOY.md`.

Another library is a separate SQLite file. One process can open two: the classic library (default `wesley`) and the library marked as your church.

```bash
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library sample --your-church
uv run app/server.py --bm25-only
uv run search/query.py "what did Wesley say about worry" --mode bm25 --side
```

`--your-church` sets `meta.role` to `church` on that file after a successful import and clears the mark on any other church import in the index directory. `wesley`, `spurgeon`, and `edwards` stay the classic libraries, and no file that is one of them (by name, path, or hardlink) is ever marked or cleared. The slug `sample` is labelled sample data. Until the church side is wired to the publish gate, `/api/side`'s church column and `/healthz` match a process with no church file, and `--church-library` / `--church-index` are only checked, never opened. The page's Side by side view still calls `/api/side`. The page keeps asking for `library=wesley`.

`--library <slug>` opens `/cache/index/<slug>.sqlite`. Pass `library=<slug>` on `/api/search`. Without a privacy config, only `wesley` and the public-domain libraries in `src/preached/libraries.py` (`spurgeon`, `edwards`) are served. A classic is served only from its own owner-only `/cache/index/<slug>.sqlite`. A church library (a YouTube or ASR import) is served only with `$PREACHED_PRIVACY` set, and always behind the publish gate: a sermon appears only after `--ack-review`. Passages with a redacted name get no link, and such a sermon loses its untimed links (see `reports/W3-PRIV-WIRE.md`). Details of the side view are in `reports/W3-SIDE.md`.

## Credits

- Text: John Wesley, *Sermons on Several Occasions* (public domain), via the [Christian Classics Ethereal Library (CCEL)](https://ccel.org/ccel/wesley/sermons).
- Recordings: [LibriVox](https://librivox.org/) volunteers (public domain in the US), streamed from the [Internet Archive](https://archive.org/).

## License

The Preached code is licensed under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE). Copyright 2026 Patrick Shouse.

This does not relicense third-party data. Sermon texts and audio keep their own licences, as recorded in `ingest/manifest/{wesley,spurgeon,edwards}.provenance.json`: the Wesley, Spurgeon, and Edwards texts (via CCEL or the Spurgeon Archive) are public domain. The Wesley First Series audio is marked CC0 1.0 (worldwide); the Wesley Second and Third-Fifth Series audio is marked Public Domain Mark 1.0; the Spurgeon and Edwards recordings carry the retired CC Public Domain Certification (`creativecommons.org/licenses/publicdomain/`); LibriVox states its recordings are public domain in the US. Check your own jurisdiction before redistributing the audio. Embedding model weights are downloaded separately and keep their own licences (see `search/models.toml`).

## YouTube channel import

Paste a channel (or one watch URL) and build a library the search server can read. Audio is downloaded only as a working file under `/cache/youtube/<slug>/` and deleted after the video is indexed. `--keep-audio` leaves the file. The index stores the transcript excerpt and the exact start and end seconds. The watch URL's `t=` starts 0.75 s before that start (never below 0) and is truncated to a whole second. The video stays on YouTube. `text_source` is `asr`. `reader` is left empty.

```bash
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library <slug> --privacy <toml> --dry-run
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library <slug> --privacy <toml> --limit 5 --since 2024-01-01
uv run --extra youtube --extra transcribe import/youtube.py "https://www.youtube.com/watch?v=VIDEO" --library <slug> --privacy <toml> --require-cc
```

A privacy config is required (`--privacy <toml>` or `$PREACHED_PRIVACY`, see `privacy.example.toml`); without one the import exits 2 before listing anything. Names are redacted, every sermon gets a private review file and lands unpublished until `--ack-review <id>`. Passages that hold a name get no play link (Patrick's decision). Announcements, prayer requests and testimonies are proposed as excluded stretches in the review file and never indexed; the passages either side of one get no play link. **Before `--ack-review`, the reviewer must listen through the whole recording**, start to end, and add an `exclude` line for anything the rules missed (CTO ruling, 2026-10-30): the rules caught 0.870 of the words on an LLM-written synthetic test set, so they are not enough alone and the human check is the real control (`reports/W3-PRIV-SKIP.md`). `wesley`, `spurgeon` and `edwards` are refused as import slugs: only those public-domain libraries are exempt from redaction and the publish gate (`src/preached/libraries.py`), and church audio must never land in them. Details: `reports/W3-PRIV-WIRE.md`.

`--dry-run` prints `id`, `title`, `YYYY-MM-DD`, and duration in seconds, and writes nothing. A second run skips video ids already imported. One bad video does not stop the rest. `--require-cc` skips a video unless yt-dlp's `license` field names Creative Commons. That flag is for a public test clip, not for a church that has given permission.

Sermon windows: by default the longest spoken stretch is indexed, and a long repeated chorus is left out. To override that for one video, copy `import/sermon_windows.example.toml` and pass `--windows`. Details and the speech-span rule are in `reports/W2-YT.md`.

Transcription uses faster-whisper (`uv sync --extra transcribe`). If the GPU already holds more than 6 GB, the run uses CPU and the small English model. Gaston Community Church is refused until the pastor's permission is confirmed.
