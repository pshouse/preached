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

`tests/test_onnx_pin_repro.py` (31 tests). No test downloads. Only `ExportIsByteIdenticalTests` exports for real, into a TMPDIR temp dir, and it only reads the snapshot. Every test points its outputs at temp dirs. Only `ExportMainTests` also checks each destructive call: it resolves the path and refuses anything outside the temp root and its temp cache (r3, §12). The other tests are kept off `/cache` by their temp environment alone, not by a check. In r2 the guard was lexical, and a `..` path or a symlinked `models` dir got past it (§12). Tests that run the script as `__main__` do it in a subprocess with a scratch environment: `PREACHED_CACHE`, `PREACHED_ONNX_DIR` and `HF_HOME` under a temp dir, `HF_HUB_OFFLINE=1`, no `PYTHONHASHSEED`, `os.execv` stubbed, and fake `torch` / `huggingface_hub` modules that stop `main()` at its first import. Each such test also asserts the temp dir is still empty afterwards.

| Class | What it proves |
| --- | --- |
| `MissingGraphMessageTests` (4) | A missing manifest or graph logs `ONNX GRAPH NOT BUILT` with the path and `EXPORT_COMMAND`, plus the D2 alert line, and returns `MISSING_GRAPH_NOTE`. A wrong graph is not called unbuilt. `ArtifactMissing` is an `ArtifactError`. |
| `HealthzSearchModeTests` (3) | `/healthz` `search_mode` / `search_mode_reason` for a missing graph, another load failure, `--bm25-only`, and hybrid. |
| `Avx2GuardTests` (4) | Importing the script sets `ATEN_CPU_CAPABILITY=avx2` (over `default`) before torch is imported. Non-x86-64 hosts, cpuinfo without `avx2`, and a missing cpuinfo are refused. Run as `__main__` on a faked `arm64` in the sandbox above, the script exits non-zero with the AVX2 message, and neither the execv stub nor `main()` is reached. |
| `MainOrderTests` (2) | `runpy` of the script as `__main__` (sandboxed; `platform.machine` and `/proc/cpuinfo` faked to an AVX2 x86-64 host; `sys.argv` carries `--extra-arg` and `x y`). With the seed unset, `0` or `random`, the output is exactly `AVX2` followed by one `EXEC` whose argv is `[script, "--extra-arg", "x y"]`. Under seed `1` it is `AVX2` then `MAIN`. |
| `ExportMainTests` (5) | `main()` in-process with torch, the Hub, the model load, the export, the ORT check and the quantizer stubbed, `PREACHED_CACHE` set to a temp dir and `PREACHED_ONNX_DIR` unset. A graph that is not the pin exits with "is not the pin" and leaves no manifest. With the pin patched to the stub graph's digest, all five files land in `$PREACHED_CACHE/models/granite-english-r2-onnx/<rev>/`. A stale file there is removed, a neighbour directory is kept, every recorded `rmtree` / `copyfile` / `mkdir` / `write_text` / `write_bytes` is inside that directory, and the server's default `verify_manifest()` reads the same directory. Before `main()` is called, `artifact_dir()` is resolved and must be under `tempfile.gettempdir()` and the resolved temp cache. Every recorded `rmtree`, `copyfile` (destination), `mkdir`, `write_text` and `write_bytes` gets the same check before it runs. Three tests show the guard holds: a `..` export dir, a `models` dir that is a symlink out of the temp cache, and an export that writes outside it from inside `main()`. In each, a canary beside the temp cache survives and nothing is written there. |
| `OnnxRootTests` (2) | `onnx_root()` precedence: `PREACHED_ONNX_DIR`, else `$PREACHED_CACHE/models/granite-english-r2-onnx`, else `/cache/models/granite-english-r2-onnx`. With a custom `PREACHED_CACHE`, `load_search` names the manifest path under it and writes nothing but the test's own index there. |
| `HfCacheDefaultTests` (4) | HF cache follows `PREACHED_CACHE`, falls back to `/cache`, an explicit `HF_HOME` wins, and an explicit hub cache under either name (`HF_HUB_CACHE` or `HUGGINGFACE_HUB_CACHE`) wins, with both names set equal. |
| `MutantGraphTests` (1) | One flipped mantissa bit, with a manifest rewritten to agree, is refused by `verify_manifest` and `OnnxEmbedder.load`. The 597 MB copy now goes to TMPDIR, not beside the cache. Skips when `artifact_dir()` has no graph. |
| `TraceOrderTests` (2) | `PINNED_TRACE_ORDER` is sliding first. `EXPORT_HASHSEED` (1) passes `_check_trace_order`, and seed 0 is refused. |
| `HashSeedReexecTests` (3) | `_reexec_with_hashseed()` in a subprocess with `os.execv` recorded. Ambient seed unset, `random`, 0, 2, 3, 4, 5: each restarts `sys.executable` on the script with `PYTHONHASHSEED=1`. Ambient `1`: no restart, also under `-R`. |
| `ExportIsByteIdenticalTests` (1) | Three real exports from different ambient settings: (a) seed unset, dispatch `default`; (b) seed 0, `avx2`; (c) seed 3, `avx512`. Outputs go to a TMPDIR temp dir. The HF cache is a temp `HF_HOME` whose hub holds one symlink to the snapshot in `PREACHED_CACHE`, offline, so the snapshot is only read. All exit 0, the fp32 files are byte-identical (`filecmp`, not shallow) and equal the pin `3861025a…`, tokenizer equals its pin, `verify_manifest` passes, manifests identical. Skips only when the Granite snapshot is absent from `PREACHED_CACHE`. |

`tests/test_deploy_alerts.py` `CITED` gains the new D2 cites (§7).

## 6. Existing exports and the demo box

The pin did not move, so **no re-export is needed anywhere**. `/cache/models/granite-english-r2-onnx/47ea…/model.fp32.onnx` hashes to `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` and `verify_manifest(variant="fp32")` passes with pins enforced (checked 2026-10-31 16:30 ET, after the restore in §9). Migration note for the PR: no action after merge. A host that sets `PREACHED_CACHE` to something other than `/cache` and relied on the old hardcoded `/cache/models/...` ONNX path must now set `PREACHED_ONNX_DIR=/cache/models/granite-english-r2-onnx` or move the export under `$PREACHED_CACHE/models/`. With `PREACHED_CACHE` unset or `/cache`, nothing changes. `scripts/build-bundle.sh` and `tests/test_shutdown.py` still default to `/cache/models/...` when `PREACHED_ONNX_DIR` is unset. They are out of this PR's scope and are listed under open issues.

## 7. DEPLOY.md cites, merge, full suite, scope

### Standing rule 4: `app/server.py` changed in this PR, so its cites are re-pinned

This PR changes `app/server.py` (+23 lines vs main: the `ArtifactMissing` import, the `MISSING_GRAPH_*` and `SEARCH_MODE_REASONS` constants, the `except ArtifactMissing` branch, and the two `/healthz` fields). Every `app/server.py` cite in `docs/DEPLOY.md` and `tests/test_deploy_alerts.py` `CITED` was re-pinned for that change in 96, and again in `ad50b77` after merging #72 (keep-alive, +55 lines in `app/server.py`) moved them. The SF1 cites (§10) on the merged `app/server.py`, each read off the file with `sed -n` (r3 re-read all 68 `CITED` pins; table in §12):

| Cite | Line at head |
| --- | --- |
| `:297` | `UNAVAILABLE_LOG = "embedding model unavailable; serving BM25 only"` |
| `:300` | `MISSING_GRAPH_LOG = "ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. %s"` |
| `:306-312` | `SEARCH_MODE_REASONS = {` … `}` |
| `:868` | `logging.error(UNAVAILABLE_LOG)` |
| `:869` | `logging.error(MISSING_GRAPH_LOG, exc)` |
| `:872` | `logging.exception(UNAVAILABLE_LOG)` |
| `:1348-1349` | `"search_mode": "hybrid" if self.encode is not None else "bm25",` / `"search_mode_reason": reason,` |

The full suite has zero `test_every_cited_file_line_holds_its_string` failures. `tests/test_deploy_regex.py` (PR #75) is not on main (`abdada3`), so there was nothing of it to re-pin.

### Merge, lock, suite

`git fetch && git merge origin/main` (merge commit, no rebase): main was `abdada3` (#68), 4 commits ahead of the branch. It merged cleanly, adding only `reports/W4-FRESH-CLONE-QA.md`. After that merge the branch was 0 behind, 23 ahead of `origin/main` `abdada3`. For the current counts, see §12. `uv lock --check`: `Resolved 79 packages`, OK. No new dependencies.

Full suite, exact command, on `9af1484`, with scratch caches. This run predates later code changes: `031f7cb` changed `EXPORT_COMMAND` in `src/preached/artifacts.py`, the `scripts/export_onnx.py` docstring and the DEPLOY.md D2 detail row, `ad50b77` merged #72, and r3 changed the tests and the export script's CUDA message. The r3 run on the current head is in §12.

`PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/tmp/onnxfix-suite/pc HF_HOME=/tmp/onnxfix-suite/hf uv run python -m unittest discover -s tests`

**`Ran 1033 tests in 218.389s`, `OK (skipped=9)`.** Zero failures, zero errors. The 9 skips are tests that need real artifacts, which a scratch cache does not have: 6 in `test_embed_backend` (granite ONNX artifacts), 1 in `test_eval_leak` (chunked corpus), and `ExportIsByteIdenticalTests` and `MutantGraphTests` here. Both scratch dirs were still empty afterwards.

Those two `test_onnx_pin_repro` tests were run separately against the real cache, with the network off and `/cache` mounted read-only (`unshare -rmn`, then `mount -o remount,bind,ro /cache`): `PREACHED_CACHE=/cache .venv/bin/python -m unittest discover -s tests -p test_onnx_pin_repro.py -k ExportIsByteIdentical -k MutantGraph`. Result: **`Ran 2 tests in 41.327s`, `OK`.** The three real exports wrote the pin into TMPDIR. Because `/cache` was read-only, they cannot have written there.

Not attributable to these tests, stated plainly: during the read-only run, `/cache/models`' mtime changed (2026-10-31 16:31:23 ET). My mount namespace could not write there (a `mkdtemp` probe in the same setup fails with EROFS), so another process on this host did it. During the full-suite run, `/cache/xdg/...` (deno and onnxruntime caches; the sandbox sets `XDG_CACHE_HOME=/cache/xdg`), `/cache/index/cc-speech.sqlite-shm` and the `/cache` directory mtime changed. I did not trace those. No test in this PR names them.

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

**Incident during the first MF1 mutant run. I deleted the shared `/cache` ONNX export, then restored it.** The first pass ran these mutants without the read-only mount, and `ExportMainTests` had no guard. Under the MF1 mutant, `artifact_dir()` resolved to the real `/cache/models/granite-english-r2-onnx/47ea…/`. The stubbed `main()` then `rmtree`d that directory and wrote stub files into it. Afterwards it held only a 10-byte `model.fp32.onnx` ("stub graph"). It happened at 2026-10-31 16:29 ET, and I found it at once from the run's `/cache` check ("newer than marker: 3").

- **Restore (2026-10-31 16:30 ET):** I removed the stub and copied (`cp`, real copies, not links) the five files from `/cache/w4-onnx-seed1/avx2-1/47ea…/`. That directory is one of the 21 §1b script exports, all of which produced identical manifests. Resulting sha256 values: fp32 `3861025a…` (the pin), tokenizer `6c8aaa9a…` (pinned), int8 `220d6de9…`, pooling `bf147696…`, manifest `96f276e6…`. `PREACHED_CACHE=/cache` `verify_manifest(variant="fp32")` with pins enforced: OK. The later read-only run (§7) loaded that graph and passed.
- **What is not known:** the pre-incident int8, pooling and manifest bytes were never recorded (see Open issues). If the directory held any other files besides the export's five, they are gone.
- **Guard since the incident:** in FIX1, `ExportMainTests._main` refused to call `main()` unless `artifact_dir()` was lexically inside the test's temp cache. That check stopped the MF1 mutant above. It did not stop a `..` path or a symlinked `models` dir (CTO mutants F2 and F3). r3 makes the check resolved, adds it to every destructive call in the test, and adds tests for both cases (§12). All mutant runs after the incident also mounted `/cache` read-only. A guard in one test class can still be bypassed, so this is a mitigation, not a guarantee.

**Infra Ops verification (2026-10-31, ET; 99-W7-ONNX-INCIDENT).**

- **Timeline.** 4:29 PM: a mutant test run `rmtree`d `/cache/models/granite-english-r2-onnx/47ea694b257b703fee9253d75c2b1f2985180498/`. Restored 4:30 PM from `/cache/w4-onnx-seed1/avx2-1/`.
- **Export re-run.** Infra Ops ran `scripts/export_onnx.py` from the `5d8a5bf` tree into temp roots: exit 0, the AVX2 and seed-1 guards passed, and it printed "fp32 sha256 matches the pin". The fresh export, the restored folder and the seed1 copy are byte-identical, all 5 files:

  | File | sha256 (first 12) | Pin |
  | --- | --- | --- |
  | `model.fp32.onnx` | `3861025a186e` | pinned |
  | `model.int8.onnx` | `220d6de96c78` | unpinned by design |
  | `tokenizer.json` | `6c8aaa9a5420` | pinned |
  | `pooling.json` | `bf1476968368` | |
  | `manifest.json` | `96f276e6b10d` | |

  The export produces exactly these 5 files; nothing is missing, so the "if the directory held any other files" worry above is closed. Perms are 0755 and 0644, owner uid 1000.
- **Live demo.** Its process started at 13:50 and loads the graph once at startup, so it never loaded the damaged folder. `/healthz` at 4:49 PM: 200, `dense` true, `fallback` false, `model_sha256` `3861025a`. No restart was needed.
- **Church index.** The main db file is unchanged (ctime from Oct 30, no `-wal` growth). Only its `-shm` changed, at 4:50:31 PM ET, from a WAL open by a concurrent test suite. No leftover temp copies remain under `/cache/models`. The 597 MB in-cache test copy is being fixed by a separate PR (`fix/w5-cache-readonly-tests`).
- **Guard, as it is in the tree.** `ExportMainTests._main` (`tests/test_onnx_pin_repro.py`) resolves `artifact_dir()` and calls `self.fail(...)` unless `folder.is_relative_to(cache)`, where `cache` is a `tempfile.TemporaryDirectory()` the test created; `main()` (the only caller of `rmtree`) runs only after that check, so a mutant that sends the export to the real `/cache` fails without touching it. All mutant runs after the incident also mounted `/cache` read-only. **Gap against standing rule 5:** the check is against the test's own temp cache, not a call to `Path.resolve()` plus an assertion under `tempfile.gettempdir()`, and it covers `main()` in `ExportMainTests` only. It is not a general guard on every destructive call. This task is report-only, so the stricter assertion is not added here; it is a candidate follow-up. *(r3: added; see §12.)*

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

## PR BODY and diff stat

The current PR body and diff stat are in §12 (r3).

## R2 (99-W4-ONNX-R2)

- Parity hashes recorded in §3 and the ADR (the `/healthz` keys change three reference hashes).
- `EXPORT_COMMAND` (`src/preached/artifacts.py`), the `scripts/export_onnx.py` docstring, the DEPLOY.md D2 detail row and the §3 log line no longer recommend `CUDA_VISIBLE_DEVICES=""`; the script sets it before torch and the bytes are identical either way. The line in §1 and W3/W4-QA reports are records of commands actually run and stay.
- Verified, no edits: DEPLOY.md cites and `CITED` pins hold at HEAD (the edits above change text within cited lines, not line numbers; zero `test_every_cited_file_line_holds_its_string` failures). *(r3 correction: "No test writes under `/cache`" overclaimed. The ExportMainTests guard was lexical; see §12.)*
- Suite: `Ran 1033 tests`, `OK`, merge of `origin/main` was a no-op.

## 12. r3 (99-W7Z-ONNX-R3): CTO r2 on 27ed9cb, must-fixes MF-A, MF-B, MF-C and S1-S3

Head: code at `5f6a8fe` (merge of `origin/main` `ebffabb`). The report commit on top of it changes only this file. Branch vs `origin/main` `ebffabb`: **0 behind, 28 ahead** (the 28 include the report commit). Commits, add-only (merges, no rebase or force-push):

- `7d94518` resolved-path guard in `ExportMainTests`, three new tests, CUDA leftovers (S3).
- `5f6a8fe` merge of `origin/main` (#69 port-busy, `ebffabb`), cites re-pinned +3.
- this report commit.

Worktree: `/work/preached/.worktrees/onnx-pin` (branch `fix/w4-onnx-pin-repro`). I fast-forwarded it to the pushed head `ad50b77` (99-W7-ONNX-INCIDENT) first. Status was clean.

### MF-A: merge with main, re-pin

`ad50b77` (99-W7) had already merged `f75bbcb` (#72) and re-pinned the server cites. While this task ran, main moved to `ebffabb` (#69, deno hard-fail and port-busy). `git merge origin/main` conflicted again in `docs/DEPLOY.md` (10 hunks) and `tests/test_deploy_alerts.py` (`CITED`). With digits masked, #69's DEPLOY and `CITED` changes are line numbers only, plus the tree sentence. So I took this branch's side and moved every `app/server.py` cite at or after line 2731 by +3. #69 replaced `self.refusals.flush()` in `PreachedServer.server_close` (this branch's 2731) with four lines. That is 12 `CITED` pins, matching #69's own "+3 on 12" note, and 18 DEPLOY.md lines. The PR's own cites (`:297 :300 :302 :306-312 :863 :868 :869 :872 :1348-1349`) are above 2731 and did not move. I read each pin off the merged file (script that prints the line, plus `sed -n 3277,3296p` for the drain range). The full table is below.

### MF-B: the guard resolves, and it covers every destructive call in the test

`tests/test_onnx_pin_repro.py`:

- `_inside_scratch(path, cache)` resolves the path. It raises unless the result is under `Path(tempfile.gettempdir()).resolve()` and under `cache.resolve()`, and the scratch cache itself is under the temp root.
- `ExportMainTests._main` calls it on `artifact_dir()` before `main()`. It replaces the lexical `folder.is_relative_to(cache)`.
- Each recorded `shutil.rmtree`, `shutil.copyfile` (destination), `Path.mkdir`, `Path.write_text` and `Path.write_bytes` calls it **before** the real call runs.
- New tests: `test_a_dotdot_export_dir_is_refused_before_main` (a `PREACHED_ONNX_DIR` of `$cache/../real/models/...`), `test_a_symlinked_models_dir_is_refused_before_main` (`$cache/models` is a symlink to a sibling stand-in), and `test_a_write_that_escapes_inside_main_is_refused` (the pre-check passes; the stubbed export writes outside). In each, a canary in the stand-in survives and nothing new appears there. 28 → 31 tests in the file.

Mutants, each in a throwaway `git archive` copy under `/tmp/r3mut*`, with `unshare -rmn`, `/cache` bind-mounted read-only, and a fake `/cache/models` holding only `granite-english-r2-onnx/47ea…/canary` bind-mounted over the real one. Scratch `PREACHED_CACHE` and `HF_HOME`, `PREACHED_ONNX_DIR` unset, `ExportMainTests`:

- **F2** ('..' traversal): `onnx_root()`'s default branch returns `$PREACHED_CACHE/../../../../../../../../../../../../cache/models/...`.
- **F3** (symlinked `$PREACHED_CACHE/models`): the fixture makes `$cache/models` a symlink to `/cache/models` before the guard.

| Mutant | Guard | Result | Fake `/cache/models` afterwards |
| --- | --- | --- | --- |
| F2 | r2 (lexical, `ad50b77`) | 1 FAIL, 1 ERROR, but only after `main()` ran | **canary deleted**; `manifest.json`, `model.fp32.onnx`, `model.int8.onnx`, `pooling.json`, `tokenizer.json` written |
| F2 | r3 (`7d94518`, and again on `5f6a8fe`) | FAIL ×2: `… resolves to /cache/models/granite-english-r2-onnx/47ea…, outside the scratch cache /tmp/tmp…/pc under /tmp` | canary only |
| F3 | r2 | **OK** (escape not detected) | **canary deleted**; `model.fp32.onnx` written |
| F3 | r3 (`7d94518`, and again on `5f6a8fe`) | FAIL: `/tmp/tmp…/pc/models/granite-english-r2-onnx/47ea… resolves to /cache/models/…, outside the scratch cache` | canary only |

This reproduces the CTO's finding on r2 and shows r3 catches both mutants before anything is touched.

What the guard does not do: it lives in `ExportMainTests` only. Other tests in the file keep off `/cache` through their temp environment (and the `__main__` tests through fake `torch`/hub modules), not through a check. Code outside this file is not covered.

### MF-C: tree-relative wording

DEPLOY.md no longer names `b224281` (`grep -rn b224281 docs tests app scripts src`: no hits). The alert-table sentence reads "The line numbers below are this tree: main with the keep-alive hand-over (#72) and the port-busy hard fail (#69), plus the ONNX pin fix, in `app/server.py`." The "Other lines this runbook names" table says "all read off this tree". There is no sha in either.

### S1-S3

- S1: §7 now gives the old counts as "at that merge" and points here. The `9af1484` suite run is no longer called code-identical to the head: `031f7cb` changed `EXPORT_COMMAND`, the export-script docstring and the DEPLOY.md D2 detail row. The R2 note's "No test writes under `/cache`" is marked as an overclaim.
- S2: §9's 16:29 and 16:30 (and §6's 16:30 and §7's 16:31:23) now carry 2026-10-31 ET. "Why it cannot recur" is replaced by "Guard since the incident", which states the r2 gap and the r3 fix and makes no non-recurrence claim. Infra Ops' byte-identical result (99-W7) is kept as written, and its "Gap against standing rule 5" bullet is marked closed here.
- S3: `scripts/export_onnx.py:307` now reads "CUDA is visible even though the exporter hides it; export runs on CPU only". `reports/W3-CPU.md:39-40` loses the `CUDA_VISIBLE_DEVICES=""` prefixes. The test-module docstring and §5 no longer say "no test … writes under /cache".

### Suite, lock

On `5f6a8fe`, all output caches temp, `/cache` read-only, tests run as uid 1000. A nested user namespace is needed because `unshare -r` alone runs the tests as root, and the server refuses to serve as root.

```
S=/tmp/r3suite/g; PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=$S/pc HF_HOME=$S/hf PREACHED_ONNX_DIR=$S/onnx \
  XDG_CACHE_HOME=$S/xdg TORCH_HOME=$S/torch UV_CACHE_DIR=$S/uv \
  unshare -rm sh -c 'mount --bind /cache /cache && mount -o remount,bind,ro /cache && exec unshare --user --map-user=1000 --map-group=1000 "$@"' \
  sh .venv/bin/python -m unittest discover -s tests -v
```

**`Ran 1043 tests in 230.138s`, `OK (skipped=9)`**: 0 failures, 0 errors. `test_every_cited_file_line_holds_its_string` and `test_the_runbook_cites_exactly_the_pinned_lines` pass. The 9 skips all need real artifacts that a scratch cache lacks:

- 6 in `test_embed_backend` ("granite onnx artifacts are not in /cache")
- 1 in `test_eval_leak` (chunked corpus)
- `ExportIsByteIdenticalTests` and `MutantGraphTests` in this file

The scratch `pc`, `hf` and `onnx` dirs were empty afterwards. Those two tests in this file then ran against the real cache, read-only, network off (`PREACHED_CACHE=/cache`, `HF_HOME` and `PREACHED_ONNX_DIR` unset, outputs in TMPDIR): `Ran 2 tests in 41.231s`, `OK`. `UV_CACHE_DIR=<tmp> uv lock --check`: `Resolved 79 packages`, OK. No new dependencies.

Before the #69 merge, `7d94518` gave `Ran 1042 tests`, `OK (skipped=9)`, the same 9 skips. Two earlier attempts are not results; I list them so the numbers are not mistaken for regressions:

- `unshare -r` alone, tests as root: 97 failures and 24 errors, mostly "refusing to serve as root".
- uid 1000 but `UV_CACHE_DIR` on the read-only `/cache/uv`: 24 `test_deploy.BundleTests` failures ("Could not acquire lock … Read-only file system"). The same class with a temp `UV_CACHE_DIR`: 46 tests OK.

### Cache snapshot (standing rule 5)

`find /cache -printf '%p\t%s\t%T@\n' | sort`. 132,573 entries at 17:24 ET (before anything ran), 132,584 at the end. 67 lines differ. Every test and mutant process of mine ran with `/cache` read-only (a `touch` probe in the same setup gets EROFS). None pointed `PREACHED_CACHE`, `PREACHED_ONNX_DIR` or `HF_HOME` at `/cache` for output. The only real-cache reads were the two tests above, with outputs in TMPDIR. So none of the differences can be my processes' writes. They are, all 2026-10-31 ET:

- 17:29:46-17:30:31: a `uv` install of `preached` into `/cache/venvs/demo-main` (11 entries), `/cache/uv` archive/sdist entries (16), then `/cache/index/wesley.sqlite-shm`, `/cache/xdg/.../onnxruntime.db-wal/-shm` and `/cache/demo-kill`. This looks like a demo redeploy and restart by another process.
- 17:26:51 and 17:46:28 `/cache/index/cc-speech.sqlite-shm`; 17:27:23 and 17:47:00 the `/cache/models` directory mtime (its listing is unchanged); 17:28:33 and 17:48:28 `/cache/xdg/deno/*` caches. Each pattern shows up twice, about 20 minutes apart. It looks like another suite running elsewhere on the host with `XDG_CACHE_HOME=/cache/xdg` (mine used a temp one). I did not trace it.

`/cache/models/granite-english-r2-onnx/47ea…/` is unchanged: same five files, mtimes 16:30:10 ET (the §9 restore), sha256 prefixes fp32 `3861025a186e` (the pin), int8 `220d6de96c78`, tokenizer `6c8aaa9a5420`, pooling `bf1476968368`, manifest `96f276e6b10d`.

### Cite table (merged `app/server.py` at `5f6a8fe`; every `CITED` pin; "string found" is the text on that line, or the first … last line of a range)

| Cite | Line | String found | Holds |
| --- | --- | --- | --- |
| `app/server.py:238` | 238 | `REQUEST_TIMEOUT_S = 15` | yes |
| `app/server.py:244` | 244 | `DRAIN_TIMEOUT_S = 10.0` | yes |
| `app/server.py:285-286` | 285-286 | `CHURCH_RETRY_FIRST_S = 1.0 … CHURCH_RETRY_MAX_S = 30.0` | yes |
| `app/server.py:296` | 296 | `MISMATCH_LOG = "stored vectors do not match search/models.toml; serving BM25 only"` | yes |
| `app/server.py:297` | 297 | `UNAVAILABLE_LOG = "embedding model unavailable; serving BM25 only"` | yes |
| `app/server.py:300` | 300 | `MISSING_GRAPH_LOG = "ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. %s"` | yes |
| `app/server.py:306-312` | 306-312 | `SEARCH_MODE_REASONS = { … }` | yes |
| `app/server.py:302` | 302 | `INDEX_STATUS_LOG = "index status unreadable after reload; serving BM25 only"` | yes |
| `app/server.py:506` | 506 | `logging.warning("refused %s %s suppressed=%d", kind, detail, suppressed)` | yes |
| `app/server.py:518` | 518 | `logging.warning("refused %s flush suppressed=%d", kind, suppressed)` | yes |
| `app/server.py:863` | 863 | `logging.exception(MISMATCH_LOG)` | yes |
| `app/server.py:868` | 868 | `logging.error(UNAVAILABLE_LOG)` | yes |
| `app/server.py:869` | 869 | `logging.error(MISSING_GRAPH_LOG, exc)` | yes |
| `app/server.py:872` | 872 | `logging.exception(UNAVAILABLE_LOG)` | yes |
| `app/server.py:896` | 896 | `logging.exception("church vectors do not match search/models.toml; that side is BM25 only")` | yes |
| `app/server.py:901` | 901 | `logging.exception("church vectors unavailable; that side is BM25 only")` | yes |
| `app/server.py:919` | 919 | `raise ChurchPaused(f"the church file is locked by a writer ({exc})") from exc` | yes |
| `app/server.py:922` | 922 | `logging.error("church side refused: its searcher could not be built (%s: %s)", exc.__class__.__name__, reason)` | yes |
| `app/server.py:1121` | 1121 | `logging.log(level, "could not read the index stamp", exc_info=True)` | yes |
| `app/server.py:1152` | 1152 | `logging.error("refusing to serve after reload: %s", problem)` | yes |
| `app/server.py:1169` | 1169 | `logging.error("%s", message)` | yes |
| `app/server.py:1201` | 1201 | `self._serve_keyword_only(STALE_NOTE, MISMATCH_LOG)` | yes |
| `app/server.py:1235` | 1235 | `logging.error("refusing to serve: %s", self._frozen_refusal)` | yes |
| `app/server.py:1244` | 1244 | `self._serve_keyword_only(INDEX_READ_NOTE, INDEX_STATUS_LOG if self._weights_ok else None)` | yes |
| `app/server.py:1348-1349` | 1348-1349 | `"search_mode": "hybrid" if self.encode is not None else "bm25", … "search_mode_reason": reason,` | yes |
| `app/server.py:1444` | 1444 | `logging.error("church side refused: %s", problem)` | yes |
| `app/server.py:1449` | 1449 | `logging.error("church side refused: the publish gate did not turn on")` | yes |
| `app/server.py:1482` | 1482 | `logging.error("church side refused: the church file could not be opened (%s)", exc)` | yes |
| `app/server.py:1489` | 1489 | `logging.info("church side pause ended: refused")` | yes |
| `app/server.py:1490` | 1490 | `self._church_paused = False` | yes |
| `app/server.py:1521` | 1521 | `logging.error("church side dropped: %s", problem)` | yes |
| `app/server.py:1532` | 1532 | `logging.info("church side paused: %s", reason)` | yes |
| `app/server.py:1540` | 1540 | `logging.info("%s", held)` | yes |
| `app/server.py:1599` | 1599 | `logging.info("church side resumed")` | yes |
| `app/server.py:1602` | 1602 | `logging.exception("church search failed; that side is empty")` | yes |
| `app/server.py:1607` | 1607 | `self._church_pause(f"the church file is locked by a writer ({exc})")` | yes |
| `app/server.py:1808` | 1808 | `logging.exception("abstain calibration unusable; abstain floor disabled")` | yes |
| `app/server.py:1814` | 1814 | `def start():` | yes |
| `app/server.py:2031` | 2031 | `logging.error("request failed: %s", "TimeoutError")` | yes |
| `app/server.py:2036` | 2036 | `logging.error("request failed: %s", type(exc).__name__)` | yes |
| `app/server.py:2081` | 2081 | `logging.error("request failed: %s", "TimeoutError")` | yes |
| `app/server.py:2083` | 2083 | `logging.error("request failed: %s", type(exc).__name__)` | yes |
| `app/server.py:2143` | 2143 | `logging.error("request failed: %s", "LogError")` | yes |
| `app/server.py:2383` | 2383 | `logging.error("request failed: %s", type(exc).__name__)` | yes |
| `app/server.py:2404` | 2404 | `logging.error("request failed: %s", type(exc).__name__)` | yes |
| `app/server.py:2840` | 2840 | `logging.info("listening on http://%s:%s", host, port)` | yes |
| `app/server.py:2844` | 2844 | `app.log_startup_pause()` | yes |
| `app/server.py:2912` | 2912 | `logging.error("church side refused: %s", problem)` | yes |
| `app/server.py:2919` | 2919 | `logging.error("church side refused: %s", exc)` | yes |
| `app/server.py:2930` | 2930 | `logging.error("church side refused: %s", problem)` | yes |
| `app/server.py:2937` | 2937 | `logging.info("church side: %s, read-only, through the publish gate", slug)` | yes |
| `app/server.py:3099` | 3099 | `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")` | yes |
| `app/server.py:3277` | 3277 | `logging.info("stopping")` | yes |
| `app/server.py:3278-3296` | 3278-3296 | `stuck = server.drain() … raise SystemExit(1)` | yes |
| `app/server.py:3282` | 3282 | `logging.error("%d handler thread(s) still running after %.0fs; index left open", len(stuck), DRAIN_TIMEOUT_S)` | yes |
| `app/server.py:3292` | 3292 | `app.church_connection.close()` | yes |
| `app/server.py:3294` | 3294 | `logging.info("stopped cleanly")` | yes |
| `scripts/build-bundle.sh:239` | 239 | `echo "tar exited 1 (file changed as we read it?); attempt ${attempt} of 3" >&2` | yes |
| `scripts/build-bundle.sh:243` | 243 | `echo "tar failed (tar ${TAR_STATUS}, gzip ${GZIP_STATUS}); no archive written" >&2` | yes |
| `scripts/build-bundle.sh:247` | 247 | `echo "tar.gz does not match MANIFEST.sha256; no archive written" >&2` | yes |
| `src/preached/library.py:468` | 468 | `raise ChurchPaused(f"the church file is locked by a writer ({exc})") from exc` | yes |
| `src/preached/library.py:883-884` | 883-884 | `f"{path.name} is in WAL journal mode; run --ack-review (it leaves DELETE mode) before serving it", … f"{path.name} is in WAL journal mode",` | yes |
| `src/preached/library.py:895-896` | 895-896 | `reason = f"the church file is locked by a writer ({exc})" … raise ChurchStartPaused(f"{reason}; it is not opened", reason) from exc` | yes |
| `src/preached/library.py:915` | 915 | `problem, paused = f"{exc}; it is not opened", str(exc)` | yes |
| `src/preached/library.py:921-922` | 921-922 | `paused = f"the church file is locked by a writer ({exc})" … problem = f"{paused}; it is not opened"` | yes |
| `src/preached/library.py:962` | 962 | `raise ChurchPaused(f"{path.name} is in WAL journal mode")` | yes |
| `src/preached/youtube/library.py:157` | 157 | `f"the church file is still in {mode} journal mode (another connection has it open in WAL mode); "` | yes |
| `src/preached/youtube/pipeline.py:333` | 333 | `print(f"warning: {exc}", file=sys.stderr)` | yes |

### Diff scope

`git diff --stat origin/main..HEAD` (`origin/main` = `ebffabb`):

```
 app/server.py                            |  23 +
 docs/DEPLOY.md                           | 118 ++---
 docs/adr/0001-onnx-export-determinism.md |  54 ++
 reports/W3-CPU.md                        |   4 +-
 reports/W4-ONNX-PIN-REPRO.md             | 472 ++++++++++++++++++
 scripts/export_onnx.py                   | 127 ++++-
 src/preached/artifacts.py                |  31 +-
 tests/test_deploy_alerts.py              |  97 ++--
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 822 +++++++++++++++++++++++++++++++
 10 files changed, 1631 insertions(+), 121 deletions(-)
```

All files are in scope: the export script, `artifacts.py`, the server's missing-graph and `/healthz` lines, their tests, the ADR, this report, DEPLOY.md with its `CITED` pins, and `reports/W3-CPU.md` (S3). The `test_embed_backend.py` change is the earlier rounds' artifact-dir fix.

### PR BODY

(Replacement for PR #71's body. CoS pastes it.)

````markdown
## W4-ONNX-PIN-REPRO: a fresh export reproduces the pinned ONNX graph

Fixes fresh-clone BLOCKER 2 (#68 finding 2). The pin stays `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`; there is no re-pin.

### What moved the bytes
Two independent variables, and each one alone changes the exported fp32 graph (measured, 12-cell raw matrix, i9-12900K):
- `PYTHONHASHSEED`: transformers 5.22.1 ModernBERT traces its two rotary tables in `set(config.layer_types)` order (6 of 3009 nodes differ).
- `ATEN_CPU_CAPABILITY`: the dispatch level changes one float32 of the `inv_freq` Constants (default vs avx2).
Four digests come out, one per (order, dispatch) pair: `3861025a` (avx2, sliding first: the pin), `aed7adba` (avx2, full first), `44038d45` and `d99ba823` (default dispatch). Neither variable is "the" cause; both must be fixed. Raw AVX512 cannot run on this host (SIGILL); the CTO's AVX512 cells are not re-verified.

### Fix
- `scripts/export_onnx.py`: sets `ATEN_CPU_CAPABILITY=avx2` before importing torch; refuses non-x86-64 or non-AVX2 hosts; re-execs under `PYTHONHASHSEED=1` (argv kept); checks the trace order; exits non-zero with no manifest if the graph is not the pin. It hides CUDA itself, so the export command has no `CUDA_VISIBLE_DEVICES` prefix. Through the script, all 21 ambient cells (seed unset/0-5 × default/avx2/avx512) write the pin.
- ONNX outputs and the server default follow `PREACHED_CACHE`: `PREACHED_ONNX_DIR`, else `$PREACHED_CACHE/models/granite-english-r2-onnx`, else `/cache/...`. The HF cache defaults to `$PREACHED_CACHE/huggingface` (an explicit `HF_HOME` / `HF_HUB_CACHE` / `HUGGINGFACE_HUB_CACHE` wins).
- `app/server.py`: a missing graph logs the D2 line `ERROR embedding model unavailable; serving BM25 only` (no traceback), then `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; …` with the path and export command. `/healthz` gains `search_mode` (`hybrid`/`bm25`) and `search_mode_reason` (a code, never a path).
- `docs/DEPLOY.md`: D2 row covers both forms, new "D2 detail" row for the NOT BUILT line and the `/healthz` fields; every `app/server.py` cite re-pinned on the tree merged with #72 and #69 (tree-relative wording) and pinned in `tests/test_deploy_alerts.py`.
- ADR: `docs/adr/0001-onnx-export-determinism.md`.

### Tests
`tests/test_onnx_pin_repro.py` (31 tests). No test downloads; only the three-export byte-identity test exports for real, into TMPDIR, reading the snapshot. Every test points its outputs at temp dirs; `__main__` runs are sandboxed (scratch caches, offline, stubbed `os.execv` and `main`). `ExportMainTests`, which runs `main()` (it `rmtree`s the export dir), resolves the export dir and every `rmtree`/copy/write/mkdir target and refuses anything not under `tempfile.gettempdir()` and its temp cache, before acting; tests cover a `..` path, a symlinked `models` dir and an escaping write. The other tests rely on their temp environment, not a check. Mutants (each fails, then reverted): avx2 guard removed from `__main__`, seed restart removed, restart drops argv, `_check_pin` removed, `onnx_root` ignoring `PREACHED_CACHE`, `HF_HUB_CACHE` ignored, and the CTO's F2 (`..` traversal) and F3 (symlinked `$PREACHED_CACHE/models`), which got past the earlier lexical guard and are now refused with a decoy cache untouched.

Full suite on the merge with main: `PREACHED_REQUIRE_DENO=1`, all output caches in temp dirs, `/cache` mounted read-only → `Ran 1043 tests`, `OK (skipped=9)` (the 9 need real artifacts). The two real-artifact tests in this file, against `/cache` read-only with the network off: `Ran 2 tests`, `OK`. `uv lock --check` OK. No new dependencies.

### Migration
None for `/cache` hosts: the existing `3861025a` export stays valid. A host with `PREACHED_CACHE` other than `/cache` that kept the export at `/cache/models/...` must set `PREACHED_ONNX_DIR` or move it.

### Incident
On 2026-10-31 at 16:29 ET, during a mutant run, a test removed and rewrote the shared `/cache/models/granite-english-r2-onnx/47ea…/`. It was restored at 16:30 ET from an identical script export (fp32 and tokenizer match their pins; `verify_manifest` OK). Infra Ops re-ran the export and found the restored folder byte-identical to a fresh export (all 5 files); the live demo never loaded the damaged folder and needed no restart; the church index main db is unchanged. The guard added after the incident was lexical and was later shown to miss `..` and symlinked paths; it now resolves paths (above). Mutant and real-artifact runs mount `/cache` read-only. Details: `reports/W4-ONNX-PIN-REPRO.md` §9 and §12.

### Branch state
0 behind, 28 ahead of `origin/main` (`ebffabb`).

`git diff --stat origin/main..HEAD`:

```
 app/server.py                            |  23 +
 docs/DEPLOY.md                           | 118 ++---
 docs/adr/0001-onnx-export-determinism.md |  54 ++
 reports/W3-CPU.md                        |   4 +-
 reports/W4-ONNX-PIN-REPRO.md             | 472 ++++++++++++++++++
 scripts/export_onnx.py                   | 127 ++++-
 src/preached/artifacts.py                |  31 +-
 tests/test_deploy_alerts.py              |  97 ++--
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 822 +++++++++++++++++++++++++++++++
 10 files changed, 1631 insertions(+), 121 deletions(-)
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

## r3b: re-check against main `ebffabb` (#69 merged)

Result: no re-merge needed. The branch already contains `ebffabb` (the #69 merge commit) as an ancestor, via merge `5f6a8fe`, and that merge re-pinned every `app/server.py` cite in `docs/DEPLOY.md` and `CITED` in `tests/test_deploy_alerts.py` against the merged tree. Commits after `5f6a8fe` touch only this report (`git diff --stat 5f6a8fe HEAD`), so `app/server.py` is unchanged since the re-pin.

- Ahead/behind `origin/main` (`ebffabb`): 28 ahead, 0 behind.
- Cites: `tests.test_deploy_alerts` re-run on the current tree with scratch `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME` (temp dirs) and `PREACHED_REQUIRE_DENO=1`: `Ran 7 tests`, `OK`, so every cited server.py line holds its string (all 30 `CITED` server.py pins, e.g. 238, 244, 285-286, 296-312, 506, 518, 863-922, 1121-1244, 1348-1349, 1444-1490, plus the DEPLOY.md cites). DEPLOY.md wording is tree-relative, with no shas.
- Full suite and `uv lock --check`: not re-run (step 1 stop condition; no code changed). The last full run is r3 above: 1043 tests, `OK (skipped=9)`.
- Cache snapshot (`/cache`, path+size+mtime, 132589 entries) before and after the cite test: identical (sha256 `cba0cf49…1783`). Nothing was written outside a temp dir.

`git diff --stat origin/main..HEAD` is unchanged from "Branch state" above (10 files, all in scope).

## r3c (99-WA-ONNX-D2-AFTER75): merge #75, D2 producer, re-pin

#75 (DEPLOY regex pins, `tests/test_deploy_regex.py`) merged; `origin/main` is `a6a27bb10b79df2eae72dec107c9473a4ce2bd39`. On #71 merged over it, `test_deploy_regex` failed on the new D2 row: `Ran 10 tests`, `FAILED (failures=3, skipped=1)`, with `'D2'` outside `EXPECTED_PATTERNS`.

Done, as the CTO required:
- (a) D2 producer in `tests/test_deploy_regex.py` (`unavailable_lines`). It drives the real `app.server.load_search` for both startup forms. No graph: `embed_backend="onnx"`, `PREACHED_ONNX_DIR` an empty dir under a fresh `TemporaryDirectory` (checked with `_under_temp`), `HF_HOME` and `PREACHED_CACHE` in the same temp dir, offline, and an index seeded with a matching fingerprint (`test_onnx_pin_repro._seed_granite`) so the load fails on the artifact. The producer asserts note `MISSING_GRAPH_NOTE`, exactly one D2 line, and that the next emitted line starts with `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. ` (the GRAPH NOT BUILT branch). Load failure: a loader that raises `RuntimeError`, giving note `FALLBACK_NOTE` and the traceback form. Both D2 lines go through the formatter `main()` installs and must fullmatch the row's regex.
- (b) `EXPECTED_PATTERNS = {"D2", "D2b", "stamp", "side-access"}`.
- (c) Cites. The merge changed no cited file except `docs/DEPLOY.md` (the `<!-- regex: side-access -->` anchor, same line), so no number moved in this round. The stamp row already reads `app/server.py:1121` on the merged tree (main had `:1102`). Line 1121 holds `logging.log(level, "could not read the index stamp", exc_info=True)`, read off the file. The DEPLOY.md sentence saying which tree the numbers hold on now names #75 too, tree-relative, no sha.
- Not done: `INFRA_RULES` has no D2 entry. The CTO did not ask for one, and the infra yaml is not mounted here, so a D2 rule id could not be checked against it.

Head (code): `5d6284d` (merge `c3e78c7`, then the D2 commit); this report is the commit on top. Ahead/behind `origin/main` (`a6a27bb`): 0 behind, 31 ahead before this report, 32 with it. Merge and commits only; no rebase, no force-push.

### test_deploy_regex
Merged tree, before the D2 change: `FAILED (failures=3, skipped=1)`. After: `Ran 10 tests`, `OK (skipped=1)` (the skip is the optional infra yaml). The test prints:
`checked table D2: ^ERROR embedding model unavailable; serving BM25 only$ <- 'ERROR embedding model unavailable; serving BM25 only'`.

### Mutants (each run with `/cache` read-only, scratch caches; each reverted from a saved copy, `git status` clean after)
| Mutant | Result |
| --- | --- |
| M1: remove the `if name == "D2"` producer branch | FAIL: `AssertionError: no producer for DEPLOY.md pattern D2: add one, do not skip it` (1 failure) |
| M2: `app/server.py` drops `logging.error(MISSING_GRAPH_LOG, exc)` | FAIL: `no ONNX GRAPH NOT BUILT line: ['ERROR embedding model unavailable; serving BM25 only']` |
| M3: no-graph D2 line logged with `logging.warning` | FAIL: `'^ERROR embedding model unavailable; serving BM25 only$' does not fullmatch real line(s) ['WARNING embedding model unavailable; serving BM25 only', 'ERROR …']` |
| Reverted | `Ran 10 tests`, `OK (skipped=1)` |

### Cite table (merged tree, every cite read off the file)
All 68 `file:line` cites in `docs/DEPLOY.md` (bare `:n` read against the file named before it, as `runbook_cites` does) are in `CITED`, and every `CITED` pin is cited (0 pinned but uncited). Line text as read:

```
PIN app/server.py:238 -> 'REQUEST_TIMEOUT_S = 15'
PIN app/server.py:244 -> 'DRAIN_TIMEOUT_S = 10.0'
PIN app/server.py:285-286 -> 'CHURCH_RETRY_FIRST_S = 1.0' .. 'CHURCH_RETRY_MAX_S = 30.0'
PIN app/server.py:296 -> 'MISMATCH_LOG = "stored vectors do not match search/models.toml; serving BM25 only"'
PIN app/server.py:297 -> 'UNAVAILABLE_LOG = "embedding model unavailable; serving BM25 only"'
PIN app/server.py:300 -> 'MISSING_GRAPH_LOG = "ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. %s"'
PIN app/server.py:302 -> 'INDEX_STATUS_LOG = "index status unreadable after reload; serving BM25 only"'
PIN app/server.py:306-312 -> 'SEARCH_MODE_REASONS = {' .. '}'
PIN app/server.py:506 -> 'logging.warning("refused %s %s suppressed=%d", kind, detail, suppressed)'
PIN app/server.py:518 -> 'logging.warning("refused %s flush suppressed=%d", kind, suppressed)'
PIN app/server.py:863 -> 'logging.exception(MISMATCH_LOG)'
PIN app/server.py:868 -> 'logging.error(UNAVAILABLE_LOG)'
PIN app/server.py:869 -> 'logging.error(MISSING_GRAPH_LOG, exc)'
PIN app/server.py:872 -> 'logging.exception(UNAVAILABLE_LOG)'
PIN app/server.py:896 -> 'logging.exception("church vectors do not match search/models.toml; that side is BM25 only")'
PIN app/server.py:901 -> 'logging.exception("church vectors unavailable; that side is BM25 only")'
PIN app/server.py:919 -> 'raise ChurchPaused(f"the church file is locked by a writer ({exc})") from exc'
PIN app/server.py:922 -> 'logging.error("church side refused: its searcher could not be built (%s: %s)", exc.__class__.__name__, reason)'
PIN app/server.py:1121 -> 'logging.log(level, "could not read the index stamp", exc_info=True)'
PIN app/server.py:1152 -> 'logging.error("refusing to serve after reload: %s", problem)'
PIN app/server.py:1169 -> 'logging.error("%s", message)'
PIN app/server.py:1201 -> 'self._serve_keyword_only(STALE_NOTE, MISMATCH_LOG)'
PIN app/server.py:1235 -> 'logging.error("refusing to serve: %s", self._frozen_refusal)'
PIN app/server.py:1244 -> 'self._serve_keyword_only(INDEX_READ_NOTE, INDEX_STATUS_LOG if self._weights_ok else None)'
PIN app/server.py:1348-1349 -> '"search_mode": "hybrid" if self.encode is not None else "bm25",' .. '"search_mode_reason": reason,'
PIN app/server.py:1444 -> 'logging.error("church side refused: %s", problem)'
PIN app/server.py:1449 -> 'logging.error("church side refused: the publish gate did not turn on")'
PIN app/server.py:1482 -> 'logging.error("church side refused: the church file could not be opened (%s)", exc)'
PIN app/server.py:1489 -> 'logging.info("church side pause ended: refused")'
PIN app/server.py:1490 -> 'self._church_paused = False'
PIN app/server.py:1521 -> 'logging.error("church side dropped: %s", problem)'
PIN app/server.py:1532 -> 'logging.info("church side paused: %s", reason)'
PIN app/server.py:1540 -> 'logging.info("%s", held)'
PIN app/server.py:1599 -> 'logging.info("church side resumed")'
PIN app/server.py:1602 -> 'logging.exception("church search failed; that side is empty")'
PIN app/server.py:1607 -> 'self._church_pause(f"the church file is locked by a writer ({exc})")'
PIN app/server.py:1808 -> 'logging.exception("abstain calibration unusable; abstain floor disabled")'
PIN app/server.py:1814 -> 'def start():'
PIN app/server.py:2031 -> 'logging.error("request failed: %s", "TimeoutError")'
PIN app/server.py:2036 -> 'logging.error("request failed: %s", type(exc).__name__)'
PIN app/server.py:2081 -> 'logging.error("request failed: %s", "TimeoutError")'
PIN app/server.py:2083 -> 'logging.error("request failed: %s", type(exc).__name__)'
PIN app/server.py:2143 -> 'logging.error("request failed: %s", "LogError")'
PIN app/server.py:2383 -> 'logging.error("request failed: %s", type(exc).__name__)'
PIN app/server.py:2404 -> 'logging.error("request failed: %s", type(exc).__name__)'
PIN app/server.py:2840 -> 'logging.info("listening on http://%s:%s", host, port)'
PIN app/server.py:2844 -> 'app.log_startup_pause()'
PIN app/server.py:2912 -> 'logging.error("church side refused: %s", problem)'
PIN app/server.py:2919 -> 'logging.error("church side refused: %s", exc)'
PIN app/server.py:2930 -> 'logging.error("church side refused: %s", problem)'
PIN app/server.py:2937 -> 'logging.info("church side: %s, read-only, through the publish gate", slug)'
PIN app/server.py:3099 -> 'logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")'
PIN app/server.py:3277 -> 'logging.info("stopping")'
PIN app/server.py:3278-3296 -> 'stuck = server.drain()' .. 'raise SystemExit(1)'
PIN app/server.py:3282 -> 'logging.error("%d handler thread(s) still running after %.0fs; index left open", len(stuck), DRAIN_TIMEOUT_S)'
PIN app/server.py:3292 -> 'app.church_connection.close()'
PIN app/server.py:3294 -> 'logging.info("stopped cleanly")'
PIN scripts/build-bundle.sh:239 -> 'echo "tar exited 1 (file changed as we read it?); attempt ${attempt} of 3" >&2'
PIN scripts/build-bundle.sh:243 -> 'echo "tar failed (tar ${TAR_STATUS}, gzip ${GZIP_STATUS}); no archive written" >&2'
PIN scripts/build-bundle.sh:247 -> 'echo "tar.gz does not match MANIFEST.sha256; no archive written" >&2'
PIN src/preached/library.py:468 -> 'raise ChurchPaused(f"the church file is locked by a writer ({exc})") from exc'
PIN src/preached/library.py:883-884 -> 'f"{path.name} is in WAL journal mode; run --ack-review (it leaves DELETE mode) before serving it",' .. 'f"{path.name} is in WAL journal mode",'
PIN src/preached/library.py:895-896 -> 'reason = f"the church file is locked by a writer ({exc})"' .. 'raise ChurchStartPaused(f"{reason}; it is not opened", reason) from exc'
PIN src/preached/library.py:915 -> 'problem, paused = f"{exc}; it is not opened", str(exc)'
PIN src/preached/library.py:921-922 -> 'paused = f"the church file is locked by a writer ({exc})"' .. 'problem = f"{paused}; it is not opened"'
PIN src/preached/library.py:962 -> 'raise ChurchPaused(f"{path.name} is in WAL journal mode")'
PIN src/preached/youtube/library.py:157 -> 'f"the church file is still in {mode} journal mode (another connection has it open in WAL mode); "'
PIN src/preached/youtube/pipeline.py:333 -> 'print(f"warning: {exc}", file=sys.stderr)'
68 cites; 68 pins; pins not cited: []
```

### Full suite
`PREACHED_REQUIRE_DENO=1`, with `PREACHED_CACHE`, `HF_HOME`, `PREACHED_ONNX_DIR`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME` all under `/tmp/r3c/suite.*`, and `/cache` mounted read-only (`unshare -rm` + ro bind, mapped back to uid 1000): **`Ran 1053 tests in 222.678s`, `OK (skipped=11)`**. 0 failures, 0 errors, so 0 `test_every_cited_file_line_holds_its_string` failures. 1053 = r3's 1043 + #75's 10. The 11 skips:
- 6 in `test_embed_backend`: granite ONNX artifacts not in the scratch dir.
- 1 in `test_eval_leak`: no chunked corpus in the scratch cache.
- 2 in `test_onnx_pin_repro`: `ExportIsByteIdenticalTests` and `MutantGraphTests`, no real artifacts under the scratch cache.
- 1 in `test_deploy_regex`: the infra yaml is absent (new with #75).
- 1 in `test_shutdown.LoadedSigtermTests`: needs `/cache/index/wesley.sqlite` and an existing `PREACHED_ONNX_DIR`. This run's scratch `PREACHED_ONNX_DIR` was never created, so the test skipped. Environment only; it is not from this change.

`uv lock --check` (scratch `UV_CACHE_DIR`): `Resolved 79 packages`, OK. No new dependencies.

### Cache snapshot
`find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`, taken before the merge and after the last test run: 132599 entries both times, sha256 of the listing `e9606819d56f167f…` both times, `diff` empty. Nothing in `/cache` changed (paths, sizes, mtimes).

### Diff stat (in scope)
`git diff --stat origin/main..HEAD`:

```
 app/server.py                            |  23 +
 docs/DEPLOY.md                           | 118 ++---
 docs/adr/0001-onnx-export-determinism.md |  54 ++
 reports/W3-CPU.md                        |   4 +-
 reports/W4-ONNX-PIN-REPRO.md             | 669 +++++++++++++++++++++++++
 scripts/export_onnx.py                   | 127 ++++-
 src/preached/artifacts.py                |  31 +-
 tests/test_deploy_alerts.py              |  97 ++--
 tests/test_deploy_regex.py               |  60 ++-
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 822 +++++++++++++++++++++++++++++++
 11 files changed, 1887 insertions(+), 122 deletions(-)
```

### PR BODY (r3c, replaces the r3 body above)

````markdown
## W4-ONNX-PIN-REPRO: a fresh export reproduces the pinned ONNX graph

Fixes fresh-clone BLOCKER 2 (#68 finding 2). The pin stays `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`; there is no re-pin.

### What moved the bytes
Two independent variables, and each one alone changes the exported fp32 graph (measured, 12-cell raw matrix, i9-12900K):
- `PYTHONHASHSEED`: transformers 5.22.1 ModernBERT traces its two rotary tables in `set(config.layer_types)` order (6 of 3009 nodes differ).
- `ATEN_CPU_CAPABILITY`: the dispatch level changes one float32 of the `inv_freq` Constants (default vs avx2).
Four digests come out, one per (order, dispatch) pair: `3861025a` (avx2, sliding first: the pin), `aed7adba` (avx2, full first), `44038d45` and `d99ba823` (default dispatch). Neither variable is "the" cause; both must be fixed. Raw AVX512 cannot run on this host (SIGILL); the CTO's AVX512 cells are not re-verified.

### Fix
- `scripts/export_onnx.py`: sets `ATEN_CPU_CAPABILITY=avx2` before importing torch; refuses non-x86-64 or non-AVX2 hosts; re-execs under `PYTHONHASHSEED=1` (argv kept); checks the trace order; exits non-zero with no manifest if the graph is not the pin. It hides CUDA itself, so the export command has no `CUDA_VISIBLE_DEVICES` prefix. Through the script, all 21 ambient cells (seed unset/0-5 × default/avx2/avx512) write the pin.
- ONNX outputs and the server default follow `PREACHED_CACHE`: `PREACHED_ONNX_DIR`, else `$PREACHED_CACHE/models/granite-english-r2-onnx`, else `/cache/...`. The HF cache defaults to `$PREACHED_CACHE/huggingface` (an explicit `HF_HOME` / `HF_HUB_CACHE` / `HUGGINGFACE_HUB_CACHE` wins).
- `app/server.py`: a missing graph logs the D2 line `ERROR embedding model unavailable; serving BM25 only` (no traceback), then `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; …` with the path and export command. `/healthz` gains `search_mode` (`hybrid`/`bm25`) and `search_mode_reason` (a code, never a path).
- `docs/DEPLOY.md`: D2 row covers both forms, new "D2 detail" row for the NOT BUILT line and the `/healthz` fields; every `app/server.py` cite re-pinned on the tree merged with #72, #69 and #75 (tree-relative wording) and pinned in `tests/test_deploy_alerts.py`.
- ADR: `docs/adr/0001-onnx-export-determinism.md`.

### Tests
`tests/test_deploy_regex.py` (from #75) now pins D2 too: `D2` is in `EXPECTED_PATTERNS`, and its producer drives the real `load_search` twice, once with the ONNX loader against an empty temp `PREACHED_ONNX_DIR` (the real `ArtifactMissing`; the next line must be `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. …`) and once with a loader that raises (the traceback form). Both lines fullmatch `^ERROR embedding model unavailable; serving BM25 only$`. Removing the producer fails with `no producer for DEPLOY.md pattern D2`.

`tests/test_onnx_pin_repro.py` (31 tests). No test downloads; only the three-export byte-identity test exports for real, into TMPDIR, reading the snapshot. Every test points its outputs at temp dirs; `__main__` runs are sandboxed (scratch caches, offline, stubbed `os.execv` and `main`). `ExportMainTests`, which runs `main()` (it `rmtree`s the export dir), resolves the export dir and every `rmtree`/copy/write/mkdir target and refuses anything not under `tempfile.gettempdir()` and its temp cache, before acting; tests cover a `..` path, a symlinked `models` dir and an escaping write. The other tests rely on their temp environment, not a check. Mutants (each fails, then reverted): avx2 guard removed from `__main__`, seed restart removed, restart drops argv, `_check_pin` removed, `onnx_root` ignoring `PREACHED_CACHE`, `HF_HUB_CACHE` ignored, and the CTO's F2 (`..` traversal) and F3 (symlinked `$PREACHED_CACHE/models`), which got past the earlier lexical guard and are now refused with a decoy cache untouched.

Full suite on the merge with main (`a6a27bb`, #75): `PREACHED_REQUIRE_DENO=1`, every output cache (incl. `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`) in temp dirs, `/cache` mounted read-only → `Ran 1053 tests`, `OK (skipped=11)` (9 need real artifacts, 1 is #75's optional infra-yaml check, 1 needs a real ONNX dir). `uv lock --check` OK. No new dependencies.

### Migration
None for `/cache` hosts: the existing `3861025a` export stays valid. A host with `PREACHED_CACHE` other than `/cache` that kept the export at `/cache/models/...` must set `PREACHED_ONNX_DIR` or move it.

### Incident
On 2026-10-31 at 16:29 ET, during a mutant run, a test removed and rewrote the shared `/cache/models/granite-english-r2-onnx/47ea…/`. It was restored at 16:30 ET from an identical script export (fp32 and tokenizer match their pins; `verify_manifest` OK). Infra Ops re-ran the export and found the restored folder byte-identical to a fresh export (all 5 files); the live demo never loaded the damaged folder and needed no restart; the church index main db is unchanged. The guard added after the incident was lexical and was later shown to miss `..` and symlinked paths; it now resolves paths (above). Mutant and real-artifact runs mount `/cache` read-only. Details: `reports/W4-ONNX-PIN-REPRO.md` §9 and §12.

### Branch state
0 behind, 32 ahead of `origin/main` (`a6a27bb`).

`git diff --stat origin/main..HEAD`:

```
 app/server.py                            |  23 +
 docs/DEPLOY.md                           | 118 ++---
 docs/adr/0001-onnx-export-determinism.md |  54 ++
 reports/W3-CPU.md                        |   4 +-
 reports/W4-ONNX-PIN-REPRO.md             | 669 +++++++++++++++++++++++++
 scripts/export_onnx.py                   | 127 ++++-
 src/preached/artifacts.py                |  31 +-
 tests/test_deploy_alerts.py              |  97 ++--
 tests/test_deploy_regex.py               |  60 ++-
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 822 +++++++++++++++++++++++++++++++
 11 files changed, 1887 insertions(+), 122 deletions(-)
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)
````

## r3d. Main-side hunks of #72, #69 and #75 in DEPLOY.md and test_deploy_alerts.py (99-WB)

Question: did resolving merge conflicts with `git checkout --ours` (in 99-W7Z) drop main-side hunks from #72, #69 or #75 in `docs/DEPLOY.md` or `tests/test_deploy_alerts.py`? **No. Every hunk is present in HEAD (`92c38fb` before this section), so nothing was re-applied and no cite moved.** This commit adds only this section.

Method. `origin/main` (`a6a27bb`) is an ancestor of HEAD (0 behind), so a main-side line that was dropped would show up as a `-` line in `git diff origin/main..HEAD`. In both files, every `-` line there is one of two things. Either it is a cite whose only change is its line numbers (the branch adds 23 lines to `app/server.py`), or it is one of two rewrites made by this branch: the D2 row and the D1/D2 traceback sentence (`9af1484`, `5d6284d`, missing-graph form), and the tree-naming sentence. I also checked each PR on its own. For each one I took `git diff <merge>^1..<merge> -- <file>` (#72: `abdada3..f75bbcb`, #69: `f75bbcb..ebffabb`, #75: `ebffabb..a6a27bb`) and looked up every `+` line of every hunk in the HEAD file. A hunk counts as "exact" when its line is unchanged, "re-pinned" when it matches with only digits changed (the cite moved with `app/server.py` and is checked by `tests.test_deploy_alerts`), and "superseded" when the branch rewrote it, in which case the text is quoted below. In `CITED`, all 46 of main's `app/server.py` pin strings are in HEAD, and the branch adds 5 more (`:300`, `:306-312`, `:868`, `:869`, `:1348-1349`).

| PR | File | Hunk (main side) | Summary | In HEAD |
|---|---|---|---|---|
| #72 | DEPLOY.md | -178,2 | `TimeoutStopSec`: `DRAIN_TIMEOUT_S` / `REQUEST_TIMEOUT_S` cites | 178-179 (re-pinned `:244`, `:238`) |
| #72 | DEPLOY.md | -193,2 | stuck-stop range, church close, `stopped cleanly` cites | 193-194 (re-pinned) |
| #72 | DEPLOY.md | -580 | **Connections row: keep-alive hand-over** (peer at cap takes its oldest idle keep-alive after 1 s, NAT/IPv6 /64 note) | 580 (exact) |
| #72 | DEPLOY.md | -653, -655 | writer-lock item: `church side paused` cite, retry backoff `CHURCH_RETRY_*` | 653, 655 (re-pinned) |
| #72 | DEPLOY.md | -719,2 / -723 / -728 / -730 | church refusal cites, searcher-build refusal and lock, paused | 719-720, 723, 728, 730 (re-pinned) |
| #72 | DEPLOY.md | -734 / -736,2 / -740,2 / -743,2 / -746 | `start` closure, failed-start cites, pause ended/cleared | 734, 736-737, 740-741, 743-744, 746 (re-pinned) |
| #72 | DEPLOY.md | -751,2 | `log_startup_pause` and its call site | 751-752 (re-pinned) |
| #72 | DEPLOY.md | -786 | `logging.basicConfig` cite | 786 (re-pinned) |
| #72 | DEPLOY.md | -791 | **Infra yaml sha `42dd7e7c762a…4d24`** (25 rules) | 791 (exact) |
| #72 | DEPLOY.md | -794,4 | tree sentence "main after the R4-COND re-pin, plus the keep-alive hand-over" | superseded at 794-796 ("main with the keep-alive hand-over (#72), the port-busy hard fail (#69) and the regex pins (#75), plus the ONNX pin fix") |
| #72 | DEPLOY.md | -803,6 / -859,2 | church alert table rows 1-7 cites | 802-807, 858-859 (re-pinned) |
| #72 | DEPLOY.md | -877,9 | D1, D2, D2b, D3-D7, stamp rows | 876-885: re-pinned, plus a D2 row superseded by the branch's two-form row (its "with a traceback" became "in two forms…"; every other sentence kept) and a new "D2 detail" row |
| #72 | DEPLOY.md | -892 / -894,2 | D4 refusal; D1/D2b reload cites | 892, 894-895 (re-pinned) |
| #72 | DEPLOY.md | -897,2 | "D2 (`:853`) fires only at startup. D1 and D2 at startup still carry a traceback" | 897-899: re-pinned, and the branch adds "except D2's missing-graph form (`:868`), which has none" |
| #72 | DEPLOY.md | -900 / -905,2 / -910 / -914,3 / -918,6 | stamp outage, `stopped cleanly`, "Other lines" table | 901, 906-907, 911 (exact), 915-917, 919-924 (re-pinned) |
| #72 | test_deploy_alerts.py | -67,46 | `CITED` server.py pins (46) | 67-117: all 46 strings present, re-pinned |
| #69 | DEPLOY.md | -193,2 | **port-busy `server_close` guard**: +3 on the stuck-stop range `:3255-3273`, `:3269`, `:3271` | 193-194 (re-pinned `:3278-3296`, `:3292`, `:3294`) |
| #69 | DEPLOY.md | -719,2 / -736 | church refusal cites +3 (`:2889`, `:2896`, `:2907`) | 719-720, 736 (re-pinned `:2912`, `:2919`, `:2930`) |
| #69 | DEPLOY.md | -752 | `log_startup_pause` call site `:2821` | 752 (re-pinned `:2844`) |
| #69 | DEPLOY.md | -786 | `basicConfig` `:3076` | 786 (re-pinned `:3099`) |
| #69 | DEPLOY.md | -795,2 | tree sentence "…plus the keep-alive hand-over (#72) and the port-busy hard fail (#69)" | superseded at 795-796 (names #72, #69, #75; tree-relative, no sha) |
| #69 | DEPLOY.md | -802 / -881 | church row 1 cites; D5 stuck-stop `:3259` / `:3254` | 802, 882 (re-pinned `:3282` / `:3277`) |
| #69 | DEPLOY.md | -904,2 / -913 / -917,4 | `stopped cleanly`, `church-opened`, `listening on` and the rest of "Other lines" | 906-907, 915, 919-922 (re-pinned) |
| #69 | test_deploy_alerts.py | -101,12 | `CITED` pins `2817`-`3271` (+3) | 106-117 (re-pinned) |
| #75 | DEPLOY.md | -821 | **regex marker `<!-- regex: side-access -->`** on the `/api/side` candidate regex | 821 (exact) |
| #75 | test_deploy_alerts.py | none | #75 made no change to this file | n/a |

Re-applied in commit: none, since no hunk was missing. #75's own test, `tests/test_deploy_regex.py`, is not one of the two files in scope. Its only `-` line against `a6a27bb` is `EXPECTED_PATTERNS`, which this branch widened to add `D2` (line 41), so that is not a drop either.

Cites (rule 4): no file cited in DEPLOY.md changed in r3d, so there was nothing to re-pin. `tests.test_deploy_alerts tests.test_deploy_regex` (scratch caches, `PREACHED_REQUIRE_DENO=1`): `Ran 17 tests`, `OK (skipped=1)` (the skip is the infra yaml, which is absent).

Full suite: `PREACHED_REQUIRE_DENO=1` with `PREACHED_CACHE`, `HF_HOME`, `PREACHED_ONNX_DIR`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR` and `TORCH_HOME` all under `/tmp/r3d/suite.mT0u/`, and `/cache` mounted read-only (`unshare -rm` + ro bind, mapped back to uid 1000) → **`Ran 1053 tests in 232.617s`, `OK (skipped=10)`**. That is 0 failures and 0 errors, so 0 `test_every_cited_file_line_holds_its_string` failures. The 10 skips:
- 6 in `test_embed_backend`: there are no granite ONNX artifacts in the scratch dir.
- 1 in `test_eval_leak`: the scratch cache has no chunked corpus.
- 2 in `test_onnx_pin_repro`: `ExportIsByteIdenticalTests` and `MutantGraphTests`, with no real artifacts in the scratch cache.
- 1 in `test_deploy_regex`: the infra yaml is absent.

r3c had 11 skips. The difference is `test_shutdown.LoadedSigtermTests`, which skipped in r3c because its scratch `PREACHED_ONNX_DIR` was never created. This time the directory was created (empty), so both of its tests ran and passed. `uv lock --check` (scratch `UV_CACHE_DIR`): `Resolved 79 packages`, OK.

Cache snapshot: `find /cache -printf '%p\t%s\t%T@\n' | sort`, taken before the suite and after the last command. Both listings have 132604 entries. sha256 before `7d38bb40…96b4`, after `a366776c…c754`. Paths: no change. Sizes: the only changes are three deno WAL files that grew (`/cache/xdg/deno/{dep_analysis,v8_code}_cache_v2-wal`; `node_analysis_cache_v2` kept its size). Mtimes changed on `/cache/index/cc-speech.sqlite-shm`, the `/cache/models` directory (same single entry, `granite-english-r2-onnx`; nothing under it is newer than the first snapshot), `/cache/xdg/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db-{shm,wal}` and `/cache/xdg/deno/*_cache_v2{,-shm,-wal}`. None of this came from this run. The suite ran with `/cache` read-only (`touch /cache/models/.r3d-probe` inside the same wrapper fails with `Read-only file system`) and with every cache env var pointed at scratch. The writes are other agents that share `/cache` (SQLite shm/WAL, deno and onnxruntime caches). No model, index or ONNX file changed.

Branch state after this commit: 0 behind, 33 ahead of `origin/main` (`a6a27bb`). In-scope diff stat below.

`git diff --stat origin/main..HEAD` at the r3d report commit, before this stat block was added (every file is in PR #71 scope; r3d itself changes only `reports/W4-ONNX-PIN-REPRO.md`):

```
 app/server.py                            |  23 +
 docs/DEPLOY.md                           | 118 ++---
 docs/adr/0001-onnx-export-determinism.md |  54 ++
 reports/W3-CPU.md                        |   4 +-
 reports/W4-ONNX-PIN-REPRO.md             | 720 +++++++++++++++++++++++++++
 scripts/export_onnx.py                   | 127 ++++-
 src/preached/artifacts.py                |  31 +-
 tests/test_deploy_alerts.py              |  97 ++--
 tests/test_deploy_regex.py               |  60 ++-
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 822 +++++++++++++++++++++++++++++++
 11 files changed, 1938 insertions(+), 122 deletions(-)
```
