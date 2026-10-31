# LICENSE-ARCTIC-NITS

## 1. What was done
- Test for the eval-only default check in `load_config` (`tests/test_search.py`).
- `load_embedder` and `TorchEmbedder.load` refuse eval-only models. `search/bench.py` is unaffected: it loads models through `preached.embed.load_model` directly (its explicit eval path), not `load_embedder`.
- `build_app` raises `ValueError` for an eval-only model (also with `bm25_only`), like `main()`, instead of quietly serving BM25.
- `Searcher` now refuses an eval-only model even when `fingerprint=` is passed (fixture models not in `models.toml` still work).
- README License section: LibriVox audio is public domain in the US only; names Wesley, Spurgeon, Edwards and points to their provenance files. Added `ingest/manifest/wesley.provenance.json`, generated only from fields already in `wesley.jsonl` (nothing invented).
- `reports/HOUSEKEEPING.md` corrected (provenance files exist); NOTICE mentions model weights; AGENTS.md no longer lists Arctic Embed as allowed.

## 2. How to run
`uv run python -m unittest discover tests`

## 3. Results
566 tests, OK. `uv lock --check`: passes (79 packages resolved).

## 4. Open issues
- The Spurgeon text source (spurgeon.org index) is a 404 now, per its provenance file; unchanged.

## 5. Dependencies added
None.
