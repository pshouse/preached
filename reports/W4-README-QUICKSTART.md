# W4-README-QUICKSTART: a judge can follow the README from a fresh cache

Fresh-clone QA findings 1 and 3–18 (`reports/W4-FRESH-CLONE-QA.md` on `qa/w4-fresh-clone`, PR #68, as corrected for CTO MF1/MF2). Branch `docs/w4-readme-quickstart`. Section 9 is the re-sync with #71 at `1907d1f`. The sections above that are the first walkthrough, at `59b44fb`. Section 10 is the CTO review of this PR, on #71's final head `27ed9cb`.

**Base.** `origin/main` is `b224281` and does not contain the ONNX PR. This branch starts at `origin/fix/w4-onnx-pin-repro` (`59b44fb`), which does contain `ATEN_CPU_CAPABILITY` in `scripts/export_onnx.py`. `git merge origin/main` returned **Already up to date**: `origin/main` is an ancestor, so there is no merge commit. **This PR must merge after the ONNX PR.**

**Result.** The README now builds the ONNX graph, checks it against the pin, and says what a missing graph prints. Retrieval figures in the README are only the pre-registered sentence. The example query is the demo-script money question, run once per mode. A paragraph number that sits right after a verse reference is hidden, with a test that failed before the change.

## 1. What was done

`README.md` is rewritten for a clone. It names uv (`uv_build>=0.13.6,<0.14`), Python `>=3.12,<3.14`, network, disk, and `ffmpeg` for audio. It documents `PREACHED_CACHE` (default `/cache`): the directory must exist and be writable, and an unset `HF_HOME` is set to `$PREACHED_CACHE/huggingface` by the library code. The quickstart is text-only (`start_s` empty, play `n/a`). The first block fetches, chunks, validates, and benches **Granite only**. It then syncs the bench group and runs `scripts/export_onnx.py`, which pins `ATEN_CPU_CAPABILITY=avx2` and needs an x86-64 host with AVX2. The export keeps an ambient `HF_HOME` (`setdefault` before torch); when that variable is unset the export reads `/cache/huggingface`. That cache path is what `59b44fb` did. Section 9 is `1907d1f`: an unset `HF_HOME` is `$PREACHED_CACHE/huggingface`, and `/cache/huggingface` only when `PREACHED_CACHE` is unset. It deletes the revision directory under `PREACHED_ONNX_DIR` (default `/cache/models/granite-english-r2-onnx/<revision>/`) before writing, and it prints the pin line or exits non-zero with no manifest. The later `uv sync` is described as dropping the bench group. Alignment is a separate step, after fetch, and the README says to do it before expecting playback. The church block is a shape (`--privacy privacy.example.toml`); `@channel` is not a channel to import. YouTube placeholders are quoted `"SLUG"` and `"privacy.toml"`. Local outputs (`corpus/catalog.json`, `eval/results/`) and `--accept-new-text` are named. The opening line is "This repo builds". The server section is "From the clone:". Wesley is described as built in on its own pipeline; `src/preached/libraries.py` lists Spurgeon and Edwards. The test command is `uv run python -m unittest discover -s tests`, and the README states no count. `reports/W3-CPU.md`'s count and worktree path are called stale.

No pin and no export code changed. Finding 2 stays on the ONNX branch.

`display_excerpt` in `src/preached/search.py` treats a number after a verse reference as a CCEL paragraph number. `Rom. 8:16 1. How many` becomes `Rom. 8:16 How many`. `See Rom. 8:16, 1. That the Spirit witnesses` stays, because the comma is an inline list. `tests/test_api_path.py` covers both strings.

## 2. How to run

From a clean clone of this branch, after the ONNX PR is in the tree. Create a writable cache first. The walkthrough used a throwaway cache so the export's delete could not touch the shared graph:

```bash
export PREACHED_CACHE=/cache/w4-readme-quickstart
export PREACHED_ONNX_DIR="$PREACHED_CACHE/onnx"
mkdir -p "$PREACHED_CACHE"
unset HF_HOME HUGGINGFACE_HUB_CACHE
```

Then the README blocks, in order: `corpus/fetch_wesley.py`, `corpus/chunk_sermons.py`, `eval/validate.py`, `search/bench.py --models granite-english-r2` under `--group bench`, `uv sync --group bench`, `uv run --group bench python scripts/export_onnx.py`, the hybrid money query, `uv sync`, `uv run app/server.py`. Alignment, the church shape, `--bm25-only`, the bm25 `--side` query, and the three quoted YouTube lines follow. The test command is the discover line above.

The required suite, from this worktree:

```bash
PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests
uv lock --check
```

Host for this run: x86-64 with AVX2 (i9-12900K), RTX 3060, uv selecting CPython 3.12.16. The fresh cache was deleted after the numbers below were recorded. The shared graph at `/cache/models/granite-english-r2-onnx/` was not deleted.

## 3. Results

Wall time is the wrapper around each command (`date +%s.%N`). Unittest's own `Ran` line is quoted beside the suite rows.

| Step | Exit | Wall (s) | Command |
| --- | --- | --- | --- |
| fetch | 0 | 1.624 | `uv run corpus/fetch_wesley.py` |
| chunk | 0 | 0.501 | `uv run corpus/chunk_sermons.py` |
| server before the index exists | 1 | 2.013 | `uv run app/server.py` with an empty ONNX dir, **before** the bench |
| validate | 0 | 136.736 | `uv run python eval/validate.py` |
| bench | 0 | 154.637 | `uv run --group bench search/bench.py --models granite-english-r2` |
| sync bench | 0 | 0.009 | `uv sync --group bench` |
| export | 0 | 14.885, measured with the previous command (see R5) | `uv run --group bench python scripts/export_onnx.py` (edited; see R5) |
| query hybrid | 0 | 1.543 | `uv run search/query.py "how should a Christian use money" --mode hybrid -k 5` |
| sync runtime | 0 | 0.594 | `uv sync` |
| server hybrid | 0 | 3.038 | `uv run app/server.py` after the export |
| align | 1 | 0.087 | `uv run align/wesley.py align` |
| align chunks | 1 | 0.064 | `uv run align/wesley.py chunks` |
| church shape | 1 | 1.100 | `uv run --extra youtube import/youtube.py "https://www.youtube.com/@channel/videos" --library sample --your-church --privacy privacy.example.toml` |
| server bm25 | 0 | 2.020 | `uv run app/server.py --bm25-only` |
| query bm25 | 0 | 0.159 | `uv run search/query.py "how should a Christian use money" --mode bm25 --side` |
| yt dry-run | 2 | 0.122 | `--library "SLUG" --privacy "privacy.toml" --dry-run` |
| yt limit | 2 | 0.174 | `--library "SLUG" --privacy "privacy.toml" --limit 5 --since 2024-01-01` |
| yt require-cc | 2 | 0.163 | `--extra transcribe` `--library "SLUG" --privacy "privacy.toml" --require-cc` |
| README tests | 1 | 227.134 | `uv run python -m unittest discover -s tests` on the fresh cache |
| suite, exact env | 1 | 255.981 | `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache`, `PREACHED_ONNX_DIR` unset |
| suite, fresh graph | 1 | 278.146 | same, plus `PREACHED_ONNX_DIR` at the export from this run |
| lock | 0 | 0.010 | `uv lock --check` |

Fetch wrote 141 sermons, 652145 words. `corpus/catalog.json` is not modified in git. Chunk wrote 8383 chunks, words min/median/max 15/122/180, overlap 0.25. Validate printed nothing, then one JSON object (`questions` 93, `chunks` 8383) and `all graded quotes match at least one chunk`.

The bench installed 49 packages, embedded Granite on CUDA in 65.9 s (127.2 chunks/s, VRAM peak 2063 MiB), and wrote `eval/results/2026-10-31.json` and `.md`. Those two files were deleted and are not in the commit. Its headline included `hybrid_rrf recall@5=0.285 mrr@10=0.219 ndcg@10=0.246`. Those numbers are not in the README. This walkthrough did not pass `--dedupe`.

`uv sync --group bench` was `Resolved 79 packages` / `Checked 70 packages` (already installed). The export read the snapshot at `/cache/huggingface/hub/models--ibm-granite--granite-embedding-english-r2/snapshots/47ea694b257b703fee9253d75c2b1f2985180498` and printed a `fp32 sha256 matches the pin` line for a digest that is not `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`. The later `uv sync` printed `Uninstalled 49 packages`, including torch.

The shared graph's sha256 was `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` before the walkthrough and the same value after it.

### Example query, once per mode

Hybrid, text-only (`start_s=None`, play `n/a`), no abstain line:

```
[1] The Use of Money  (score 0.0320, wesley-050-c0007)
    text: https://ccel.org/ccel/wesley/sermons/sermons.v.l.html
[2] The Use of Money  (score 0.0318, wesley-050-c0004)
    text: https://ccel.org/ccel/wesley/sermons/sermons.v.l.html
[3] Upon our Lord's Sermon on the Mount, Discourse 8  (score 0.0317, wesley-028-c0076)
    text: https://ccel.org/ccel/wesley/sermons/sermons.v.xxviii.html
```

The excerpts start "The fault does not lie in the money", "An excellent branch of Christian wisdom", and `"If we waste our money`. Rows 4 and 5 were The More Excellent Way `wesley-089-c0050` (0.0311) and The Use of Money `wesley-050-c0032` (0.0298).

BM25 `--side` (`mode: bm25`, `confidence: unrated`, `Classic library: John Wesley`):

```
[1] The Use of Money  (score 9.0136, wesley-050-c0007)
[2] The Use of Money  (score 7.8838, wesley-050-c0032)
[3] Upon our Lord's Sermon on the Mount, Discourse 8  (score 7.8549, wesley-028-c0076)
```

The church column printed `Nothing from your church yet.`

### Missing graph

`corpus/chunk_sermons.py` does not create SQLite. The server started before the bench exited 1 in 2.013 s with only `missing index /cache/w4-readme-quickstart/index/wesley.sqlite`. The README order runs the bench, which builds the index, before the server.

After that index existed, the same server command with `PREACHED_ONNX_DIR` pointed at an empty directory printed, in order (edited; see R5):

```
ERROR embedding model unavailable; serving BM25 only
ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. missing ONNX manifest at /tmp/w4-empty-onnx/47ea694b257b703fee9253d75c2b1f2985180498/manifest.json; build it with: uv run --group bench python scripts/export_onnx.py
WARNING The search model has not been built; results are BM25 only.
PREACHED_LISTENING http://127.0.0.1:8000
```

`GET /healthz` was `fallback: true`, `dense: false`, `search_mode: bm25`, `search_mode_reason: onnx_graph_not_built`, `model: null`, `chunks: 8383`. The money query was not run again. `search/query.py` prints `error:` plus the `ArtifactMissing` text and exits 1; that string is the same missing-manifest sentence. A graph that is present and is not the pin raises `ONNX sha256 for model.fp32.onnx is not the pinned digest` (seen on the shared old graph in the exact suite).

With the fresh graph, `/healthz` was `fallback: false`, `dense: true`, `search_mode: hybrid`, `search_mode_reason: null`, `backend: onnx`, `model: granite-english-r2`, and `model_sha256` was not the pin `3861025a…`. The log line was `INFO embed backend=onnx variant=fp32 threads=1`. `--bm25-only` logged `INFO BM25 only; the embedding model was not loaded` and `/healthz` was `search_mode: bm25`, `search_mode_reason: bm25_only`, `fallback: false`, `model: null`.

### Align, church shape, quoted slugs

`align` exited 1: `FileNotFoundError` for `/cache/w4-readme-quickstart/transcripts/wesley/wesley-s1-01.json`. `chunks` exited 1: `not aligned yet: ['wesley-001', ...]... run align first`. Transcripts were not copied in.

The church shape installed the youtube extra and exited 1. yt-dlp reported `HTTP Error 404` for `@channel/videos`. Nothing was indexed. Each quoted `"SLUG"` command exited 2 with `library must be a short slug: lowercase letters, digits, and hyphens`.

### Paragraph-number test

On the strip as it stood at `59b44fb`, with the new test already in the tree:

```
AssertionError: 'Rom. 8:16 1. How many' != 'Rom. 8:16 How many'
Ran 1 test in 0.000s
FAILED (failures=1)
```

The negative assertion was not reached. After the regex change, `DisplayExcerptTests`: `Ran 3 tests in 0.000s`, `OK`.

### Full suite and lock

`uv lock --check`: exit 0, `Resolved 79 packages in 0.74ms`.

Exact command (`PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache`, `PREACHED_ONNX_DIR` unset, so the shared graph `3861025a…`): `Ran 1021 tests in 255.196s`, `FAILED (failures=55, errors=2)`, no skip line. 1021 is the previous 1020 plus `test_paragraph_number_after_a_verse_reference_is_hidden`. The new test is not among the failures.

- **52** subtests of `test_deploy_alerts.RunbookTests.test_every_cited_file_line_holds_its_string`. These came from #71 at `59b44fb`. They are gone at `4d6ae86` (§10). This walkthrough started at `59b44fb` and did not edit `docs/DEPLOY.md`.
- **3 failures and 2 errors** open the shared graph and refuse it (`ONNX sha256 for model.fp32.onnx is not the pinned digest`; the pin at `59b44fb` was not the shared graph's `3861025a…`):
  - `test_embed_backend.RealOnnxTests.test_cached_fp32_and_tokenizer_match_the_pins`
  - `test_fp32_directory_without_int8_loads` (error)
  - `test_fp32_query_is_unit_normalized` (error)
  - `ImportGuardTests.test_youtube_embed_path_does_not_import_torch`
  - `test_shutdown.LoadedSigtermTests.test_sigterm_under_hybrid_load_exits_zero_and_cleans_up`

The same suite with `PREACHED_ONNX_DIR=/cache/w4-readme-quickstart/onnx`: `Ran 1021 tests in 277.323s`, `FAILED (failures=52)`. Only the 52 cite subtests. No errors, no skip line.

The README discover command on the fresh cache (`PREACHED_CACHE` and `PREACHED_ONNX_DIR` there): `Ran 1021 tests in 226.642s`, `FAILED (failures=52, skipped=1)`. The one skip is `ExportIsByteIdenticalTests`: it runs only when `$PREACHED_CACHE/huggingface/.../model.safetensors` is present. That file is under `/cache/huggingface`. It is not under the fresh cache, because the export's `setdefault` read `/cache/huggingface` while `HF_HOME` was unset.

### Pre-registered sentence

The README contains this sentence once, byte-exact with `docs/SUBMISSION-DRAFT.md`, including U+2212 in `−0.034`, and cites `reports/W3-CONFIRMATORY.md`:

`In a pre-registered evaluation (58 questions; relevance labels drafted with AI help, a subset confirmed blind by a human), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086).`

Checked absent from `README.md`: `0.629`, `0.614`, `0.506`, `0.558`, `0.497`, `0.546`, `0.285`, `0.219`, `0.246`, `0.297`, `0.241`, `0.265`, and `worry`.

## 4. Finding map

| # | Status | Why |
| --- | --- | --- |
| 1 | fixed | README builds the graph (bench sync, then `scripts/export_onnx.py`), names avx2 and the x86-64/AVX2 host, `setdefault` of `HF_HOME`, the revision-directory delete, and the pin check. The missing-graph log and `/healthz` are quoted from a server started against an empty ONNX dir after the index existed. No pin or loader code was changed. |
| 2 | deferred | The pin move and `ATEN_CPU_CAPABILITY=avx2` are the ONNX PR. This task does not change pins or export code. This branch contains that work only because it starts there, and this PR merges after that PR. The shared `/cache` graph was left at `3861025a…`. |
| 3 | fixed | The bench snippet is `--models granite-english-r2`, with network, disk, GPU, and time. This GPU run was 154.637 s wall and 65.9 s of embed. The README says a few minutes on a GPU. The full bench, without `--models`, is described as three models. |
| 4 | fixed | The six README figures are gone (listed below). The only retrieval figure is the pre-registered sentence. `0.285` was reproduced by the bench and left out. |
| 5 | fixed | The example is `how should a Christian use money`, once in hybrid and once in bm25. Top-3 are recorded above. |
| 6 | fixed | The quickstart says it is text-only. Align and `chunks` are written before playback is promised. On a fresh cache both exit 1, and the README says why. |
| 7 | fixed | `PREACHED_CACHE` is documented, including that the directory must exist and be writable. |
| 8 | fixed | `eval/validate.py` is described as silent for about two minutes. This run was 136.736 s, then one JSON line. |
| 9 | fixed | The later `uv sync` is described as dropping the bench group. This run uninstalled 49 packages, including torch. |
| 10 | fixed | The church example passes `--privacy privacy.example.toml` and says a real channel and a reviewed config are required. Listing `@channel` exited 1 with yt-dlp HTTP 404 and indexed nothing. |
| 11 | fixed | Placeholders are quoted `"SLUG"` and `"privacy.toml"`. Each exited 2 with the slug message, so the quotes reached Python. |
| 12 | fixed | `corpus/catalog.json` and `eval/results/` are named as local outputs, with `--accept-new-text` when CCEL text changes. The catalog was unchanged in git. The result files were deleted. |
| 13 | fixed | One prerequisites line: uv, Python `>=3.12,<3.14`, network, disk, and `ffmpeg` for audio. |
| 14 | fixed | "This repo builds". |
| 15 | fixed | "From the clone:". |
| 16 | fixed | Wesley is built in on its own pipeline. `libraries.py` lists Spurgeon and Edwards (`PUBLIC_DOMAIN`). |
| 17 | fixed | The strip hides a paragraph number after a verse reference. The new test failed on the old regex and passed after the change. The negative case keeps a real number. |
| 18 | fixed | The discover command is in the README. No pass count is stated. The stale 172 and the `feat/w3-cpu` path in `reports/W3-CPU.md` are called out as stale. |

## 5. Figures removed

Removed from `README.md` (the sentence on `origin/main` that compared Granite hybrid `--dedupe` with the raw top 10; the QA report identifies that pair as the 35-answerable-question run):

- R@5 0.614, MRR@10 0.497, nDCG@10 0.546
- R@5 0.629, MRR@10 0.506, nDCG@10 0.558

The example question `what did Wesley say about worry` was replaced by the demo-script money question. It is not a retrieval figure.

Seen on this bench and not added to the README: hybrid_rrf recall@5 0.285, MRR@10 0.219, nDCG@10 0.246. The QA note's `--dedupe` triple (0.297 / 0.241 / 0.265) was not re-run here.

Kept, inside the one pre-registered sentence only: hit@10 51 vs 50, paired difference +0.017, 95% CI −0.034 to +0.086.

## 6. Diff scope

`git merge origin/main` was already up to date (opening). The four files of this task are the diff against the ONNX base. `origin/main..HEAD` also lists the ONNX PR, because this branch starts at that PR and `origin/main` does not contain it yet. **This PR must merge after the ONNX PR.** Open it with base `fix/w4-onnx-pin-repro` so the review diff is these four files.

`git diff --stat origin/fix/w4-onnx-pin-repro..HEAD` at `89e47ed` (the commit before this paragraph):

```
 README.md                       |  70 ++++++++++---
 reports/W4-README-QUICKSTART.md | 214 ++++++++++++++++++++++++++++++++++++++++
 src/preached/search.py          |  12 ++-
 tests/test_api_path.py          |   9 ++
 4 files changed, 285 insertions(+), 20 deletions(-)
```

`git diff --stat origin/main..HEAD` at the same commit:

```
 README.md                                |  70 +++--
 app/server.py                            |  23 ++
 docs/adr/0001-onnx-export-determinism.md |  43 ++++
 reports/W4-ONNX-PIN-REPRO.md             | 138 ++++++++++
 reports/W4-README-QUICKSTART.md          | 214 ++++++++++++++++
 scripts/export_onnx.py                   |  84 +++++-
 src/preached/artifacts.py                |  21 +-
 src/preached/search.py                   |  12 +-
 tests/test_api_path.py                   |   9 +
 tests/test_embed_backend.py              |   4 +-
 tests/test_onnx_pin_repro.py             | 427 +++++++++++++++++++++++++++++++
 11 files changed, 1017 insertions(+), 28 deletions(-)
```

The seven extra paths versus `origin/main` are the ONNX PR (`59b44fb`): `app/server.py`, `docs/adr/0001-onnx-export-determinism.md`, `reports/W4-ONNX-PIN-REPRO.md`, `scripts/export_onnx.py`, `src/preached/artifacts.py`, `tests/test_embed_backend.py`, `tests/test_onnx_pin_repro.py`. They are not edits made on this branch. The commit that adds this paragraph changes only this file's insertion count. The push-time stats are re-run and must still list only those paths.

## 7. Open issues

Section 9 closes the pin and the shared-graph failures. The 52 cite failures are not closed here: they came from #71 at `59b44fb` and are gone at `4d6ae86` (§10). The bullets under them stood at the first walkthrough.

- Finding 2 is deferred, as the table says. Until the ONNX PR has merged, a PR of this branch into `main` would also carry that PR's diff.
- The shared graph on this machine is still the old pin. The exact suite stays red on those five tests until that directory is re-exported. This task did not re-export it.
- The 52 `docs/DEPLOY.md` cite failures came from #71 at `59b44fb`. They are gone at `4d6ae86`. They are not a failure of this README diff, and they were not still open when §9 ran.
- A fresh cache has no Wesley transcripts, so align cannot succeed from the README alone. The audio ingest is `reports/W1-C.md`.
- `@channel` is a shape. It exits 1. A judge needs a real channel URL and a privacy config they have reviewed.

## 8. Dependencies added

None.

## 9. Re-sync with #71 at 1907d1f

**Precondition.** After `git fetch`, `origin/fix/w4-onnx-pin-repro` is `1907d1f`. `scripts/export_onnx.py` re-executes under `PYTHONHASHSEED=1`, sets `ATEN_CPU_CAPABILITY=avx2`, keeps the pin `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`, and defaults `HF_HOME` to `$PREACHED_CACHE/huggingface` (`/cache/huggingface` only when `PREACHED_CACHE` is unset). Not blocked.

**Merges.** Merge commits, no rebase. Both were clean (`ort`).

- `9b82a65` merges `origin/fix/w4-onnx-pin-repro` (`1907d1f`).
- `15e77c2` merges `origin/main` (`abdada3`). The only file that merge adds is `reports/W4-FRESH-CLONE-QA.md`.

`scripts/export_onnx.py` was not edited on this branch. It arrived with the first merge.

**README.** The export command is `uv run --group bench python scripts/export_onnx.py`, with no environment variables on the line. The script disables the GPU itself (`scripts/export_onnx.py:52`) before it imports torch, so no prefix is needed. This round did not run a second export with a prefix set. The run below wrote the pin. The missing-graph sentence still quotes `uv run --group bench python scripts/export_onnx.py`, which is `EXPORT_COMMAND` in `src/preached/artifacts.py`. That file was not edited here.

The `/cache` caveat is gone. An `HF_HOME` already set is kept. When it is unset, the export sets `$PREACHED_CACHE/huggingface`, and `/cache/huggingface` only when `PREACHED_CACHE` is unset. The sentence in §1 that says an unset `HF_HOME` reads `/cache/huggingface` is the export at `59b44fb`, not `1907d1f`.

The README names the pin `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`, the x86-64 + AVX2 requirement, the missing-graph log (`ERROR` embedding line, `ERROR ONNX GRAPH NOT BUILT`, `WARNING` model-not-built, then `PREACHED_LISTENING`), and `/healthz` `"search_mode": "bm25"` with `"search_mode_reason": "onnx_graph_not_built"`. Those reader-visible strings are unchanged at `1907d1f`. A graph that is present and is not the pin is still `error: ONNX sha256 for model.fp32.onnx is not the pinned digest`.

Finding 2 in the table was deferred to #71. That head is merged. The open pin item in §7 is closed by this section. The table cell is the first-round status.

**Re-run.** Fresh `PREACHED_CACHE=/cache/w4-readme-resync`, deleted afterwards. Unset: `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `PYTHONHASHSEED`, `ATEN_CPU_CAPABILITY`. `PREACHED_ONNX_DIR=$PREACHED_CACHE/onnx`, so the export's delete could not touch `/cache/models/granite-english-r2-onnx/`. That shared file's mtime stayed `2026-10-30 11:58:17` and its sha256 stayed `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`.

Host: x86-64, and `/proc/cpuinfo` flags include `avx2`.

| Step | Exit | Wall (s) | Notes |
| --- | --- | --- | --- |
| export | 0 | 35.41 | `uv run --group bench python scripts/export_onnx.py` |
| fetch | 0 | 1.432 | index for the query; the command text did not change |
| chunk | 0 | 0.476 | 8383 chunks |
| bench | 0 | 144.02 | CUDA embed 63.9 s; the headline is not in the README |
| query hybrid | 0 | 1.381 | once |
| query bm25 | 0 | 0.113 | once, `--side` |

The export downloaded the snapshot into the fresh cache and printed `snapshot /cache/w4-readme-resync/huggingface/hub/models--ibm-granite--granite-embedding-english-r2/snapshots/47ea694b257b703fee9253d75c2b1f2985180498`, then `fp32 sha256 matches the pin 3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`. The first walkthrough's export did not write that pin, because that script did not fix the hash seed. This graph is the pin, so the money query was re-run once per mode and recorded as run.

Hybrid, text-only (`start_s=None`, play `n/a`), no abstain line. Same rows as §3:

```
[1] The Use of Money  (score 0.0320, wesley-050-c0007)
[2] The Use of Money  (score 0.0318, wesley-050-c0004)
[3] Upon our Lord's Sermon on the Mount, Discourse 8  (score 0.0317, wesley-028-c0076)
```

Rows 4 and 5 were again The More Excellent Way `wesley-089-c0050` (0.0311) and The Use of Money `wesley-050-c0032` (0.0298).

BM25 `--side` (`mode: bm25`, `confidence: unrated`, `Classic library: John Wesley`), same top 3 as §3:

```
[1] The Use of Money  (score 9.0136, wesley-050-c0007)
[2] The Use of Money  (score 7.8838, wesley-050-c0032)
[3] Upon our Lord's Sermon on the Mount, Discourse 8  (score 7.8549, wesley-028-c0076)
```

The church column printed `Nothing from your church yet.`

The bench headline was again `hybrid_rrf recall@5=0.285 mrr@10=0.219 ndcg@10=0.246`. Those numbers are not in the README. `eval/results/2026-10-31.json` and `.md` were deleted and are not in the commit. `corpus/catalog.json` is not modified in git.

**Suite.** Exact command, from this worktree, `PREACHED_ONNX_DIR` unset (shared graph `3861025a…`):

```bash
PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests
```

Exit 0. Wall 271.101 s. `Ran 1027 tests in 270.453s`, `OK`, no skip line. The 52 cite failures and the five pin failures from §3 are not in this run. The cite failures had already gone at `4d6ae86` on #71; this re-sync is later than that commit. The five pin failures went away because the pin stayed `3861025a…` and the shared graph matches it.

`uv lock --check`: exit 0, wall 0.008 s, `Resolved 79 packages in 0.49ms`.

**Diff stat.** `git diff --stat origin/fix/w4-onnx-pin-repro..HEAD` after the commit that adds this section. The five paths are the four files of this PR plus `reports/W4-FRESH-CLONE-QA.md` from the main merge. `src/preached/search.py` and `tests/test_api_path.py` are the finding-17 change from the first round. They are not edited again here.

```
 README.md                       |  70 +++++++--
 reports/W4-FRESH-CLONE-QA.md    | 139 +++++++++++++++++
 reports/W4-README-QUICKSTART.md | 320 ++++++++++++++++++++++++++++++++++++++++
 src/preached/search.py          |  12 +-
 tests/test_api_path.py          |   9 ++
 5 files changed, 530 insertions(+), 20 deletions(-)
```

## 10. CTO review, on #71 at 27ed9cb

**Precondition.** After `git fetch`, `origin/fix/w4-onnx-pin-repro` is `27ed9cb`. `artifacts.onnx_root()` is `PREACHED_ONNX_DIR` when that variable is set, otherwise `$PREACHED_CACHE/models/granite-english-r2-onnx`, otherwise `/cache/models/granite-english-r2-onnx`. `EXPORT_COMMAND` in `src/preached/artifacts.py` is `uv run --group bench python scripts/export_onnx.py`. Not blocked.

**Merges.** Merge commits, no rebase and no force.

- `b662a0b` merges `origin/fix/w4-onnx-pin-repro` (`27ed9cb`). Clean (`ort`). The files that merge brings are `docs/DEPLOY.md`, `docs/adr/0001-onnx-export-determinism.md`, `reports/W4-ONNX-PIN-REPRO.md`, `scripts/export_onnx.py`, `src/preached/artifacts.py`, `tests/test_deploy_alerts.py`, and `tests/test_onnx_pin_repro.py`.
- `git merge origin/main` (`abdada3`) was already up to date. No second merge commit.

**README.** One knob, `PREACHED_CACHE`. The corpus, the SQLite index, the Hugging Face files, and the ONNX graph all live under it. The README does not name `PREACHED_ONNX_DIR`, and it does not describe an `HF_HOME` or `/cache/huggingface` caveat. The export line is `uv run --group bench python scripts/export_onnx.py`. It carries no environment prefix. The missing-graph sentence quotes that same command, which is `EXPORT_COMMAND` at this head. The pin is `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`. The script forces `ATEN_CPU_CAPABILITY=avx2` before torch and re-executes under `PYTHONHASHSEED=1`. An x86-64 host with AVX2 is required. A GPU is recommended for the bench. A CPU-only bench takes about 9 minutes (541.9 s measured on 8 cores). The README does not say the bench needs a GPU. Until the bench fail-closed change lands, a judge checks the bench output for an `error:` line: a model that fails to load currently falls back to BM25-only and the bench exits 0. The pre-registered sentence is unchanged, including U+2212 in `−0.034`. No other retrieval figure was added.

**Cites.** The 52 `test_every_cited_file_line_holds_its_string` failures in §3 came from #71 at `59b44fb`. They are gone at `4d6ae86`. §3's walkthrough started on `59b44fb`, where #71's own report counted those 52 subtests. #71's report at `4d6ae86` records `Ran 1023 tests in 266.212s`, `OK`, and zero `test_every_cited_file_line_holds_its_string` failures. §7's "unchanged / out of scope" and §9's "this section closes the cite failures" were the wrong attribution. §9's re-run is later than `4d6ae86`, so those 52 were already gone before that re-sync.

**Finding 17.** Two tests in `tests/test_api_path.py`. A Roman numeral after a verse, from the corpus: `Rom. 8:16 I. 1. None who believe` becomes `Rom. 8:16 None who believe`. `Matt. 5:13-16 1. The beauty of holiness` becomes `Matt. 5:13-16 The beauty of holiness`. The regex already did both. `src/preached/search.py` is not edited in this round.

**Suite.** From this worktree. `HF_HOME` was unset (the shell had it at `/cache/huggingface`). `PREACHED_ONNX_DIR` was unset. The shared graph stayed `3861025a…`.

```bash
PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests
```

Exit 0. `Ran 1036 tests in 269.285s`, `OK`, no skip line. Zero `test_every_cited_file_line_holds_its_string` failures.

**Cache.** A listing of `/cache` (path, size, mtime) had 132547 entries before that run and 132563 after. No file under the ONNX graph directory, the Hugging Face hub, or the SQLite index files themselves changed size or mtime. The fp32 graph sha256 is still `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`. What moved: `wesley.sqlite-shm` and `cc-speech.sqlite-shm` mtimes (sizes unchanged), the `/cache/models` directory mtime only, uv's editable metadata for the `/work/preached` install, deno's analysis-cache wal, an empty `/cache/demo-kill` mtime, and Claude MCP logs under `/cache/xdg` from another process.

**Diff stat.** `git diff --stat origin/fix/w4-onnx-pin-repro...HEAD` and `git diff --stat origin/fix/w4-onnx-pin-repro..HEAD` are the same, because `27ed9cb` is an ancestor of HEAD. `src/preached/search.py` is the finding-17 change from the first round. It is not edited in this round. The four paths are the whole diff against #71.

```
 README.md                       |  70 ++++++--
 reports/W4-README-QUICKSTART.md | 355 ++++++++++++++++++++++++++++++++++++++++
 src/preached/search.py          |  12 +-
 tests/test_api_path.py          |  25 +++
 4 files changed, 442 insertions(+), 20 deletions(-)
```

## 11. R3 resync

**Precondition.** After `git fetch`, `origin/fix/w4-onnx-pin-repro` is `1275223`. `reports/W4-ONNX-PIN-REPRO.md` on that head contains an `r3d` section (99-WB, main-side hunks of #72, #69 and #75). Not blocked.

**Merges.** Merge commits only. No rebase and no force-push. Conflicts were edited to the merged text. No `git checkout --ours` or `--theirs`, and no whole-file pick of one side.

- `1a52c0e` merges `origin/fix/w4-onnx-pin-repro` (`1275223`). Clean (`ort`). No conflicted files.
- `7d326dd` merges `origin/main` (`97537ae`, PR #76, bench fail-closed). One conflicted file: `README.md`.

**README conflict.** Kept this branch's quickstart, including the single `PREACHED_CACHE` knob and the `eval/validate.py` paragraph. Did not take main's sentence that weights use `HF_HOME=/cache/huggingface`. That sentence is the old workaround; Hugging Face files and the ONNX graph both live under `PREACHED_CACHE` (README line 7). Main's new sentence is the fail-closed behaviour. It replaces the interim note on this branch ("Until the bench fail-closed change lands… the bench exits 0"). The words are main's README line 14, now README line 20 here.

**Pin and seed, read on the r3d tree** (`src/preached/artifacts.py` and `scripts/export_onnx.py` at `1275223`, unchanged by this resync). `FP32_ONNX_SHA256` is `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` (`src/preached/artifacts.py:36`). The comment at `src/preached/artifacts.py:30-32` says the export fixes `ATEN_CPU_CAPABILITY=avx2` and `PYTHONHASHSEED=1`. `EXPORT_HASHSEED = "1"` is `scripts/export_onnx.py:94`. `_reexec_with_hashseed` sets that value and re-executes (`scripts/export_onnx.py:123-127`). `EXPORT_COMMAND` is `uv run --group bench python scripts/export_onnx.py` (`src/preached/artifacts.py:53`). The README export block (lines 25-27) is that command. The script itself disables the GPU at `scripts/export_onnx.py:52`, before it imports torch. The README does not name `PREACHED_ONNX_DIR` or `HF_HOME`. `onnx_root()` still honours `PREACHED_ONNX_DIR` when set (`src/preached/artifacts.py:72-76`); the quickstart does not document that override.

**Bench.** A GPU is recommended. A CPU-only bench takes about 9 minutes (541.9 s measured on 8 cores). README line 20. The fail-closed behaviour is what `search/bench.py` does on `97537ae`: the module docstring (`search/bench.py:37-41`) says exit 1 if any selected model fails to load or score, the report is still written, the model is marked `error`, or `skipped_gated` when the failure looks like a gated repo, and gated still fails. Under `--abstain` a gated failure is recorded as plain `error`. `--allow-bm25-only` turns that into a warning on stderr and exit 0. `run_abstain` always sets `entry["status"] = "error"` (`search/bench.py:880-882`). The plain loop sets `skipped_gated` only when `is_gated` matches (`search/bench.py:1067-1070`). Both paths write the json and markdown, then call `fail_closed` (`search/bench.py:1099-1102` and `889-896`). `fail_closed` (`search/bench.py:901-913`) exits 1 unless `--allow-bm25-only`, which prints the warning to stderr and returns.

**CTO sentence.** One occurrence, byte-exact with `docs/SUBMISSION-DRAFT.md`, U+2212 in `−0.034` (code point U+2212, README line 52):

`In a pre-registered evaluation (58 questions; relevance labels drafted with AI help, a subset confirmed blind by a human), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086).`

Checked absent from `README.md`: `0.629`, `0.614`, `0.506`, `0.558`, `0.497`, `0.546`, `0.285`, `0.219`, `0.246`, `0.297`, `0.241`, `0.265`. No other retrieval figure was added.

**Finding 17.** Not edited. `git diff 3252baa HEAD -- src/preached/search.py tests/test_api_path.py` is empty. The two tests stay in `tests/test_api_path.py`: `test_roman_numeral_after_a_verse_is_hidden` (lines 123-130) and `test_paragraph_number_after_matt_5_13_16_is_hidden` (lines 132-137). `Rom. 8:16 I. 1. None who believe` becomes `Rom. 8:16 None who believe`. `Matt. 5:13-16 1. The beauty of holiness` becomes `Matt. 5:13-16 The beauty of holiness`.

**Cites.** This resync does not edit `app/server.py` or any file cited in `docs/DEPLOY.md`. After both merges, `git diff origin/fix/w4-onnx-pin-repro -- app/server.py docs/DEPLOY.md tests/test_deploy_alerts.py` is empty, so nothing was re-pinned. The suite below has zero `test_every_cited_file_line_holds_its_string` failures.

**Suite.** Cache safety: `PREACHED_CACHE`, `PREACHED_ONNX_DIR` and `HF_HOME` pointed at `/tmp/w4-r3-suite/` (under `tempfile.gettempdir()`), not at `/cache`. `/cache` was bind-mounted read-only (`unshare -rm`, then `unshare --user --map-user=1000 --map-group=1000` so `geteuid()` stayed 1000). A touch of `/cache/.w4-r3-probe` inside that wrapper failed with `Read-only file system`. Also under the scratch dir: `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME`. `PREACHED_ONNX_DIR` was an empty directory. An earlier run that stayed at euid 0 was discarded: the server refused with `refusing to serve as root` (83 failures, 23 errors). It is not the result below.

```bash
PREACHED_REQUIRE_DENO=1 \
PREACHED_CACHE=/tmp/w4-r3-suite/cache \
PREACHED_ONNX_DIR=/tmp/w4-r3-suite/onnx \
HF_HOME=/tmp/w4-r3-suite/hf \
uv run python -m unittest discover -s tests
```

Exit 0. `Ran 1064 tests in 228.160s`, `OK (skipped=10)`. The 10 skips, from a scratch graph and no infra yaml:

- 6 in `test_embed_backend` (`artifact_dir()` has no `model.fp32.onnx`): `test_youtube_embed_path_does_not_import_torch`, `test_cached_fp32_and_tokenizer_match_the_pins`, `test_fp32_directory_without_int8_loads`, `test_fp32_query_is_unit_normalized`, `test_real_graph_has_no_external_data`, `test_load_refuses_a_symlinked_graph`.
- 1 in `test_onnx_pin_repro`: `MutantGraphTests.test_one_flipped_initializer_value_is_refused`.
- 1 in `test_onnx_pin_repro`: `ExportIsByteIdenticalTests` (no `model.safetensors` under the scratch `PREACHED_CACHE`).
- 1 in `test_eval_leak`: `test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk`.
- 1 in `test_deploy_regex`: `test_infra_yaml_matches_when_the_file_is_present`.

`uv lock --check` with the same scratch `UV_CACHE_DIR`: exit 0, `Resolved 79 packages in 0.52ms`.

**Cache.** `find /cache -printf '%p\t%s\t%T@\n' | sort`, before the suite and after `uv lock --check`. Both listings have 132629 entries. sha256 both `9742ff943e45839c910c6d14434471c5130aefa7ecaf161a43dd7124bd112122`. Paths, sizes and mtimes: no difference. An empty writability probe `/cache/.r3-probe-w4` was created and removed before that before-snapshot. It is not in either listing.

**Head.** `8d22cb7297264b26d1784335b73a12fd82bf9370` is the R3 section commit, the parent of the pushed head. The pushed head only replaces those 40 hex digits. Ahead/behind at the pushed head: vs `origin/main`, 0 behind and 48 ahead; vs `origin/fix/w4-onnx-pin-repro`, 0 behind and 18 ahead.

**Diff stat.** `git diff --stat origin/fix/w4-onnx-pin-repro...HEAD` at the pushed head. `1275223` is an ancestor, so `..` and `...` match. `src/preached/search.py` and `tests/test_api_path.py` are finding 17 from the first round. `search/bench.py`, `tests/test_bench_failclosed.py` and `reports/W5-BENCH-FAILCLOSED-R2.md` arrived with the merge of `origin/main` (`97537ae`, PR #76). They were not edited again here. Every path is in that set.

```
 README.md                         |  70 +++++--
 reports/W4-README-QUICKSTART.md   | 417 ++++++++++++++++++++++++++++++++++++++
 reports/W5-BENCH-FAILCLOSED-R2.md |  36 ++++
 search/bench.py                   |  25 +++
 src/preached/search.py            |  12 +-
 tests/test_api_path.py            |  25 +++
 tests/test_bench_failclosed.py    | 167 +++++++++++++++
 7 files changed, 732 insertions(+), 20 deletions(-)
```

## R5 (MF2)

The count of the retired GPU-mask variable name in this report is `0` (`grep -c` for it returns 0). The retired prefixed export command is replaced by the README command, `uv run --group bench python scripts/export_onnx.py`. The captured missing-graph line in the sandbox log now shows that command too; it was edited, not re-captured. `origin/main` was merged cleanly with no conflicts. That drops the three bench files from the diff.

`git diff --stat origin/main...HEAD`:

```
 README.md                       |  70 +++++--
 reports/W4-README-QUICKSTART.md | 431 ++++++++++++++++++++++++++++++++++++++++
 src/preached/search.py          |  12 +-
 tests/test_api_path.py          |  25 +++
 4 files changed, 517 insertions(+), 21 deletions(-)
```

## R6 (CTO CONDITIONAL at ffd31a5)

CTO marked `ffd31a5` conditional. R5 replaced the export command in two places and left the surrounding words as if the new command had been timed and printed. This round does not re-time or re-capture.

The §3 export row still shows wall 14.885 s next to `uv run --group bench python scripts/export_onnx.py`. That time was measured with the previous command (see R5). The row is labeled with that phrase, and the command cell is marked (edited; see R5).

The missing-graph block is introduced as what the server printed. The build command inside the block was edited in R5, not re-captured. That introduction now says (edited; see R5).
