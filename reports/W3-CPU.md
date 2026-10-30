# W3-CPU: lean CPU runtime for Granite English R2

Branch `feat/w3-cpu`. The server embeds queries with ONNX Runtime on CPU. Torch is not installed by `uv sync`. The picked variant is fp32. int8 is faster and smaller, and it misses the quality bar.

CPU for every measurement: 12th Gen Intel Core i9-12900K (8 P-cores with SMT, 8 E-cores, 24 logical CPUs). `CUDA_VISIBLE_DEVICES=""` on every command. The GPU was not used.

Pinned model: `ibm-granite/granite-embedding-english-r2` revision `47ea694b257b703fee9253d75c2b1f2985180498`. Recorded in `src/preached/artifacts.py` and in the on-disk manifest. `trust_remote_code` is false in export and at runtime. Pooling is CLS (`1_Pooling/config.json`: CLS on, mean and max off), then L2 norm, hidden size 768, max length 8192. Granite has no query or document prefix, and `is_question` still runs the same way as the torch path.

## What was done

- Exported the encoder to ONNX (opset 18, legacy tracer, dynamic batch and sequence, output `last_hidden_state`). Pooling and L2 norm stay in numpy (`preached.pooling`), matching the sentence-transformers path.
- Dynamic int8 quantization of that graph (`QuantType.QInt8`, per-channel, `MatMulConstBOnly`).
- Runtime loader checks the manifest sha256 of the selected graph, `tokenizer.json`, and `pooling.json`, then the pinned sha256 of `model.fp32.onnx` and `tokenizer.json`. A missing int8 file does not matter for fp32. A needed file that is missing or mismatched, or a swapped file whose manifest was rewritten, falls back to BM25. The session and the tokenizer are loaded from the bytes just hashed. The loader does not download and it does not crash.
- Embedder interface: `encode_queries` / `encode_documents` return float32 L2-normalized vectors. `--embed-backend onnx|torch`, default `onnx`. Torch is imported only when that backend is selected.
- Tokenizer is `tokenizers` plus the pinned `tokenizer.json`. Ids and attention masks match the transformers tokenizer on all 8,383 chunk texts and all 40 eval queries (0 mismatches, 3.3 s).
- Re-embedded copies live under `/cache/index/` and do not replace `wesley.sqlite`.
- `search/bench.py` takes `--embed-backend`, `--onnx-variant`, `--ort-threads`, and `--index`. ONNX refuses to write into the shipped `wesley.sqlite`.

172 tests, `python -m unittest discover -s tests`, all passing after the merge of `origin/main` (`af1c3de`, PR #7 and PR #9). That includes the earlier backend, pooling, tokenizer, and import-guard tests, plus fp32-without-int8, int8-absent fallback, a mismatched fp32 fallback, the pinned-digest refusal, a real fp32 load from a directory that has no int8 file, the null-timing refusal, read-only `query.py`, and the server reload when the chunk hash or embedding records change.

## How to run

From `/work/preached/.worktrees/feat/w3-cpu`.

Runtime (no torch, no NVIDIA wheels):

```bash
uv sync
uv run app/server.py
uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
uv run python -m unittest discover -s tests
```

`default-groups` is empty, so `uv sync` and `uv sync --no-default-groups` install the same set. Optional flags: `--embed-backend onnx|torch`, `--onnx-variant fp32`, `--ort-threads N`. The same knobs are `PREACHED_EMBED_BACKEND`, `PREACHED_ONNX_VARIANT`, and `PREACHED_ORT_INTRA_OP_THREADS`. `PREACHED_ONNX_VARIANT=int8` is refused. Artifacts default to `/cache/models/granite-english-r2-onnx/<revision>/` (`PREACHED_ONNX_DIR` overrides the root).

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

Artifact directory `/cache/models/granite-english-r2-onnx/47ea694b257b703fee9253d75c2b1f2985180498/` is 716.1 MiB. The loader hashes the selected graph plus `tokenizer.json` and `pooling.json`. int8 is not required for the fp32 server. The fp32 graph and the tokenizer are also pinned in `src/preached/artifacts.py` (`FP32_ONNX_SHA256`, `TOKENIZER_SHA256`). The on-disk fp32 file hashes to `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`, which matches that pin. The tokenizer hashes to `6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30`.

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

- Copy `model.fp32.onnx`, `tokenizer.json`, `pooling.json`, and `manifest.json`. `model.int8.onnx` is not required. A missing or edited file that the fp32 load needs fails the sha256 check and the server serves BM25 with the existing fallback note. A file that matches a rewritten manifest but not the pinned fp32 or tokenizer digest does the same.
- Copy `chunks_aligned.jsonl` and `chunks_aligned.source.json` with the corpus (`/cache/corpus/wesley/`). The live index was built from the aligned file. The server and `search/query.py` do not sync, so they will not rebuild it, and they also will not invent timings if that file was never loaded. `search/bench.py` and `search/build_index.py` still sync, and they refuse to replace stored timings with nulls.
- Path: `/cache/models/granite-english-r2-onnx/47ea694b257b703fee9253d75c2b1f2985180498/` or set `PREACHED_ONNX_DIR` to the parent of the revision folder.
- Env: `PREACHED_EMBED_BACKEND=onnx` (the default), `PREACHED_ONNX_VARIANT=fp32` (the manifest default), `PREACHED_ORT_INTRA_OP_THREADS=1` (the default). Do not set 4 threads on a 1-vCPU Sprite.
- `CUDA_VISIBLE_DEVICES=""` if a GPU is visible. The session asks for `CPUExecutionProvider` only and refuses anything else.
- RSS after load was 946 MiB at 1 thread and 960 MiB at 4 threads on this box, with the 8,383-chunk index open. Plan about 1.2 GiB of headroom over a 58 MiB BM25 process so the model and the index fit. Cold start to the first query was 1.4 s.
- The shipped `/cache/index/wesley.sqlite` can stay. Its granite vectors match ONNX fp32 (min cosine 0.99999988). A same-backend copy is `/cache/index/wesley-onnx-fp32.sqlite` if the Sprite would rather not depend on that.
- Install with `uv sync` and do not pass `--group bench` or `--extra transcribe`.
- No Dockerfile in this task.

YouTube import embeds through the same ONNX loader. See "Merge with #4" below. `_embed_on_cpu` calls `load_embedder("granite-english-r2", "onnx")` and `encode_documents(texts, titles)`. Granite's document template is empty, so titles do not change the encoded text. The matrix is float32 and L2-normalized, which is what `library.py` stores. That call does not import torch. Install the import tool with `uv sync --extra youtube`. Transcription is still `uv sync --extra transcribe`. Neither extra installs torch.

## Fix-up (CTO review of `7c6b330`)

Checked read-only against `/cache/index/wesley.sqlite` and the two chunk files. Nothing in this fix-up wrote to that index.

| item | commit | test |
| --- | --- | --- |
| Rename this branch's `2026-10-30-{2,3,4}` and `dedupe-{2,3,4}` results so they do not collide with main's `2026-10-30-2`. Main's `eval/results/2026-10-30-2.json` and `.md` are unchanged. `--tag` and `--out` on `search/bench.py` keep a later run from taking the next number. | `353c6d3` (rename), `ee6e29d` (`--tag` / `--out`) | `BenchOutputTests.test_tag_and_out_avoid_the_numbered_collision` |
| Merge `origin/main` (`af1c3de`, PR #7 and PR #9). No rebase. README keeps the ONNX runtime note and the W1-CLI timestamp sentence. `search/query.py` keeps the play URL, h:mm:ss, and `--embed-backend`. `search/bench.py` keeps `index_chunks_jsonl()` and the ONNX flags. `uv lock --check` passed; the lock was not regenerated. | `12eb566` | full suite, 172 tests |
| Verify only the selected graph, tokenizer, and pooling config. int8 is not on the fp32 runtime path. fp32 present and int8 absent loads. int8 selected and int8 absent falls back to BM25. A mismatched fp32 falls back. | `ee6e29d` | `ManifestTests.test_fp32_without_int8_verifies`, `test_listed_int8_is_not_required_for_fp32`, `test_int8_selected_without_the_file_is_refused`, `FallbackTests.test_int8_absent_falls_back`, `test_mismatched_fp32_without_int8_falls_back`, `RealOnnxTests.test_fp32_directory_without_int8_loads` |
| `query.py` opens the index read-only and does not sync. `sync_chunks` refuses to replace stored `start_s`, `end_s`, `audio_url`, or `reader` with nulls unless `force_null_timings=True` (`--force-null-timings` on bench and build_index). | `ee6e29d` | `PrerollTests.test_query_does_not_sync_or_write_the_index`, `InPlaceMetadataTests.test_null_timings_are_refused_unless_forced` |
| The server rechecks the chunk hash and the embedding meta, count, and byte size on each search and health request. A change reloads the rows and vectors. Missing or mismatched vectors fall back to BM25 until a later change brings them back. The weights stay loaded. | `ee6e29d` | `ServerTests.test_search_reloads_when_the_chunk_hash_or_embeddings_change` |
| Sprite steps copy `chunks_aligned.jsonl` and `chunks_aligned.source.json`. | `60efda7` | deploy text under "What the Sprite task needs" |
| Pin fp32 ONNX sha256 `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` and tokenizer sha256 `6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30`. Both match the `/cache` bytes, not only `manifest.json`. A self-consistent rewritten manifest is refused. | `ee6e29d` | `RealOnnxTests.test_cached_fp32_and_tokenizer_match_the_pins`, `ManifestTests.test_pinned_digest_refuses_a_rewritten_manifest` |
| int8 queries are not paired with non-int8 document vectors. No one-chunk re-embed at startup: the shipped vectors are fp32, and the default variant is fp32. | `ee6e29d` | `VariantPairingTests.test_int8_query_refuses_fp32_document_vectors` |
| `OnnxEmbedder.load` builds the ORT session and the tokenizer from the verified bytes (`InferenceSession` bytes, `Tokenizer.from_buffer`). | `ee6e29d` | `RealOnnxTests.test_fp32_directory_without_int8_loads`, `test_fp32_query_is_unit_normalized` |

Fresh runtime check after this fix-up: `UV_PROJECT_ENVIRONMENT=/cache/w3-cpu/venv-runtime-check uv sync --frozen --no-default-groups` installed 21 packages (numpy 2.5.4, onnxruntime 1.31.1, tokenizers 0.23.3, and the huggingface-hub stack). No `torch`, no `nvidia-*`, no `sentence-transformers`. Importing `app.server` and `preached.search` in that venv did not put `torch` on `sys.modules`.

## Merge with #4

Merged `origin/main` at `9c3e303` (no rebase). That is PR #4, YouTube import, at `23bc496`, plus PR #8, privacy, at `9c3e303`. Merge commit `59258b6`.

Conflicts were `app/server.py` and `uv.lock`. Everything else auto-merged, including `src/preached/store.py` (null-timing refusal and the privacy review-item refusal both stayed).

`app/server.py` keeps both sides. From this branch: the ONNX `default_loader`, `--embed-backend` / `--onnx-variant` / `--ort-threads`, per-request reload when the chunk hash or embedding records change, BM25 fallback, and the `/healthz` `backend` field. From main: `--library`, the index path `/cache/index/<slug>.sqlite`, `parse_search_args(..., library=app.library)`, sermon ids that are either a Wesley slug or an 11-character YouTube id, and the CSP string exactly as main has it (archive.org in `media-src`, no YouTube host). `pyproject.toml` keeps the runtime dependencies (numpy, onnxruntime, tokenizers), `default-groups = []`, the `bench` group, and main's `youtube` extra (`yt-dlp==2026.10.26`).

`uv.lock` was not hand-merged. It was replaced with `origin/main`'s lock and regenerated with `uv lock`. `uv lock --check` passed. Direct runtime dependencies are numpy, onnxruntime, and tokenizers. Torch, `nvidia-*`, and sentence-transformers stay in the opt-in bench group. yt-dlp stays in the youtube extra.

`_embed_on_cpu` in `src/preached/youtube/pipeline.py` no longer calls `preached.embed.load_model`. It calls `load_embedder("granite-english-r2", "onnx")` and `encode_documents(texts, titles)` (commit `0dba208`). The library writer still stores float32 L2-normalized blobs. The chunk columns, watch URL (`t=` is the stored start minus 0.75 s, truncated, never below 0), `text_source=asr`, and empty `reader` are unchanged.

Tests, `uv run python -m unittest discover -s tests`: 235 ran, 0 skipped, 0 failed. Main alone was 173 plus 3 skipped. The three `AppJsTests` ran here because deno is installed. The real fp32 checks ran because `/cache` has `model.fp32.onnx` (`ImportGuardTests.test_youtube_embed_path_does_not_import_torch`, `RealOnnxTests.test_fp32_directory_without_int8_loads`, `test_fp32_query_is_unit_normalized`, `test_cached_fp32_and_tokenizer_match_the_pins`). The new YouTube guard encodes two passages in a subprocess: shape `(2, 768)`, dtype `float32`, L2 norm 1, and `torch` is not in `sys.modules`. `ImportTests.test_server_reloads_youtube_library_and_falls_back` serves a fixture library over HTTP (watch URL, `asr`, library `sample`, `backend` null while BM25), then reloads the text when `chunks_sha256` changes and falls back to BM25 with the stale-vector note when the embedding rows are deleted. No YouTube download and no network in the tests.

Fresh environments under `/cache/w3-cpu/`, not the shipped index:

- `UV_PROJECT_ENVIRONMENT=/cache/w3-cpu/venv-merge2-runtime uv sync --frozen --no-default-groups` installed 21 packages. No `torch`, no `nvidia-*`, no `sentence-transformers`. In that interpreter, `app.server`, `preached.search`, and `_embed_on_cpu` did not import torch. Two passages came back `(2, 768)` float32 with L2 norm 1 (load 2.7 s, encode 0.2 s).
- `UV_PROJECT_ENVIRONMENT=/cache/w3-cpu/venv-merge2-youtube uv sync --frozen --extra youtube --no-default-groups` installed those 21 plus `yt-dlp==2026.10.26`. Still no torch.

No new dependency. yt-dlp was already justified on main: the stdlib cannot speak YouTube's player.

## Open issues

- int8 is exported and measured and is not the default. Another quantizer (static, or int8 only on the MatMuls that moved the rankings) would be a new experiment. The dynamic int8 graph can stay next to the fp32 graph. The fp32 server does not hash it and does not require it.
- The live-index timing wipe is closed. `/cache/index/wesley.sqlite` records `chunks_sha256` `198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2`, which is `/cache/corpus/wesley/chunks_aligned.jsonl`. All 8,383 rows have `start_s`, `audio_url`, and `reader`. `chunks.jsonl` (`110dd519…`) has the same chunk ids, titles, scripture, and text, and null `start_s`, `audio_url`, and `reader` on every row. With the aligned file present, `index_chunks_jsonl()` selects it and a sync is a hash no-op, so bench and build_index do not rebuild and do not delete embeddings. If that file is absent, those commands now raise `NullTimingRefused` instead of nulling the 8,383 timings. `query.py` does not sync. This was checked by reading the index with `mode=ro` and comparing the two JSONL files. Nothing wrote to `wesley.sqlite`.
- The fp32 server no longer requires the int8 file. A mismatched or missing file that fp32 does need still falls back to BM25.
- huggingface-hub is installed because tokenizers requires it. The server never downloads.
- Default one thread is the safe Sprite setting. On this 24-thread CPU, four threads is the fast setting (26 ms embed+search p50). Measure again on the Sprite before raising it.
- Retrieval knobs (chunking, RRF k=60, adjacent-chunk dedupe) are unchanged.
- The bench group still resolves CUDA torch from PyPI so other models can be timed on the GPU later. That group must stay opt-in.

## Merge with #11

Merged `origin/main` at `6a16b1f` (no rebase). That is PR #11, W3-POLISH, the abstain floor. Merge commit `d4f513d0b63133df2f6d55fe7b1d398d91e6f0a5`. Parents are `abbf735` (this branch) and `6a16b1f`.

Conflicts were `app/server.py`, `search/bench.py`, and `search/query.py`. `uv.lock` merged clean. It and `pyproject.toml` had changed only on this branch since the merge base `9c3e303`. `uv lock` and then `uv lock --check` each resolved 79 packages. `git diff uv.lock` was empty after both.

`app/server.py` keeps both sides. From this branch: the ONNX default loader, `--embed-backend` / `--onnx-variant` / `--ort-threads`, the per-request reload, the BM25 fallback, and the `/healthz` `backend` field. From main: `search_with_confidence`, the `confidence` and `abstain` payload fields, `chunk_ids` on each hit, and the low-confidence page. `src/preached/search.py` (dedupe of overlapping neighbours, `Hit.chunk_ids`) auto-merged. `build_app` looks up `floor_for` on the encode callable's backend and variant. A missing backend attribute still means torch, so an older caller keeps the torch floor. The app stores that floor and puts it back when a reload still has vectors. A reload that falls back to BM25 clears it. `/healthz` adds `abstain_calibrated`.

`search/bench.py` keeps `--embed-backend` (default torch), `--onnx-variant`, `--ort-threads`, `--index`, `--latency-repeats`, `--allow-cached`, `--tag`, `--out`, `--force-null-timings`, and main's `--abstain` / `--write-calibration`. `--write-calibration` upserts the row for this (model, backend, variant) and leaves every other row.

`search/query.py` keeps the read-only index, the play URL, h:mm:ss, and `--embed-backend` / `--onnx-variant` / `--ort-threads`. It also keeps #11's default: low-confidence hits stay on the page under the banner, and `--hide-low-confidence` hides them. The floor is the one for the loaded embedder's backend and variant. BM25 mode skips it.

The calibration file is a TOML array of tables, one `[[models]]` row per (model, backend, variant). #11 allowed one table per model, and every shipped row was torch/fp32, so the ONNX default server resolved no floor and never marked a hit low-confidence. A bad file still logs a warning and returns no floors. The server stays up. A duplicate (model, backend, variant) disables that combo. `dense_floor` has to be a finite cosine in [-1, 1]. `1` and `-1` are valid. `+inf`, `nan`, a string, and a value outside that range are not. Loading never raises.

Granite ONNX fp32 was fitted with the existing bench command. The index was a copy, `/cache/w3-cpu/wesley-onnx-fp32-merge11.sqlite`, taken from `/cache/index/wesley-onnx-fp32.sqlite`. `/cache/index/wesley.sqlite` is still mtime 2026-10-30 13:21:53, 189042688 bytes. The source ONNX file is still mtime 13:10:32, 189050880 bytes. `ensure_chunks` updated metadata on the copy only (194768896 bytes, 14:35).

```bash
cd /work/preached/.worktrees/feat/w3-cpu
CUDA_VISIBLE_DEVICES="" uv run --group bench search/bench.py \
  --abstain --write-calibration --models granite-english-r2 \
  --embed-backend onnx --onnx-variant fp32 \
  --index /cache/w3-cpu/wesley-onnx-fp32-merge11.sqlite --tag w3cpu-merge11
```

| backend | in-sample floor | LOO precision | LOO recall | LOO floor range | in-sample recall |
| --- | --- | --- | --- | --- | --- |
| torch/fp32 (w3polish, `eval/results/2026-10-30-w3polish-abstain.md`) | 0.8129 | 1.000 | 0.600 | 0.7988–0.8129 | 0.800 |
| onnx/fp32 (this merge) | 0.8129 | 1.000 | 0.600 | 0.7988–0.8129 | 0.800 |

The committed cell is `dense_floor = 0.8129`. The markdown prints that cell as 0.813. EmbeddingGemma's torch floor stays 0.7413. Rows are in `search/abstain.toml`. Numbers are in `eval/results/2026-10-30-abstain-w3cpu-merge11.json` and `.md`. Those files name commit `abbf735` (dirty) because the bench ran before this merge commit, the same way #11's files name a pre-merge commit. False abstain is 0.000 on both. R@5 stays 0.657 and MRR@10 stays 0.540 when the floor abstains (an abstained answerable question counts as a miss, and LOO abstained none of them).

The same copy, with `--dedupe --tag w3cpu-merge11`, matches the granite quality cells in `eval/results/2026-10-30-w3polish-dedupe.md` (torch, API path). The corpus vectors were already cached (fingerprint matches). No re-embed.

| mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | CPU p50 this ONNX run |
| --- | --- | --- | --- | --- | --- |
| dense | 0.629 | 0.471 | 0.510 | 0.800 | 61.8 ms |
| hybrid_rrf | 0.657 | 0.540 | 0.590 | 0.971 | 64.3 ms |
| hybrid_weighted | 0.600 | 0.515 | 0.576 | 0.943 | 66.0 ms |

Bootstrap intervals on those four quality columns match the w3polish granite rows. CPU p50 is this ONNX run (the w3polish torch file records about 110–112 ms). Files: `eval/results/2026-10-30-dedupe-w3cpu-merge11.json` and `.md`.

```bash
CUDA_VISIBLE_DEVICES="" uv run --group bench search/bench.py \
  --models granite-english-r2 --embed-backend onnx --onnx-variant fp32 \
  --dedupe --tag w3cpu-merge11 \
  --index /cache/w3-cpu/wesley-onnx-fp32-merge11.sqlite
```

Tests: `uv run python -m unittest discover -s tests` ran 274 tests in 19.077 s, OK. The count after the #4 merge was 235. `DefaultServerFloorTests.test_default_configuration_resolves_a_floor` checks that the default server (onnx, fp32, `granite-english-r2`) resolves a floor, that int8 resolves none, and that `build_app` with that encode sets `health["abstain_calibrated"]` and `backend == "onnx"`. `ServerTests.test_floor_survives_reload_and_is_skipped_on_bm25_fallback` checks that the floor still abstains after a chunk-hash reload that keeps the vectors, and that deleting the embeddings falls back to BM25 with level unrated and `abstain_calibrated` false. `test_floor_of_one_is_a_cosine` accepts `1`. The bad-file list includes `+inf`.

Fresh runtime venv, separate from the worktree `.venv` (that one has the bench group's torch):

```bash
cd /work/preached/.worktrees/feat/w3-cpu
UV_PROJECT_ENVIRONMENT=/cache/w3-cpu/venv-merge11-runtime \
  uv sync --frozen --no-default-groups
```

That installed 21 packages: numpy 2.5.4, onnxruntime 1.31.1, tokenizers 0.23.3, and the huggingface-hub stack (anyio, click, filelock, flatbuffers, fsspec, h11, hf-xet, httpcore2, httpx2, huggingface-hub, idna, packaging, protobuf, pyyaml, tqdm, truststore, typing-extensions), plus preached 0.1.0 from this worktree. No torch, no `nvidia-*`, no sentence-transformers. Importing `app.server` and `preached.search` there left `torch` and `sentence_transformers` off `sys.modules`. onnxruntime loads when the embedder loads.

No new dependency. Direct runtime dependencies are still numpy, onnxruntime, and tokenizers. Torch stays in the opt-in bench group.

Run the calibrated server from this worktree with `uv sync` and `uv run app/server.py`. The default is onnx, fp32, `granite-english-r2`. `/healthz` reports `backend` `onnx` and `abstain_calibrated` true while the committed floor's fingerprints match `search/models.toml` and the query embedder.

Open on this merge: int8 has no floor, on purpose, because int8 moves the top cosine. The floor is still the W3-POLISH heuristic on five unanswerable questions, with LLM-written labels pending human review. `search/bench.py` still imports torch inside `environment()` on an ONNX run, so the bench command needs `--group bench`. The runtime install does not.

## Merge with #13

Merged `origin/main` at `e2ddbc7` (no rebase). That is PR #13, YouTube watch-URL play, plus the watch-URL parser fix-up. Merge commit `945a5bc`. Parents are `98b577d` (this branch) and `e2ddbc7`.

The only conflict was `search/query.py`, in the imports. `uv.lock` and `pyproject.toml` did not change on main since the #11 merge, so the lockfile was left as this branch has it. No `uv lock` regeneration.

`search/query.py` keeps this branch's read-only index (`open_readonly`, no `sync_chunks`), h:mm:ss, `--embed-backend` / `--onnx-variant` / `--ort-threads`, #11's low-confidence banner with `--hide-low-confidence`, and the onnx/fp32 floor via `floor_for`. It takes #13's play line: a validated `youtube_watch_url` is printed as stored (no extra `#t=`), and `check_audio_url` failures, including a parser `ValueError`, print `n/a (unsafe URL hidden)`. `app/static/app.js`, `app/static/app.css`, `src/preached/youtube/listing.py`, and the YouTube tests came in from main unchanged.

Tests, from this worktree:

```bash
cd /work/preached/.worktrees/feat/w3-cpu
uv run python -m unittest discover -s tests
```

280 tests ran in 19.011 s, 0 failed, 0 skipped. The count after the #11 merge was 274.

No new dependency. Direct runtime dependencies are still numpy, onnxruntime, and tokenizers.

## Round-2 fix-up

CTO review of PR #10, then a merge of `origin/main` at `4129646` (PR #15, YouTube source labels). Merge commit `5a9838b`. Parents are `48ed538` (this branch) and `4129646`. The only conflict was the import block in `app/server.py`. Both sides stayed: `EmbeddingMismatch`, `check_query_variant`, `index_stamp`, `open_readonly`, and `public_audio_url`. No rebase. `ModelSpec.fingerprint()` is unchanged, so the shipped `wesley.sqlite` fingerprint stays `13e0ed78bb32d86b`. `search/abstain.toml` is unchanged. There is still no int8 floor.

### fp32 file name is pinned (`8111066`)

`VARIANT_FILES` hard-codes `fp32` to `model.fp32.onnx`. `VARIANT_SHA256` pins that graph's digest by variant, not by the name the manifest writes. `resolve_variant` refuses a declared name that is not the hard-coded file, including when `enforce_pins` is false. `OnnxEmbedder` opens `VARIANT_FILES[chosen]`. An extra `variants.int8` key is ignored when `variants.fp32` is `model.fp32.onnx`. The real cache manifest still names `model.fp32.onnx` and still matches the pin.

int8 is not a runtime variant. It is gone from `VARIANTS` and from `--onnx-variant` on `app/server.py`, `search/query.py`, `search/bench.py`, and `scripts/bench_api.py`. The export script may still write `model.int8.onnx`. The server does not open it. `scripts/measure_parity.py` was left as it was.

A stored `embeddings` variant other than `fp32` is refused with `EmbeddingMismatch` (the BM25 note is `STALE_NOTE`). A missing variant is the shipped index and stays legal. A query variant other than `fp32` is refused too. `check_query_variant` runs in `default_loader` and again in `_reload_cached_index`.

Tests: `ManifestTests.test_fp32_cannot_be_redirected_to_another_file`, `ManifestTests.test_int8_is_not_a_runtime_variant`, `FallbackTests.test_redirected_fp32_serves_keyword_search` (keyword hit, mode `bm25`, `FALLBACK_NOTE`), `VariantPairingTests.test_non_fp32_index_fingerprint_is_refused`, `ServerTests.test_non_fp32_index_fingerprint_is_refused_on_reload`.

### Failed index read reloads on the next success (`8111066`)

`_capture_stamp` still returns `None` on any exception and keeps the last good stamp. The first failed read, or any later failed read, sets `_status_failed` and serves keyword search with `INDEX_READ_NOTE`. Weights stay loaded. The next successful read reloads cached rows even when the stamp equals the last good one, then clears the flag. A later success can restore dense search.

Test: `ServerTests.test_failed_index_read_reloads_on_the_next_success`.

### query.py prints one line (`8111066`)

`check_query_variant` sits in its own `try`. `EmbeddingMismatch` prints one `error:` line on stderr and exits 1. The traceback is not shown.

Test: `VariantPairingTests.test_query_variant_mismatch_is_one_line`.

### YouTube id length (`c035f87`)

`tests/test_youtube.py` used the 12-character id `samplevid001`. PR #15 rejects that. The reload test now uses `samplevid02`. `test_server_reloads_youtube_library_and_falls_back` covers it.

### Userinfo is not a source link (`8111066`)

`public_audio_url` and `safeUrl` drop a URL whose username or password is set, before the host is labeled. `https://evil.com@ccel.org` is not a CCEL link. A plain `https://ccel.org/...` URL still is. Same-origin userinfo is dropped too.

Tests: `ServerTests.test_hit_dict_audio_url_matches_the_page_allow_list` (also `user:pass@ccel.org` and `user:pass@archive.org`). `AppJsTests.test_url_rules` runs the page script under Deno: userinfo, user and password, audio userinfo, and same-origin userinfo are null; a CCEL URL without userinfo is kept; `renderCard` draws no text link and no CCEL label for `evil.com@ccel.org` or `user:pass@ccel.org`. The page was not opened in a browser.

### Checks

From this worktree:

```bash
cd /work/preached/.worktrees/feat/w3-cpu
uv lock --check
uv run python -m unittest discover -s tests
UV_PROJECT_ENVIRONMENT=/cache/w3-cpu/venv-round2-runtime \
  uv sync --frozen --no-default-groups
```

`uv lock --check` exited 0 (resolved 79 packages). The lockfile was not regenerated.

288 tests ran in 18.458 s, 0 failed, 0 skipped. The count after the #13 merge was 280.

The fresh runtime venv is `/cache/w3-cpu/venv-round2-runtime`, separate from the worktree `.venv` (that one has the bench group's torch) and from `/cache/w3-cpu/venv-merge11-runtime`. `uv sync --frozen --no-default-groups` installed 21 packages: numpy 2.5.4, onnxruntime 1.31.1, tokenizers 0.23.3, and the huggingface-hub stack (anyio, click, filelock, flatbuffers, fsspec, h11, hf-xet, httpcore2, httpx2, huggingface-hub, idna, packaging, protobuf, pyyaml, tqdm, truststore, typing-extensions), plus preached 0.1.0 from this worktree. No torch, no `nvidia-*`, no sentence-transformers. Importing `app.server` and `preached.search` there left `torch` and `sentence_transformers` off `sys.modules`. onnxruntime loads when the embedder loads.

No new dependency. Direct runtime dependencies are still numpy, onnxruntime, and tokenizers.

The historical int8 eval rows above stay. They record why int8 was not picked. Operators pass `--onnx-variant fp32` only.

