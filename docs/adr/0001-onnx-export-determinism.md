# ADR 0001: The ONNX export fixes avx2 dispatch and PYTHONHASHSEED=1

Status: accepted, 2026-10-31. Tasks 95, 96, 96-W4-ONNX-SEED1-PIN (the CTO's seed 1 + avx2 ruling) and 99-W4-ONNX-PIN-FIX1. Evidence is in `reports/W4-ONNX-PIN-REPRO.md`.

## Context

`src/preached/artifacts.py` pins the sha256 of `model.fp32.onnx`, and the runtime refuses any other graph. A fresh clone runs `scripts/export_onnx.py` to build that graph, so the export must write the same bytes on every supported host. It did not. Depending on host and hash seed, the export produced `3861025a…` (the 2026-10-30 pin), `aed7adba…`, `d99ba823…` or `44038d45…` (the four digests of the matrix below).

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

The CTO's seeded exports agree with every cell above where they overlap: avx2 + seed 1 → `3861025a…` (the pin), avx2 + seed 0 → `aed7adba…`, default dispatch → `d99ba823…` or `44038d45…` by seed class. The CTO's AVX512 cells (seed 0 or 3 → `aed7adba…`, seed 1 → `3861025a…`) match the avx2 cells, so on those hosts AVX512 and avx2 dispatch gave the same bytes. They cannot be re-run here.

**Through `scripts/export_onnx.py`**: see `reports/W4-ONNX-PIN-REPRO.md` §1b. Every ambient seed (unset, 0-5) and dispatch level writes `3861025a…`.

## Decision

- **Dispatch.** `scripts/export_onnx.py` sets `ATEN_CPU_CAPABILITY=avx2` at module top, before torch is imported, overriding any ambient value. After the import it checks `torch.backends.cpu.get_cpu_capability() == "AVX2"`. It refuses a host that is not x86-64 or whose CPU flags lack `avx2`, exiting non-zero with a message that names AVX2.
- **Hash seed.** String hashing is fixed when the interpreter starts, so the seed cannot be set from inside the process. The script re-executes itself (`os.execv`) under `PYTHONHASHSEED=1` before it imports torch, unless `PYTHONHASHSEED` is already `1`. (It tests the variable, not `sys.flags.hash_randomization`, which reads 1 under every seed but 0; a numeric seed wins over `-R`.) Before tracing it also refuses unless `set(config.layer_types)` iterates `["sliding_attention", "full_attention"]`, the order seed 1 gives on CPython 3.12 and the order of the pinned graph.
- **Pin.** Unchanged: `FP32_ONNX_SHA256 = 3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`. Seed 1 + avx2 reproduces it, so there is no re-pin and existing exports stay valid. The export exits non-zero, before it writes a manifest, if its graph is not the pin.
- **Tests.** `tests/test_onnx_pin_repro.py` runs the real exporter three times (outputs and HF cache in a TMPDIR temp dir; the Granite snapshot is only read) under ambient `PYTHONHASHSEED` unset, 0 and 3 (and dispatch `default`, `avx2`, `avx512`) and asserts byte-identical fp32 graphs equal to the pin with identical manifests. `HashSeedReexecTests` checks that any ambient seed other than the export seed restarts. `TraceOrderTests` checks that seed 0 is refused.
- No semantic digest, and no committed graph.

## Equivalence

Seed 1 + avx2 writes the existing pin, so nothing changes for the runtime. For reference, the other avx2 graph (`aed7adba…`, seed 0) was compared against the pin: header equal, 134 / 134 initializers byte-identical, 3009 nodes each with 6 differing (the two rotary Constants and four `Unsqueeze` inputs), ORT CPU outputs bitwise identical on all 93 `eval/questions.jsonl` queries and 21 corpus chunks, and `App.search(q, 10, "hybrid")` top-10 identical on 93 / 93 questions with equal response, chunk-id and vector hashes. The graphs are functionally identical; the export is pinned to one of them for byte reproducibility, not for behavior.

## Consequences

- Everything the export reads or writes follows `PREACHED_CACHE` (`/cache` only when it is unset). The Hugging Face cache defaults to `$PREACHED_CACHE/huggingface`, set before the seed restart (an explicit `HF_HOME`, `HF_HUB_CACHE` or `HUGGINGFACE_HUB_CACHE` wins). The outputs go to `preached.artifacts.artifact_dir()`, `$PREACHED_CACHE/models/granite-english-r2-onnx/<revision>/` (`PREACHED_ONNX_DIR` replaces the root), the same directory the server reads, and the export removes and rewrites only that directory. So a fresh clone with a custom `PREACHED_CACHE`, and no cache variables pointing elsewhere, does not touch `/cache`.
- An existing `/cache` export of `3861025a…` stays valid; no re-export is needed. A fresh clone's export now writes the same bytes.
- Export hosts must be x86-64 with AVX2. ARM hosts can still run the server with a graph exported elsewhere.
- The order fix relies on CPython 3.12's seeded string hash. If a future interpreter maps seed 1 to another order, the export stops with a clear message instead of writing a wrong graph. The lasting fix is upstream `sorted(set(...))`.
- A torch, transformers or onnx version other than the one in `uv.lock` may trace another graph. The export refuses it and never re-pins.
