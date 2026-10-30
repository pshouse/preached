# Retrieval benchmark, 2026-10-30T13:14:27-04:00

Scored list: the API path (`--dedupe`): top 100, `dedupe_adjacent`, top 10, as `GET /api/search` returns it.

Questions: 35 answerable, 5 unanswerable. Chunks: 8383. Commit `826f8eb31ac2a29f4d077b265f06196a3bdf48ff`.
Libraries: torch 2.15.0+cpu, transformers 5.22.1, sentence-transformers 6.2.0. GPU: NVIDIA GeForce RTX 3060, 615.78.08. CPU: 12th Gen Intel(R) Core(TM) i9-12900K.

Cells are the mean with a bootstrap 95% interval over questions. Δ is a paired bootstrap of nDCG@10 against `granite-english-r2` `hybrid_rrf` (wins/ties/losses per question). See docs/research/embeddings.md.

| model | revision | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs ref | corpus dtype | chunks/s | CPU p50 / p95 ms | dim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 (SQLite FTS5) | | bm25 | 0.429 [0.26, 0.60] | 0.314 [0.19, 0.44] | 0.372 [0.25, 0.50] | 0.914 [0.80, 1.00] | -0.136 [-0.24, -0.04] (3/18/14) | | | | |
| granite-english-r2 | `47ea694b25` | dense | 0.486 [0.33, 0.64] | 0.424 [0.28, 0.57] | 0.476 [0.34, 0.61] | 0.857 [0.74, 0.97] | -0.032 [-0.13, +0.07] (7/17/11) | int8 | 17.5 | 11.6 / 13.4 |  |
| granite-english-r2 | `47ea694b25` | hybrid_rrf | 0.614 [0.46, 0.77] | 0.439 [0.31, 0.57] | 0.507 [0.38, 0.63] | 0.971 [0.91, 1.00] | +0.000 [+0.00, +0.00] (0/35/0) | int8 | 17.5 | 13.3 / 16.3 |  |
| granite-english-r2 | `47ea694b25` | hybrid_weighted | 0.514 [0.36, 0.67] | 0.474 [0.33, 0.62] | 0.526 [0.39, 0.66] | 0.914 [0.80, 1.00] | +0.018 [-0.05, +0.09] (4/26/5) | int8 | 17.5 | 13.4 / 16.6 |  |

Prompts as the model sees them:

- `granite-english-r2`: question `What did Wesley say about worry?`; keyword `Christian perfection`; document `By grace are ye saved.`
