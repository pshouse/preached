# W4-ONNX-PIN-REPRO: a fresh export reproduces the pinned graph

Fresh-clone BLOCKER 2 (`reports/W4-FRESH-CLONE-QA.md` on `qa/w4-fresh-clone`, PR #68, finding 2). Branch `fix/w4-onnx-pin-repro`, PR #71. Task 95 did the first pass. Task 96 (`96-W4-ONNX-AVX2-PIN`) applied the CTO's avx2 ruling. Task 96-W4-ONNX-MATRIX adds the CTO's hard requirements: the full seed × dispatch matrix, a pin for each variable that moves the bytes, a two-export test that varies the ambient seed and dispatch level, and re-measured equivalence. Task 99-W4-ONNX-PIN-FIX1 (CTO changes on r1 at `1907d1f`) makes the ONNX paths follow `PREACHED_CACHE`, sandboxes the export tests, adds `__main__`-order and `main()` unit tests, and documents the missing-graph D2 form in DEPLOY.md (§9-§11). This report describes the branch as it now stands.

**Result.** Both variables drive the bytes, so the export fixes both: `ATEN_CPU_CAPABILITY=avx2` (set before torch is imported) and `PYTHONHASHSEED=1` (re-exec). Seed 1 + avx2 reproduces the **existing pin `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`**, so there is no re-pin: `src/preached/artifacts.py` and `docs/DEPLOY.md` are back to the main values, and the shared `/cache` graph (also `3861025a`) matches. Through `scripts/export_onnx.py`, all 21 ambient cells (seed unset, 0-5 × dispatch default, avx2, avx512) exit 0 and write the pin. The raw 18-cell matrix agrees with the CTO's seeded exports. The graphs `aed7adba…` (avx2 + seed 0) and `3861025a…` are functionally identical. The decision record is `docs/adr/0001-onnx-export-determinism.md`.

History: task 96 wrongly re-pinned to `aed7adba…` (seed 0) and attributed the difference to dispatch. The CTO's correction showed seed alone splits the pin from `aed7adba`, and that default dispatch changes bytes on its own. This task supersedes 96's pin and wording.

## 1. Cause: the matrix (hard requirement 1)

The two variables do not conflict. They act on different things, and each one alone moves the bytes:

- `PYTHONHASHSEED` sets the iteration order of `set(self.config.layer_types)` in transformers 5.22.1 ModernBERT (`modeling_modernbert.py:454`). That order decides which rotary table is traced first. The two orders swap the θ=10000 and θ=80000 Constants and rewire four `Unsqueeze` inputs (6 of 3009 nodes).
- `ATEN_CPU_CAPABILITY` sets the kernel that computes the `inv_freq` values stored in those Constants. Between `default` and `avx2`, 1 of 32 float32 values differs, by 1.5e-11.

Host: i9-12900K (AVX2, no AVX512), CPython 3.12.16, torch 2.15.0+cu132, transformers 5.22.1, onnx 1.23.2, `CUDA_VISIBLE_DEVICES=""`, `HF_HUB_OFFLINE=1`.

### 1a. Raw export: what moves the bytes

`/tmp/onnxmatrix/probe.py` (not committed, and no longer on disk: `/tmp` was a per-session tmpfs) loads the model and makes the same `torch.onnx.export` call as `scripts/export_onnx.py`, but without its environment overrides. Each cell is a fresh process with the two variables set. Output: `/cache/w4-onnx-matrix/raw.jsonl`. Full fp32 sha256 values:

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

`/tmp/seed1m/cell.sh` (not committed, and no longer on disk) runs the real `uv run --group bench python scripts/export_onnx.py` once per cell into `/cache/w4-onnx-seed1/<cap>-<seed>` (a branch-specific cache; the shared `/cache/models` graph is never written), with the cell's values as the **ambient** environment. Output: `/cache/w4-onnx-seed1/script.tsv`.

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

6. Paths follow `PREACHED_CACHE` (FIX1, MF1). `artifacts.onnx_root()` is `PREACHED_ONNX_DIR`, else `$PREACHED_CACHE/models/granite-english-r2-onnx`, else `/cache/models/granite-english-r2-onnx`. It used to be a hardcoded `/cache/...` constant (`DEFAULT_ONNX_ROOT`, now removed). The export writes to `artifact_dir()` and the server reads `artifact_dir()`, so they agree. The HF cache defaults to `$PREACHED_CACHE/huggingface`; an ambient `HF_HUB_CACHE` (the name huggingface_hub reads first) or `HUGGINGFACE_HUB_CACHE` wins, and both are set to the one in use.

`src/preached/artifacts.py` keeps `FP32_ONNX_SHA256 = 3861025a…`. Only comments, the missing-graph additions and `onnx_root()` differ from main. `docs/DEPLOY.md` quotes the same value as main (the 96 edits to the two sha quotes are reverted).

## 3. Startup log and /healthz

`app/server.py`, in `load_search`'s `except ArtifactMissing` branch:

- Logs `ERROR embedding model unavailable; serving BM25 only` (`UNAVAILABLE_LOG`). This fixes a regression I introduced in 95: the runbook's D2 page (`deploy-embedding-unavailable-bm25`) matches that line, and 95 had replaced it.
- Then logs the loud line `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. missing ONNX manifest at …; build it with: uv run --group bench python scripts/export_onnx.py`.
- Returns the new `MISSING_GRAPH_NOTE` ("The search model has not been built; results are BM25 only."). Startup logs it again as a WARNING, and search responses carry it as `note`.

`App.health()` (`/healthz`) gains two fields:

- `search_mode`: `"hybrid"` or `"bm25"`.
- `search_mode_reason`: `null` when hybrid. When BM25, a code from `SEARCH_MODE_REASONS`: `onnx_graph_not_built`, `model_unavailable`, `stale_vectors`, `index_unreadable`, `bm25_only` (started with `--bm25-only`), or `fallback` for any other note. It is a code, never a path. A graph that is present but not the pin (for example an `aed7adba` export, avx2 with seed 0) is `model_unavailable`.

**Parity hashes.** The two new keys change the three reference hashes that include `/healthz`: HTTP `41ef875c` (was `ead2d78f`); HTTP without church `b0ad4285` (was `a08cb861`); in-process `c3436409` (was `d5490339`). The side, search+sermon and in-process-without-health hashes are unchanged.

## 4. Equivalence of the two avx2 graphs (evidence kept from task 96)

Because the pin is unchanged, nothing at runtime changes. For the record, the avx2 / seed 0 graph `aed7adba…` was compared with the pin `3861025a…` (old scripts, now gone; output `/cache/w4-onnx-matrix/equiv.json`; ORT CPU, 1 thread):

- Header equal. **Initializers: 134 / 134 byte-identical.** Nodes: 3009 each, 6 differ (`rotary_emb/Constant_1`, `rotary_emb_1/Constant`, `layers.{0,1}/attn/Unsqueeze_{2,3}`).
- **ORT outputs bitwise identical** (max abs diff 0.0) on all 93 `eval/questions.jsonl` queries and 21 corpus chunks.
- `App.search(q, 10, "hybrid")` on `/cache/index/wesley.sqlite`: top-10 identical 93 / 93. Response, chunk-id and vector hashes were equal under both graphs (`f66c732275af497f`, `c397bf6f45d22114`, `7d11acdaaa1f1c20`, `29b07255a0733b1f`, `66b31d7885d2d20e`). The CTO's literal `20bf48af596a4d4d` / `73463e64b1ce508a` are not reproduced (harness not in the repo).

This evidence was not re-run in this task (the pin did not move); it is stated as measured in 96. Plainly: the scripts that produced it are gone and were never committed, and `equiv.json` exists only under `/cache` on this host, so nobody can re-derive these figures from the repo.

## 5. Tests (hard requirement 3)

`tests/test_onnx_pin_repro.py` (28 tests). No test downloads, exports for real, or writes under `/cache`, except `ExportIsByteIdenticalTests`, which exports for real but only into a TMPDIR temp dir and only reads the snapshot. Tests that run the script as `__main__` do it in a subprocess with a scratch environment: `PREACHED_CACHE`, `PREACHED_ONNX_DIR` and `HF_HOME` under a temp dir, `HF_HUB_OFFLINE=1`, no `PYTHONHASHSEED`, `os.execv` stubbed, and fake `torch` / `huggingface_hub` modules that stop `main()` at its first import. Each such test also asserts the temp dir is still empty afterwards.

| Class | What it proves |
| --- | --- |
| `MissingGraphMessageTests` (4) | A missing manifest or graph logs `ONNX GRAPH NOT BUILT` with the path and `EXPORT_COMMAND`, plus the D2 alert line, and returns `MISSING_GRAPH_NOTE`. A wrong graph is not called unbuilt. `ArtifactMissing` is an `ArtifactError`. |
| `HealthzSearchModeTests` (3) | `/healthz` `search_mode` / `search_mode_reason` for a missing graph, another load failure, `--bm25-only`, and hybrid. |
| `Avx2GuardTests` (4) | Importing the script sets `ATEN_CPU_CAPABILITY=avx2` (over `default`) before torch is imported. Non-x86-64 hosts, cpuinfo without `avx2`, and a missing cpuinfo are refused. Run as `__main__` on a faked `arm64` in the sandbox above, the script exits non-zero with the AVX2 message, and neither the execv stub nor `main()` is reached. |
| `MainOrderTests` (2) | `runpy` of the script as `__main__` (sandboxed; `platform.machine` and `/proc/cpuinfo` faked to an AVX2 x86-64 host; `sys.argv` carries `--extra-arg` and `x y`). With the seed unset, `0` or `random`, the output is exactly `AVX2` followed by one `EXEC` whose argv is `[script, "--extra-arg", "x y"]`. Under seed `1` it is `AVX2` then `MAIN`. |
| `ExportMainTests` (2) | `main()` in-process with torch, the Hub, the model load, the export, the ORT check and the quantizer stubbed, `PREACHED_CACHE` set to a temp dir and `PREACHED_ONNX_DIR` unset. A graph that is not the pin exits with "is not the pin" and leaves no manifest. With the pin patched to the stub graph's digest, all five files land in `$PREACHED_CACHE/models/granite-english-r2-onnx/<rev>/`. A stale file there is removed, a neighbour directory is kept, every recorded `rmtree` / `copyfile` / `mkdir` / `write_text` / `write_bytes` is inside that directory, and the server's default `verify_manifest()` reads the same directory. The test refuses to call `main()` at all unless `artifact_dir()` is inside the temp cache. |
| `OnnxRootTests` (2) | `onnx_root()` precedence: `PREACHED_ONNX_DIR`, else `$PREACHED_CACHE/models/granite-english-r2-onnx`, else `/cache/models/granite-english-r2-onnx`. With a custom `PREACHED_CACHE`, `load_search` names the manifest path under it and writes nothing but the test's own index there. |
| `HfCacheDefaultTests` (4) | HF cache follows `PREACHED_CACHE`, falls back to `/cache`, an explicit `HF_HOME` wins, and an explicit hub cache under either name (`HF_HUB_CACHE` or `HUGGINGFACE_HUB_CACHE`) wins, with both names set equal. |
| `MutantGraphTests` (1) | One flipped mantissa bit, with a manifest rewritten to agree, is refused by `verify_manifest` and `OnnxEmbedder.load`. The 597 MB copy now goes to TMPDIR, not beside the cache. Skips when `artifact_dir()` has no graph. |
| `TraceOrderTests` (2) | `PINNED_TRACE_ORDER` is sliding first. `EXPORT_HASHSEED` (1) passes `_check_trace_order`, and seed 0 is refused. |
| `HashSeedReexecTests` (3) | `_reexec_with_hashseed()` in a subprocess with `os.execv` recorded. Ambient seed unset, `random`, 0, 2, 3, 4, 5: each restarts `sys.executable` on the script with `PYTHONHASHSEED=1`. Ambient `1`: no restart, also under `-R`. |
| `ExportIsByteIdenticalTests` (1) | Three real exports from different ambient settings: (a) seed unset, dispatch `default`; (b) seed 0, `avx2`; (c) seed 3, `avx512`. Outputs go to a TMPDIR temp dir. The HF cache is a temp `HF_HOME` whose hub holds one symlink to the snapshot in `PREACHED_CACHE`, offline, so the snapshot is only read. All exit 0, the fp32 files are byte-identical (`filecmp`, not shallow) and equal the pin `3861025a…`, tokenizer equals its pin, `verify_manifest` passes, manifests identical. Skips only when the Granite snapshot is absent from `PREACHED_CACHE`. |

`tests/test_deploy_alerts.py` `CITED` gains the new D2 cites (§7).

## 6. Existing exports and the demo box

The pin did not move, so **no re-export is needed anywhere**. `/cache/models/granite-english-r2-onnx/47ea…/model.fp32.onnx` hashes to `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` and `verify_manifest(variant="fp32")` passes with pins enforced (checked 2026-10-31 16:30, after the restore in §9). Migration note for the PR: no action after merge. A host that sets `PREACHED_CACHE` to something other than `/cache` and relied on the old hardcoded `/cache/models/...` ONNX path must now set `PREACHED_ONNX_DIR=/cache/models/granite-english-r2-onnx` or move the export under `$PREACHED_CACHE/models/`. With `PREACHED_CACHE` unset or `/cache`, nothing changes. `scripts/build-bundle.sh` and `tests/test_shutdown.py` still default to `/cache/models/...` when `PREACHED_ONNX_DIR` is unset. They are out of this PR's scope and are listed under open issues.

## 7. DEPLOY.md cites, merge, full suite, scope

### Standing rule 4: `app/server.py` changed in this PR, so its cites are re-pinned

This PR changes `app/server.py` (+23 lines vs main: the `ArtifactMissing` import, the `MISSING_GRAPH_*` and `SEARCH_MODE_REASONS` constants, the `except ArtifactMissing` branch, and the two `/healthz` fields). Every `app/server.py` cite in `docs/DEPLOY.md` and `tests/test_deploy_alerts.py` `CITED` was re-pinned for that change in 96. FIX1 does not edit `app/server.py` further, so those pins stand. FIX1 adds new cites for SF1 (§10), each pinned in `CITED` and checked by reading `app/server.py` at this head (`sed -n`):

| Cite | Line at head |
| --- | --- |
| `:286` | `UNAVAILABLE_LOG = "embedding model unavailable; serving BM25 only"` |
| `:289` | `MISSING_GRAPH_LOG = "ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. %s"` |
| `:295-301` | `SEARCH_MODE_REASONS = {` … `}` |
| `:857` | `logging.error(UNAVAILABLE_LOG)` |
| `:858` | `logging.error(MISSING_GRAPH_LOG, exc)` |
| `:861` | `logging.exception(UNAVAILABLE_LOG)` |
| `:1337-1338` | `"search_mode": "hybrid" if self.encode is not None else "bm25",` / `"search_mode_reason": reason,` |

The full suite has zero `test_every_cited_file_line_holds_its_string` failures. `tests/test_deploy_regex.py` (PR #75) is not on main (`abdada3`), so there was nothing of it to re-pin.

### Merge, lock, suite

`git fetch && git merge origin/main` (merge commit, no rebase): main was `abdada3` (#68), 4 commits ahead of the branch. It merged cleanly, adding only `reports/W4-FRESH-CLONE-QA.md`. The branch is now **0 behind, 21 ahead** of `origin/main` `abdada3`. `uv lock --check`: `Resolved 79 packages`, OK. No new dependencies.

Full suite, exact command, on `9af1484` (code identical to the head; the later commits touch only this report and the ADR), with scratch caches:

`PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/tmp/onnxfix-suite/pc HF_HOME=/tmp/onnxfix-suite/hf uv run python -m unittest discover -s tests`

**`Ran 1033 tests in 218.389s`, `OK (skipped=9)`.** Zero failures, zero errors. The 9 skips are tests that need real artifacts, which a scratch cache does not have: 6 in `test_embed_backend` (granite ONNX artifacts), 1 in `test_eval_leak` (chunked corpus), and `ExportIsByteIdenticalTests` and `MutantGraphTests` here. Both scratch dirs were still empty afterwards.

Those two `test_onnx_pin_repro` tests were run separately against the real cache, with the network off and `/cache` mounted read-only (`unshare -rmn`, then `mount -o remount,bind,ro /cache`): `PREACHED_CACHE=/cache .venv/bin/python -m unittest discover -s tests -p test_onnx_pin_repro.py -k ExportIsByteIdentical -k MutantGraph`. Result: **`Ran 2 tests in 41.327s`, `OK`.** The three real exports wrote the pin into TMPDIR. Because `/cache` was read-only, they cannot have written there.

Not attributable to these tests, stated plainly: during the read-only run, `/cache/models`' mtime changed (16:31:23). My mount namespace could not write there (a `mkdtemp` probe in the same setup fails with EROFS), so another process on this host did it. During the full-suite run, `/cache/xdg/...` (deno and onnxruntime caches; the sandbox sets `XDG_CACHE_HOME=/cache/xdg`), `/cache/index/cc-speech.sqlite-shm` and the `/cache` directory mtime changed. I did not trace those. No test in this PR names them.

## 8. Diff scope

See "Diff stat" at the end (`git diff --stat origin/main..HEAD`, 9 files). The files in scope: the export script, `artifacts.py`, server/healthz, their tests, the ADR, this report, and `docs/DEPLOY.md` plus `tests/test_deploy_alerts.py` (cite re-pin and SF1). No README.md and no keep-alive code.

## Open issues

- **I deleted and then restored the shared `/cache` ONNX export (§9).** The fp32 graph and tokenizer are pinned, and they are byte-identical to what was there before. `model.int8.onnx`, `pooling.json` and `manifest.json` are the deterministic export's (manifest `96f276e6…`). Whether the 2026-10-30 originals of those three files had the same bytes was never recorded, so I cannot say. The runtime does not read int8.
- **Raw AVX512 is unverified here.** This CPU cannot run it (SIGILL). The script always dispatches avx2, so this does not matter for the export; the raw AVX512 cells are the CTO's measurement alone.
- **The CTO's literal search hashes are not reproduced** (§4). The §1a/§4 figures come from scripts that were never committed and are gone, plus files that exist only under `/cache` on this host.
- `scripts/build-bundle.sh:48` and `tests/test_shutdown.py:35` still default the ONNX root to `/cache/models/...`, ignoring `PREACHED_CACHE`. They are out of scope; a follow-up should make them use `artifact_dir()`'s rule.
- Any later PR that changes `app/server.py` above a cited line must re-pin again. `test_deploy_alerts` catches a miss.
- The order fix relies on CPython 3.12's seeded string hash. If a future interpreter maps seed 1 differently, `_check_trace_order` stops the export with a message. The lasting fix is upstream `sorted(set(...))`.
- Scratch dirs that are safe to delete: `/cache/w4-onnx-matrix/` (about 0.6 GB), `/cache/w4-onnx-avx2/` (about 0.75 GB), `/cache/w4-onnx-repro/` (95, about 1.5 GB). Keep `/cache/w4-onnx-seed1/avx2-1/` until someone has confirmed the restored `/cache/models` export; it was the restore source.

## Dependencies added

None.

## 96-W4-ONNX-HFHOME addendum

`scripts/export_onnx.py` now defaults `HF_HOME` to `$PREACHED_CACHE/huggingface` and the hub cache to `$HF_HOME/hub`, falling back to `/cache` only when `PREACHED_CACHE` is unset. An explicit `HF_HOME` wins. The default is set at import, before the `PYTHONHASHSEED` restart and any HF/torch import, and the restart inherits it. `HfCacheDefaultTests` covers the three cases without downloading anything.

## 9. FIX1: paths follow PREACHED_CACHE, sandboxed tests, mutants (MF1, MF2, SF3)

**MF1.** `artifacts.onnx_root()` is now `PREACHED_ONNX_DIR`, else `$PREACHED_CACHE/models/granite-english-r2-onnx`, else `/cache/...` (§2 item 6). The export and the server both go through `artifact_dir()`. `ExportMainTests` and `OnnxRootTests` (§5) show that with a custom `PREACHED_CACHE` the export writes all five files under it, every write, mkdir and rmtree stays inside the export dir, a neighbour dir is untouched, and the server's default `verify_manifest()` and its missing-graph message use the same path.

**MF2.** `test_the_script_exits_non_zero_on_a_refused_host` runs in the sandbox described in §5 (tmp `PREACHED_ONNX_DIR`, `PREACHED_CACHE` and `HF_HOME`, `HF_HUB_OFFLINE=1`, stubbed `os.execv`, fake torch/hub). `ExportIsByteIdenticalTests` writes to a TMPDIR temp dir and reads the snapshot through a symlink in a temp `HF_HOME`. `MutantGraphTests` copies to TMPDIR, not beside the cache.

**Mutants.** Each mutant is one exact-string edit by a script, applied, run, then restored. After each, the file's sha256 matched the original (`scripts/export_onnx.py` `9515aea1ee7d`, `src/preached/artifacts.py` `b23468ef610f`). Every run was under `unshare -rmn` (no network) with `/cache` bind-mounted read-only, scratch `PREACHED_CACHE`/`HF_HOME`, `.venv/bin/python -m unittest discover -s tests -p test_onnx_pin_repro.py -k <class>`. After each run: scratch dir empty, nothing under `/cache` newer than the run's marker, and the real export's manifest+fp32 hash unchanged.

| Mutant | Test(s) | Result |
| --- | --- | --- |
| none (baseline) | Avx2Guard, MainOrder, ExportMain, OnnxRoot, HfCache | `Ran 14 tests`, OK |
| MF2: `_require_avx2()` removed from `__main__` | `Avx2GuardTests` | FAIL `test_the_script_exits_non_zero_on_a_refused_host`: `0 == 0 : EXEC [".../export_onnx.py"]` (reached the execv stub, exit 0). No network, no `/cache` write. |
| M11: `_reexec_with_hashseed()` removed from `__main__` | `MainOrderTests` | FAIL ×3 (seed unset, 0, random): `['MAIN'] != ['EXEC [...]']` |
| M8: restart argv drops `sys.argv[1:]` | `MainOrderTests` | FAIL ×3: `EXEC [".../export_onnx.py"]` vs `[..., "--extra-arg", "x y"]` |
| M9: `_check_pin(fp32)` removed from `main()` | `ExportMainTests` | FAIL `test_a_graph_that_is_not_the_pin_writes_no_manifest`: `SystemExit not raised` |
| MF1: `onnx_root()` ignores `PREACHED_CACHE` | `ExportMainTests`, `OnnxRootTests` | FAIL ×4. ExportMain: `export dir /cache/models/... is not under PREACHED_CACHE ...; main() not run`. OnnxRoot: wrong path. |
| nit: `HF_HUB_CACHE` ignored | `HfCacheDefaultTests` | FAIL (`HF_HUB_CACHE` subtest) |

**Incident during the first MF1 mutant run. I deleted the shared `/cache` ONNX export, then restored it.** The first pass ran these mutants without the read-only mount, and `ExportMainTests` had no guard. Under the MF1 mutant, `artifact_dir()` resolved to the real `/cache/models/granite-english-r2-onnx/47ea…/`. The stubbed `main()` then `rmtree`d that directory and wrote stub files into it. Afterwards it held only a 10-byte `model.fp32.onnx` ("stub graph"). It happened at 16:29, and I found it at once from the run's `/cache` check ("newer than marker: 3").

- **Restore (16:30):** I removed the stub and copied (`cp`, real copies, not links) the five files from `/cache/w4-onnx-seed1/avx2-1/47ea…/`. That directory is one of the 21 §1b script exports, all of which produced identical manifests. Resulting sha256 values: fp32 `3861025a…` (the pin), tokenizer `6c8aaa9a…` (pinned), int8 `220d6de9…`, pooling `bf147696…`, manifest `96f276e6…`. `PREACHED_CACHE=/cache` `verify_manifest(variant="fp32")` with pins enforced: OK. The later read-only run (§7) loaded that graph and passed.
- **What is not known:** the pre-incident int8, pooling and manifest bytes were never recorded (see Open issues). If the directory held any other files besides the export's five, they are gone.
- **Why it cannot recur:** `ExportMainTests._main` now refuses to call `main()` unless `artifact_dir()` is inside the test's temp cache. That is how the MF1 mutant fails above, without touching anything. All mutant runs after the incident also mounted `/cache` read-only.

## 10. FIX1: DEPLOY.md D2 (SF1)

- The D2 row now says it fires only at startup **in two forms**. A load failure logs it with a traceback (`:861`). A missing graph or manifest logs it with `logging.error`, no traceback (`:857`), and the next line is `ERROR ONNX GRAPH NOT BUILT…`. The Infra regex `^ERROR embedding model unavailable; serving BM25 only$` matches both. `MissingGraphMessageTests` asserts the exact line `ERROR:root:embedding model unavailable; serving BM25 only`, and the server's log format is `%(levelname)s %(message)s`.
- A new non-alert row, "D2 detail", covers the `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only.` line (`:858`, text `:289`) and the `/healthz` `search_mode` / `search_mode_reason` fields (`:1337-1338`, codes `:295-301`), with every reason code.
- The observability bullet's "D1 and D2 at startup still carry a traceback" now excepts D2's missing-graph form.
- New `CITED` pins: `:289`, `:295-301`, `:857`, `:858`, `:1337-1338` (§7 table). No existing cite moved, because FIX1 did not edit `app/server.py`.

## 11. FIX1: accuracy (SF2) and nits

- §3: the non-pin example is now `aed7adba` (`3861025a` is the pin).
- §7: no longer says `app/server.py` is untouched. The PR changes it; FIX1 does not change it further.
- Main sha (`abdada3`), suite count (1033), and the diff stat are refreshed.
- ADR Context lists all four digests, including `44038d45`. The ADR Consequences claim of "never touches /cache" is now true and is stated precisely: with `PREACHED_CACHE` set and no cache variable pointing elsewhere, the export writes and removes only under it.
- Nit, `HF_HUB_CACHE`: an ambient `HF_HUB_CACHE` (which huggingface_hub 2.4.0 prefers) or `HUGGINGFACE_HUB_CACHE` now wins, and both are set to the one in use.
- Nit, equivalence figures: the §1a/§4 scripts were never committed and no longer exist. The JSON outputs exist only under `/cache` on this host. I am stating that plainly rather than committing a reconstructed script.

## PR BODY

(Replacement for PR #71's body. The coordinator pastes it.)

```markdown
## W4-ONNX-PIN-REPRO: a fresh export reproduces the pinned ONNX graph

Fixes fresh-clone BLOCKER 2 (#68 finding 2). The pin stays `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`; there is no re-pin.

### What moved the bytes
Two independent variables, and each one alone changes the exported fp32 graph (measured, 12-cell raw matrix, i9-12900K):
- `PYTHONHASHSEED`: transformers 5.22.1 ModernBERT traces its two rotary tables in `set(config.layer_types)` order (6 of 3009 nodes differ).
- `ATEN_CPU_CAPABILITY`: the dispatch level changes one float32 of the `inv_freq` Constants (default vs avx2).
Four digests come out, one per (order, dispatch) pair: `3861025a` (avx2, sliding first: the pin), `aed7adba` (avx2, full first), `44038d45` and `d99ba823` (default dispatch). Neither variable is "the" cause; both must be fixed. Raw AVX512 cannot run on this host (SIGILL); the CTO's AVX512 cells are not re-verified.

### Fix
- `scripts/export_onnx.py`: sets `ATEN_CPU_CAPABILITY=avx2` before importing torch; refuses non-x86-64 or non-AVX2 hosts; re-execs under `PYTHONHASHSEED=1` (argv kept); checks the trace order; exits non-zero with no manifest if the graph is not the pin. Through the script, all 21 ambient cells (seed unset/0-5 × default/avx2/avx512) write the pin.
- ONNX outputs and the server default follow `PREACHED_CACHE`: `PREACHED_ONNX_DIR`, else `$PREACHED_CACHE/models/granite-english-r2-onnx`, else `/cache/...`. The HF cache defaults to `$PREACHED_CACHE/huggingface` (an explicit `HF_HOME` / `HF_HUB_CACHE` / `HUGGINGFACE_HUB_CACHE` wins).
- `app/server.py`: a missing graph logs the D2 line `ERROR embedding model unavailable; serving BM25 only` (no traceback), then `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; …` with the path and export command. `/healthz` gains `search_mode` (`hybrid`/`bm25`) and `search_mode_reason` (a code, never a path).
- `docs/DEPLOY.md`: D2 row covers both forms, new "D2 detail" row for the NOT BUILT line and the `/healthz` fields; cites pinned in `tests/test_deploy_alerts.py`.
- ADR: `docs/adr/0001-onnx-export-determinism.md`.

### Tests
`tests/test_onnx_pin_repro.py` (28 tests). No test downloads or writes under `/cache`. `__main__` runs are sandboxed (scratch caches, offline, stubbed `os.execv` and `main`). The three-export byte-identity test writes to TMPDIR and only reads the snapshot. Mutants (each fails, then reverted): avx2 guard removed from `__main__`, seed restart removed, restart drops argv, `_check_pin` removed, `onnx_root` ignoring `PREACHED_CACHE`, `HF_HUB_CACHE` ignored.

Full suite, final head (R2): `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests` → `Ran 1033 tests`, `OK`, 0 failures, 0 skips (real artifacts present; an earlier scratch-cache run gave `OK (skipped=9)`). The two real-artifact tests in this file, run separately against `/cache` mounted read-only with the network off: `Ran 2 tests`, `OK`. `uv lock --check` OK. No new dependencies.

### Migration
None for `/cache` hosts: the existing `3861025a` export stays valid. A host with `PREACHED_CACHE` other than `/cache` that kept the export at `/cache/models/...` must set `PREACHED_ONNX_DIR` or move it.

### Incident
While running a mutant, a test removed and rewrote the shared `/cache/models/granite-english-r2-onnx/47ea…/`. It was restored from an identical script export (fp32 and tokenizer match their pins; `verify_manifest` OK). The test now refuses to run `main()` outside its temp cache. Details: `reports/W4-ONNX-PIN-REPRO.md` §9.

### Branch state
0 behind, 21 ahead of `origin/main` (`abdada3`).

`git diff --stat origin/main..HEAD`:

```
 app/server.py                            |  23 +
 docs/DEPLOY.md                           | 114 ++---
 docs/adr/0001-onnx-export-determinism.md |  53 +++
 reports/W4-ONNX-PIN-REPRO.md             | 282 ++++++++++++
 scripts/export_onnx.py                   | 123 ++++-
 src/preached/artifacts.py                |  31 +-
 tests/test_deploy_alerts.py              |  97 ++--
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 760 +++++++++++++++++++++++++++++++
 9 files changed, 1372 insertions(+), 115 deletions(-)
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## Diff stat

`git diff --stat origin/main..HEAD`:

```
 app/server.py                            |  23 +
 docs/DEPLOY.md                           | 114 ++---
 docs/adr/0001-onnx-export-determinism.md |  53 +++
 reports/W4-ONNX-PIN-REPRO.md             | 282 ++++++++++++
 scripts/export_onnx.py                   | 123 ++++-
 src/preached/artifacts.py                |  31 +-
 tests/test_deploy_alerts.py              |  97 ++--
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 760 +++++++++++++++++++++++++++++++
 9 files changed, 1372 insertions(+), 115 deletions(-)
```

## R2 (99-W4-ONNX-R2)

- Parity hashes recorded in §3 and the ADR (the `/healthz` keys change three reference hashes).
- `EXPORT_COMMAND` (`src/preached/artifacts.py`), the `scripts/export_onnx.py` docstring, the DEPLOY.md D2 detail row and the §3 log line no longer recommend `CUDA_VISIBLE_DEVICES=""`; the script sets it before torch and the bytes are identical either way. The line in §1 and W3/W4-QA reports are records of commands actually run and stay.
- Verified, no edits: DEPLOY.md cites and `CITED` pins hold at HEAD (the edits above change text within cited lines, not line numbers; zero `test_every_cited_file_line_holds_its_string` failures). No test writes under `/cache`.
- Suite: `Ran 1033 tests`, `OK`, merge of `origin/main` was a no-op.
