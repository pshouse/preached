# Retrieval benchmark, 2026-10-31T04:50:53-04:00

Questions: 86 answerable, 7 unanswerable. Chunks: 8383. Commit `57799618233917316f02e8c6cd1c1624df52f406`.
Libraries: torch 2.15.0+cu132, transformers 5.22.1, sentence-transformers 6.2.0. GPU: NVIDIA GeForce RTX 3060, 615.78.08. CPU: 12th Gen Intel(R) Core(TM) i9-12900K.

Cells are the mean with a bootstrap 95% interval over questions. Δ is a paired bootstrap of nDCG@10 against `granite-english-r2` `hybrid_rrf` (wins/ties/losses per question). See docs/research/embeddings.md.

| model | revision | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs ref | corpus dtype | chunks/s | CPU p50 / p95 ms | dim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 (SQLite FTS5) | | bm25 | 0.198 [0.12, 0.28] | 0.138 [0.08, 0.20] | 0.164 [0.10, 0.23] | 0.442 [0.34, 0.55] | -0.077 [-0.13, -0.03] (5/62/19) | | | | |
| granite-english-r2 | `47ea694b25` | dense | 0.267 [0.18, 0.36] | 0.196 [0.13, 0.27] | 0.237 [0.17, 0.31] | 0.535 [0.43, 0.64] | -0.004 [-0.06, +0.05] (14/60/12) | fp32 | 131.1 | 112.9 / 130.9 | 768 |
| granite-english-r2 | `47ea694b25` | hybrid_rrf | 0.279 [0.19, 0.37] | 0.214 [0.14, 0.29] | 0.241 [0.16, 0.32] | 0.605 [0.50, 0.71] | +0.000 [+0.00, +0.00] (0/86/0) | fp32 | 131.1 | 114.6 / 138.3 | 768 |
| granite-english-r2 | `47ea694b25` | hybrid_weighted | 0.244 [0.16, 0.34] | 0.202 [0.13, 0.28] | 0.239 [0.17, 0.32] | 0.581 [0.48, 0.69] | -0.002 [-0.02, +0.02] (7/72/7) | fp32 | 131.1 | 117.7 / 134.0 | 768 |

Per question group (mean nDCG@10 / R@5 / MRR@10; n answerable in the header). Group definitions: eval/README.md.

| model | mode | names-topic (n=23) | plain (n=25) | scripture-keyword (n=7) | title-keyword (n=3) | plain-blind (n=28) | overall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.272 / 0.348 / 0.188 | 0.004 / 0.000 / 0.007 | 0.876 / 1.000 / 0.833 | 0.544 / 0.667 / 0.500 | 0.000 / 0.000 / 0.000 | 0.164 / 0.198 / 0.138 |
| granite-english-r2 | dense | 0.360 / 0.435 / 0.308 | 0.078 / 0.040 / 0.043 | 0.704 / 0.857 / 0.655 | 1.000 / 1.000 / 1.000 | 0.080 / 0.107 / 0.041 | 0.237 / 0.267 / 0.196 |
| granite-english-r2 | hybrid_rrf | 0.472 / 0.522 / 0.413 | 0.028 / 0.040 / 0.013 | 0.895 / 1.000 / 0.857 | 0.667 / 0.667 / 0.667 | 0.032 / 0.071 / 0.019 | 0.241 / 0.279 / 0.214 |
| granite-english-r2 | hybrid_weighted | 0.438 / 0.478 / 0.369 | 0.025 / 0.000 / 0.010 | 0.895 / 1.000 / 0.857 | 0.767 / 0.667 / 0.704 | 0.047 / 0.036 / 0.020 | 0.239 / 0.244 / 0.202 |

Paired Δ nDCG@10 against the reference, per group (95% CI, wins/ties/losses):

| model | mode | names-topic | plain | scripture-keyword | title-keyword | plain-blind |
| --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | -0.200 [-0.35, -0.06] (3/8/12) | -0.024 [-0.07, +0.01] (1/22/2) | -0.019 [-0.16, +0.14] (1/4/2) | -0.123 [-0.37, +0.00] (0/2/1) | -0.032 [-0.08, +0.00] (0/26/2) |
| granite-english-r2 | dense | -0.113 [-0.22, -0.01] (3/13/7) | +0.050 [+0.01, +0.10] (4/20/1) | -0.190 [-0.44, +0.07] (1/3/3) | +0.333 [+0.00, +1.00] (1/2/0) | +0.049 [-0.01, +0.11] (5/22/1) |
| granite-english-r2 | hybrid_rrf | +0.000 [+0.00, +0.00] (0/23/0) | +0.000 [+0.00, +0.00] (0/25/0) | +0.000 [+0.00, +0.00] (0/7/0) | +0.000 [+0.00, +0.00] (0/3/0) | +0.000 [+0.00, +0.00] (0/28/0) |
| granite-english-r2 | hybrid_weighted | -0.034 [-0.08, +0.01] (2/17/4) | -0.003 [-0.01, +0.00] (1/23/1) | +0.000 [+0.00, +0.00] (0/7/0) | +0.100 [+0.00, +0.30] (1/2/0) | +0.016 [-0.03, +0.06] (3/23/2) |

## Strict vs lenient, per group

strict = grade-2 labels only; pre-grading = the labels before EVAL-GRADE; lenient = adds the grade-1 labels still marked "proposed" (not confirmed by a person). hit@10 = at least one labelled passage in the top 10. sermon@k = a top-k chunk from a grade-2 sermon.

### names-topic (n=23)

| model | mode | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | MRR@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.277 | 0.272 | 0.279 | 0.565 | 0.913 | 0.535 | 0.913 | 0.913 | 1.000 |
| granite-english-r2 | dense | 0.371 | 0.360 | 0.338 | 0.565 | 0.913 | 0.592 | 0.826 | 0.913 | 1.000 |
| granite-english-r2 | hybrid_rrf | 0.480 | 0.472 | 0.402 | 0.696 | 0.957 | 0.681 | 0.957 | 0.957 | 0.957 |
| granite-english-r2 | hybrid_weighted | 0.447 | 0.438 | 0.398 | 0.696 | 0.957 | 0.675 | 0.957 | 0.957 | 1.000 |

### plain (n=25)

| model | mode | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | MRR@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.000 | 0.004 | 0.037 | 0.000 | 0.320 | 0.131 | 0.120 | 0.240 | 0.680 |
| granite-english-r2 | dense | 0.078 | 0.078 | 0.155 | 0.200 | 0.680 | 0.412 | 0.400 | 0.600 | 0.880 |
| granite-english-r2 | hybrid_rrf | 0.028 | 0.028 | 0.132 | 0.080 | 0.720 | 0.395 | 0.400 | 0.560 | 0.880 |
| granite-english-r2 | hybrid_weighted | 0.025 | 0.025 | 0.112 | 0.080 | 0.680 | 0.359 | 0.400 | 0.560 | 0.840 |

### scripture-keyword (n=7)

| model | mode | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | MRR@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.876 | 0.876 | 0.486 | 1.000 | 1.000 | 0.929 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | dense | 0.704 | 0.704 | 0.394 | 0.857 | 0.857 | 0.667 | 0.714 | 0.714 | 0.857 |
| granite-english-r2 | hybrid_rrf | 0.895 | 0.895 | 0.513 | 1.000 | 1.000 | 0.929 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | hybrid_weighted | 0.895 | 0.895 | 0.519 | 1.000 | 1.000 | 0.929 | 1.000 | 1.000 | 1.000 |

### title-keyword (n=3)

| model | mode | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | MRR@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.544 | 0.544 | 0.462 | 0.667 | 1.000 | 0.611 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | dense | 1.000 | 1.000 | 0.661 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | hybrid_rrf | 0.667 | 0.667 | 0.544 | 0.667 | 1.000 | 0.833 | 1.000 | 1.000 | 1.000 |
| granite-english-r2 | hybrid_weighted | 0.767 | 0.767 | 0.561 | 1.000 | 1.000 | 0.778 | 1.000 | 1.000 | 1.000 |

### plain-blind (n=28)

| model | mode | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | MRR@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.000 | 0.000 | 0.011 | 0.000 | 0.107 | 0.048 | 0.143 | 0.143 | 0.429 |
| granite-english-r2 | dense | 0.080 | 0.080 | 0.073 | 0.214 | 0.393 | 0.106 | 0.321 | 0.536 | 0.893 |
| granite-english-r2 | hybrid_rrf | 0.032 | 0.032 | 0.027 | 0.071 | 0.107 | 0.050 | 0.357 | 0.357 | 0.821 |
| granite-english-r2 | hybrid_weighted | 0.047 | 0.047 | 0.042 | 0.143 | 0.214 | 0.060 | 0.286 | 0.429 | 0.786 |

### overall (n=86)

| model | mode | nDCG@10 strict | nDCG@10 pre-grading | nDCG@10 lenient | hit@10 strict | hit@10 lenient | MRR@10 lenient | sermon@5 | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.164 | 0.164 | 0.145 | 0.256 | 0.488 | 0.294 | 0.442 | 0.477 | 0.721 |
| granite-english-r2 | dense | 0.240 | 0.237 | 0.215 | 0.384 | 0.674 | 0.402 | 0.535 | 0.686 | 0.919 |
| granite-english-r2 | hybrid_rrf | 0.243 | 0.241 | 0.216 | 0.337 | 0.616 | 0.418 | 0.605 | 0.651 | 0.895 |
| granite-english-r2 | hybrid_weighted | 0.242 | 0.239 | 0.215 | 0.372 | 0.640 | 0.407 | 0.581 | 0.674 | 0.884 |

Prompts as the model sees them:

- `granite-english-r2`: question `What did Wesley say about worry?`; keyword `Christian perfection`; document `By grace are ye saved.`
