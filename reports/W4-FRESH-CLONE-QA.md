# W4 fresh-clone QA

Judge's-eye walkthrough of `README.md` on `main` at `e552cfd` (Merge pull request #62). Every "README line N" below is that commit's README. `main` has moved since; do not check these numbers against a later README. No README edits. A clone that follows the README top to bottom does not get a working hybrid search, and the README's own example command (`search/query.py` … `-k 5`) does not print Wesley's "take no thought for the morrow" sermon.

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
| `CUDA_VISIBLE_DEVICES="" uv sync --group bench` then `uv run --group bench python scripts/export_onnx.py` (the command in `reports/W3-CPU.md`) | 23.079s | 0 | Wrote a fresh `model.fp32.onnx` (596635043 bytes, sha256 `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`). The script's `setdefault` sent the snapshot read at the existing `/cache/huggingface/hub` (fetch line was instant). That sha256 is the avx2 dispatch level, not a second pin; see finding 2. |
| same query as step 6, after that export | 0.453s | 1 | `error: ONNX sha256 for model.fp32.onnx is not the pinned digest` |
| same query with `PREACHED_ONNX_DIR` pointed at the prebuilt pinned tree (read-only probe) | 2.002s | 0 | Hybrid runs. See below. |
| same query with `PREACHED_EMBED_BACKEND=torch` | 5.968s | 0 | Same five hits as the pinned ONNX probe. |

`GET /api/search` for `Romans 8:16` on the BM25 fallback returns sermon 10, "THE WITNESS OF THE SPIRIT, Discourse I", quoting Rom. 8:16, with a CCEL link. That query is not the one the README tells the judge to run.

## What the example query returns

The word "worry" occurs in 0 of 8383 chunks, so BM25 of the README's question is empty. That is the whole result of steps 8–10 and of the `--side` command.

With a pinned graph (the prebuilt file, not the fresh export) on this fresh index, hybrid `-k 5` returns real Wesley text and then prints the level-`none` note, which starts "Low confidence: these passages may not answer your question." That is abstain (`confidence.level` is `none`). It is not level `weak`. Top 5 from `search/query.py`: On Riches, The Danger of Riches, Satan's Devices, On Public Diversions, On Conscience. The labeled passage for anxiety is sermon 29, "Upon our Lord's Sermon on the Mount, Discourse 9" ("Take therefore no thought for the morrow"). `search/query.py` does not de-dup, so on that list the sermon is rank 11: outside `-k 5`, and outside a `query.py` page of `k=10` (rank 10 is Wandering Thoughts). "Outside the page default `k=10`" holds only for `query.py`. `GET /api/search` de-dups adjacent chunks (`dedupe_adjacent` inside `api_search`), and on that list the gold sermon is result 10 (CTO review of this report; this walkthrough's step 10 was still the BM25 fallback). Every hit has `start_s=None`, `audio_url=None`, and `play: n/a`. The quickstart never builds timings.

## Findings

### BLOCKER

1. README lines 11 and 20. The query and the server default to ONNX fp32, and the loader does not download. No README command creates `/cache/models/granite-english-r2-onnx/<revision>/`. Fresh query exits 1 in 0.17s. The server still listens and answers the example with an empty BM25 list. Fix: put a bench sync plus the export in the quickstart, before `search/query.py`, and say where the files must be. The runtime `uv sync` does not install torch; export needs the bench group (`uv sync --group bench`, then `CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py`, the commands in `reports/W3-CPU.md`). Name the dispatch caveat with that step. `scripts/export_onnx.py` calls `os.environ.setdefault` for `HF_HOME` and `HUGGINGFACE_HUB_CACHE` at import, before any `import torch`, so an ambient `HF_HOME` is kept and the snapshot is read from there (this run's fetch line was instant against `/cache/huggingface/hub`). `main` does `shutil.rmtree(artifact_dir())` when that directory exists, which deletes the revision directory under `PREACHED_ONNX_DIR` (default `/cache/models/granite-english-r2-onnx/<revision>/`) before writing. The graph bytes depend on torch's ATEN CPU dispatch level at export time (finding 2). The pin is the AVX512 graph. An export at another level, including the avx2 graph this walkthrough wrote, fails the pin check.

2. README line 23, via the commands in `reports/W3-CPU.md` lines 39–40. A fresh `scripts/export_onnx.py` on this walkthrough exited 0 and wrote a graph of the same size as the pinned file (596635043 bytes) whose sha256 is `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`, not the pin `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` in `src/preached/artifacts.py`. The runtime then refused it (`ONNX sha256 for model.fp32.onnx is not the pinned digest`). Tokenizer sha256 did match.

The export is deterministic run-to-run. Its bytes depend on torch's ATEN CPU dispatch level at export time (CTO review of this report). AVX512, this box's default, gives `3861025a…`, the pin, reproduced twice. `ATEN_CPU_CAPABILITY=avx2` gives `aed7adba…5b78`, byte-for-byte the hash this walkthrough wrote. The `default` dispatch level gives `d99ba823`. `aed7adba…` is functionally identical to the pin: all 134 initializers are byte-identical, and only 6 nodes differ (the rotary `inv_freq` Constants are swapped, and 4 Unsqueeze inputs are rewired). ORT outputs are bitwise identical, and the search harness over all 93 questions gives the same response and embedding hashes. Re-pinning to `aed7adba…` would break every AVX512 host. That recommendation is withdrawn.

Fix, per the CTO's ruling: the export pins `ATEN_CPU_CAPABILITY=avx2` before importing torch, and the pin moves once, with an ADR. That work is being implemented separately. It has not landed on this branch or on `main` as of this report.

### CONFUSING

3. README lines 9–11 and 25. The first bench embeds every enabled model, not Granite alone: `embeddinggemma-2`, `granite-english-r2`, and `arctic-embed-l` (eval-only, lineage flagged unclear in the result table). Here that was 672s on a 3060, about 3.8 GB under the fresh cache once the ONNX files were added, plus an anonymous Hub warning. The README does not say GPU, network, disk, or time. CPU fallback was not timed. Fix: point the snippet at `--models granite-english-r2` and say the full bench downloads three models and wants a GPU.

4. README line 25. The quoted Granite hybrid figures (raw R@5 0.629, MRR@10 0.506, nDCG@10 0.558; `--dedupe` 0.614 / 0.497 / 0.546) are the 35-answerable-question run in `eval/results/2026-10-30.json`. This tree has 86 answerable questions (93 total). The same commands now print a different bench headline (raw hybrid_rrf R@5 0.285, MRR@10 0.219, nDCG@10 0.246; `--dedupe` 0.297 / 0.241 / 0.265). Those newer figures reproduce. They are the bench headline over all 86 answerable questions, including 30 LLM-written ones, on pre-grading labels. They are not pre-registered and not citable. Do not tell the README to quote them. Fix: drop the README retrieval figures, or use only the CTO pre-registered sentence from `docs/DEMO-SCRIPT.md:106` and `docs/SUBMISSION-DRAFT.md:33`, verbatim: "In a pre-registered evaluation (58 questions; relevance labels drafted with AI help, a subset confirmed blind by a human), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086)."

5. README line 11. The worked example is a question BM25 cannot answer ("worry" is not in the corpus). On this fresh index, hybrid is level `none` with abstain, and `search/query.py` prints the low-confidence note. It is not level `weak`. The gold sermon is rank 11 on `query.py`'s raw list, so `-k 5` and a `query.py` page of `k=10` both miss it (rank 10 is Wandering Thoughts). `/api/search` de-dups, and the gold sermon is result 10 there, so "outside the page default `k=10`" is true only of `query.py`. `Romans 8:16` returns the right sermon immediately on the BM25 fallback. Fix: change the sample question, or warn that this wording abstains (level `none`) and that `query.py` will not show the Sermon on the Mount in its first 10 rows, while the page's de-duped `/api/search` list places that sermon at result 10.

6. README line 25. "Passages with no `start_s`" reads like an exception. After the documented steps it is every passage: `corpus/chunk_sermons.py` writes null timings, and `chunks_aligned.jsonl` is never built. Play links are `n/a`. The alignment command (`uv run align/wesley.py chunks`) and the audio ingest are not in the README. Fix: say the quickstart is text-only, and add the align step before promising a recording.

7. README line 14. Data "stay under `/cache`" and "Weights use `HF_HOME=/cache/huggingface`" are stated as facts. The code key is `PREACHED_CACHE` (default `/cache`), which then sets `HF_HOME`. README never says to create that directory or how to point it elsewhere. This sandbox can create a directory at `/`; a normal laptop often cannot, and the first command would die on `mkdir`. Fix: document `PREACHED_CACHE` and that the directory must exist and be writable.

8. README line 7. `eval/validate.py` is a silent 137s nested scan. A judge can easily take it for a hang. Fix: say it checks every graded quote against every chunk and prints nothing until it finishes.

9. README lines 5–12 then 19. `uv sync` after the bench uninstalls the 49 bench packages (0.619s), including torch. That matches the sentence that torch is not in the runtime set, and it surprises anyone who thinks the first block's install sticks. Fix: say the later `uv sync` drops the bench group.

10. README line 31. The church example omits `--privacy`, so it exits 2 before listing. The error does name `privacy.example.toml`. The URL `@channel` is not a channel a judge can import. Fix: add `--privacy privacy.example.toml` only as a shape, and say a real channel URL and a reviewed config are required before anything is indexed. The CTO did not reproduce this YouTube step (command-log row 11).

11. README lines 57–60. `<slug>` and `<toml>` are unquoted. Pasting the block into bash is a redirection (`slug: No such file or directory`) and never reaches Python. Fix: use `SLUG` and `privacy.toml`, quoted. The CTO did not reproduce these YouTube steps (command-log rows 12–13).

12. README lines 9–10. The bench writes `eval/results/2026-10-31.json` and `.md` (and the `-dedupe` pair) into the clone. They are untracked. `corpus/fetch_wesley.py` rewrites `corpus/catalog.json`; the bytes matched this time (sha256 `66b83ba7…`). Fix: say both are local outputs and that a changed CCEL file needs `--accept-new-text`.

13. No prerequisites section. A judge needs uv (the build pin is `uv_build>=0.13.6,<0.14`), Python `>=3.12,<3.14`, network, and a lot of disk. YouTube coverage calls `ffmpeg`, which the README never names. `deno` is only for tests, which the README also never names. Fix: one requirements line for uv, Python, network, disk, and ffmpeg if they will import audio.

### NIT

14. README line 3. "This branch builds the Wesley text corpus..." On `main`, after a clone, there is no feature branch. Fix: say "This repo builds..."

15. README line 16. "From this worktree:" Fix: say "From the clone:"

16. README line 62. "`src/preached/libraries.py`" is cited for the libraries exempt from redaction. That tuple is `("spurgeon", "edwards")` only. Wesley is a separate pipeline. Fix: say Wesley is built in, and that file lists Spurgeon and Edwards.

17. README line 25. "Excerpts on the page hide CCEL paragraph numbers." The riches hit lost a leading "8." The Romans 8:16 hit still shows "1." after the verse (`Rom. 8:16 1. How many...`), which the strip regex does not treat as a paragraph number. Fix: extend the strip so a number after a verse reference is hidden too.

18. README does not document a test command or a pass/skip count. The file it points at for commands, `reports/W3-CPU.md` line 19 and the block at line 31, says 172 tests and `cd /work/preached/.worktrees/feat/w3-cpu`, a path this clone does not have. `uv run python -m unittest discover -s tests` on this tree collected 996 tests in 223.962s. The CTO did not reproduce that count. With `PREACHED_ONNX_DIR` on the fresh export: `FAILED (failures=3, errors=2)`, no `skipped=` clause. All five are the pin refusal (`test_cached_fp32_and_tokenizer_match_the_pins`, two load errors, the YouTube ONNX import guard, and `test_sigterm_under_hybrid_load_exits_zero_and_cleans_up`). This run still saw the prebuilt `/cache` index, `/cache/asr-repro`, and deno, so it does not measure skips on a machine that lacks those. Fix: put the discover command in the README and drop the 172 figure.

## Links and paths

Every relative path and Markdown link in the README exists on this `main`: `reports/W1-B.md`, `eval/README.md`, `reports/W3-CPU.md`, `src/preached/search.py` (`api_search` is defined; `SEARCH_POOL` is 100; hybrid RRF `k` is 60), `reports/W2-A.md`, `reports/W1-CLI.md`, `reports/W1-C.md`, `docs/DEPLOY.md`, `src/preached/libraries.py`, `reports/W3-PRIV-WIRE.md`, `reports/W3-SIDE.md`, `LICENSE`, `NOTICE`, `ingest/manifest/{wesley,spurgeon,edwards}.provenance.json`, `search/models.toml`, `privacy.example.toml`, `reports/W3-PRIV-SKIP.md`, `import/sermon_windows.example.toml`, `reports/W2-YT.md`, and the scripts in the code blocks.

`https://ccel.org/ccel/wesley/sermons`, `https://librivox.org/`, and `https://archive.org/` returned HTTP 200. `creativecommons.org/licenses/publicdomain/` (named in prose, not a Markdown link) returned 301.

Checked in code and not wrong: chunk overlap 0.25, client caps described as 4 and 4, `Retry-After: 1` is the constant the README states (not exercised under load), `uv sync` really does install numpy, onnxruntime, and tokenizers and not torch. The 0.870 word-recall figure is in `reports/W3-PRIV-SKIP.md` (635/730) and was not re-measured.

## CTO review round 2 (PR #68)

Corrections above replace the earlier wording. They follow the CTO's review. This round did not re-run the walkthrough.

Line numbers. Every "README line N" is `e552cfd`'s README (the `main` this branch was cut from). Later commits have edited that file. A line number checked against today's `main` can point at a different sentence.

Finding 2. The fresh export's sha256 is a function of torch's ATEN CPU dispatch level, and the export is deterministic run-to-run. The earlier fix (re-pin to `aed7adba…`, or stop refusing the exporter's bytes) is wrong: that hash is `ATEN_CPU_CAPABILITY=avx2`, the pin `3861025a…` is AVX512 (this box's default, reproduced twice), and `default` gives `d99ba823`. Re-pinning to `aed7adba…` would break every AVX512 host. The two graphs are functionally identical (134 initializers byte-identical; 6 nodes differ; ORT outputs bitwise identical; the same response and embedding hashes on all 93 questions). The fix the CTO ruled, which this PR does not contain: export pins `ATEN_CPU_CAPABILITY=avx2` before importing torch, and the pin moves once, with an ADR. That change is being implemented separately and had not landed when this section was written.

Finding 4. The replacement figures this report used to recommend (R@5 0.285, MRR 0.219, nDCG 0.246; dedupe 0.297 / 0.241 / 0.265) reproduce, and they stay out of the README. They are the bench headline over all 86 answerable questions, including 30 LLM-written ones, on pre-grading labels. They are not pre-registered and not citable. The README should drop its retrieval figures or quote the pre-registered sentence at `docs/DEMO-SCRIPT.md:106` and `docs/SUBMISSION-DRAFT.md:33`.

Finding 1. The quickstart fix names a bench sync plus the export, the dispatch caveat, `setdefault` of `HF_HOME`, and `rmtree(artifact_dir())`.

Worry query. "Outside the page default `k=10`" is `search/query.py` only (no de-dup; gold at rank 11). `/api/search` de-dups, and the gold sermon is result 10. On the fresh index the worry query is level `none` with abstain, not `weak`.

Not reproduced by the CTO: the 996-test count in finding 18, and the YouTube steps in command-log rows 11–13 (findings 10 and 11). Those remain this walkthrough's notes.
