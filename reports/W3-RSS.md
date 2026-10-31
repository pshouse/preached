# W3-RSS: stop keeping a second ONNX graph copy

## What was done
`OnnxEmbedder.load` (src/preached/onnx_embed.py) passed the graph as `bytes` to
`ort.InferenceSession`, so Python held the 565 MiB graph while ORT held its own.
Now:
1. `verify_manifest` still checks the manifest, pooling, and tokenizer. The graph
   bytes it returns are dropped at once.
2. The graph is opened with `O_NOFOLLOW`, must be a regular file, and is hashed
   through that fd. The digest must equal the manifest digest and the code pin.
3. ORT loads `/proc/self/fd/N` (the same open file), then the fd is closed.
4. `malloc_trim(0)` runs via ctypes; any failure (non-glibc, no libc) is skipped.

## Measurements
Harness: a script that calls `OnnxEmbedder.load(variant="fp32", ort_threads=1,
batch_size=1)`, reads VmRSS, then runs 15 single queries and reads it again.
(`scripts/bench_api.py` currently refuses to run: it hard-codes 40 eval queries and
`eval/questions.jsonl` has 93. I did not touch scripts.)

| | after load | after 15 queries |
|---|---|---|
| before (main 5a58b6f) | 1456 MiB | 1459 MiB |
| after | 683 MiB | 685 MiB |

## Tests
Full suite: 567 tests, OK (`uv run python -m unittest discover -s tests`).
New: fd open/hash, symlink refusal, manifest/pin mismatch refusal with no fd leak,
`trim_heap` never raises, loader refuses a symlinked graph. All #10 pin/refusal tests pass.
`test_fp32_directory_without_int8_loads` now hard-links the graph instead of symlinking it
(O_NOFOLLOW refuses symlinks by design).
`uv lock --check`: OK (Resolved 79 packages). No dependencies added.

## Risks / open
- `verify_manifest` (artifacts.py, out of scope) still reads and hashes the graph once, so
  load hashes it twice (~1 s extra, transient peak). A follow-up could skip the graph there.
- The fd hash and ORT's read are the same inode, but an in-place writer to the model file
  between them is not blocked. The model directory should be root/service owned.
- Requires `/proc` (Linux).
