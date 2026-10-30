# Retrieval benchmark, 2026-10-30T13:13:57-04:00

Scored list: the API path (`--dedupe`): top 100, `dedupe_adjacent`, top 10, as `GET /api/search` returns it.

Questions: 35 answerable, 5 unanswerable. Chunks: 8383. Commit `826f8eb31ac2a29f4d077b265f06196a3bdf48ff`.
Libraries: torch 2.15.0+cpu, transformers 5.22.1, sentence-transformers 6.2.0. GPU: NVIDIA GeForce RTX 3060, 615.78.08. CPU: 12th Gen Intel(R) Core(TM) i9-12900K.

Cells are the mean with a bootstrap 95% interval over questions. Δ is a paired bootstrap of nDCG@10 against `granite-english-r2` `hybrid_rrf` (wins/ties/losses per question). See docs/research/embeddings.md.

| model | revision | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs ref | corpus dtype | chunks/s | CPU p50 / p95 ms | dim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 (SQLite FTS5) | | bm25 | 0.429 [0.26, 0.60] | 0.314 [0.19, 0.44] | 0.372 [0.25, 0.50] | 0.914 [0.80, 1.00] | -0.175 [-0.29, -0.07] (4/16/15) | | | | |
| granite-english-r2 | `47ea694b25` | dense | 0.600 [0.44, 0.76] | 0.420 [0.28, 0.56] | 0.464 [0.33, 0.60] | 0.800 [0.66, 0.91] | -0.082 [-0.19, +0.04] (5/18/12) | fp32 |  | 28.0 / 30.7 |  |
| granite-english-r2 | `47ea694b25` | hybrid_rrf | 0.614 [0.44, 0.77] | 0.497 [0.35, 0.64] | 0.546 [0.41, 0.68] | 0.971 [0.91, 1.00] | +0.000 [+0.00, +0.00] (0/35/0) | fp32 |  | 29.8 / 33.5 |  |
| granite-english-r2 | `47ea694b25` | hybrid_weighted | 0.543 [0.39, 0.70] | 0.461 [0.32, 0.60] | 0.528 [0.40, 0.66] | 0.943 [0.86, 1.00] | -0.018 [-0.08, +0.04] (3/26/6) | fp32 |  | 30.1 / 33.6 |  |

Prompts as the model sees them:

- `granite-english-r2`: question `What did Wesley say about worry?`; keyword `Christian perfection`; document `By grace are ye saved.`
