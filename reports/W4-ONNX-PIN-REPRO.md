# W4-ONNX-PIN-REPRO: a fresh export reproduces the pinned graph

Fresh-clone BLOCKER 2 (`reports/W4-FRESH-CLONE-QA.md` on `qa/w4-fresh-clone`, PR #68, finding 2). Branch `fix/w4-onnx-pin-repro`, PR #71. Task 95 did the first pass. Task 96 (`96-W4-ONNX-AVX2-PIN`) applied the CTO's avx2 ruling. Task 96-W4-ONNX-MATRIX adds the CTO's hard requirements: the full seed × dispatch matrix, a pin for each variable that moves the bytes, a two-export test that varies the ambient seed and dispatch level, and re-measured equivalence. This report describes the branch as it now stands.

**Result.** Both variables drive the bytes, so both are pinned. I measured the 18-cell matrix `PYTHONHASHSEED` {0..5} × `ATEN_CPU_CAPABILITY` {default, avx2, avx512}. Without the script's overrides, the 12 runnable cells give **four** digests. The 6 avx512 cells cannot run on this CPU (SIGILL). Through `scripts/export_onnx.py`, all **18 / 18** cells give one digest, `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`. That is the single pin in `src/preached/artifacts.py`, and `docs/DEPLOY.md` now quotes it too. The new graph is equivalent to the old pin: initializers byte-identical, ORT outputs bitwise identical, search results identical. The decision record is `docs/adr/0001-onnx-export-determinism.md`.

## 1. Cause: the matrix (hard requirement 1)

The two variables do not conflict. They act on different things, and each one alone moves the bytes:

- `PYTHONHASHSEED` sets the iteration order of `set(self.config.layer_types)` in transformers 5.22.1 ModernBERT (`modeling_modernbert.py:454`). That order decides which rotary table is traced first. The two orders swap the θ=10000 and θ=80000 Constants and rewire four `Unsqueeze` inputs (6 of 3009 nodes).
- `ATEN_CPU_CAPABILITY` sets the kernel that computes the `inv_freq` values stored in those Constants. Between `default` and `avx2`, 1 of 32 float32 values differs, by 1.5e-11.

Host: i9-12900K (AVX2, no AVX512), CPython 3.12.16, torch 2.15.0+cu132, transformers 5.22.1, onnx 1.23.2, `CUDA_VISIBLE_DEVICES=""`, `HF_HUB_OFFLINE=1`.

### 1a. Raw export: what moves the bytes

`/tmp/onnxmatrix/probe.py` (not committed) loads the model and makes the same `torch.onnx.export` call as `scripts/export_onnx.py`, but without its environment overrides. Each cell is a fresh process with the two variables set. Output: `/cache/w4-onnx-matrix/raw.jsonl`. Full fp32 sha256 values:

| `ATEN_CPU_CAPABILITY` | `PYTHONHASHSEED` | torch dispatch | `set()` order | fp32 sha256 |
| --- | --- | --- | --- | --- |
| default | 0 | DEFAULT | full, sliding | `d99ba82356d7ce907f012fc36a9634e098ecf221827e2c5ae708968ad883d63a` |
| default | 1 | DEFAULT | sliding, full | `44038d45b736393e93ed43912e4215832bd3c104b464d74aa4d8de6ab67e2487` |
| default | 2 | DEFAULT | sliding, full | `44038d45b736393e93ed43912e4215832bd3c104b464d74aa4d8de6ab67e2487` |
| default | 3 | DEFAULT | full, sliding | `d99ba82356d7ce907f012fc36a9634e098ecf221827e2c5ae708968ad883d63a` |
| default | 4 | DEFAULT | full, sliding | `d99ba82356d7ce907f012fc36a9634e098ecf221827e2c5ae708968ad883d63a` |
| default | 5 | DEFAULT | full, sliding | `d99ba82356d7ce907f012fc36a9634e098ecf221827e2c5ae708968ad883d63a` |
| avx2 | 0 | AVX2 | full, sliding | `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78` |
| avx2 | 1 | AVX2 | sliding, full | `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` |
| avx2 | 2 | AVX2 | sliding, full | `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` |
| avx2 | 3 | AVX2 | full, sliding | `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78` |
| avx2 | 4 | AVX2 | full, sliding | `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78` |
| avx2 | 5 | AVX2 | full, sliding | `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78` |
| avx512 | 0-5 | (reports AVX512) | — | **cannot run**: SIGILL, exit 132 |

Why the avx512 cells cannot run: this CPU has no AVX512 (none of the `avx512*` flags in `/proc/cpuinfo`). torch does not clamp a requested level to the CPU. `PYTHONHASHSEED=0 ATEN_CPU_CAPABILITY=avx512 python -c "import torch; print(torch.backends.cpu.get_cpu_capability())"` prints `AVX512`. The export itself then dies on an illegal instruction, exit 132, with no graph written. No host with AVX512 is available to me. The AVX512 digest is the CTO's measurement, and I did not re-verify it.

Reading the table: each (order, dispatch) pair has exactly one digest. Seed changes the digest at fixed dispatch, and dispatch changes it at fixed seed. So both variables matter, and with unset/ambient settings the result is a per-host, per-run lottery. `3861025a…` (the 2026-10-30 pin) is avx2 with the sliding-first order. `d99ba823…` (the CTO's "other host" digest) is default dispatch with the full-first order.

### 1b. Through the script: one digest

`/tmp/onnxmatrix/script.sh` (not committed) runs the real `uv run --group bench python scripts/export_onnx.py` once per cell, into `/cache/w4-onnx-matrix/script-<cap>-<seed>`, with the cell's values as the **ambient** environment. Output: `/cache/w4-onnx-matrix/script.tsv` and per-cell logs.

| ambient `ATEN_CPU_CAPABILITY` | ambient `PYTHONHASHSEED` 0 / 1 / 2 / 3 / 4 / 5 |
| --- | --- |
| default | `aed7adba…5b78` ×6, exit 0 |
| avx2 | `aed7adba…5b78` ×6, exit 0 |
| avx512 | `aed7adba…5b78` ×6, exit 0 |

All 18 cells: exit 0, `fp32 sha256 matches the pin` in the log, fp32 `aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`, and manifest sha256 `b36f04e9b9c044f46e442b7ce2dfa0063c88addf9aa98f1d6ab2b55ae74c0638` in every cell. Because the manifest lists every file's digest, int8, tokenizer and pooling are identical too. The ambient avx512 cells run here because the script replaces the value with avx2 before torch is imported.

## 2. Fix (hard requirements 2 and 4)

`scripts/export_onnx.py`, run as `__main__`:

1. `_require_avx2()` refuses a host that is not `x86_64`/`amd64`, a CPU whose `/proc/cpuinfo` flags lack `avx2`, or an unreadable cpuinfo. The message is `export needs an x86-64 host with AVX2 …`, with exit code 1. Kept from 96.
2. `_reexec_with_hashseed()` handles the hash seed. The seed cannot be set inside a running interpreter, so the script sets `PYTHONHASHSEED=0` (`EXPORT_HASHSEED`) in the environment and `os.execv`s itself. The new interpreter starts with the seed fixed. The re-exec happens before torch is imported (torch is imported only inside `main()`). It is skipped only when the seed is already `0` **and** `sys.flags.hash_randomization` is 0. That second condition is new in this task: `python -R` keeps hashing random even under `PYTHONHASHSEED=0`, and the restart drops interpreter flags.
3. `ATEN_CPU_CAPABILITY=avx2` (`EXPORT_CPU_CAPABILITY`) is set at module top, before torch is imported, and overrides any ambient value. After import, `main()` refuses unless `torch.backends.cpu.get_cpu_capability() == "AVX2"`. Kept from 96.
4. `_check_trace_order` refuses to trace unless `set(config.layer_types)` iterates `["full_attention", "sliding_attention"]` (sorted order).
5. `_check_pin` exits non-zero before writing a manifest if the fp32 graph is not the pin.

`src/preached/artifacts.py` has one pin value, `FP32_ONNX_SHA256 = aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`, and the matrix (§1b) is the evidence for it. The value is the one 96 set. This task did not change it, because the matrix showed it is the only digest the script writes. Its comment now records the matrix. `docs/DEPLOY.md` §7 and its ONNX file table quoted the old `3861025a…`. Both now quote `aed7adba…`, so the branch has exactly one fp32 pin value anywhere (`grep -rn 3861025a` finds it only in the ADR, this report and the artifacts.py comment, as history).

## 3. Startup log and /healthz

`app/server.py`, in `load_search`'s `except ArtifactMissing` branch:

- Logs `ERROR embedding model unavailable; serving BM25 only` (`UNAVAILABLE_LOG`). This fixes a regression I introduced in 95: the runbook's D2 page (`deploy-embedding-unavailable-bm25`) matches that line, and 95 had replaced it.
- Then logs the loud line `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. missing ONNX manifest at …; build it with: CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py`.
- Returns the new `MISSING_GRAPH_NOTE` ("The search model has not been built; results are BM25 only."). Startup logs it again as a WARNING, and search responses carry it as `note`.

`App.health()` (`/healthz`) gains two fields:

- `search_mode`: `"hybrid"` or `"bm25"`.
- `search_mode_reason`: `null` when hybrid. When BM25, a code from `SEARCH_MODE_REASONS`: `onnx_graph_not_built`, `model_unavailable`, `stale_vectors`, `index_unreadable`, `bm25_only` (started with `--bm25-only`), or `fallback` for any other note. It is a code, never a path. A graph that is present but not the pin (for example an old `3861025a` export) is `model_unavailable`.

## 4. Equivalence (hard requirement 5, re-measured)

This was re-measured in this task, with fresh scripts. The old `/tmp/onnxtools` scripts are gone. `/tmp/onnxmatrix/equiv_one.py` runs once per graph, as a subprocess, and patches the code pin to that graph's own digest so the old graph loads. `/tmp/onnxmatrix/equiv_cmp.py` compares the two runs. Output: `/cache/w4-onnx-matrix/equiv.json`. Old graph: `3861025a…` in `/cache/models/granite-english-r2-onnx`. New graph: `aed7adba…`, the matrix's avx2 / seed 0 export by the script (`/cache/w4-onnx-matrix/script-avx2-0`). ORT CPU, 1 thread, `OnnxEmbedder.load(variant="fp32", batch_size=1)`.

- Header (ir version, opsets, producer) equal.
- **Initializers: 134 / 134 byte-identical** (serialized `TensorProto` compared).
- Nodes: 3009 each. **6 differ**: `/inner/rotary_emb/Constant_1`, `/inner/rotary_emb_1/Constant`, and `/inner/layers.{0,1}/attn/Unsqueeze_{2,3}`.
- **ORT outputs: bitwise identical** (`tobytes()` equal), max abs diff 0.0. That covers all 93 `eval/questions.jsonl` queries (`encode_queries`) and 21 corpus chunks (`rowid % 419 = 1`, `encode_documents` with titles).
- **Search**: `build_app(..., embed_backend="onnx", variant="fp32", ort_threads=1)` on `/cache/index/wesley.sqlite` (opened read-only), then `App.search(q, 10, "hybrid")` for all 93 questions with `took_ms` removed. Top-10 identical 93 / 93, with 0 empty result lists.

Hashes (sha256, first 16 hex characters) under each graph:

| Definition | old `3861025a` | new `aed7adba` |
| --- | --- | --- |
| responses, `json.dumps(sort_keys=True)` | `f66c732275af497f` | `f66c732275af497f` |
| responses, sorted keys, compact separators | `c397bf6f45d22114` | `c397bf6f45d22114` |
| top-10 chunk ids per query | `7d11acdaaa1f1c20` | `7d11acdaaa1f1c20` |
| query vectors, float32 bytes | `29b07255a0733b1f` | `29b07255a0733b1f` |
| query then document vectors, float32 bytes | `66b31d7885d2d20e` | `66b31d7885d2d20e` |

**The CTO's `20bf48af596a4d4d` / `73463e64b1ce508a`.** I can re-measure that they are unchanged, but I cannot reproduce the literal values. The CTO's harness and hash definition are not in the repo, in `/cache`, or in git history (`git log --all -S20bf48af596a4d4d` finds only this branch's report). None of my five definitions produces those values. Under every definition I tried, the hash is the same for both graphs. This matches the bitwise-identical outputs, so any hash of the outputs is unchanged as well. To check the literal values, the CTO's harness needs to be run against `/cache/w4-onnx-matrix/script-avx2-0` (or committed).

The new export's `int8` is not pinned, and the server never opens it.

## 5. Tests (hard requirement 3)

`tests/test_onnx_pin_repro.py` (18 tests):

| Class | What it proves |
| --- | --- |
| `MissingGraphMessageTests` (4) | A missing manifest or graph logs `ONNX GRAPH NOT BUILT` with the path and `EXPORT_COMMAND`, plus the D2 alert line, and returns `MISSING_GRAPH_NOTE`. A wrong graph is not called unbuilt. `ArtifactMissing` is an `ArtifactError`. |
| `HealthzSearchModeTests` (3) | `/healthz` `search_mode` / `search_mode_reason` for a missing graph, another load failure, `--bm25-only`, and hybrid. |
| `Avx2GuardTests` (4) | Importing the script sets `ATEN_CPU_CAPABILITY=avx2` (over `default`) before torch is imported. Non-x86-64 hosts, cpuinfo without `avx2`, and a missing cpuinfo are refused. The script run as `__main__` on a faked `arm64` exits non-zero. |
| `MutantGraphTests` (1) | One flipped mantissa bit, with a manifest rewritten to agree, is refused by `verify_manifest` and `OnnxEmbedder.load`. |
| `TraceOrderTests` (2) | `PINNED_TRACE_ORDER` is sorted order. `EXPORT_HASHSEED` passes `_check_trace_order`, and seed 1 is refused. |
| `HashSeedReexecTests` (3, **new**) | Runs `_reexec_with_hashseed()` in a subprocess with `os.execv` recorded. Ambient seed unset, `random`, 1, 2, 3, 4, 5: each restarts `sys.executable` on the script with `PYTHONHASHSEED=0`. Ambient `0`: no restart. `python -R` with seed 0: restarts. |
| `ExportIsByteIdenticalTests` (1, **changed**) | Two real exports from **different ambient settings**. Run a uses `PYTHONHASHSEED=1`, `ATEN_CPU_CAPABILITY=default` (raw: `44038d45…`). Run b uses `PYTHONHASHSEED=3`, `ATEN_CPU_CAPABILITY=avx512` (raw: the other order; on this CPU raw avx512 would SIGILL). Both exit 0. The fp32 files are byte-identical (`filecmp`, not shallow) and equal the pin. The tokenizer equals its pin, both pass `verify_manifest` with pins, and the manifests are identical. It skips only when the Granite snapshot is absent from `PREACHED_CACHE`. Before, run b inherited the ambient dispatch level instead of setting one. |

`PREACHED_CACHE=/cache uv run python -m unittest discover -s tests -p test_onnx_pin_repro.py -v`: see §7 for the full-suite run, which includes it.

`tests/test_deploy_alerts.py` `CITED` is re-pinned (§7).

## 6. Demo box and every existing export (action needed after merge)

The `/cache/models/granite-english-r2-onnx/47ea…/` graph is still `3861025a…`. I did not replace it: main still pins `3861025a`, and replacing it before merge would turn main's server and tests BM25-only or red. **Once this PR merges, the runtime refuses that graph.** The server starts BM25 only, logs `embedding model unavailable` with `not the pinned digest`, and `/healthz` shows `search_mode: "bm25"`, `search_mode_reason: "model_unavailable"`. After merge, run on every box:

```
CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py
```

This takes under a minute here once the HF snapshot is cached. Stored passage vectors need no rebuild (outputs are bitwise identical). Or copy `/cache/w4-onnx-avx2/final/47ea694b257b703fee9253d75c2b1f2985180498/` over it.

## 7. DEPLOY.md cites, merge, full suite, scope

### Standing rule 4: `app/server.py` changed, so its cites are re-pinned

This PR changes `app/server.py` (+23 lines: the `ArtifactMissing` import, the `MISSING_GRAPH_*` and `SEARCH_MODE_REASONS` constants, the `except ArtifactMissing` branch, and the two `/healthz` fields). So every `app/server.py` cite in `docs/DEPLOY.md` and in `tests/test_deploy_alerts.py` `CITED` is re-pinned in this PR.

- **Before.** On `origin/main`, all 52 `app/server.py` cites were stale by a uniform +3: each needle sat exactly 3 lines below its cite (the 52 known failures). On this branch before the re-pin, the same 52 were off by +4 to +26.
- **Method.** `/tmp/onnxmatrix/cites/repin.py` (not committed) maps each cite to `origin/main` line cite+3, where its needle was verified. It then follows that line through a `difflib` line alignment of main's `app/server.py` onto this branch's, and asserts the needle is on the target line. DEPLOY.md is rewritten using the runbook parser's own rules (`runbook_cites`: per row, list item and paragraph, a bare `:n` belongs to the last named file). Only cites it attributes to `app/server.py` change. `src/preached/library.py` and `scripts/build-bundle.sh` cites are untouched.
- **Verified by reading the file.** `/tmp/onnxmatrix/cites/check.py` reads each `CITED` line from `app/server.py` at HEAD and checks the needle: 0 misses (54 misses before, counting both ends of the two ranges). `test_deploy_alerts` passes: 7 tests OK. That includes `test_every_cited_file_line_holds_its_string` (reads each file) and `test_the_runbook_cites_exactly_the_pinned_lines` (DEPLOY.md set == `CITED` set). Examples: `REQUEST_TIMEOUT_S` 231→235, `UNAVAILABLE_LOG` 282→286, `INDEX_STATUS_LOG` 283→291, D2's `logging.exception(UNAVAILABLE_LOG)` 839→861, stop path 3200-3218→3226-3244, `stopped cleanly` 3216→3242.
- DEPLOY.md's two fp32 sha quotes (§7 go-live, ONNX file table) now give `aed7adba…`. The diff touches no other DEPLOY.md text.

### Merge, lock, suite

`git fetch origin && git merge origin/main` after the code commit returned **Already up to date**. `origin/main` is still `b224281`, the branch base, so there was no merge commit to make and no conflicts. I checked again right before pushing (§8).

`uv lock --check`: OK (`Resolved 79 packages`). No new dependencies.

Full suite, exact command: `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests` (log `/cache/w4-onnx-matrix/suite1.log`):

`Ran 1023 tests in 247.993s`, **`FAILED (failures=3, errors=2)`**, 0 skipped. The two-export test ran and passed. The 52 stale-cite failures are gone, because this PR re-pins those cites. The 5 failures are all the box's own graph, which is still the old `3861025a…` (§6). Each message is `not the pinned digest`:

- `test_embed_backend.RealOnnxTests.test_cached_fp32_and_tokenizer_match_the_pins` (fail)
- `test_embed_backend.RealOnnxTests.test_fp32_directory_without_int8_loads` (error)
- `test_embed_backend.RealOnnxTests.test_fp32_query_is_unit_normalized` (error)
- `test_embed_backend.ImportGuardTests.test_youtube_embed_path_does_not_import_torch` (fail)
- `test_shutdown.LoadedSigtermTests.test_sigterm_under_hybrid_load_exits_zero_and_cleans_up` (fail: the server fell back to BM25)

The same command with `PREACHED_ONNX_DIR=/cache/w4-onnx-avx2/final`, a complete export by this branch (log `suite2.log`): `Ran 1023 tests in 258.879s`, **`OK`**, 0 skipped. So the 5 clear once the box is re-exported after merge.

## 8. Diff scope

`git diff --stat origin/main..HEAD`: see the final commit's output below (filled in before push).

DIFFSTAT

The files in scope: the export script, `artifacts.py`, server/healthz, their tests, the ADR, this report, and the standing-rule-4 cite re-pin (`docs/DEPLOY.md`, `tests/test_deploy_alerts.py`). No README.md and no keep-alive code.

## Open issues

- **AVX512 is unverified here.** This CPU cannot run it (SIGILL). The script makes it moot for export, since it always dispatches avx2, but the raw AVX512 digest is the CTO's measurement alone.
- **The CTO's literal search hashes are not reproduced** (§4). The equivalence is re-measured under five definitions, but `20bf48af596a4d4d` / `73463e64b1ce508a` need the CTO's harness.
- **Every existing export must be redone after merge** (§6), including this box's `/cache/models/granite-english-r2-onnx`. Until then that box's server is BM25 only, and the 5 tests in §7 fail there.
- **Possible conflict with R4-COND.** This PR re-pins all 52 `app/server.py` cites in `docs/DEPLOY.md`, as standing rule 4 requires. If R4-COND (Grok) also edits those lines, whichever lands second must re-run the check. `test_deploy_alerts` catches any miss.
- The runbook still has no row for the `ONNX GRAPH NOT BUILT` line or the new `/healthz` fields. D2 still fires, because its line is emitted first.
- The order fix relies on CPython 3.12's seeded string hash. If a future interpreter maps seed 0 differently, `_check_trace_order` stops the export with a message. The lasting fix is upstream `sorted(set(...))`.
- Scratch files are safe to delete: `/cache/w4-onnx-matrix/` (about 0.6 GB: one kept fp32 graph, logs, matrix data), `/cache/w4-onnx-avx2/` (about 0.75 GB) and `/cache/w4-onnx-repro/` (95, about 1.5 GB).

## Dependencies added

None.
