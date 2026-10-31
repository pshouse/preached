# BENCH-API-FIX

## What was done
`scripts/bench_api.py` refused to run: it required exactly 40 queries, and `eval/questions.jsonl` now has 93. It now reads every query from the eval file. The integrity check is that every line parses, ids are unique and queries are non-empty. The summary records `n_queries` and `queries_sha256` instead of a magic number. It also reports `rss_peak_bytes` (VmHWM). `tests/test_bench_api.py` loads the real eval file and compares it row-for-row, and checks that other counts are accepted and bad rows refused. The old 40 check would have failed it.

## How to run it
```
CUDA_VISIBLE_DEVICES="" uv run python scripts/bench_api.py --repeats 3
```
Hybrid mode, library wesley, k=10, one warmup query excluded, foreground (~30 s).

## Results (current index, /cache/index/wesley.sqlite, 8383 chunks, granite-english-r2, onnx)
CPU: 12th Gen Intel Core i9-12900K (omarchy, no AMX). 93 queries x 3 repeats = 279 samples.

| metric | value |
| --- | --- |
| p50 | 96.8 ms |
| p95 | 135.3 ms |
| min / max | 49.7 / 160.9 ms |
| RSS after model load | 1.60 GB (1597095936 B) |
| RSS after queries | 1.66 GB (1656262656 B) |
| peak RSS (VmHWM) | 1.90 GB (1898250240 B) |
| cold start | 1.6 s |
| queries_sha256 | b54589a98a2c6cdf... |

## Open issues
The latency figures are one run on a desktop CPU with default ORT threads, so they are not comparable with a Sprite. No dependencies added.
