# Retrieval benchmark, 2026-10-30T14:35:47-04:00

Scored list: the API path (`--dedupe`): top 100, `dedupe_adjacent`, top 10, as `GET /api/search` returns it.

Questions: 35 answerable, 5 unanswerable. Chunks: 8383. Commit `abbf735a3c286cb44c325de124543267387b784c` (dirty).
Libraries: torch 2.15.0+cu132, transformers 5.22.1, sentence-transformers 6.2.0. GPU: NVIDIA GeForce RTX 3060, 615.78.08. CPU: 12th Gen Intel(R) Core(TM) i9-12900K.

Cells are the mean with a bootstrap 95% interval over questions. Δ is a paired bootstrap of nDCG@10 against `granite-english-r2` `hybrid_rrf` (wins/ties/losses per question). See docs/research/embeddings.md.

| model | revision | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs ref | corpus dtype | chunks/s | CPU p50 / p95 ms | dim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 (SQLite FTS5) | | bm25 | 0.514 [0.34, 0.69] | 0.385 [0.26, 0.52] | 0.447 [0.32, 0.58] | 0.914 [0.80, 1.00] | -0.143 [-0.24, -0.05] (4/16/15) | | | | |
| granite-english-r2 | `47ea694b25` | dense | 0.629 [0.47, 0.79] | 0.471 [0.33, 0.61] | 0.510 [0.37, 0.65] | 0.800 [0.66, 0.91] | -0.080 [-0.18, +0.03] (5/19/11) | fp32 | 12.2 | 61.8 / 96.2 |  |
| granite-english-r2 | `47ea694b25` | hybrid_rrf | 0.657 [0.50, 0.80] | 0.540 [0.40, 0.68] | 0.590 [0.45, 0.72] | 0.971 [0.91, 1.00] | +0.000 [+0.00, +0.00] (0/35/0) | fp32 | 12.2 | 64.3 / 95.1 |  |
| granite-english-r2 | `47ea694b25` | hybrid_weighted | 0.600 [0.44, 0.76] | 0.515 [0.38, 0.65] | 0.576 [0.44, 0.70] | 0.943 [0.86, 1.00] | -0.013 [-0.05, +0.02] (2/28/5) | fp32 | 12.2 | 66.0 / 120.1 |  |

Prompts as the model sees them:

- `granite-english-r2`: question `What did Wesley say about worry?`; keyword `Christian perfection`; document `By grace are ye saved.`
