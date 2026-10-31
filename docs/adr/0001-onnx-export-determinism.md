# ADR 0001: The ONNX export is pinned at avx2 dispatch and a fixed rotary order

Status: accepted, 2026-10-31. Task 96-W4-ONNX-AVX2-PIN; evidence in `reports/W4-ONNX-PIN-REPRO.md`.

## Context

`src/preached/artifacts.py` pins the sha256 of `model.fp32.onnx`, and the runtime refuses any other graph. A fresh clone runs `scripts/export_onnx.py` to build that graph, so the export must write the same bytes on every supported host. It did not: hosts produced `3861025a…` (the 2026-10-30 pin), `aed7adba…` or `d99ba823…`.

Two inputs move the bytes. Neither changes the weights.

1. **torch's ATen CPU dispatch level (`ATEN_CPU_CAPABILITY`).** The rotary `inv_freq` tables are computed while the graph is traced and stored as Constants, using whichever vector kernel torch dispatched. Measured on an AVX2-only i9-12900K, rotary order held fixed: `default` dispatch gives `d99ba823…`, and `avx2` gives `aed7adba…`. The two graphs differ in **one** node (`/inner/rotary_emb/Constant_1`): one float32 of the 32-value table differs, by 1.5e-11. All 134 initializers are byte-identical. AVX512 hosts dispatch to AVX512 by default, so they trace a third value set. The CTO reproduced that case; this host has no AVX512.
2. **The rotary trace order (`PYTHONHASHSEED`).** transformers 5.22.1 ModernBERT loops `for layer_type in set(self.config.layer_types)` and calls `rotary_emb` once per type. A two-string set iterates in hash order, so the two tables trace in one of two orders. Measured at `ATEN_CPU_CAPABILITY=avx2`, CPython 3.12.16: seeds 0 and 3 give `aed7adba…`, and seeds 1 and 2 give `3861025a…`. The two orders swap the θ=10000 and θ=80000 Constants and rewire four `Unsqueeze` inputs (6 of 3009 nodes).

Fixing the dispatch level alone therefore leaves a coin flip per run.

## Decision

- `scripts/export_onnx.py` sets `ATEN_CPU_CAPABILITY=avx2` before torch is imported. It checks `torch.backends.cpu.get_cpu_capability() == "AVX2"` after import. It refuses (non-zero exit, a message naming AVX2) to run on a host that is not x86-64 or whose CPU flags lack `avx2`.
- It re-executes itself under `PYTHONHASHSEED=0` and refuses to trace unless `set(config.layer_types)` iterates `["full_attention", "sliding_attention"]`. That is sorted order, the order an upstream `sorted(set(...))` fix would produce.
- The pin is re-pinned **once** to the avx2 export: `FP32_ONNX_SHA256 = aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`. The tokenizer pin is unchanged. The export exits non-zero, before writing a manifest, if its graph is not the pin.
- `tests/test_onnx_pin_repro.py` runs the real exporter twice. One run starts under `PYTHONHASHSEED=1` with `ATEN_CPU_CAPABILITY=default`, the other under seed 3. The test asserts the two fp32 graphs are byte-identical, equal the pin, and have identical manifests (so int8 matches too). It skips only when the Granite weights are not in `PREACHED_CACHE`.
- No semantic digest, and no committed graph.

## Equivalence of the new pin to the old

Measured 2026-10-31 by `/tmp/onnxtools/equiv.py` (not committed; output `/cache/w4-onnx-avx2/equiv.json`). It compares `3861025a…` (the 2026-10-30 graph in `/cache/models/granite-english-r2-onnx`) with `aed7adba…` (a fresh avx2 export):

| Check | Result |
| --- | --- |
| Header (ir, opset, producer) | equal |
| Initializers | 134 / 134 byte-identical |
| Nodes | 3009 each; 6 differ (`rotary_emb/Constant_1`, `rotary_emb_1/Constant`, `layers.{0,1}/attn/Unsqueeze_{2,3}`) |
| ORT CPU, 1 thread: all 93 `eval/questions.jsonl` queries, 21 corpus chunks (`rowid % 419 = 1`) | bitwise identical, max abs diff 0.0 |
| Search harness: `App.search(q, 10, "hybrid")` on `/cache/index/wesley.sqlite` for all 93 questions | top-10 identical 93 / 93; response hash (`took_ms` dropped) `f66c732275af497f` under both graphs; query-embedding hash `29b07255a0733b1f` under both graphs |

The CTO's harness reported `20bf48af596a4d4d` (responses) and `73463e64b1ce508a` (embeddings) as unchanged across the two graphs. That harness and its hash definition are not in the repo, so the hashes above are a re-measurement of the same claim with a different hash. They do not reproduce the CTO's literal values.

## Consequences

- An existing `/cache` export of `3861025a…` is refused once this pin lands. The server starts BM25 only, says so in the log, and `/healthz` reports `search_mode: "bm25"`, `search_mode_reason: "onnx_graph_not_built"` or `"model_unavailable"`. Re-run `CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py` on every box after merge. Stored passage vectors do not need rebuilding: outputs are bitwise identical.
- Export hosts must be x86-64 with AVX2. ARM hosts can still *run* the server with a graph exported elsewhere.
- The order fix relies on CPython 3.12's seeded string hash. A future interpreter with another mapping makes the export stop with a clear message, not write a wrong graph. The lasting fix is upstream `sorted(set(...))`.
- A different torch, transformers or onnx than `uv.lock` may trace another graph. The export refuses it; it never re-pins.
