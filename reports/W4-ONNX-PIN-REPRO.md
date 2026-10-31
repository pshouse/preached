# W4-ONNX-PIN-REPRO: a fresh export reproduces the pinned graph

Fresh-clone BLOCKER 2 (`reports/W4-FRESH-CLONE-QA.md` on `qa/w4-fresh-clone`, PR #68, finding 2). Branch `fix/w4-onnx-pin-repro`.

**Result: fix (a).** The existing pin `3861025a…` can be reproduced byte for byte. It was not changed. A fresh export now writes it on every run. The demo box's `/cache` graph is untouched and still loads.

## 1. Cause, with evidence

The exporter was deterministic *within* one Python process but not *across* processes. Transformers' ModernBERT builds its rotary position tables like this:

```
# .venv/.../transformers/models/modernbert/modeling_modernbert.py:454-455 (transformers 5.22.1)
for layer_type in set(self.config.layer_types):
    position_embeddings[layer_type] = self.rotary_emb(hidden_states, position_ids, layer_type)
```

Python randomizes string hashes per process (`PYTHONHASHSEED`), so a set of two strings iterates in one of two orders. The tracer names the two `rotary_emb` calls in call order. That produces one of two graphs: the same weights and outputs, but the two inv-freq constant tables (`local_rope_theta` 10000 and `global_rope_theta` 80000) swap names and the consumers are rewired to match.

Evidence:

| Check | Result |
| --- | --- |
| Toolchain at pin time vs now (`git diff e3fa88c origin/main -- uv.lock scripts/export_onnx.py`) | No change to torch/onnx/ort/transformers; exporter changed only in comments |
| Versions used | CPython 3.12.16, torch 2.15.0+cu132 (CPU, `CUDA_VISIBLE_DEVICES=""`), onnx 1.23.2, onnxruntime 1.31.1, transformers 5.22.1, huggingface-hub 2.4.0 |
| HF revision | `ibm-granite/granite-embedding-english-r2@47ea694b257b703fee9253d75c2b1f2985180498`, the same as the pin (`snapshot_download(..., revision=GRANITE_REVISION)`, `scripts/export_onnx.py:252`) |
| Unfixed exporter, two fresh dirs, default env | Both `aed7adba…` (the QA digest): equal to each other, not the pin. Two runs happening to share an order is a coin flip. |
| Structural diff pin vs `aed7adba…` (`onnx.load`) | ir 8, opset 18, producer `pytorch 2.15.0`, no metadata/doc_string: all equal. 134/134 initializers have equal names and order and are **bit-identical**. 3009 nodes each; **6 differ**: `/inner/rotary_emb/Constant_1` ↔ `/inner/rotary_emb_1/Constant` carry the θ=10000 vs θ=80000 tables in swapped slots, plus their `Unsqueeze` consumers in layer 0 attention (e.g. `/inner/layers.0/attn/Unsqueeze_2` reads `rotary_emb_1/Cast_output_0` in the pin, `rotary_emb/Cast_1_output_0` in the fresh export). Same file size (596635043); first differing byte at offset 16098. |
| fp32 export per seed (export only) | `PYTHONHASHSEED` 1, 2 → `set` order `[sliding_attention, full_attention]` → **`3861025a…` (pin)**. Seeds 0, 3, 4, 5 → `[full_attention, sliding_attention]` → `aed7adba…`. |

So the hunch (version drift, flags, initializer ordering, metadata, HF revision) was wrong on every count except that the exporter was "not byte-deterministic": the variable was the interpreter's hash seed.

## 2. Fix

`scripts/export_onnx.py`:

- `:58-59` `EXPORT_HASHSEED = "1"` and `PINNED_TRACE_ORDER = ["sliding_attention", "full_attention"]`.
- `:62` `_reexec_with_hashseed()`, called at `:300` before `main()`. String hashing is fixed at interpreter start, so the script sets `PYTHONHASHSEED=1` and `os.execv`s itself unless it already runs under that seed.
- `:71` `_check_trace_order(model)`, called at `:133` before `torch.onnx.export`. It refuses (exit non-zero) if `set(config.layer_types)` would trace in the other order. This also covers callers that import `_export` directly, and a future CPython whose seed→order mapping differs.
- `:84` `_check_pin(path)`, called at `:276` right after export. If the fp32 sha256 is not `FP32_ONNX_SHA256`, the script exits non-zero **before writing `manifest.json`**, so the runtime sees "missing manifest", not a usable-looking directory. It never re-pins.
- Docstring: the command is now from the repo root, not `.worktrees/feat/w3-cpu`. It explains the seed.

`src/preached/artifacts.py`:

- `:26-28` the pin comment says the export rebuilds it. `FP32_ONNX_SHA256` (`:31`) and `TOKENIZER_SHA256` are **unchanged**.
- `:46` `EXPORT_COMMAND`, the one-line build step.
- `:57` `ArtifactMissing(ArtifactError)`. It is raised only for an absent manifest (`:88`) or absent needed file (`:173`), and its message names the path and `EXPORT_COMMAND`. A present-but-wrong file stays a plain `ArtifactError`; "rebuild" is not the advice for a tampered graph. `search/query.py` catches `ArtifactError`, so the CLI now prints `error: missing ONNX manifest at …; build it with: CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py`.

Verification was not weakened. `verify_manifest` (`artifacts.py:185`) and `_open_hashed_graph` (`src/preached/onnx_embed.py:91`) still refuse any graph whose digest is not the pin, even with a manifest that agrees with it.

### Missing-graph startup message

`app/server.py:289` `MISSING_GRAPH_LOG`; `:845-847` the `except ArtifactMissing` branch in `load_search`, which `build_app` calls at startup (`:1761`). Real run with an empty `PREACHED_ONNX_DIR` (`uv run app/server.py --port 8199`), stderr:

```
ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. missing ONNX manifest at /tmp/emptyonnx/47ea694b257b703fee9253d75c2b1f2985180498/manifest.json; build it with: CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py
WARNING Embedding model failed to load; results are BM25 only.
INFO listening on http://127.0.0.1:8199
```

Before, this was `ERROR embedding model unavailable; serving BM25 only` plus a traceback. Any other load failure keeps that old path (`UNAVAILABLE_LOG`, with traceback). The change is 6 lines in `load_search`, the constant block and one import. It is separate from keep-alive and connection-cap code.

## 3. Numerics

The task asks for numerics between "the fresh export" and the old pin. With the fix, the fresh export *is* the pin, so I compared the old pin against the other graph, the unfixed `aed7adba…` export. That is the strongest version of the check: the two graphs are the only ones the unfixed exporter could produce. Script `/tmp/onnxtools/numerics.py` (not committed); output `/cache/w4-onnx-repro/numerics.json`. ORT CPU, 1 thread, `ORT_ENABLE_ALL`, pinned `tokenizer.json`, index `/cache/index/wesley.sqlite` opened read-only.

- **20 corpus chunks** (rowids 1, 420, 839, … 7962: every 419th of 8383). Tolerance stated: max abs ≤ 1e-6, cosine ≥ 0.99999. Measured: **max abs diff 0.0; 20/20 embeddings bit-identical** (min cosine prints 0.99999988, the float32 rounding of a unit vector's self dot product).
- **Hybrid top-10, 5 fixed questions** (the first five in `eval/questions.jsonl`: q-worry, q-worry-plain, q-assurance, q-assurance-plain, q-money): **identical, 5/5**. For example, q-worry is `wesley-029-c0062, wesley-029-c0064, wesley-126-c0011, wesley-141-c0063, wesley-089-c0058, wesley-041-c0005, wesley-041-c0017, wesley-135-c0013, wesley-029-c0043, wesley-050-c0048` under both.

Since the two graphs compute the same thing, re-pinning would have been eval-neutral. It is not needed, and nothing was re-pinned.

## 4. Mutant proof

`tests/test_onnx_pin_repro.py:191` `test_one_flipped_initializer_value_is_refused`:

1. Copies the pinned graph.
2. Walks the protobuf to the first `raw_data` initializer: `inner.embeddings.tok_embeddings.weight` [50368, 768], file offset 572580.
3. Flips the low mantissa bit of its first float (-0.00909423828125 → -0.009094239212572575).
4. Rewrites `manifest.json` to the mutant's own sha256, so the manifest check passes.

Then it asserts:

- `verify_manifest(..., enforce_pins=False)` passes, proving the manifest agrees.
- `verify_manifest(...)` raises `not the pinned digest`.
- `OnnxEmbedder.load(...)` raises `not the pinned digest`.

It passes.

## 5. Demo box

Nothing to do. `/cache/models/granite-english-r2-onnx/47ea…/` was not touched; its fp32 (`3861025a…`) and int8 (`220d6de9…`) match what the fixed exporter writes. Scratch exports are under `/cache/w4-onnx-repro/` (about 1.5 GB; safe to delete).

## 6. Tests

New `tests/test_onnx_pin_repro.py`:

| Test | What it proves |
| --- | --- |
| `MissingGraphMessageTests` (4) | Missing manifest and missing graph each log `ONNX GRAPH NOT BUILT` with the path and `EXPORT_COMMAND`. A wrong graph does not. `ArtifactMissing` is an `ArtifactError`. |
| `MutantGraphTests` (1) | Section 4 |
| `TraceOrderTests` (2) | Subprocess with `PYTHONHASHSEED=EXPORT_HASHSEED` passes `_check_trace_order`; seed 0 is refused before export |
| `ExportReproducesThePinTests` (1, slow) | Runs the real exporter twice, starting under seeds **0 and 3** (both gave `aed7adba…` before the fix). Both must write fp32 == pin and tokenizer == pin, pass `verify_manifest` with pins, and write identical manifests. Gated: `PREACHED_TEST_EXPORT=1 uv run --group bench python -m unittest tests.test_onnx_pin_repro`. It needs the bench group and the HF snapshot (network on first run). |

Results:

- `PREACHED_TEST_EXPORT=1 uv run --group bench python -m unittest tests.test_onnx_pin_repro -v`: `Ran 8 tests in 30.388s`, **OK**, 0 skipped.
- Manual exports with the fixed script under `PYTHONHASHSEED=0` and `=3`: both fp32 `3861025a…` and int8 `220d6de9…`. The log prints `fp32 sha256 matches the pin`; the torch parity check gives min cosine 1.000000 at lengths 8/17/64.
- `uv lock --check`: OK (`Resolved 79 packages`).
- Full suite, `PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`, before the merge: `Ran 1013 tests in 232.267s`, `FAILED (failures=52, skipped=1)`. The skip is the gated slow export test. **All 52 failures are subtests of one pre-existing test**, `tests/test_deploy_alerts.py` `RunbookTests.test_every_cited_file_line_holds_its_string`. It fails identically (52) on a clean `origin/main` b224281 checkout. PR #45 merged `docs/DEPLOY.md` with `app/server.py:N` cites pinned to a tree from before #63 (for example, cite 281 expects `MISMATCH_LOG`, which is at line 284 on main). `docs/DEPLOY.md` is out of scope here. This branch moves `server.py` lines by +1 from line 143 and +6 from line 845, so the re-pin task should run after this merges. No other failures.

Post-merge results are in section 8.

## 7. README export step (for the separate README task)

```
CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py
```

Run it from the repo root after the bench group can download the HF snapshot. It writes `/cache/models/granite-english-r2-onnx/47ea694b257b703fee9253d75c2b1f2985180498/` (or `$PREACHED_ONNX_DIR/<revision>/`), exits non-zero with no manifest if the graph is not the pin, and takes about 25 s on CPU once the snapshot is cached. Note: the script defaults `HF_HOME` to `/cache/huggingface` itself (`setdefault`), not from `PREACHED_CACHE`. It was left as is (not in this blocker).

## 8. Merge with origin/main and diff scope

`git fetch origin && git merge origin/main` immediately before push returned **Already up to date**. `origin/main` was still b224281, the branch base. Grok's 16-W3-KEEPALIVE-CAP had not merged yet, so the merge touched nothing: no merge commit, no change to `app/server.py`, no conflicts. If keep-alive lands first, the only overlap is the `load_search` except block, the constants block near line 284, and one import line.

Re-run after the (no-op) merge: `uv lock --check` OK. `PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`: `Ran 1013 tests in 226.786s`, `FAILED (failures=52, skipped=1)`. These are the same 52 pre-existing `test_deploy_alerts` cite subtests (section 6) and the same gated skip.

`git diff --stat origin/main..HEAD` (before this report edit; the final push adds only this file's lines):

```
 app/server.py                |   8 ++
 reports/W4-ONNX-PIN-REPRO.md | 132 +++++++++++++++++++
 scripts/export_onnx.py       |  54 +++++++-
 src/preached/artifacts.py    |  18 ++-
 tests/test_onnx_pin_repro.py | 302 +++++++++++++++++++++++++++++++++++++++++++
 5 files changed, 509 insertions(+), 5 deletions(-)
```

All five are in scope. No README.md or docs/DEPLOY.md.

## Open issues

- The fix relies on CPython's seeded SipHash giving the same set order for seed 1 on future interpreters. If not, `_check_trace_order` stops the export with a clear message instead of writing a wrong graph. The lasting fix is upstream: transformers should iterate `sorted(set(...))`, as its own `ModernBertRotaryEmbedding.__init__` already does at `modeling_modernbert.py:99`.
- A different torch/transformers than `uv.lock` may trace a different graph. `_check_pin` refuses it; it does not re-pin.
- `docs/DEPLOY.md` cite drift (section 6) is pre-existing and needs its own task.

## Dependencies added

None.
