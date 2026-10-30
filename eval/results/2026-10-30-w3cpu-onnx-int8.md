# Retrieval benchmark, 2026-10-30T13:11:01-04:00

Questions: 35 answerable, 5 unanswerable. Chunks: 8383. Commit `826f8eb31ac2a29f4d077b265f06196a3bdf48ff`.
Libraries: torch 2.15.0+cpu, transformers 5.22.1, sentence-transformers 6.2.0. GPU: NVIDIA GeForce RTX 3060, 615.78.08. CPU: 12th Gen Intel(R) Core(TM) i9-12900K.

Cells are the mean with a bootstrap 95% interval over questions. Δ is a paired bootstrap of nDCG@10 against `granite-english-r2` `hybrid_rrf` (wins/ties/losses per question). See docs/research/embeddings.md.

| model | revision | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs ref | corpus dtype | chunks/s | CPU p50 / p95 ms | dim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 (SQLite FTS5) | | bm25 | 0.486 [0.31, 0.66] | 0.333 [0.22, 0.46] | 0.401 [0.28, 0.53] | 0.886 [0.77, 0.97] | -0.130 [-0.22, -0.04] (4/15/16) | | | | |
| granite-english-r2 | `47ea694b25` | dense | 0.457 [0.30, 0.61] | 0.420 [0.28, 0.56] | 0.478 [0.35, 0.61] | 0.857 [0.74, 0.97] | -0.052 [-0.14, +0.04] (6/16/13) | int8 | 17.5 | 11.1 / 12.7 |  |
| granite-english-r2 | `47ea694b25` | hybrid_rrf | 0.600 [0.44, 0.76] | 0.462 [0.33, 0.59] | 0.530 [0.40, 0.65] | 0.914 [0.80, 1.00] | +0.000 [+0.00, +0.00] (0/35/0) | int8 | 17.5 | 13.0 / 16.0 |  |
| granite-english-r2 | `47ea694b25` | hybrid_weighted | 0.514 [0.36, 0.67] | 0.486 [0.34, 0.63] | 0.526 [0.38, 0.66] | 0.914 [0.80, 1.00] | -0.004 [-0.06, +0.06] (3/27/5) | int8 | 17.5 | 13.1 / 16.2 |  |

Prompts as the model sees them:

- `granite-english-r2`: question `What did Wesley say about worry?`; keyword `Christian perfection`; document `By grace are ye saved.`
