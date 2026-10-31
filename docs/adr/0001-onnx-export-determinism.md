# ADR 0001: The ONNX export is pinned at avx2 dispatch and a fixed hash seed

Status: accepted, 2026-10-31. Tasks 96-W4-ONNX-AVX2-PIN and 96-W4-ONNX-MATRIX. Evidence is in `reports/W4-ONNX-PIN-REPRO.md`.

## Context

`src/preached/artifacts.py` pins the sha256 of `model.fp32.onnx`, and the runtime refuses any other graph. A fresh clone runs `scripts/export_onnx.py` to build that graph, so the export must write the same bytes on every supported host. It did not. Different hosts produced `3861025a…` (the 2026-10-30 pin), `aed7adba…` or `d99ba823…`.

**Both** of these variables move the bytes. Neither changes the weights. They act independently: the hash seed picks the order of the rotary tables, and the dispatch level picks the values in them.

1. **`PYTHONHASHSEED`: the rotary trace order.** transformers 5.22.1 ModernBERT loops `for layer_type in set(self.config.layer_types)` and calls `rotary_emb` once per type. A set of two strings iterates in hash order, so the two tables trace in one of two orders. The two orders swap the θ=10000 and θ=80000 Constants and rewire four `Unsqueeze` inputs (6 of 3009 nodes).
2. **`ATEN_CPU_CAPABILITY`: torch's ATen CPU dispatch level.** The rotary `inv_freq` tables are computed while the graph is traced and stored as Constants, using whichever vector kernel torch dispatched. Between `default` and `avx2`, one float32 of a 32-value table differs, by 1.5e-11. All 134 initializers are byte-identical.

### Matrix, measured 2026-10-31

Host: i9-12900K (AVX2, no AVX512), CPython 3.12.16, torch 2.15.0, transformers 5.22.1, onnx 1.23.2.

**Raw export** (the script's model load and `torch.onnx.export` call, without its overrides), fp32 sha256:

| `PYTHONHASHSEED` | `set()` order | `default` | `avx2` | `avx512` |
| --- | --- | --- | --- | --- |
| 0 | full, sliding | `d99ba823…d63a` | `aed7adba…5b78` | cannot run |
| 1 | sliding, full | `44038d45…2487` | `3861025a…8fa9` | cannot run |
| 2 | sliding, full | `44038d45…2487` | `3861025a…8fa9` | cannot run |
| 3 | full, sliding | `d99ba823…d63a` | `aed7adba…5b78` | cannot run |
| 4 | full, sliding | `d99ba823…d63a` | `aed7adba…5b78` | cannot run |
| 5 | full, sliding | `d99ba823…d63a` | `aed7adba…5b78` | cannot run |

The 12 cells that ran give four digests, one for each (order, dispatch) pair. The six `avx512` cells cannot run on this CPU. torch does not clamp the requested level to what the CPU supports. `get_cpu_capability()` reports `AVX512`, and the export dies with SIGILL (exit 132). The CTO measured AVX512 on another host. That case is not verified here.

**Through `scripts/export_onnx.py`**, with the ambient environment set as in each cell: all **18 of 18** cells (avx512 included) exit 0 and write `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`, with byte-identical manifests (so int8 matches too). The script's own settings yield a single, stable digest.

## Decision

- **Dispatch.** `scripts/export_onnx.py` sets `ATEN_CPU_CAPABILITY=avx2` at module top, before torch is imported, and this overrides any ambient value. After the import it checks `torch.backends.cpu.get_cpu_capability() == "AVX2"`. It refuses to run on a host that is not x86-64 or whose CPU flags lack `avx2`, exiting non-zero with a message that names AVX2.
- **Hash seed.** String hashing is fixed when the interpreter starts, so the seed cannot be set from inside the running process. The script therefore re-executes itself (`os.execv`) under `PYTHONHASHSEED=0` before it imports torch. It does this unless the seed is already `0` and hash randomization is off: `-R` keeps hashing random even under seed 0. Before tracing, it also refuses unless `set(config.layer_types)` iterates `["full_attention", "sliding_attention"]`. That is sorted order, the order an upstream `sorted(set(...))` fix would produce.
- **Pin.** One value: `FP32_ONNX_SHA256 = aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`. It is set only after the matrix showed it is the single digest under the script's settings. The tokenizer pin is unchanged. The export exits non-zero, before it writes a manifest, if its graph is not the pin. `docs/DEPLOY.md` cites the same value.
- **Tests.** `tests/test_onnx_pin_repro.py`:
  - It runs the real exporter twice, varying the ambient environment. Run a uses `PYTHONHASHSEED=1` with `ATEN_CPU_CAPABILITY=default`. Unfixed, that traces `44038d45…`. Run b uses `PYTHONHASHSEED=3` with `ATEN_CPU_CAPABILITY=avx512`. The test asserts the two fp32 graphs are byte-identical, equal the pin, and have identical manifests. It skips only when the Granite weights are not in `PREACHED_CACHE`.
  - `HashSeedReexecTests` checks that every other ambient seed restarts under seed 0: unset, `random`, 1-5, and `-R` with seed 0.
- No semantic digest, and no committed graph.

## Equivalence of the new pin to the old

Re-measured 2026-10-31 (`reports/W4-ONNX-PIN-REPRO.md` §4; output `/cache/w4-onnx-matrix/equiv.json`). It compares `3861025a…` (the 2026-10-30 graph in `/cache/models/granite-english-r2-onnx`) with `aed7adba…` (the matrix's avx2 / seed 0 export by the script):

| Check | Result |
| --- | --- |
| Header (ir, opset, producer) | equal |
| Initializers | 134 / 134 byte-identical |
| Nodes | 3009 each; 6 differ (`rotary_emb/Constant_1`, `rotary_emb_1/Constant`, `layers.{0,1}/attn/Unsqueeze_{2,3}`) |
| ORT CPU, 1 thread: all 93 `eval/questions.jsonl` queries, 21 corpus chunks (`rowid % 419 = 1`) | bitwise identical, max abs diff 0.0 |
| `App.search(q, 10, "hybrid")` on `/cache/index/wesley.sqlite`, all 93 questions | top-10 identical 93 / 93; every hash below equal under both graphs |

The CTO's harness reported `20bf48af596a4d4d` (responses) and `73463e64b1ce508a` (embeddings), unchanged across the two graphs. That harness and its hash definitions are not in the repo or `/cache`. I tried five definitions: responses as sorted-key JSON, the same compact, top-10 chunk ids, float32 query vectors, and query plus document vectors. Each is identical across the two graphs (for example `f66c732275af497f` and `29b07255a0733b1f`). None equals the CTO's literal values. So the claim "unchanged" is re-measured and holds. The literal hashes are not reproduced.

## Consequences

- An existing `/cache` export of `3861025a…` is refused once this pin lands. The server starts BM25 only and says so in the log. `/healthz` then reports `search_mode: "bm25"` with `search_mode_reason: "model_unavailable"`, or `"onnx_graph_not_built"` if no graph is present. After merge, re-run `CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py` on every box. Stored passage vectors do not need rebuilding, because the outputs are bitwise identical.
- Export hosts must be x86-64 with AVX2. ARM hosts can still *run* the server with a graph exported elsewhere.
- The order fix relies on CPython 3.12's seeded string hash. If a future interpreter maps seed 0 to another order, the export stops with a clear message instead of writing a wrong graph. The lasting fix is upstream `sorted(set(...))`.
- A torch, transformers or onnx version other than the one in `uv.lock` may trace another graph. The export refuses it and never re-pins.
