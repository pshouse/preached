# Preached

Search a sermon archive and return the preacher's own words. This branch builds the Wesley text corpus, the eval set, and the retrieval benchmark.

```bash
uv run corpus/fetch_wesley.py
uv run corpus/chunk_sermons.py
uv run python eval/validate.py
uv run search/bench.py
uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
```

Corpus text and the SQLite index stay under `/cache`. Weights use `HF_HOME=/cache/huggingface`. The default embedder is IBM Granite English R2, hybrid RRF. How that was chosen is in `reports/W1-B.md`. Labeling notes are in `eval/README.md`.

The page is a stdlib server. From this worktree:

```bash
uv run app/server.py
```

Then open http://127.0.0.1:8000. Search returns Wesley's published words. Hybrid mode is reciprocal rank fusion with k=60. Adjacent chunks overlap by about 25%, and the API keeps the higher-scoring one so the same words are not listed twice. Passages with no `start_s` say that audio timing is still coming and link to the CCEL text. Details are in `reports/W2-A.md`.

Another library is a separate SQLite file. The server still serves one file per process:

```bash
uv run app/server.py --library <slug> --bm25-only
```

That opens `/cache/index/<slug>.sqlite`. The page keeps asking for `library=wesley`. Pass `library=<slug>` on `/api/search`.

## YouTube channel import

Paste a channel (or one watch URL) and build a library the search server can read. Audio is downloaded only as a working file under `/cache/youtube/<slug>/`. The index stores the transcript excerpt, the start and end seconds, and a YouTube watch URL with `t=<seconds>s`. The video stays on YouTube. `text_source` is `asr`. `reader` is left empty.

```bash
uv run import/youtube.py "https://www.youtube.com/@channel/videos" --library <slug> --dry-run
uv run import/youtube.py "https://www.youtube.com/@channel/videos" --library <slug> --limit 5 --since 2024-01-01
uv run --extra transcribe import/youtube.py "https://www.youtube.com/watch?v=VIDEO" --library <slug> --require-cc
```

`--dry-run` prints `id`, `title`, `YYYY-MM-DD`, and duration in seconds, and writes nothing. A second run skips video ids already imported. One bad video does not stop the rest. `--require-cc` skips a video unless yt-dlp's `license` field names Creative Commons. That flag is for a public test clip, not for a church that has given permission.

Sermon windows: by default the longest spoken stretch is indexed, and a long repeated chorus is left out. To override that for one video, copy `import/sermon_windows.example.toml` and pass `--windows`. Details and the speech-span rule are in `reports/W2-YT.md`.

Transcription uses faster-whisper (`uv sync --extra transcribe`). If the GPU already holds more than 6 GB, the run uses CPU and the small English model. Gaston Community Church is refused until the pastor's permission is confirmed.
