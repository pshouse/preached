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

Then open http://127.0.0.1:8000. Search returns Wesley's published words. Hybrid mode is reciprocal rank fusion with k=60. Adjacent chunks overlap by about 25%, and the API keeps the higher-scoring one so the same words are not listed twice. So `/api/search` does not return the raw top k that `search/query.py` prints: it takes the ranker's top 100 and de-dups down to k (`api_search` in `src/preached/search.py`). `search/bench.py --dedupe` scores that path. For Granite hybrid it gives R@5 0.614, MRR@10 0.497 and nDCG@10 0.546, against 0.629, 0.506 and 0.558 for the raw top 10. Excerpts on the page hide CCEL paragraph numbers. The indexed text is unchanged. Passages with no `start_s` say that audio timing is still coming and link to the CCEL text. Details are in `reports/W2-A.md`. The timestamp hit@k in `reports/W1-CLI.md` is derived from the alignment: equal to the text metric by construction, not an independent audio-accuracy result. Audio accuracy is the W1-C spot-check (median 0.42 s, max 0.76 s against the audio, covered by the 0.75 s pre-roll).

Another library is a separate SQLite file. One process can open two: the classic library (default `wesley`) and the library marked as your church.

```bash
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library sample --your-church
uv run app/server.py --bm25-only
uv run search/query.py "what did Wesley say about worry" --mode bm25 --side
```

`--your-church` sets `meta.role` to `church` on that file and clears the mark on any other file in `/cache/index`. The slug `sample` is labelled sample data. A missing church file does not stop the server. `GET /api/search?library=<slug>` searches only an open library. `GET /api/side` returns the top hits from each side. The page's Side by side view calls that. Details are in `reports/W3-SIDE.md`.

## Credits

- Text: John Wesley, *Sermons on Several Occasions* (public domain), via the [Christian Classics Ethereal Library (CCEL)](https://ccel.org/ccel/wesley/sermons).
- Recordings: [LibriVox](https://librivox.org/) volunteers (public domain), streamed from the [Internet Archive](https://archive.org/).

## YouTube channel import

Paste a channel (or one watch URL) and build a library the search server can read. Audio is downloaded only as a working file under `/cache/youtube/<slug>/` and deleted after the video is indexed. `--keep-audio` leaves the file. The index stores the transcript excerpt and the exact start and end seconds. The watch URL's `t=` starts 0.75 s before that start (never below 0) and is truncated to a whole second. The video stays on YouTube. `text_source` is `asr`. `reader` is left empty.

```bash
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library <slug> --dry-run
uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library <slug> --limit 5 --since 2024-01-01
uv run --extra youtube --extra transcribe import/youtube.py "https://www.youtube.com/watch?v=VIDEO" --library <slug> --require-cc
```

`--dry-run` prints `id`, `title`, `YYYY-MM-DD`, and duration in seconds, and writes nothing. A second run skips video ids already imported. One bad video does not stop the rest. `--require-cc` skips a video unless yt-dlp's `license` field names Creative Commons. That flag is for a public test clip, not for a church that has given permission.

Sermon windows: by default the longest spoken stretch is indexed, and a long repeated chorus is left out. To override that for one video, copy `import/sermon_windows.example.toml` and pass `--windows`. Details and the speech-span rule are in `reports/W2-YT.md`.

Transcription uses faster-whisper (`uv sync --extra transcribe`). If the GPU already holds more than 6 GB, the run uses CPU and the small English model. Gaston Community Church is refused until the pastor's permission is confirmed.
