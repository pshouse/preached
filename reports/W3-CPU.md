# W3-CPU: lean CPU runtime for Granite English R2

Branch `feat/w3-cpu`. The server embeds queries with ONNX Runtime on CPU. Torch is not installed by `uv sync`. The picked variant is fp32. int8 is faster and smaller, and it misses the quality bar.

CPU for every measurement: 12th Gen Intel Core i9-12900K (8 P-cores with SMT, 8 E-cores, 24 logical CPUs). `CUDA_VISIBLE_DEVICES=""` on every command. The GPU was not used.

Pinned model: `ibm-granite/granite-embedding-english-r2` revision `47ea694b257b703fee9253d75c2b1f2985180498`. Recorded in `src/preached/artifacts.py` and in the on-disk manifest. `trust_remote_code` is false in export and at runtime. Pooling is CLS (`1_Pooling/config.json`: CLS on, mean and max off), then L2 norm, hidden size 768, max length 8192. Granite has no query or document prefix, and `is_question` still runs the same way as the torch path.

## What was done

- Exported the encoder to ONNX (opset 18, legacy tracer, dynamic batch and sequence, output `last_hidden_state`). Pooling and L2 norm stay in numpy (`preached.pooling`), matching the sentence-transformers path.
- Dynamic int8 quantization of that graph (`QuantType.QInt8`, per-channel, `MatMulConstBOnly`).
- Runtime loader checks the manifest sha256 of every file and falls back to BM25 with the existing note if anything is missing or mismatched. It does not download and it does not crash.
- Embedder interface: `encode_queries` / `encode_documents` return float32 L2-normalized vectors. `--embed-backend onnx|torch`, default `onnx`. Torch is imported only when that backend is selected.
- Tokenizer is `tokenizers` plus the pinned `tokenizer.json`. Ids and attention masks match the transformers tokenizer on all 8,383 chunk texts and all 40 eval queries (0 mismatches, 3.3 s).
- Re-embedded copies live under `/cache/index/` and do not replace `wesley.sqlite`.
- `search/bench.py` takes `--embed-backend`, `--onnx-variant`, `--ort-threads`, and `--index`. ONNX refuses to write into the shipped `wesley.sqlite`.

118 tests, `python -m unittest discover -s tests`, all passing. That includes backend selection, manifest sha256 refusal, BM25 fallback, CLS pooling, the fixture tokenizer (truncation, padding, mask), the import guard (`app.server` and `preached.search` do not load `torch`), the API field list, and a real fp32 ONNX query when the artifacts are present.

## How to run

From `/work/preached/.worktrees/feat/w3-cpu`.

Runtime (no torch, no NVIDIA wheels):

```bash
uv sync
uv run app/server.py
uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
uv run python -m unittest discover -s tests
```

`default-groups` is empty, so `uv sync` and `uv sync --no-default-groups` install the same set. Optional flags: `--embed-backend onnx|torch`, `--onnx-variant fp32|int8`, `--ort-threads N`. The same knobs are `PREACHED_EMBED_BACKEND`, `PREACHED_ONNX_VARIANT`, and `PREACHED_ORT_INTRA_OP_THREADS`. Artifacts default to `/cache/models/granite-english-r2-onnx/<revision>/` (`PREACHED_ONNX_DIR` overrides the root).

Export and quantize (bench group, CPU, writes the manifest):

```bash
CUDA_VISIBLE_DEVICES="" uv sync --group bench
CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py
```

Benchmark the ONNX index (bench group, because `search/bench.py` records the torch environment even when the embedder is ONNX):

```bash
CUDA_VISIBLE_DEVICES="" uv run --group bench search/bench.py \
  --models granite-english-r2 \
  --embed-backend onnx --onnx-variant fp32 --ort-threads 1 \
  --index /cache/index/wesley-onnx-fp32.sqlite
```

`--dedupe` scores the `/api/search` list. API latency, RSS, and cold start:

```bash
CUDA_VISIBLE_DEVICES="" uv run python scripts/bench_api.py \
  --embed-backend onnx --onnx-variant fp32 --ort-threads 1 --repeats 3 \
  --index /cache/index/wesley-onnx-fp32.sqlite
```

Parity checkpoints are `/cache/w3-cpu/`. `scripts/measure_parity.py` resumes ONNX document encodes and does not recompute the torch document matrix already stored in `/cache/index/wesley-torch-cpu.sqlite`.

CPU-torch control venv used for the reference numbers (not the runtime install):

```bash
uv venv /cache/venvs/w3-torch-cpu
uv pip install --python /cache/venvs/w3-torch-cpu/bin/python \
  'torch==2.15.0+cpu' --index-url https://download.pytorch.org/whl/cpu
uv pip install --python /cache/venvs/w3-torch-cpu/bin/python 'sentence-transformers==6.2.0'
```

The bench group keeps the PyPI CUDA torch build for GPU benches of the other models. It is opt-in (`uv run --group bench`). The transcribe extra (`faster-whisper`, `av`, `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) came in with `origin/main` and is also opt-in (`--extra transcribe`).

## Pick

ONNX fp32. It matches the torch reference on every metric and every top-10. The runtime venv is 149 MiB instead of a torch install, and RSS is lower than both the W2-A CUDA-torch server and the CPU-torch control. int8 would win on size and latency, and its eval deltas are outside ±0.005 with a different top-10 on every answerable query.

| | Quality (hybrid RRF, raw top 10) | API hybrid p50 / p95 | RSS after load | Runtime install | Weights on disk | Complexity | Licenses |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ONNX fp32 (pick) | 0.629 / 0.506 / 0.558, identical to torch | 28 ms / 35 ms at 4 threads on the full chip; 56 ms / 68 ms at 1 thread on one CPU | 960 MiB | 149 MiB | 569 MiB ONNX + 3.4 MiB tokenizer | One ORT session, numpy pool | onnxruntime MIT; tokenizers Apache-2.0; numpy BSD-3-Clause |
| ONNX int8 | 0.600 / 0.462 / 0.530 (fails) | 16 ms / 21 ms at 4 threads | 348 MiB | same 149 MiB | 144 MiB ONNX | Dynamic quant on top of the fp32 export | same |
| CPU torch (control) | 0.629 / 0.506 / 0.558 | 37 ms / 50 ms | 1,073 MiB | 1,179 MiB venv (torch package 773 MiB) | 284 MiB safetensors | sentence-transformers | torch wheel Apache-2.0 AND BSD-3-Clause AND others; sentence-transformers Apache-2.0 |

W2-A's server, the previous runtime (CUDA torch wheel, CPU inference), was API p50 114 ms / p95 126 ms, RSS 1,507 MiB after load and 1,587 MiB after the 40 queries. That install held a 1.08 GiB torch package plus 2.96 GiB of NVIDIA libraries. The controlled comparison on this machine is the CPU-torch row above, not that 114 ms figure: a CPU wheel is already much faster than the number in W2-A. ONNX fp32 is a bit faster than that CPU wheel and smaller in RSS and on disk.

Default intra-op threads is 1 (`src/preached/artifacts.py`). Four threads on one pinned CPU made `/api/search` slower (134 ms p50), which is past the W2-A number. Set `PREACHED_ORT_INTRA_OP_THREADS=4` on a machine with several cores (28 ms p50 here).

## Parity

Reference is sentence-transformers fp32 on CPU, same revision. Cosine is the dot product of L2-normalized vectors. p01 is nearest-rank (`ceil(0.01 * n) - 1` on the sorted scores).

| | n | min | mean | p01 |
| --- | --- | --- | --- | --- |
| fp32 documents | 8,383 | 0.99999988 | 1.000 | 0.99999994 |
| fp32 queries | 40 | 0.99999994 | 1.000 | 0.99999994 |
| int8 documents | 8,383 | 0.924 | 0.958 | 0.940 |
| int8 queries | 40 | 0.956 | 0.971 | 0.956 |

fp32 passes the 0.999 floor. The same fp32 matrix against the shipped CUDA document vectors in `wesley.sqlite` has min cosine 0.99999988, so those stored vectors and the ONNX query vectors are interchangeable at fp32.

Tokenizer check: 8,383 chunks + 40 queries, truncation at 8192 including `[CLS]`/`[SEP]`, attention mask included. 0 mismatches. `reports/w3_parity.json`.

Document encode (batch 32, intra-op 8, this CPU): fp32 12.2 chunks/s (686 s), int8 17.5 chunks/s (479 s).

## Eval

35 answerable questions. Raw top 10 is what W1-B reported. Dedupe is top 100 then `dedupe_adjacent` to 10, which is what `/api/search` returns. Recall@5, MRR@10, nDCG@10.

| backend | mode | R@5 | MRR@10 | nDCG@10 | embed+search p50 / p95 |
| --- | --- | --- | --- | --- | --- |
| torch CPU | dense | 0.543 | 0.424 | 0.473 | 27.3 / 29.6 ms |
| torch CPU | hybrid RRF | 0.629 | 0.506 | 0.558 | 29.4 / 33.2 ms |
| ONNX fp32 | dense | 0.543 | 0.424 | 0.473 | 24.0 / 26.8 ms |
| ONNX fp32 | hybrid RRF | 0.629 | 0.506 | 0.558 | 26.1 / 30.5 ms |
| ONNX int8 | dense | 0.457 | 0.420 | 0.478 | 11.1 / 12.7 ms |
| ONNX int8 | hybrid RRF | 0.600 | 0.462 | 0.530 | 13.0 / 16.0 ms |
| torch CPU, dedupe | hybrid RRF | 0.614 | 0.497 | 0.546 | 29.8 ms p50 |
| ONNX fp32, dedupe | hybrid RRF | 0.614 | 0.497 | 0.546 | 26.4 ms p50 |
| ONNX int8, dedupe | hybrid RRF | 0.614 | 0.439 | 0.507 | 13.3 ms p50 |

Query latency above is embed plus search, warmup excluded, 40 queries × 3 repeats (n=120), intra-op 4 on the full chip for ONNX and `OMP_NUM_THREADS=4` for torch. Files: `eval/results/2026-10-30-w3cpu-torch-cpu.json`, `2026-10-30-w3cpu-onnx-fp32.json`, `2026-10-30-w3cpu-onnx-int8.json`, and the dedupe runs `2026-10-30-dedupe-w3cpu-torch-cpu.json`, `2026-10-30-dedupe-w3cpu-onnx-fp32.json`, `2026-10-30-dedupe-w3cpu-onnx-int8.json`. The names are descriptive so they do not collide with another branch's auto-numbered `2026-10-30-2`.

fp32 vs torch, raw and dedupe, dense and hybrid RRF: delta 0.000 on all three metrics, top-10 chunk ids identical on 35/35 answerable queries. Hybrid weighted matched as well (0.571 / 0.477 / 0.541, top-10 identical). There are no per-query differences to list for fp32.

int8 vs torch, raw hybrid RRF: R@5 −0.029, MRR@10 −0.044, nDCG@10 −0.027. Top-10 changed for all 35 answerable queries. Ten of those also moved a metric:

| query | what moved |
| --- | --- |
| k-witness-of-the-spirit | MRR 0.000 → 0.143, nDCG 0.000 → 0.333 |
| q-catholic-spirit | MRR 1.000 → 0.500, nDCG 1.000 → 0.631 |
| q-communion | MRR 0.167 → 0.143, nDCG 0.356 → 0.333 |
| q-heaviness | MRR 0.111 → 0.125, nDCG 0.301 → 0.315 |
| q-means | MRR 1.000 → 0.500, nDCG 1.000 → 0.631 |
| q-mourning | MRR 1.000 → 0.500, nDCG 1.000 → 0.631 |
| q-original-sin | R@5 1 → 0, MRR 0.500 → 0.143, nDCG 0.631 → 0.333 |
| q-perfection | MRR 0.333 → 0.500, nDCG 0.413 → 0.521 |
| q-self-denial | MRR 0.250 → 0.200, nDCG 0.431 → 0.387 |
| q-temptation | MRR 0.111 → 0.167, nDCG 0.301 → 0.356 |

The other 25 kept the same three metrics with a different top-10. Dedupe hybrid RRF happens to keep R@5 at 0.614 and still loses MRR@10 (−0.058) and nDCG@10 (−0.039), with every top-10 changed. int8 is not the runtime.

## Latency, RSS, install size, cold start

`/api/search` hybrid, k=10, 40 queries × 3 repeats, one warmup excluded. Cold start is process start through the first successful query, including model load. RSS is VmRSS.

| run | p50 | p95 | RSS after load | RSS after queries | cold start |
| --- | --- | --- | --- | --- | --- |
| W2-A CUDA-torch wheel, CPU inference | 114 ms | 126 ms | 1,580,302,336 (1,507 MiB) | 1,664,008,192 (1,587 MiB) | not recorded |
| ONNX fp32, 4 threads, full chip | 28.2 ms | 34.5 ms | 1,006,817,280 (960.2 MiB) | 1,020,723,200 (973.4 MiB) | 1.38 s |
| ONNX fp32, 1 thread, pinned to CPU 0 | 56.5 ms | 68.3 ms | 992,342,016 (946.2 MiB) | 1,000,296,448 (953.8 MiB) | 1.39 s |
| ONNX int8, 4 threads, full chip | 15.7 ms | 20.7 ms | 365,371,392 (348.4 MiB) | 379,912,192 (362.3 MiB) | 1.04 s |
| CPU torch, OMP 4 | 36.7 ms | 49.7 ms | 1,125,314,560 (1,073.2 MiB) | 1,142,693,888 (1,089.8 MiB) | 2.72 s |

Fresh runtime venv, `UV_PROJECT_ENVIRONMENT=/cache/w3-cpu/venv-runtime uv sync --frozen --no-default-groups`: 156,609,454 bytes (149.4 MiB) right after install. `uv pip list` has numpy 2.5.4, onnxruntime 1.31.1, tokenizers 0.23.3, and the libraries those pull in (huggingface-hub, hf-xet, httpx2, protobuf, flatbuffers, pyyaml, and their dependencies). No `torch`, no `nvidia-*`, no sentence-transformers, no Pillow. `uv tree` still names the transcribe extra because it is in the lock; those packages are not installed. Importing `app.server` and `preached.search` in that venv does not put `torch` on `sys.modules`.

Artifact directory `/cache/models/granite-english-r2-onnx/47ea694b257b703fee9253d75c2b1f2985180498/` is 716.1 MiB. The loader hashes every file in `manifest.json`, so the directory has to be complete:

| file | bytes | MiB |
| --- | --- | --- |
| model.fp32.onnx | 596,635,043 | 569.0 |
| model.int8.onnx | 150,685,319 | 143.7 |
| tokenizer.json | 3,583,228 | 3.4 |
| pooling.json | 150 | |
| manifest.json | 915 | |

The CPU-torch control venv is 1,236,401,126 bytes (1,179 MiB), including an onnxruntime install added so that venv could run the ONNX benches (about 63 MiB). The torch package itself is 773 MiB.

### Thread count

Embed + hybrid search, no HTTP, full chip, n=120:

| intra-op threads | fp32 p50 / p95 | int8 p50 / p95 |
| --- | --- | --- |
| 1 | 56.6 / 67.3 ms | 23.6 / 27.9 ms |
| 2 | 35.0 / 41.7 ms | 16.5 / 20.2 ms |
| 4 | 26.2 / 30.2 ms | 13.2 / 16.3 ms |

RSS barely moves with thread count (about 946–960 MiB for fp32).

Pinned `/api/search`, fp32, so a 1-vCPU or 2-vCPU Sprite can be read off a desktop. CPU 0 and CPU 2 are different P-cores. CPU 0 and CPU 1 are SMT siblings of one core and are not used as the two-core pair.

| pin | threads | p50 | p95 | RSS after load | cold start |
| --- | --- | --- | --- | --- | --- |
| 1 logical CPU | 1 | 56.5 ms | 68.3 ms | 946 MiB | 1.39 s |
| 1 logical CPU | 4 | 133.6 ms | 180.5 ms | 967 MiB | 2.62 s |
| 2 physical P-cores | 1 | 57.1 ms | 69.2 ms | 960 MiB | 1.42 s |
| 2 physical P-cores | 2 | 74.6 ms | 104.2 ms | 933 MiB | 1.40 s |
| 2 physical P-cores | 4 | 101.2 ms | 133.5 ms | 933 MiB | 1.77 s |

On these short queries, one thread beats two threads even with two cores available. Four threads on one CPU is the worst cell. The default is therefore 1. Raise it only after measuring on the Sprite's actual CPU count.

## Dependencies

Runtime, direct:

| package | version | why | license |
| --- | --- | --- | --- |
| numpy | 2.5.4 | pooling, L2, brute-force scores | BSD-3-Clause |
| onnxruntime | 1.31.1 | CPU execution of the exported encoder | MIT |
| tokenizers | 0.23.3 | `tokenizer.json` without transformers | Apache-2.0 |

tokenizers 0.23 requires `huggingface-hub`. The server loads `tokenizer.json` from disk and does not call the Hub. huggingface-hub brings httpx2, hf-xet, filelock, pyyaml, tqdm. That is the cost of the current tokenizers package. Removed from the runtime, relative to W2-A: torch, sentence-transformers, and the NVIDIA CUDA wheels.

Bench group (opt-in): `torch` (PyPI CUDA build 2.15.0), `sentence-transformers`, `onnx`, `onnxscript` (export), `pillow`, `torchvision` (EmbeddingGemma's processor imports). Pillow and torchvision were already bench-only. `onnx` and `onnxscript` are there so export does not live in the server install.

Transcribe extra, unchanged from main, opt-in: faster-whisper, av, nvidia-cublas-cu12, nvidia-cudnn-cu12. Not part of search.

`uv.lock` is committed. The runtime resolution does not install torch or any `nvidia-*` package. Confirmed with `uv pip list` in the fresh venv.

## What the Sprite task needs

- Copy the whole artifact directory, including `model.int8.onnx`. A missing or edited file fails the sha256 check and the server serves BM25 with the existing fallback note.
- Path: `/cache/models/granite-english-r2-onnx/47ea694b257b703fee9253d75c2b1f2985180498/` or set `PREACHED_ONNX_DIR` to the parent of the revision folder.
- Env: `PREACHED_EMBED_BACKEND=onnx` (the default), `PREACHED_ONNX_VARIANT=fp32` (the manifest default), `PREACHED_ORT_INTRA_OP_THREADS=1` (the default). Do not set 4 threads on a 1-vCPU Sprite.
- `CUDA_VISIBLE_DEVICES=""` if a GPU is visible. The session asks for `CPUExecutionProvider` only and refuses anything else.
- RSS after load was 946 MiB at 1 thread and 960 MiB at 4 threads on this box, with the 8,383-chunk index open. Plan about 1.2 GiB of headroom over a 58 MiB BM25 process so the model and the index fit. Cold start to the first query was 1.4 s.
- The shipped `/cache/index/wesley.sqlite` can stay. Its granite vectors match ONNX fp32 (min cosine 0.99999988). A same-backend copy is `/cache/index/wesley-onnx-fp32.sqlite` if the Sprite would rather not depend on that.
- Install with `uv sync` and do not pass `--group bench` or `--extra transcribe`.
- No Dockerfile in this task.

YouTube import (`feat/w2-youtube`, not on this branch) embeds in `src/preached/youtube/pipeline.py` `_embed_on_cpu`, which calls `preached.embed.load_model` and `encode_documents`. Swap that for `load_embedder("granite-english-r2", "onnx")` and `encode_documents(texts, titles)`. Granite's document template is empty, so titles are ignored, same as today. The returned matrix is float32 and L2-normalized, which is what `library.py` stores. That call does not import torch.

## Open issues

- int8 is exported and measured and is not the default. Another quantizer (static, or int8 only on the MatMuls that moved the rankings) would be a new experiment. The dynamic int8 graph stays in the artifact directory because the manifest hashes it.
- `search/query.py` and `search/bench.py` call `sync_chunks` against `chunks.jsonl`. The live `/cache/index/wesley.sqlite` was built from `chunks_aligned.jsonl` (same 8,383 texts and chunk ids, different `start_s` / `end_s`, hash `198339132f68…`). Running those commands against the live file will rebuild the chunks and delete embeddings. The server opens the index read-only and does not sync. This branch's eval copies use the `chunks.jsonl` hash, so benching them is safe. Text is identical, so the vectors match either file.
- The manifest requires the unused int8 file. A Sprite that only has room for the 569 MiB fp32 graph has to edit the manifest or the load falls back to BM25.
- huggingface-hub is installed because tokenizers requires it. The server never downloads.
- Default one thread is the safe Sprite setting. On this 24-thread CPU, four threads is the fast setting (26 ms embed+search p50). Measure again on the Sprite before raising it.
- Retrieval knobs (chunking, RRF k=60, adjacent-chunk dedupe) are unchanged.
- The bench group still resolves CUDA torch from PyPI so other models can be timed on the GPU later. That group must stay opt-in.
