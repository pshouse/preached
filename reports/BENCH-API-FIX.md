# BENCH-API-FIX

## What was done
`scripts/bench_api.py` refused to run: it required exactly 40 queries, and `eval/questions.jsonl` now has 93. It now reads every query from the eval file. The integrity check is that every line parses, ids are unique and queries are non-empty. The summary records `n_queries` and `queries_id_sha256` instead of a magic number. It also reports `rss_peak_bytes` (VmHWM). `tests/test_bench_api.py` loads the real eval file and compares it row-for-row, and checks that other counts are accepted and bad rows refused. The old 40 check would have failed it.

## How to run it
```
CUDA_VISIBLE_DEVICES="" uv run python scripts/bench_api.py --repeats 3
```
Hybrid mode, library wesley, k=10, one warmup query excluded, foreground (~30 s). The script sets `PREACHED_RATE_LIMIT` and `PREACHED_GLOBAL_RATE_LIMIT` to 1000000 on the loopback-only child (unless already set), so #18's 120/60 s per-IP limit (and #29's knobs of the same names) no longer 429 a `--repeats 3` run. `cold_start_s` is process spawn to the end of the healthz check plus one warmup query; the eval parse happens before spawn and is excluded.

## Results
Measured on main at ef4d4eb (before #26; no heap trim), not on #26. Which sha is which: the eval file at ef4d4eb hashes (with this script's `queries_sha256`) to `0c6718a9c792...`; the post-#22 file, at fc0492a and since, hashes to `2a42a2118872...`, the value quoted in the table. The table's queries are the post-#22 set, so the latency numbers were not taken on ef4d4eb's exact query file. A `--repeats 1` re-run on the merged branch (fcbd29a + this fix) gave p50 96.1 ms, p95 132.1 ms, peak 1.898 GB, so the table below still holds. `rss_peak_bytes` is the model-load high-water mark: RSS after load is 1.60 GB and VmHWM is already ~1.85 GB before any query, so #26's heap trim may not show up in the peak; compare `rss_bytes_after_queries` instead.

Index and setup (current index, /cache/index/wesley.sqlite, 8383 chunks, granite-english-r2, onnx)
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
| queries_id_sha256 | 2a42a2118872ac26... (sha256 of `[[id, query], ...]` JSON, file order) |

## CTO round 1 fixes (PR #28)
| item | change | test |
| --- | --- | --- |
| MUST-FIX 1 (429) | `env.setdefault` of rate-limit knobs; `once()` catches `HTTPError`, exits with status and body | not run against #18/#29 (not in this branch); knob names checked in their code |
| SHOULD 1 | `queries()` refuses non-dict rows, non-str/empty ids, bad JSON with path:line; runs before server start | `test_bad_rows_are_refused_with_path_and_line`, `test_int_and_string_ids_are_not_both_accepted` |
| SHOULD 2 | `queries_id_sha256` over `[[id, query], ...]` | `test_hash_covers_ids_and_query_boundaries` |
| SHOULD 3 | commit provenance and peak-RSS caveat above | n/a |
| SHOULD 4 | invariants asserted on the real eval file | `test_queries_match_every_row_of_the_real_eval_file` |
| NITS | per-run temp stderr file (removed on success); cold_start documented | n/a |

`tests/test_bench_api.py`: 5 tests, OK. `uv lock --check`: OK (79 packages). Head SHA: see PR.

## Open issues
The latency figures are one run on a desktop CPU with default ORT threads, so they are not comparable with a Sprite. No dependencies added.
