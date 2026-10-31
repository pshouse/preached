# W4-ONNX-PIN-REPRO: a fresh export reproduces the pinned graph

Fresh-clone BLOCKER 2 (`reports/W4-FRESH-CLONE-QA.md` on `qa/w4-fresh-clone`, PR #68, finding 2). Branch `fix/w4-onnx-pin-repro`, PR #71. Task 95 did the first pass. Task 96 (`96-W4-ONNX-AVX2-PIN`) applied the CTO's avx2 ruling. Task 96-W4-ONNX-MATRIX adds the CTO's hard requirements: the full seed × dispatch matrix, a pin for each variable that moves the bytes, a two-export test that varies the ambient seed and dispatch level, and re-measured equivalence. This report describes the branch as it now stands.

**Result.** Both variables drive the bytes, so the export fixes both: `ATEN_CPU_CAPABILITY=avx2` (set before torch is imported) and `PYTHONHASHSEED=1` (re-exec). Seed 1 + avx2 reproduces the **existing pin `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`**, so there is no re-pin: `src/preached/artifacts.py` and `docs/DEPLOY.md` are back to the main values, and the shared `/cache` graph (also `3861025a`) matches. Through `scripts/export_onnx.py`, all 21 ambient cells (seed unset, 0-5 × dispatch default, avx2, avx512) exit 0 and write the pin. The raw 18-cell matrix agrees with the CTO's seeded exports. The graphs `aed7adba…` (avx2 + seed 0) and `3861025a…` are functionally identical. The decision record is `docs/adr/0001-onnx-export-determinism.md`.

History: task 96 wrongly re-pinned to `aed7adba…` (seed 0) and attributed the difference to dispatch. The CTO's correction showed seed alone splits the pin from `aed7adba`, and that default dispatch changes bytes on its own. This task supersedes 96's pin and wording.

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

### 1b. Through the script: one digest, the pin

`/tmp/seed1m/cell.sh` (not committed) runs the real `uv run --group bench python scripts/export_onnx.py` once per cell into `/cache/w4-onnx-seed1/<cap>-<seed>` (a branch-specific cache; the shared `/cache/models` graph is never written), with the cell's values as the **ambient** environment. Output: `/cache/w4-onnx-seed1/script.tsv`.

| ambient `ATEN_CPU_CAPABILITY` | ambient `PYTHONHASHSEED` unset / 0 / 1 / 2 / 3 / 4 / 5 |
| --- | --- |
| default | `3861025a…8fa9` ×7, exit 0 |
| avx2 | `3861025a…8fa9` ×7, exit 0 |
| avx512 | `3861025a…8fa9` ×7, exit 0 |

All 21 cells: exit 0, `fp32 sha256 matches the pin`, fp32 `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`, and manifest sha256 `96f276e6b10d89cea0aa763e61f99af1b8e082353a8e3f1397908b0cf6f064fd` in every cell (so int8, tokenizer and pooling are identical too). The ambient avx512 cells run here because the script replaces the value with avx2 before torch is imported.

**Reconciliation with the CTO's cells.** Raw avx2 + seed 1 → `3861025a` and avx2 + seed 0 → `aed7adba` (this host, §1a) match the CTO. Raw default dispatch → `d99ba823` (seed 0/3/4/5) or `44038d45` (seed 1/2) matches the CTO's "d99ba823 or 44038d45 by seed class". The CTO's AVX512 cells (seed 0 or 3 → `aed7adba`, seed 1 → `3861025a`) equal my avx2 cells for the same seeds; I cannot run raw AVX512 here (SIGILL), so those are the CTO's, not re-verified. **No disagreement.** The r1 claim that dispatch alone explained the bytes was wrong, and it is removed.

**A bug found on the way.** My first re-exec guard also tested `sys.flags.hash_randomization`. That flag reads 1 under every seed except 0, so under seed 1 the script re-executed itself forever (the first matrix attempt hung, burning CPU, until I killed it). The guard now tests only `PYTHONHASHSEED == "1"`; a numeric seed wins over `-R` (checked: `PYTHONHASHSEED=1 python -R` iterates sliding first). `HashSeedReexecTests` covers it.

## 2. Fix

`scripts/export_onnx.py`, run as `__main__`:

1. `_require_avx2()` refuses a host that is not `x86_64`/`amd64`, a CPU whose `/proc/cpuinfo` flags lack `avx2`, or an unreadable cpuinfo (exit 1, message names AVX2).
2. `_reexec_with_hashseed()`: the seed cannot be set in a running interpreter, so the script sets `PYTHONHASHSEED=1` (`EXPORT_HASHSEED`) and `os.execv`s itself unless it is already `1`. This happens before torch is imported.
3. `ATEN_CPU_CAPABILITY=avx2` is set at module top, before torch is imported, overriding any ambient value. `main()` refuses unless `get_cpu_capability() == "AVX2"`.
4. `_check_trace_order` refuses unless `set(config.layer_types)` iterates `["sliding_attention", "full_attention"]` (seed 1 on CPython 3.12).
5. `_check_pin` exits non-zero before writing a manifest if the fp32 graph is not the pin.

`src/preached/artifacts.py` keeps `FP32_ONNX_SHA256 = 3861025a…` (only comments and the missing-graph additions differ from main). `docs/DEPLOY.md` quotes the same value as main (the 96 edits to the two sha quotes are reverted).

## 3. Startup log and /healthz

`app/server.py`, in `load_search`'s `except ArtifactMissing` branch:

- Logs `ERROR embedding model unavailable; serving BM25 only` (`UNAVAILABLE_LOG`). This fixes a regression I introduced in 95: the runbook's D2 page (`deploy-embedding-unavailable-bm25`) matches that line, and 95 had replaced it.
- Then logs the loud line `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. missing ONNX manifest at …; build it with: CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py`.
- Returns the new `MISSING_GRAPH_NOTE` ("The search model has not been built; results are BM25 only."). Startup logs it again as a WARNING, and search responses carry it as `note`.

`App.health()` (`/healthz`) gains two fields:

- `search_mode`: `"hybrid"` or `"bm25"`.
- `search_mode_reason`: `null` when hybrid. When BM25, a code from `SEARCH_MODE_REASONS`: `onnx_graph_not_built`, `model_unavailable`, `stale_vectors`, `index_unreadable`, `bm25_only` (started with `--bm25-only`), or `fallback` for any other note. It is a code, never a path. A graph that is present but not the pin (for example an old `3861025a` export) is `model_unavailable`.

## 4. Equivalence of the two avx2 graphs (evidence kept from task 96)

Because the pin is unchanged, nothing at runtime changes. For the record, the avx2 / seed 0 graph `aed7adba…` was compared with the pin `3861025a…` (old scripts, now gone; output `/cache/w4-onnx-matrix/equiv.json`; ORT CPU, 1 thread):

- Header equal. **Initializers: 134 / 134 byte-identical.** Nodes: 3009 each, 6 differ (`rotary_emb/Constant_1`, `rotary_emb_1/Constant`, `layers.{0,1}/attn/Unsqueeze_{2,3}`).
- **ORT outputs bitwise identical** (max abs diff 0.0) on all 93 `eval/questions.jsonl` queries and 21 corpus chunks.
- `App.search(q, 10, "hybrid")` on `/cache/index/wesley.sqlite`: top-10 identical 93 / 93. Response, chunk-id and vector hashes were equal under both graphs (`f66c732275af497f`, `c397bf6f45d22114`, `7d11acdaaa1f1c20`, `29b07255a0733b1f`, `66b31d7885d2d20e`). The CTO's literal `20bf48af596a4d4d` / `73463e64b1ce508a` are not reproduced (harness not in the repo).

This evidence was not re-run in this task (the pin did not move); it is stated as measured in 96.

## 5. Tests (hard requirement 3)

`tests/test_onnx_pin_repro.py` (18 tests):

| Class | What it proves |
| --- | --- |
| `MissingGraphMessageTests` (4) | A missing manifest or graph logs `ONNX GRAPH NOT BUILT` with the path and `EXPORT_COMMAND`, plus the D2 alert line, and returns `MISSING_GRAPH_NOTE`. A wrong graph is not called unbuilt. `ArtifactMissing` is an `ArtifactError`. |
| `HealthzSearchModeTests` (3) | `/healthz` `search_mode` / `search_mode_reason` for a missing graph, another load failure, `--bm25-only`, and hybrid. |
| `Avx2GuardTests` (4) | Importing the script sets `ATEN_CPU_CAPABILITY=avx2` (over `default`) before torch is imported. Non-x86-64 hosts, cpuinfo without `avx2`, and a missing cpuinfo are refused. The script run as `__main__` on a faked `arm64` exits non-zero. |
| `MutantGraphTests` (1) | One flipped mantissa bit, with a manifest rewritten to agree, is refused by `verify_manifest` and `OnnxEmbedder.load`. |
| `TraceOrderTests` (2) | `PINNED_TRACE_ORDER` is sliding first. `EXPORT_HASHSEED` (1) passes `_check_trace_order`, and seed 0 is refused. |
| `HashSeedReexecTests` (3) | `_reexec_with_hashseed()` in a subprocess with `os.execv` recorded. Ambient seed unset, `random`, 0, 2, 3, 4, 5: each restarts `sys.executable` on the script with `PYTHONHASHSEED=1`. Ambient `1`: no restart, also under `-R`. |
| `ExportIsByteIdenticalTests` (1) | Three real exports from different ambient settings: (a) seed unset, dispatch `default`; (b) seed 0, `avx2`; (c) seed 3, `avx512`. All exit 0, the fp32 files are byte-identical (`filecmp`, not shallow) and equal the pin `3861025a…`, tokenizer equals its pin, `verify_manifest` passes, manifests identical. Skips only when the Granite snapshot is absent from `PREACHED_CACHE`. |

`PREACHED_CACHE=/cache uv run python -m unittest discover -s tests -p test_onnx_pin_repro.py -v`: see §7 for the full-suite run, which includes it.

`tests/test_deploy_alerts.py` `CITED` is re-pinned (§7).

## 6. Existing exports and the demo box

The pin did not move, so **no re-export is needed anywhere**. Verified: `/cache/models/granite-english-r2-onnx/47ea…/model.fp32.onnx` hashes to `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`, and the full suite passes against it (§7). The 3 failures and 2 errors that 96 produced (§7 of the earlier report) came from the moved pin and are gone. The PR migration note is: no action after merge; a fresh clone runs `CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py` (x86-64 with AVX2) and gets the same bytes.

## 7. DEPLOY.md cites, merge, full suite, scope

### Standing rule 4: `app/server.py` changed, so its cites are re-pinned

This PR changes `app/server.py` (+23 lines: the `ArtifactMissing` import, the `MISSING_GRAPH_*` and `SEARCH_MODE_REASONS` constants, the `except ArtifactMissing` branch, and the two `/healthz` fields). So every `app/server.py` cite in `docs/DEPLOY.md` and in `tests/test_deploy_alerts.py` `CITED` is re-pinned in this PR.

- **Cites.** This task did not touch `app/server.py` (the cites re-pinned in 96 stand: main `0559b02`/`b2c7b77`, merged and green). Standing rule 4 holds: the full suite shows zero `test_every_cited_file_line_holds_its_string` failures. `docs/DEPLOY.md` differs from main only in the 96 cite numbers; its two fp32 sha quotes are back to `3861025a…`.

### Merge, lock, suite

`git fetch origin && git merge origin/main`: already up to date (main is `b2c7b77`, already merged by 96). `uv lock --check`: OK (`Resolved 79 packages`). No new dependencies.

Full suite, exact command: `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests` against the shared `/cache` graph (log `/cache/w4-onnx-seed1/suite.log`):

**`Ran 1023 tests in 266.212s`, `OK`.** Zero failures, zero errors, zero skipped. The three-export test ran and passed. The 3 failures and 2 errors from 96 are gone.

## 8. Diff scope

@@STAT@@

The files in scope: the export script, `artifacts.py`, server/healthz, their tests, the ADR, this report, and the standing-rule-4 cite re-pin (`docs/DEPLOY.md`, `tests/test_deploy_alerts.py`). No README.md and no keep-alive code.

## Open issues

- **Raw AVX512 is unverified here.** This CPU cannot run it (SIGILL). The script makes it moot for export, since it always dispatches avx2; the raw AVX512 cells are the CTO's measurement alone.
- **The CTO's literal search hashes are not reproduced** (§4), and the equivalence in §4 was measured in 96, not re-run.
- Any later PR that changes `app/server.py` above a cited line must re-pin again. `test_deploy_alerts` catches a miss.
- The runbook still has no row for the `ONNX GRAPH NOT BUILT` line or the new `/healthz` fields. D2 still fires, because its line is emitted first.
- The order fix relies on CPython 3.12's seeded string hash. If a future interpreter maps seed 1 differently, `_check_trace_order` stops the export with a message. The lasting fix is upstream `sorted(set(...))`.
- Scratch files are safe to delete: `/cache/w4-onnx-matrix/` (about 0.6 GB), `/cache/w4-onnx-avx2/` (about 0.75 GB), `/cache/w4-onnx-repro/` (95, about 1.5 GB) and `/cache/w4-onnx-seed1/` (this task: one kept pin graph, logs, `script.tsv`).

## Dependencies added

None.
