# Retrieval benchmark, 2026-10-30T13:59:27-04:00

Scored list: the API path (`--dedupe`): top 100, `dedupe_adjacent`, top 10, as `GET /api/search` returns it.

Questions: 35 answerable, 5 unanswerable. Chunks: 8383. Commit `39bc8e2b59819ff4e7dad672d041b53fd31c3ad3`.
Libraries: torch 2.15.0+cu132, transformers 5.22.1, sentence-transformers 6.2.0. GPU: NVIDIA GeForce RTX 3060, 615.78.08. CPU: 12th Gen Intel(R) Core(TM) i9-12900K.

Cells are the mean with a bootstrap 95% interval over questions. Δ is a paired bootstrap of nDCG@10 against `granite-english-r2` `hybrid_rrf` (wins/ties/losses per question). See docs/research/embeddings.md.

| model | revision | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs ref | corpus dtype | chunks/s | CPU p50 / p95 ms | dim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 (SQLite FTS5) | | bm25 | 0.514 [0.34, 0.69] | 0.385 [0.26, 0.52] | 0.447 [0.32, 0.58] | 0.914 [0.80, 1.00] | -0.143 [-0.24, -0.05] (4/16/15) | | | | |
| granite-english-r2 | `47ea694b25` | dense | 0.629 [0.47, 0.79] | 0.471 [0.33, 0.61] | 0.510 [0.37, 0.65] | 0.800 [0.66, 0.91] | -0.080 [-0.18, +0.03] (5/19/11) | fp32 | 131.1 | 112.3 / 127.2 | 768 |
| granite-english-r2 | `47ea694b25` | hybrid_rrf | 0.657 [0.50, 0.80] | 0.540 [0.40, 0.68] | 0.590 [0.45, 0.72] | 0.971 [0.91, 1.00] | +0.000 [+0.00, +0.00] (0/35/0) | fp32 | 131.1 | 112.0 / 135.0 | 768 |
| granite-english-r2 | `47ea694b25` | hybrid_weighted | 0.600 [0.44, 0.76] | 0.515 [0.38, 0.65] | 0.576 [0.44, 0.70] | 0.943 [0.86, 1.00] | -0.013 [-0.05, +0.02] (2/28/5) | fp32 | 131.1 | 110.0 / 138.8 | 768 |
| embeddinggemma-2 | `f9972ac22e` | dense | 0.614 [0.46, 0.77] | 0.366 [0.25, 0.49] | 0.441 [0.32, 0.56] | 0.857 [0.74, 0.97] | -0.149 [-0.25, -0.05] (6/14/15) | fp32 | 80.6 | 129.6 / 155.1 | 768 |
| embeddinggemma-2 | `f9972ac22e` | hybrid_rrf | 0.671 [0.51, 0.81] | 0.509 [0.37, 0.64] | 0.561 [0.43, 0.69] | 0.943 [0.86, 1.00] | -0.028 [-0.09, +0.03] (7/21/7) | fp32 | 80.6 | 127.0 / 146.8 | 768 |
| embeddinggemma-2 | `f9972ac22e` | hybrid_weighted | 0.614 [0.46, 0.77] | 0.468 [0.33, 0.60] | 0.524 [0.39, 0.66] | 0.943 [0.86, 1.00] | -0.066 [-0.15, +0.01] (7/20/8) | fp32 | 80.6 | 135.0 / 147.6 | 768 |

Prompts as the model sees them:

- `granite-english-r2`: question `What did Wesley say about worry?`; keyword `Christian perfection`; document `By grace are ye saved.`
- `embeddinggemma-2`: question `task: question answering | query: What did Wesley say about worry?`; keyword `task: search result | query: Christian perfection`; document `title: none | text: By grace are ye saved.`
