# W2-YT: YouTube channel import

Branch `feat/w2-youtube`. The first cut was based on `origin/feat/w2-web` before PR #3 landed on `origin/main`. Review fix-ups merged `origin/main` (`feat/w2-web` at `73df6c4`, which includes PR #2 `aaee310`). `ingest/` from `feat/w1-ingest` is still not on this base, so transcription is a thin adapter rather than a call into W1-A. Report written 2026-10-30.

## What was done

`uv run import/youtube.py <channel-url> --library <slug>` builds one SQLite library at `/cache/index/<slug>.sqlite`. A channel URL, a playlist URL, or a single watch URL all work. yt-dlp lists videos (`--flat-playlist`, metadata only). A live or upcoming stream is skipped. The same video id on two tabs is kept once.

For each selected video the pipeline downloads audio only to `/cache/youtube/<slug>/`, transcribes words with timestamps, keeps the sermon window, calls `privacy.redact`, chunks the words, and writes the rows. One video's failure is recorded and the rest continue. The next run retries `error` rows and skips `ok` and `skipped` rows. `--redo` imports again. `--dry-run` prints `id`, `title`, `YYYY-MM-DD`, and duration in seconds, and does not download or write the index.

The chunks table is the Wesley schema plus `audio_url`, `reader`, `text_source`, `video_id`, `title`, and `published`. FTS5 is the same trigger-maintained `chunks_fts`. Embeddings are `granite-english-r2` float32, L2-normalized, in the `embeddings` table. There is no vector database and no new embedding model. `reader` is NULL. `text_source` is `asr`. `audio_url` is `https://www.youtube.com/watch?v=<id>&t=<seconds>s`, with the seconds truncated toward zero so YouTube's `t=` parameter seeks to that second. `source_url` is the watch URL without `t=`.

`app/server.py` still serves one index per process. `--library <slug>` opens `/cache/index/<slug>.sqlite` and accepts that slug on `/api/search`. The default remains `wesley` and `/cache/index/wesley.sqlite`. A request for a different slug is still a 400. The page keeps sending `library=wesley`.

### Sermon window

No music model and no LLM. The rule is in `src/preached/youtube/sermon.py`.

1. A TOML override wins. Copy `import/sermon_windows.example.toml` and pass `--windows`. Times are seconds on the video. Only words that start inside `[start_s, end_s)` are indexed.
2. Otherwise words split where the gap from one word's end to the next word's start is more than 15 seconds. A gap of exactly 15 seconds stays one run.
3. A run of at least 20 seconds is treated as singing when the most common word is at least a quarter of the words, or when the most common 4-word phrase covers at least a quarter of the tokens. A chorus does that. A sermon does not.
4. The window is the longest remaining run. A tie keeps the earlier run.
5. If every run looks like singing, the longest run is indexed anyway and the log says so.

A chorus with no 15-second gap before the sermon stays inside the sermon run. The override is the way to cut that.

### Transcription

`transcribe(audio_path)` returns `list[Word]` with `start`, `end`, and `text` on the file timeline. It uses faster-whisper's sequential API, English, word timestamps, VAD, and a one-line punctuated prompt. It does not copy W1-A's batched pass, gap fill, or loop repair. Those should replace this adapter when `feat/w1-ingest` merges.

Before loading the model it reads `nvidia-smi`. If more than 6 GB is already in use, or the reading fails, it uses CPU and `tiny.en`. Otherwise it uses the cached OpenAI `large-v3-turbo` conversion `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (Mobius Labs, Berlin; the weights W1-A already checked) on CUDA, `int8_float16`. This box has no system CUDA toolkit on the loader path. The adapter loads `libcublas.so.12` and cuDNN from the nvidia wheels with `ctypes` before ctranslate2 starts. The first attempt failed with "Library libcublas.so.12 is not found" until that preload was added.

Embeddings run on CPU after the Whisper model is released, the same choice the search server makes, so the two jobs do not share the GPU.

### Privacy

`preached.youtube.privacy.redact(words)` is `privacy.redact(words) -> words`, an identity function. The pipeline always calls it on the words inside the sermon window, before chunking. W3-PRIV replaces the function. This task does not add a name list.

Gaston Community Church is refused before any yt-dlp call when the URL matches the channel name or the public `@gastoncommunitychurch` handle, and again if a listing's channel title matches. No video from that channel was fetched. The real run is one Creative Commons video from New Media Rights, not a church.

## How to run

From `/work/preached/.worktrees/feat/w2-youtube`:

```bash
uv run import/youtube.py "https://www.youtube.com/@channel/videos" --library <slug> --dry-run
uv run import/youtube.py "https://www.youtube.com/@channel/videos" --library <slug> --limit 5 --since 2024-01-01
uv sync --extra transcribe
uv run --extra transcribe import/youtube.py "https://www.youtube.com/watch?v=VIDEO" --library <slug> --require-cc
uv run app/server.py --library <slug>
```

`--require-cc` skips a video unless yt-dlp's `license` field contains "Creative Commons". Use it for a public test clip. A church that has given permission will not have that license, so leave the flag off for them.

`--since` uses the date on the listing. A channel tab often has only yt-dlp's approximate date (`youtubetab:approximate_date`). The `published` column stored in the index is the exact `upload_date` from the full video metadata, fetched when that video is actually imported. A video with no date is left out when `--since` is set.

```bash
uv run python -m unittest discover -s tests
```

Audio, transcripts, and the library file stay under `/cache`. They are not committed.

## Results

55 tests, `unittest`, all passing. 36 are the existing corpus, FTS, fusion, dedupe, and server tests. 19 are new: channel-fixture parse, Creative Commons field check, `t=` URL, blocked channel, dry-run columns, resume after a one-video failure, `--require-cc` skip, sermon-span rule, chunk start/end seconds, and a fixture library queried through `App.search` and over HTTP. Tests use fixtures and fakes. They do not touch the network or the GPU.

### Test video

| | |
| --- | --- |
| id | `BGoD6CIpLWQ` |
| title | Are speeches public domain? |
| uploader | New Media Rights |
| license | Creative Commons Attribution license (reuse allowed) |
| published | 2012-08-06 |
| duration | 322 s |
| audio | `/cache/youtube/cc-speech/BGoD6CIpLWQ.webm` (4.8 MB, opus) |

The license string is yt-dlp's `license` field, not a guess from the channel name. The channel is not a church.

The index is `/cache/index/cc-speech.sqlite`: 11 chunks, span 0.02 s to 320.88 s, `text_source=asr`, `reader` NULL, embeddings `granite-english-r2` dimension 768 float32. A second `--dry-run` printed nothing and exited 0.

### Timings

The successful import reused the audio from the failed first attempt, so its `download_s` was 0.0. A separate download of the same file, through the same helper, took 2.36 s. Transcribe and index are from the successful run. Per audio hour is `seconds * 3600 / 322`.

| stage | this file | per audio hour |
| --- | --- | --- |
| download | 2.36 s | 26 s |
| transcribe (GPU, model already on disk) | 16.9 s | 189 s |
| index, including Granite load | 7.7 s | 86 s |
| of which Granite load | 6.8 s | paid once per process |
| of which encode, 11 chunks | 0.7 s | 8 s |

GPU memory in use before the model load was 4689 MiB of 12288, under the 6 GB cutoff, so the run used CUDA rather than CPU `tiny.en`. Transcribe was about 19× realtime on this short file. Download time follows the file size (4.8 MB), not the duration, and yt-dlp still has to solve the player page first.

### Search

```bash
uv run app/server.py --library cc-speech --port 8765
```

`/healthz` reported `library=cc-speech`, 11 chunks, model `granite-english-r2`, `dense: true`. RSS after the model load was 1,700,462,592 bytes (1622 MiB).

`GET /api/search?q=Are%20speeches%20in%20the%20public%20domain%3F&k=2&mode=hybrid&library=cc-speech` returned the video's own words. `took_ms` was 41. The second hit starts at 87.66 s and its `audio_url` is `https://www.youtube.com/watch?v=BGoD6CIpLWQ&t=87s`. `reader` is null and `text_source` is `asr`. BM25 for "public domain" returned in 0 ms with the same URL shape. `library=wesley` against this process returned 400, `library must be cc-speech`.

A headless Chromium load of that `t=87s` URL got the page title "Are speeches public domain? - YouTube" and the player config `"startSeconds":87`. YouTube's oEmbed endpoint returns the same title and author. The `<audio>` element on the Wesley page will not play this URL. That player change is a later task. The content security policy still does not allow a YouTube frame.

## Open issues

- YouTube's terms and the player change underneath yt-dlp. This run warned that the remote JS challenge solver was skipped and that the n-challenge failed, then still downloaded audio format 251. A later player change can refuse the download. Do not add a cookie jar or a challenge bypass here. The working file is only for transcription. Playback stays a link to YouTube.
- Channel-tab dates are approximate until each video is opened. `--since` on a dry-run can be off by weeks. The stored `published` date is the exact one.
- The sermon rule cannot see a song that Whisper transcribes as ordinary prose with no long gap and no repeated line. Worship that runs straight into the sermon needs a `--windows` override.
- The adapter is not W1-A. Punctuation is uneven, and there is no gap fill or loop repair. Unify them when ingest merges. The CUDA preload should move with that code.
- The page always requests `library=wesley` and plays `audio_url` in one `<audio>` element. A church library needs a library picker and a link or a `youtube-nocookie` frame. W2-A already says not to open `script-src` to do that. `/api/sermon/<id>` now accepts an 11-character YouTube id; the page still does not link to it.
- Embedding on the Sprite is the same Granite CPU load as W2-A, about 1.6 GiB RSS, plus brute-force scan of one SQLite file. Eleven vectors are nothing. A multi-year church archive is still one file and one model, which is the point of the design, until the brute-force scan itself gets slow. No second model, no vector database.
- Permission: do not point this at a church channel until a person has the pastor's yes. The tool refuses Gaston Community Church by name. `--require-cc` is the wrong gate for a church. Before any church audio is indexed, W3-PRIV has to replace `privacy.redact`. Indexes and audio stay in `/cache`. Nothing from a church was downloaded for this task.

## Dependencies added and why

- `yt-dlp==2026.10.26`, required. The standard library cannot list a YouTube channel or download the audio stream. The player signature changes, which is the whole reason this package exists. It is pure Python, about 3 MB. Pinned to the current PyPI release.
- Optional extra `transcribe`, not installed by a normal `uv sync`: `faster-whisper>=1.2.1,<1.3`, `av>=18.1,<19`, `nvidia-cublas-cu12>=12.4,<13`, `nvidia-cudnn-cu12>=9,<10`. These are the same pins as W1-A. faster-whisper 1.2.1 breaks on av 19. The box has no system cuBLAS, so the wheels have to come with the extra. The search server does not need them. The lockfile also picks up what those packages require (ctranslate2, onnxruntime, and the CUDA runtime pieces). No new embedding model.

## Review fix-ups

Merged `origin/main` (PR #3 is on main; head of `feat/w2-web` is `73df6c4`, which already contains PR #2 `aaee310`). Conflict resolution kept both sides: https and same-origin URL checks, CCEL and LibriVox credits, the de-dup API path and its metrics, and `--library`. `yt-dlp` stayed a runtime dependency. Pillow and torchvision stayed in the `bench` group. einops stayed out.

A channel URL that is not `https` on `youtube.com`, `www.youtube.com`, `m.youtube.com`, or `youtu.be` is rejected in the CLI before `run`, and again in the fetcher before `subprocess`. That includes a URL that starts with `-` and a URL on any other host. Every yt-dlp invocation passes the URL after `--`.

`/api/sermon/<id>` still accepts a lowercase Wesley slug. It also accepts an 11-character YouTube id (`[A-Za-z0-9_-]`, case-sensitive). A dot, a slash, or `Wesley-001` is still 404. The fixture library test imports `BGoD6CIpLWQ` and checks that route.

Indexing a video records `embeddings:<model>` with `save_embedding_info` and the current `models.toml` fingerprint, in the same transaction as the vectors. `Searcher` can then open that library under the Granite key. A test fixture that writes vectors checks the stored fingerprint.

88 tests, `unittest discover -s tests`, all passing. No YouTube download in this pass. No new dependency.
