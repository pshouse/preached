# Retrieval benchmark, 2026-10-30T13:58:33-04:00

Scored list: the API path (`--dedupe`): top 100, `dedupe_adjacent`, top 10, as `GET /api/search` returns it.

Questions: 35 answerable, 5 unanswerable. Chunks: 8383. Commit `23bc496e6abfa8bea3e18450ab5a76c66e8585b4`.
Libraries: torch 2.15.0+cu132, transformers 5.22.1, sentence-transformers 6.2.0. GPU: NVIDIA GeForce RTX 3060, 615.78.08. CPU: 12th Gen Intel(R) Core(TM) i9-12900K.

Cells are the mean with a bootstrap 95% interval over questions. Δ is a paired bootstrap of nDCG@10 against `granite-english-r2` `hybrid_rrf` (wins/ties/losses per question). See docs/research/embeddings.md.

| model | revision | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs ref | corpus dtype | chunks/s | CPU p50 / p95 ms | dim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 (SQLite FTS5) | | bm25 | 0.429 [0.26, 0.60] | 0.314 [0.19, 0.44] | 0.372 [0.25, 0.50] | 0.914 [0.80, 1.00] | -0.175 [-0.29, -0.07] (4/16/15) | | | | |
| granite-english-r2 | `47ea694b25` | dense | 0.600 [0.44, 0.76] | 0.420 [0.28, 0.56] | 0.464 [0.33, 0.60] | 0.800 [0.66, 0.91] | -0.082 [-0.19, +0.04] (5/18/12) | fp32 | 131.1 | 112.0 / 118.6 | 768 |
| granite-english-r2 | `47ea694b25` | hybrid_rrf | 0.614 [0.44, 0.77] | 0.497 [0.35, 0.64] | 0.546 [0.41, 0.68] | 0.971 [0.91, 1.00] | +0.000 [+0.00, +0.00] (0/35/0) | fp32 | 131.1 | 111.2 / 131.5 | 768 |
| granite-english-r2 | `47ea694b25` | hybrid_weighted | 0.543 [0.39, 0.70] | 0.461 [0.32, 0.60] | 0.528 [0.40, 0.66] | 0.943 [0.86, 1.00] | -0.018 [-0.08, +0.04] (3/26/6) | fp32 | 131.1 | 110.1 / 129.3 | 768 |
| embeddinggemma-2 | `f9972ac22e` | dense | 0.557 [0.40, 0.71] | 0.329 [0.22, 0.45] | 0.406 [0.29, 0.52] | 0.857 [0.74, 0.97] | -0.141 [-0.27, -0.00] (8/11/16) | fp32 | 80.6 | 132.0 / 144.1 | 768 |
| embeddinggemma-2 | `f9972ac22e` | hybrid_rrf | 0.671 [0.51, 0.81] | 0.462 [0.33, 0.60] | 0.522 [0.39, 0.65] | 0.943 [0.86, 1.00] | -0.025 [-0.12, +0.08] (8/18/9) | fp32 | 80.6 | 127.3 / 145.8 | 768 |
| embeddinggemma-2 | `f9972ac22e` | hybrid_weighted | 0.586 [0.43, 0.74] | 0.453 [0.32, 0.59] | 0.506 [0.37, 0.64] | 0.943 [0.86, 1.00] | -0.040 [-0.16, +0.07] (9/18/8) | fp32 | 80.6 | 134.7 / 150.1 | 768 |

Prompts as the model sees them:

- `granite-english-r2`: question `What did Wesley say about worry?`; keyword `Christian perfection`; document `By grace are ye saved.`
- `embeddinggemma-2`: question `task: question answering | query: What did Wesley say about worry?`; keyword `task: search result | query: Christian perfection`; document `title: none | text: By grace are ye saved.`
