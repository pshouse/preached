# W4-README-QUICKSTART: a judge can follow the README from a fresh cache

Fresh-clone QA findings 1 and 3–18 (`reports/W4-FRESH-CLONE-QA.md` on `qa/w4-fresh-clone`, PR #68, as corrected for CTO MF1/MF2). Branch `docs/w4-readme-quickstart`.

**Base.** `origin/main` is `b224281` and does not contain the ONNX PR. This branch starts at `origin/fix/w4-onnx-pin-repro` (`59b44fb`), which does contain `ATEN_CPU_CAPABILITY` in `scripts/export_onnx.py`. `git merge origin/main` returned **Already up to date**: `origin/main` is an ancestor, so there is no merge commit. **This PR must merge after the ONNX PR.**

**Result.** The README now builds the ONNX graph, checks it against the pin, and says what a missing graph prints. Retrieval figures in the README are only the pre-registered sentence. The example query is the demo-script money question, run once per mode. A paragraph number that sits right after a verse reference is hidden, with a test that failed before the change.

## 1. What was done

`README.md` is rewritten for a clone. It names uv (`uv_build>=0.13.6,<0.14`), Python `>=3.12,<3.14`, network, disk, and `ffmpeg` for audio. It documents `PREACHED_CACHE` (default `/cache`): the directory must exist and be writable, and an unset `HF_HOME` is set to `$PREACHED_CACHE/huggingface` by the library code. The quickstart is text-only (`start_s` empty, play `n/a`). The first block fetches, chunks, validates, and benches **Granite only**. It then syncs the bench group and runs `scripts/export_onnx.py`, which pins `ATEN_CPU_CAPABILITY=avx2` and needs an x86-64 host with AVX2. The export keeps an ambient `HF_HOME` (`setdefault` before torch); when that variable is unset the export reads `/cache/huggingface`. It deletes the revision directory under `PREACHED_ONNX_DIR` (default `/cache/models/granite-english-r2-onnx/<revision>/`) before writing, and it prints the pin line or exits non-zero with no manifest. The later `uv sync` is described as dropping the bench group. Alignment is a separate step, after fetch, and the README says to do it before expecting playback. The church block is a shape (`--privacy privacy.example.toml`); `@channel` is not a channel to import. YouTube placeholders are quoted `"SLUG"` and `"privacy.toml"`. Local outputs (`corpus/catalog.json`, `eval/results/`) and `--accept-new-text` are named. The opening line is "This repo builds". The server section is "From the clone:". Wesley is described as built in on its own pipeline; `src/preached/libraries.py` lists Spurgeon and Edwards. The test command is `uv run python -m unittest discover -s tests`, and the README states no count. `reports/W3-CPU.md`'s count and worktree path are called stale.

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

Then the README blocks, in order: `corpus/fetch_wesley.py`, `corpus/chunk_sermons.py`, `eval/validate.py`, `search/bench.py --models granite-english-r2` under `--group bench`, `uv sync --group bench`, `CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py`, the hybrid money query, `uv sync`, `uv run app/server.py`. Alignment, the church shape, `--bm25-only`, the bm25 `--side` query, and the three quoted YouTube lines follow. The test command is the discover line above.

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
| export | 0 | 14.885 | `CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py` |
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

`uv sync --group bench` was `Resolved 79 packages` / `Checked 70 packages` (already installed). The export read the snapshot at `/cache/huggingface/hub/models--ibm-granite--granite-embedding-english-r2/snapshots/47ea694b257b703fee9253d75c2b1f2985180498` and printed `fp32 sha256 matches the pin aed7adbae73975b28f076b68d6e7429f40c74e7b1ea9612f390b952dedf85b78`. The later `uv sync` printed `Uninstalled 49 packages`, including torch.

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

After that index existed, the same server command with `PREACHED_ONNX_DIR` pointed at an empty directory printed, in order:

```
ERROR embedding model unavailable; serving BM25 only
ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only. missing ONNX manifest at /tmp/w4-empty-onnx/47ea694b257b703fee9253d75c2b1f2985180498/manifest.json; build it with: CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py
WARNING The search model has not been built; results are BM25 only.
PREACHED_LISTENING http://127.0.0.1:8000
```

`GET /healthz` was `fallback: true`, `dense: false`, `search_mode: bm25`, `search_mode_reason: onnx_graph_not_built`, `model: null`, `chunks: 8383`. The money query was not run again. `search/query.py` prints `error:` plus the `ArtifactMissing` text and exits 1; that string is the same missing-manifest sentence. A graph that is present and is not the pin raises `ONNX sha256 for model.fp32.onnx is not the pinned digest` (seen on the shared old graph in the exact suite).

With the fresh graph, `/healthz` was `fallback: false`, `dense: true`, `search_mode: hybrid`, `search_mode_reason: null`, `backend: onnx`, `model: granite-english-r2`, `model_sha256: aed7adba…`. The log line was `INFO embed backend=onnx variant=fp32 threads=1`. `--bm25-only` logged `INFO BM25 only; the embedding model was not loaded` and `/healthz` was `search_mode: bm25`, `search_mode_reason: bm25_only`, `fallback: false`, `model: null`.

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

- **52** subtests of `test_deploy_alerts.RunbookTests.test_every_cited_file_line_holds_its_string`. Stale `docs/DEPLOY.md` cites. `docs/DEPLOY.md` was not edited.
- **3 failures and 2 errors** open the shared graph and refuse it (`ONNX sha256 for model.fp32.onnx is not the pinned digest`; the pin test asserts `3861025a… != aed7adba…`):
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

`git merge origin/main` was already up to date (section opening). No files outside the task were edited: `README.md`, `src/preached/search.py`, `tests/test_api_path.py`, and this report.

`git diff --stat origin/fix/w4-onnx-pin-repro..HEAD` is the in-scope check, because that commit is the branch base. `git diff --stat origin/main..HEAD` also lists the ONNX PR's files (`app/server.py`, `docs/adr/0001-onnx-export-determinism.md`, `reports/W4-ONNX-PIN-REPRO.md`, `scripts/export_onnx.py`, `src/preached/artifacts.py`, `tests/test_embed_backend.py`, `tests/test_onnx_pin_repro.py`). Those belong to the PR this one must follow. The stat blocks are filled in the commit that records them.

## 7. Open issues

- Finding 2 is deferred, as the table says. Until the ONNX PR has merged, a PR of this branch into `main` would also carry that PR's diff.
- The shared graph on this machine is still the old pin. The exact suite stays red on those five tests until that directory is re-exported. This task did not re-export it.
- The 52 `docs/DEPLOY.md` cite failures are unchanged. That file is out of scope.
- A fresh cache has no Wesley transcripts, so align cannot succeed from the README alone. The audio ingest is `reports/W1-C.md`.
- `@channel` is a shape. It exits 1. A judge needs a real channel URL and a privacy config they have reviewed.

## 8. Dependencies added

None.
