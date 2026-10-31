# W4-ONNX-PIN-REPRO: a fresh export reproduces the pinned graph

Fresh-clone BLOCKER 2 (`reports/W4-FRESH-CLONE-QA.md` on `qa/w4-fresh-clone`, PR #68, finding 2). Branch `fix/w4-onnx-pin-repro`. Task 95 did the first pass; task 96 (`96-W4-ONNX-AVX2-PIN`) applies the CTO's ruling and replaces 95's approach. This report describes the branch as it now stands.

**Result.** The export pins torch's dispatch level (`ATEN_CPU_CAPABILITY=avx2`) and the rotary trace order. The pin is re-pinned once, to the avx2 export: `FP32_ONNX_SHA256 = aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`. I exported it myself; I did not copy it. Two exports are byte-identical, and a test now enforces that. The new graph is equivalent to the old pin: initializers byte-identical, ORT outputs bitwise identical, search results identical. The decision record is `docs/adr/0001-onnx-export-determinism.md`.

## 1. Cause

The exported bytes depend on **two** inputs (ADR, Context):

1. **torch's ATen CPU dispatch level.** This is the CTO's root cause. The rotary `inv_freq` tables are computed at trace time by the dispatched kernel and stored as Constants. Re-measured here, rotary order held fixed: `ATEN_CPU_CAPABILITY=default` gives `d99ba823…` (the CTO's "other host" digest), and `avx2` gives `aed7adba…`. The two graphs differ in one node, `/inner/rotary_emb/Constant_1`: 1 of 32 float32 values differs, by 1.5e-11. All 134 initializers are identical. This host (i9-12900K) has no AVX512, so I could not reproduce the AVX512 case. Its default dispatch is AVX2, which is why the QA box and this box both produced `aed7adba…` with no variable set.
2. **The rotary trace order.** This is a second cause, and it is still needed. The CTO's ruling said the export is deterministic from run to run. **It is not, on this host, at `ATEN_CPU_CAPABILITY=avx2`.** Measured with origin/main's unfixed exporter (export only, `/tmp/onnxtools/probe.py`):

| `ATEN_CPU_CAPABILITY` | `PYTHONHASHSEED` | `set(layer_types)` order | fp32 sha256 |
| --- | --- | --- | --- |
| avx2 | 0 | full, sliding | `aed7adba…5b78` |
| avx2 | 1 | sliding, full | `3861025a…8fa9` |
| avx2 | 2 | sliding, full | `3861025a…8fa9` |
| avx2 | 3 | full, sliding | `aed7adba…5b78` |
| unset (AVX2 here) | 0 / 1 / 2 / 3 | same as above | same as above |
| default | 0 | full, sliding | `d99ba823…d63a` |
| default | 1 | sliding, full | `44038d45…2487` |

transformers 5.22.1 ModernBERT loops `for layer_type in set(self.config.layer_types)` (`modeling_modernbert.py:454`). A two-string set iterates in hash order, and the two orders swap the θ=10000 and θ=80000 Constants and rewire four `Unsqueeze` inputs. `3861025a` vs `aed7adba` is exactly that 6-node difference. So the old pin was avx2 dispatch with the sliding-first order. It was reachable here, but only on half the runs. Pinning `avx2` without fixing the order would leave the two-export test failing about half the time. That is why I kept the order fix: ruling item 2 allows keeping a 95 change with justification, and this table is the justification.

## 2. Fix

`scripts/export_onnx.py`:

- Sets `ATEN_CPU_CAPABILITY=avx2` at module top, before torch is imported (`EXPORT_CPU_CAPABILITY`). It overrides any value in the caller's environment.
- `_require_avx2()` runs first in `__main__`. It refuses a host that is not `x86_64`/`amd64`, a CPU whose `/proc/cpuinfo` flags lack `avx2`, or an unreadable cpuinfo. Message: `export needs an x86-64 host with AVX2 …`; exit code 1.
- After `import torch`, `main()` refuses unless `torch.backends.cpu.get_cpu_capability() == "AVX2"`.
- Kept from 95, with one change: re-exec under `EXPORT_HASHSEED`, and `_check_trace_order` before tracing. The seed changed from 1 to **0**, and `PINNED_TRACE_ORDER` is now `["full_attention", "sliding_attention"]`. That is sorted order, the order an upstream `sorted(set(...))` fix would give, and with avx2 it traces `aed7adba…`, the graph the ruling names.
- Kept: `_check_pin` exits non-zero before writing a manifest if the fp32 graph is not the pin.

`src/preached/artifacts.py`: `FP32_ONNX_SHA256` is now `aed7adba…5b78`. The comment cites the ADR and states that the 2026-10-30 pin `3861025a…` has the same weights and outputs. Tokenizer pin unchanged. Kept from 95: `EXPORT_COMMAND`, and `ArtifactMissing` for an absent manifest or file (its message names the path and the command).

Dropped from 95: the hash-seed-only explanation, and the claim that the fix reproduces `3861025a`.

## 3. Startup log and /healthz

`app/server.py`, in `load_search`'s `except ArtifactMissing` branch:

- Logs `ERROR embedding model unavailable; serving BM25 only` (`UNAVAILABLE_LOG`). This fixes a regression I introduced in 95: the runbook's D2 page (`deploy-embedding-unavailable-bm25`) matches that line, and 95 had replaced it.
- Then logs the loud line `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. missing ONNX manifest at …; build it with: CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py`.
- Returns the new `MISSING_GRAPH_NOTE` ("The search model has not been built; results are BM25 only."). Startup logs it again as a WARNING, and search responses carry it as `note`.

`App.health()` (`/healthz`) gains two fields:

- `search_mode`: `"hybrid"` or `"bm25"`.
- `search_mode_reason`: `null` when hybrid. When BM25, a code from `SEARCH_MODE_REASONS`: `onnx_graph_not_built`, `model_unavailable`, `stale_vectors`, `index_unreadable`, `bm25_only` (started with `--bm25-only`), or `fallback` for any other note. It is a code, never a path. A graph that is present but not the pin (for example an old `3861025a` export) is `model_unavailable`.

## 4. Equivalence (ruling item 3, re-measured)

`/tmp/onnxtools/equiv.py` (not committed), output `/cache/w4-onnx-avx2/equiv.json`. It compares old `3861025a…` (`/cache/models/granite-english-r2-onnx`) with new `aed7adba…` (`/cache/w4-onnx-avx2/final`, a full export by this branch). ORT CPU, 1 thread.

- Header equal. **Initializers: 134 / 134 byte-identical.** Nodes: 3009 each, **6 differ** (`/inner/rotary_emb/Constant_1`, `/inner/rotary_emb_1/Constant`, `/inner/layers.0/attn/Unsqueeze_2`, `_3`, `/inner/layers.1/attn/Unsqueeze_2`, `_3`).
- **ORT parity: bitwise identical**, max abs diff 0.0, on all 93 `eval/questions.jsonl` queries (`encode_queries`) and 21 corpus chunks (`rowid % 419 = 1`, `encode_documents`).
- **Search harness**, all 93 questions, `App.search(q, 10, "hybrid")` through `build_app(..., embed_backend="onnx", variant="fp32")` on `/cache/index/wesley.sqlite`. Under both graphs: top-10 identical 93 / 93, response hash `f66c732275af497f`, query-embedding hash `29b07255a0733b1f`. The response hash is sha256 of the sorted-key JSON of all 93 responses with `took_ms` removed (wall time), truncated to 16 hex characters. The embedding hash is sha256 of the stacked float32 query vectors.
- **The CTO's `20bf48af596a4d4d` / `73463e64b1ce508a`.** Their harness and hash definition are not in the repo or `/cache`. My hashes are a re-measurement of the same claim (identical across the graphs), not the CTO's literal values.

`int8` sha of the new export is `9cb48a50…7651` (old `220d6de9…`). It is not pinned; the server never opens int8.

## 5. Tests

`tests/test_onnx_pin_repro.py` (15 tests):

| Class | What it proves |
| --- | --- |
| `MissingGraphMessageTests` (4) | Kept from 95. A missing manifest or graph logs `ONNX GRAPH NOT BUILT` with the path and `EXPORT_COMMAND`, plus the D2 alert line, and returns `MISSING_GRAPH_NOTE`. A wrong graph is not called unbuilt. `ArtifactMissing` is an `ArtifactError`. |
| `HealthzSearchModeTests` (3) | `/healthz` gives `bm25` / `onnx_graph_not_built` for a missing graph (and no path in the payload), `bm25` / `model_unavailable` for another load failure, `bm25` / `bm25_only` under `--bm25-only`, and `hybrid` / `null` when the model loads. |
| `Avx2GuardTests` (4) | Importing the script sets `ATEN_CPU_CAPABILITY=avx2` (over `default`) with torch not yet imported. `aarch64` is refused. A cpuinfo without `avx2`, or no cpuinfo, is refused; one with it passes. The script run as `__main__` on a faked `arm64` exits non-zero with the message. |
| `MutantGraphTests` (1) | Kept from 95. One flipped mantissa bit in the first initializer, with a manifest rewritten to agree, is refused by `verify_manifest` and `OnnxEmbedder.load` (`not the pinned digest`). |
| `TraceOrderTests` (2) | `PINNED_TRACE_ORDER` is sorted order. `EXPORT_HASHSEED` passes `_check_trace_order`; seed 1 is refused before export. |
| `ExportIsByteIdenticalTests` (1) | Two real exports. One starts under `PYTHONHASHSEED=1` with `ATEN_CPU_CAPABILITY=default`, the other under seed 3 with no variable set. Both exit 0, the two fp32 files are byte-identical (`filecmp`, not shallow), fp32 equals the pin, the tokenizer equals its pin, both pass `verify_manifest` with pins, and the manifests are identical (so int8 matches too). It skips only when `$PREACHED_CACHE/huggingface/hub/models--ibm-granite--granite-embedding-english-r2/snapshots/<rev>/model.safetensors` is absent, and says so. It is no longer gated on an opt-in variable, so it runs in the full suite. |

`PREACHED_CACHE=/cache uv run python -m unittest discover -s tests -p test_onnx_pin_repro.py -v`: `Ran 15 tests in 29.347s`, **OK**, 0 skipped.

Parity run (ruling item 4), by hand: two full exports into `/cache/w4-onnx-avx2/run-a` (seed 1, `ATEN_CPU_CAPABILITY=default`) and `run-b` (seed 3, unset). Both fp32 `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`. A third full export, `/cache/w4-onnx-avx2/final`, exits 0 and logs `fp32 sha256 matches the pin`; its torch-vs-ORT check gives min cosine 1.000000 at lengths 8/17/64 (max abs 3.8e-05 / 3.1e-04 / 8.4e-04).

Full-suite results are in section 7.

## 6. Demo box and every existing export (action needed after merge)

The `/cache/models/granite-english-r2-onnx/47ea…/` graph is still `3861025a…`. I did not replace it: main still pins `3861025a`, and replacing it before merge would turn main's server and tests BM25-only or red. **Once this PR merges, the runtime refuses that graph.** The server starts BM25 only, logs `embedding model unavailable` with `not the pinned digest`, and `/healthz` shows `search_mode: "bm25"`, `search_mode_reason: "model_unavailable"`. After merge, run on every box:

```
CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py
```

This takes under a minute here once the HF snapshot is cached. Stored passage vectors need no rebuild (outputs are bitwise identical). Or copy `/cache/w4-onnx-avx2/final/47ea694b257b703fee9253d75c2b1f2985180498/` over it.

## 7. Merge, full suite, scope

`git fetch origin && git merge origin/main` (after the code commit) returned **Already up to date**. `origin/main` is still b224281, the branch base, so there is no merge commit to make and no conflicts.

`uv lock --check`: OK (`Resolved 79 packages`).

Full suite, exact command, after the merge: `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`. Result: `Ran 1020 tests in 252.536s`, `FAILED (failures=55, errors=2)`, 0 skipped. That breaks down as follows:

- **52**: subtests of `test_deploy_alerts.RunbookTests.test_every_cited_file_line_holds_its_string`. These are the known stale `docs/DEPLOY.md` cites (Grok's R4-COND). I evaluated every `CITED` entry against `origin/main` and against this branch. **The same 52 cites fail on both; none is newly broken and none newly fixed.** All `app/server.py` cites below my edits were already stale on main, so the standing re-pin rule had no affected cite that currently holds. `docs/DEPLOY.md` and the `CITED` pins are untouched.
- **3 failures and 2 errors**: tests that open the real graph in `/cache/models/granite-english-r2-onnx`, which is still the old `3861025a…` (section 6):
  - `test_embed_backend.RealOnnxTests.test_cached_fp32_and_tokenizer_match_the_pins`
  - `test_fp32_directory_without_int8_loads` (error)
  - `test_fp32_query_is_unit_normalized` (error)
  - `ImportGuardTests.test_youtube_embed_path_does_not_import_torch`
  - `test_shutdown.LoadedSigtermTests.test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` (the server fell back to BM25)

  Each failure message is `not the pinned digest`. They clear once the box is re-exported. On the same tree with `PREACHED_ONNX_DIR=/cache/w4-onnx-avx2/final` (a complete export by this branch), the run is `Ran 1020 tests in 261.241s`, `FAILED (failures=52)`: only the 52 cite subtests.

Before this fix, one more failure was mine: `test_embed_backend.FallbackTests.test_missing_artifacts_serve_bm25` asserted the old note for a missing graph. It now asserts `MISSING_GRAPH_NOTE`.

`git diff --stat origin/main..HEAD` (before this report's final edit):

```
 app/server.py                            |  23 ++
 docs/adr/0001-onnx-export-determinism.md |  43 ++++
 reports/W4-ONNX-PIN-REPRO.md             | 147 +++++++++++
 scripts/export_onnx.py                   |  84 +++++-
 src/preached/artifacts.py                |  21 +-
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 427 +++++++++++++++++++++++++++++++
 7 files changed, 741 insertions(+), 8 deletions(-)
```

All seven files are in scope: export script, `artifacts.py`, server/healthz, their tests (`test_embed_backend.py` holds the existing missing-artifact server test), the ADR, and this report. No README.md or docs/DEPLOY.md. No keep-alive code.

## Open issues

- **`docs/DEPLOY.md` still cites the old sha** (`3861025a…` at lines 208 and 324). It is out of this task's diff scope, and Grok's R4-COND is editing that file, so I left it. It must become `aed7adba…` when R4-COND or a follow-up lands. Until then, an operator checking a fresh export against DEPLOY.md would see a mismatch.
- The runbook has no row for the `ONNX GRAPH NOT BUILT` line or the new `/healthz` fields. D2 still fires, because its line is emitted first. Also for the DEPLOY.md follow-up.
- The order fix relies on CPython 3.12's seeded string hash. If a future interpreter maps seed 0 differently, `_check_trace_order` stops the export with a message. The lasting fix is upstream `sorted(set(...))`.
- AVX512 behaviour is the CTO's measurement. This host cannot run it, so the claim that `avx2` overrides an AVX512 default was verified only via the `default` → `avx2` override.
- Scratch exports under `/cache/w4-onnx-avx2/` (about 0.75 GB) and `/cache/w4-onnx-repro/` (95, about 1.5 GB) are safe to delete.

## Dependencies added

None.
