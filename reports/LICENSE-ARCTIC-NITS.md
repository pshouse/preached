# LICENSE-ARCTIC-NITS

## 1. What was done
- Test for the eval-only default check in `load_config` (`tests/test_search.py`).
- `load_embedder` and `TorchEmbedder.load` refuse eval-only models. `search/bench.py` loads models through `preached.embed.load_model` directly (its explicit eval path), not `load_embedder`.
- `build_app` raises `ValueError` for an eval-only model (also with `bm25_only`), like `main()`, instead of quietly serving BM25.
- `Searcher` refuses an eval-only model, also when `fingerprint=` is passed, unless the keyword-only `allow_eval_only=True` is given (fixture models not in `models.toml` still work).
- README License section: names Wesley, Spurgeon, Edwards and points to their provenance files. Added `ingest/manifest/wesley.provenance.json`, generated only from fields already in `wesley.jsonl` (nothing invented). Round 1 corrected the wording: Wesley First Series audio is CC0 1.0, Second and Third-Fifth Series are Public Domain Mark 1.0 (as are Spurgeon/Edwards), LibriVox states public domain in the US.
- `reports/HOUSEKEEPING.md` corrected (provenance files exist); NOTICE mentions model weights; AGENTS.md no longer lists Arctic Embed as allowed.

## 2. How to run
`uv run python -m unittest discover tests`

## 3. Results
628 tests, OK. `uv lock --check`: passes (79 packages resolved). Head SHA: see the last commit on `chore/license-arctic-nits` (`git rev-parse HEAD`).

## 3a. Round 1 fix-up (CTO CHANGES on 20fd863)
Merged origin/main (merge commit, no rebase).

| Item | Change | Test |
|---|---|---|
| M1 | `Searcher(..., *, allow_eval_only=False)`; `True` only in `search/bench.py` (cpu_eval, abstain_rows), `eval/pool.py`, `scripts/check_dedupe.py`, `scripts/check_nl_questions.py`. `load_embedder`, `TorchEmbedder.load`, `build_app` still refuse, no flag. | `tests/test_eval_only.py`: `test_cpu_eval_scores_arctic_without_weights` (stub encode, tiny Arctic index, `load_model` patched to fail), `test_searcher_needs_the_explicit_flag`, `test_flag_stays_out_of_the_product` (source scan of app/, search/query.py, src/preached/ except search.py) |
| M1 docs | Fixed false lines in `docs/research/embeddings.md`, `reports/HOUSEKEEPING.md`, this report | n/a |
| S1 | README and `wesley.provenance.json` licence wording corrected; "US-only" and "Nothing here is added" dropped | n/a |
| S2 | Drift guard | `tests/test_licenses.py` (tracks and licence per `ia_identifier` vs `wesley.jsonl`) |
| N1 | `build_app` rejects any key not in `RUNTIME_MODELS` ("unknown model" vs "eval-only") | `test_build_app_rejects_unknown_model` |
| N2 | `hosts={"127.0.0.1"}` in the eval-only build_app test | `test_build_app_rejects_eval_only_model` |
| N3 | `preached.embed.load_model` patched in the TorchEmbedder.load test | `test_load_embedder_rejects_eval_only_model` |

Bench re-run: `uv run --group bench search/bench.py --models arctic-embed-l --allow-cached --out /tmp/arctic-rerun.json` (foreground, exit 0): arctic-embed-l status **"ok"** (it also ran granite, the default). 93 questions, 8383 chunks, cached vectors, CPU p50 about 152 ms.

| arctic-embed-l | recall@5 | mrr@10 | ndcg@10 | hit@10 | sermon@5 | sermon@10 | sermon@50 |
|---|---|---|---|---|---|---|---|
| dense | 0.244 | 0.166 | 0.195 | 0.302 | 0.512 | 0.616 | 0.849 |
| hybrid_rrf | 0.267 | 0.182 | 0.215 | 0.326 | 0.558 | 0.651 | 0.860 |
| hybrid_weighted | 0.308 | 0.216 | 0.245 | 0.349 | 0.547 | 0.628 | 0.849 |

Not re-run: `eval/pool.py --models arctic-embed-l` (needs weights loaded plus a pool build); it uses the same one-line change.

## 4. Open issues
- The Spurgeon text source (spurgeon.org index) is a 404 now, per its provenance file; unchanged.

## 5. Dependencies added
None.
