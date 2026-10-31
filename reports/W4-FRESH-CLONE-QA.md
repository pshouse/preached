# W4 fresh-clone QA

Judge's-eye walkthrough of `README.md` on `main` at `e552cfd` (Merge pull request #62). No README edits. A clone that follows the README top to bottom does not get a working hybrid search, and the README's own example question does not surface Wesley's "take no thought for the morrow" sermon.

## Harness

Commands ran in `/work/preached/.worktrees/qa-w4-fresh-clone` (branch `qa/w4-fresh-clone`, created from `origin/main`, not checked out in `/work/preached`).

The shell already had `HF_HOME=/cache/huggingface`. That was unset for every README command so `preached.env` would put weights under the fresh cache. Also set, because README never mentions them and the defaults would have reused this box's prebuilt tree:

- `PREACHED_CACHE=/cache/fresh-clone-qa` (created empty, deleted after this report)
- `PREACHED_ONNX_DIR=/cache/fresh-clone-qa/models/granite-english-r2-onnx` (empty until the export detour)

`UV_CACHE_DIR=/cache/uv` was left as the environment had it. Package installs below are cache hits, not a cold download of the CUDA torch wheel. The real `/cache/index/wesley.sqlite` mtime stayed `2026-10-30 15:39:09` (189042688 bytes). Nothing was written into that index.

This box already has a pinned ONNX graph at `/cache/models/granite-english-r2-onnx/.../model.fp32.onnx` (sha256 `3861025a…`). A judge who does not override the paths will use that file and the existing index, and will not see the failures below. The fresh directory is what a clone sees when those files are absent.

Tools on the machine, none of them named in the README: uv 0.13.6, system Python 3.14.8 (outside `requires-python` `>=3.12,<3.14`; uv selected CPython 3.12.16), deno, ffmpeg. No `HF_TOKEN`. GPU: NVIDIA GeForce RTX 3060, 12 GB. The bench used it.

## Command log

Wall times are the README command only, from the worktree.

| # | Command (as in the README) | Wall | Exit | First error / note |
| --- | --- | --- | --- | --- |
| 1 | `uv run corpus/fetch_wesley.py` | 1.691s | 0 | Created `.venv`, "Installed 21 packages in 32ms", "Using CPython 3.12.16". Wrote 141 sermons, 652145 words, to the fresh cache. Needs network (CCEL). |
| 2 | `uv run corpus/chunk_sermons.py` | 0.596s | 0 | 8383 chunks, overlap 0.25, words min/median/max 15/122/180. `start_s` stays null. |
| 3 | `uv run python eval/validate.py` | 136.935s | 0 | No progress output. `{"questions": 93, ... "chunks": 8383}` then "all graded quotes match at least one chunk". |
| 4 | `uv run --group bench search/bench.py` | 672.515s | 0 | Installs the bench group ("Installed 49 packages in 395ms", cache hit). stderr: "You are sending unauthenticated requests to the HF Hub." Embeds three enabled models on CUDA. Writes `eval/results/2026-10-31.json` into the clone. |
| 5 | `uv run --group bench search/bench.py --models granite-english-r2 --dedupe` | 63.531s | 0 | "corpus vectors cached". Same HF warning. Writes `eval/results/2026-10-31-dedupe.json`. |
| 6 | `uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5` | 0.170s | 1 | `error: missing ONNX manifest at .../47ea694b257b703fee9253d75c2b1f2985180498/manifest.json` |
| 7 | `uv sync` | 0.619s | 0 | "Uninstalled 49 packages" including torch, sentence-transformers, nvidia-*. Runtime set remains (numpy, onnxruntime, tokenizers). |
| 8 | `uv run app/server.py` | ~0.4s to listen | (left running) | stderr: `ERROR embedding model unavailable; serving BM25 only` then the missing-manifest traceback, then `WARNING Embedding model failed to load; results are BM25 only.` stdout: `PREACHED_LISTENING http://127.0.0.1:8000`. |
| 9 | open http://127.0.0.1:8000 | page 0.003s | HTTP 200 | `/`, `/static/app.js`, `app.css`, `favicon.svg`, `/healthz` all 200. `healthz` has `"model": null, "fallback": true, "chunks": 8383`. No browser here; checked with curl. |
| 10 | `GET /api/search?q=what+did+Wesley+say+about+worry&mode=hybrid&k=5` | 0.001s | HTTP 200 | `"mode": "bm25"`, `"results": []`, note "Embedding model failed to load; results are BM25 only." |
| 11 | `uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library sample --your-church` | 0.171s | 2 | `privacy: MissingConfig: a church library needs a privacy config...` Installed yt-dlp (1 package). No network listing. |
| 12 | paste of the `<slug>` / `<toml>` block, unquoted, in bash | 0.003s | 1 | `bash: line 1: slug: No such file or directory` |
| 13 | same three YouTube lines with the angle brackets passed as literal arguments | 0.136s, 0.130s, 0.192s | 2 | `library must be a short slug...` The `--extra transcribe` line installed 6 packages before that check. |
| 14 | `uv run app/server.py --bm25-only` | 0.611s to listen | (stopped) | `INFO BM25 only; the embedding model was not loaded` then listening. |
| 15 | `uv run search/query.py "what did Wesley say about worry" --mode bm25 --side` | 0.130s | 0 | Classic column: "Nothing found in the indexed sermons." Church column: "Nothing from your church yet." |

Detours, not README code blocks, after step 6 failed:

| Detour | Wall | Exit | Note |
| --- | --- | --- | --- |
| `CUDA_VISIBLE_DEVICES="" uv sync --group bench` then `uv run --group bench python scripts/export_onnx.py` (the command in `reports/W3-CPU.md`) | 23.079s | 0 | Wrote a fresh `model.fp32.onnx` (596635043 bytes, sha256 `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`). The script's `setdefault` sent the snapshot read at the existing `/cache/huggingface/hub` (fetch line was instant). |
| same query as step 6, after that export | 0.453s | 1 | `error: ONNX sha256 for model.fp32.onnx is not the pinned digest` |
| same query with `PREACHED_ONNX_DIR` pointed at the prebuilt pinned tree (read-only probe) | 2.002s | 0 | Hybrid runs. See below. |
| same query with `PREACHED_EMBED_BACKEND=torch` | 5.968s | 0 | Same five hits as the pinned ONNX probe. |

`GET /api/search` for `Romans 8:16` on the BM25 fallback returns sermon 10, "THE WITNESS OF THE SPIRIT, Discourse I", quoting Rom. 8:16, with a CCEL link. That query is not the one the README tells the judge to run.

## What the example query returns

The word "worry" occurs in 0 of 8383 chunks, so BM25 of the README's question is empty. That is the whole result of steps 8–10 and of the `--side` command.

With a pinned graph (the prebuilt file, not the fresh export), hybrid `-k 5` returns real Wesley text and then prints "Low confidence: these passages may not answer your question." Top 5: On Riches, The Danger of Riches, Satan's Devices, On Public Diversions, On Conscience. The labeled passage for anxiety is sermon 29, "Upon our Lord's Sermon on the Mount, Discourse 9" ("Take therefore no thought for the morrow"). It is rank 11, so it is outside `-k 5` and outside the page default `k=10` (rank 10 is Wandering Thoughts). Every hit has `start_s=None`, `audio_url=None`, and `play: n/a`. The quickstart never builds timings.

## Findings

### BLOCKER

1. README lines 11 and 20. The query and the server default to ONNX fp32, and the loader does not download. No README command creates `/cache/models/granite-english-r2-onnx/<revision>/`. Fresh query exits 1 in 0.17s. The server still listens and answers the example with an empty BM25 list. Fix: put the export in the quickstart before `search/query.py`, and say where the files must be.

2. README line 23, via the "commands" in `reports/W3-CPU.md` lines 39–40. A fresh `scripts/export_onnx.py` exits 0 and writes a graph of the same size as the pinned file (596635043 bytes) whose sha256 is `aed7adba…`, not the pin `3861025a…` in `src/preached/artifacts.py`. The runtime then refuses it (`ONNX sha256 for model.fp32.onnx is not the pinned digest`). Tokenizer sha256 does match. Fix: re-pin the digest to the bytes this exporter writes, or stop refusing a graph the repo's own export just produced.

### CONFUSING

3. README lines 9–11 and 25. The first bench embeds every enabled model, not Granite alone: `embeddinggemma-2`, `granite-english-r2`, and `arctic-embed-l` (eval-only, lineage flagged unclear in the result table). Here that was 672s on a 3060, about 3.8 GB under the fresh cache once the ONNX files were added, plus an anonymous Hub warning. The README does not say GPU, network, disk, or time. CPU fallback was not timed. Fix: point the snippet at `--models granite-english-r2` and say the full bench downloads three models and wants a GPU.

4. README line 25. The quoted Granite hybrid figures are the 35-answerable-question run in `eval/results/2026-10-30.json`. This tree has 86 answerable questions (93 total). The same commands now print raw hybrid_rrf R@5 0.285, MRR@10 0.219, nDCG@10 0.246 (not 0.629, 0.506, 0.558) and `--dedupe` 0.297, 0.241, 0.265 (not 0.614, 0.497, 0.546). Fix: replace those six numbers or label them as the old 35-question set.

5. README line 11. The worked example is a question BM25 cannot answer ("worry" is not in the corpus) and that hybrid ranks poorly (gold sermon at 11, low-confidence banner). `Romans 8:16` returns the right sermon immediately. Fix: change the sample question, or warn that this wording is low-confidence and will not show the Sermon on the Mount in the first page.

6. README line 25. "Passages with no `start_s`" reads like an exception. After the documented steps it is every passage: `corpus/chunk_sermons.py` writes null timings, and `chunks_aligned.jsonl` is never built. Play links are `n/a`. The alignment command (`uv run align/wesley.py chunks`) and the audio ingest are not in the README. Fix: say the quickstart is text-only, and add the align step before promising a recording.

7. README line 14. Data "stay under `/cache`" and "Weights use `HF_HOME=/cache/huggingface`" are stated as facts. The code key is `PREACHED_CACHE` (default `/cache`), which then sets `HF_HOME`. README never says to create that directory or how to point it elsewhere. This sandbox can create a directory at `/`; a normal laptop often cannot, and the first command would die on `mkdir`. Fix: document `PREACHED_CACHE` and that the directory must exist and be writable.

8. README line 7. `eval/validate.py` is a silent 137s nested scan. A judge can easily take it for a hang. Fix: say it checks every graded quote against every chunk and prints nothing until it finishes.

9. README lines 5–12 then 19. `uv sync` after the bench uninstalls the 49 bench packages (0.619s), including torch. That matches the sentence that torch is not in the runtime set, and it surprises anyone who thinks the first block's install sticks. Fix: say the later `uv sync` drops the bench group.

10. README line 31. The church example omits `--privacy`, so it exits 2 before listing. The error does name `privacy.example.toml`. The URL `@channel` is not a channel a judge can import. Fix: add `--privacy privacy.example.toml` only as a shape, and say a real channel URL and a reviewed config are required before anything is indexed.

11. README lines 57–60. `<slug>` and `<toml>` are unquoted. Pasting the block into bash is a redirection (`slug: No such file or directory`) and never reaches Python. Fix: use `SLUG` and `privacy.toml`, quoted.

12. README lines 9–10. The bench writes `eval/results/2026-10-31.json` and `.md` (and the `-dedupe` pair) into the clone. They are untracked. `corpus/fetch_wesley.py` rewrites `corpus/catalog.json`; the bytes matched this time (sha256 `66b83ba7…`). Fix: say both are local outputs and that a changed CCEL file needs `--accept-new-text`.

13. No prerequisites section. A judge needs uv (the build pin is `uv_build>=0.13.6,<0.14`), Python `>=3.12,<3.14`, network, and a lot of disk. YouTube coverage calls `ffmpeg`, which the README never names. `deno` is only for tests, which the README also never names. Fix: one requirements line for uv, Python, network, disk, and ffmpeg if they will import audio.

### NIT

14. README line 3. "This branch builds the Wesley text corpus..." On `main`, after a clone, there is no feature branch. Fix: say "This repo builds..."

15. README line 16. "From this worktree:" Fix: say "From the clone:"

16. README line 62. "`src/preached/libraries.py`" is cited for the libraries exempt from redaction. That tuple is `("spurgeon", "edwards")` only. Wesley is a separate pipeline. Fix: say Wesley is built in, and that file lists Spurgeon and Edwards.

17. README line 25. "Excerpts on the page hide CCEL paragraph numbers." The riches hit lost a leading "8." The Romans 8:16 hit still shows "1." after the verse (`Rom. 8:16 1. How many...`), which the strip regex does not treat as a paragraph number. Fix: extend the strip so a number after a verse reference is hidden too.

18. README does not document a test command or a pass/skip count. The file it points at for commands, `reports/W3-CPU.md` line 19 and the block at line 31, says 172 tests and `cd /work/preached/.worktrees/feat/w3-cpu`, a path this clone does not have. `uv run python -m unittest discover -s tests` on this tree collected 996 tests in 223.962s. With `PREACHED_ONNX_DIR` on the fresh export: `FAILED (failures=3, errors=2)`, no `skipped=` clause. All five are the pin refusal (`test_cached_fp32_and_tokenizer_match_the_pins`, two load errors, the YouTube ONNX import guard, and `test_sigterm_under_hybrid_load_exits_zero_and_cleans_up`). This run still saw the prebuilt `/cache` index, `/cache/asr-repro`, and deno, so it does not measure skips on a machine that lacks those. Fix: put the discover command in the README and drop the 172 figure.

## Links and paths

Every relative path and Markdown link in the README exists on this `main`: `reports/W1-B.md`, `eval/README.md`, `reports/W3-CPU.md`, `src/preached/search.py` (`api_search` is defined; `SEARCH_POOL` is 100; hybrid RRF `k` is 60), `reports/W2-A.md`, `reports/W1-CLI.md`, `reports/W1-C.md`, `docs/DEPLOY.md`, `src/preached/libraries.py`, `reports/W3-PRIV-WIRE.md`, `reports/W3-SIDE.md`, `LICENSE`, `NOTICE`, `ingest/manifest/{wesley,spurgeon,edwards}.provenance.json`, `search/models.toml`, `privacy.example.toml`, `reports/W3-PRIV-SKIP.md`, `import/sermon_windows.example.toml`, `reports/W2-YT.md`, and the scripts in the code blocks.

`https://ccel.org/ccel/wesley/sermons`, `https://librivox.org/`, and `https://archive.org/` returned HTTP 200. `creativecommons.org/licenses/publicdomain/` (named in prose, not a Markdown link) returned 301.

Checked in code and not wrong: chunk overlap 0.25, client caps described as 4 and 4, `Retry-After: 1` is the constant the README states (not exercised under load), `uv sync` really does install numpy, onnxruntime, and tokenizers and not torch. The 0.870 word-recall figure is in `reports/W3-PRIV-SKIP.md` (635/730) and was not re-measured.
