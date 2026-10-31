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
- (Resolved in the fix-up below: the double hash, and an in-place writer between the hash
  and ORT's read.)
- Requires `/proc` (Linux).

## Fix-up: CTO round 1 (PR #26, head 4df5df6)

Merged `origin/main` (5358c6e) into `feat/w3-rss` with a merge commit (565504b). Nothing was
rebased or force-pushed. Code fix commit: `48058ae`. No new dependencies.

### M1: owner, mode and link checks on the fd ORT loads
On main, the bytes that were hashed were the bytes that were loaded. On this branch, ORT
reopens `/proc/self/fd/N` after the hash, so anyone who could write the file could change it
in between. `_open_hashed_graph` (src/preached/onnx_embed.py) now:
1. Opens the containing directory (`O_DIRECTORY`), `fstat`s it, and refuses it unless it is
   owned by root or the euid with no group or world write bit. Like `classic_index_problem`,
   there is no exception for the sticky bit, so a 1777 folder is refused too.
2. Opens the graph with `openat` from that directory fd, using
   `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`. A directory swap after step 1 cannot redirect it.
3. `fstat`s that same fd and refuses it unless it is a regular file, owned by root or the euid,
   has no group or world write, and has `st_nlink == 1`.
The owner and mode rule calls `libraries._owner_mode_problem`, the same function the index
rules use, so the two rules can't drift apart. Every refusal closes the fd, and every test
checks the `/proc/self/fd` count. The CTO's case (a 0666 graph with two hard links in a 0777
folder) is now refused three ways: directory mode, file mode, and link count.
`test_fp32_directory_without_int8_loads` now copies the graph instead of hard-linking it.

### S1: verify_manifest no longer holds the graph
`verify_manifest` hashes the graph by streaming (`sha256_file`) and never puts its bytes in
`VerifiedArtifacts.files`, which now holds only `tokenizer.json` and `pooling.json`. The new
`hash_graph=False` option skips that hash: the graph must still exist and have a manifest
digest. `OnnxEmbedder.load` passes it, because it hashes the fd that ORT loads. The graph is
now read once per load, not twice, and load time fell from 1.62 s to 1.27 s. Moving the
cleanup line can no longer bring back a 565 MiB copy.

### S2: O_NONBLOCK
The graph open uses `O_NONBLOCK`. A FIFO at the graph path opens at once and is refused as
not a regular file (`test_fifo_at_the_graph_path_is_refused_without_hanging`).

### S3: external data is refused
After the hash, `_uses_external_data` mmaps the same fd and walks the ModelProto with the
stdlib only. It descends into graph -> node -> attribute (`t`, `g`, `tensors`, `graphs`,
`sparse_tensor(s)`), `sparse_initializer`, `functions` and `training_info`. Payloads are
skipped by length, so only field headers are read. It refuses any TensorProto that has
`data_location != DEFAULT` or an `external_data` entry. Malformed protobuf, nesting deeper
than 64 levels, and an empty file are refused too. On the shipped graph the walk takes
0.016 s and finds no external data (`test_real_graph_has_no_external_data`).

### Nits
- `FdLoadTests` now sits above the `__main__` block.
- When `trim_heap()` returns False, the loader writes a `log.debug` line.
- The real-model int8-absent test makes its temp folder in the parent of the ONNX root
  (`/cache/models`). That is outside the model dir and on disk, not on tmpfs `/tmp`.

### New tests (tests/test_embed_backend.py)
Each refusal test also checks that no fd is leaked:
- graph mode 0664, 0646, 0666
- graph owned by another uid (`fstat` mocked)
- graph with two hard links
- FIFO at the graph path
- directory mode 0775, 0757, 0777, 1777
- directory owned by another uid
- missing directory
- external data, via `data_location` and via `external_data`, both top level and in an `If`
  subgraph
- malformed, truncated or empty graph

Two tests check that valid graphs still load: a graph with an inline tensor in a subgraph,
and the real graph. One more covers `verify_manifest(hash_graph=False)`. The fixtures are now
real minimal ModelProtos.

### RSS re-measured
PR #28 (the `scripts/bench_api.py` fix) is not on main, so I used the same harness as before:
`OnnxEmbedder.load(variant="fp32", ort_threads=1, batch_size=1)`, then 15 single queries,
reading VmRSS and VmHWM from `/proc/self/status`. Each figure below is the median of 3 runs on
this machine.

| | load | VmRSS after load | VmRSS after 15 queries | peak (VmHWM) |
|---|---|---|---|---|
| main 5358c6e | 1.35 s | 1469 MiB | 1472 MiB | 1774 MiB |
| PR head 4df5df6 | 1.62 s | 682 MiB | 684 MiB | 908 MiB |
| fix-up 48058ae | 1.27 s | 683 MiB | 685 MiB | 903 MiB |

The first four components of the query vector are identical in all three, and the real-model
tests (Wesley-query parity and unit norm) pass.

### Checks
- Full suite: 581 tests OK (`uv run python -m unittest discover -s tests`), no skips in
  `test_embed_backend`.
- `uv lock --check`: OK (Resolved 79 packages).
- #12 sweep: none of #12's files are touched except `test_embed_backend.py`, and the
  `libraries.py` helper is imported, not changed. `discover -p "test_priv*.py"`: 180 OK.
  `test_libraries.py`: 73 OK. `test_youtube.py`: 40 OK. The diff contains no member
  information and no Gaston material.

### Still open
- Root or the service euid can still rewrite the graph in place between the hash and ORT's
  read. That account is trusted by the same rules as the index.
- Loading still needs Linux `/proc/self/fd`.
- The sticky bit is not exempt, matching the index rules. A model folder must not sit
  directly in `/tmp`, but a private folder under `/tmp` works.

## Merge with main (CTO merged-tree check, 33-W3-RSS-MERGE-FIX)

Merged origin/main `b01c1f0` (which includes #18 W3-DEPLOY-PREP) into `feat/w3-rss` with a merge
commit, `2cc3bf7`. No rebase, no force-push, no new dependencies.

### M1: model_sha256 was null after the obvious resolution
#18 added `VerifiedArtifacts.digests`, and `OnnxEmbedder.load` set `model_sha256` (the value
`/healthz` reports) from `verified.digests.get(filename)`. This branch loads with
`verify_manifest(hash_graph=False)`, so the graph never gets an entry in `digests`. It is hashed
later, in `_open_hashed_graph`, and that digest was thrown away (`fd, _ = ...`).

Resolution:
- `src/preached/artifacts.py` (the only textual conflict): `digests[name] = actual` for every
  file that is hashed, and `verified[name] = data` only when `data is not None` (the graph is
  streamed, so its bytes are never kept). The two `VerifiedArtifacts` docstrings are merged. The
  docstring says the graph has no `digests` entry when `hash_graph=False`.
- `src/preached/onnx_embed.py`: `fd, graph_sha = _open_hashed_graph(...)`. Removed
  `graph_sha = verified.digests.get(filename)`. `model_sha256` is now the digest of the bytes
  read through the fd that ORT loads. The `_open_hashed_graph` docstring says it returns that
  digest.

### Test
`tests/test_embed_backend.py::FdLoadTests::test_load_reports_the_sha256_of_the_graph_it_loaded`
is hermetic, so it runs on a box without `/cache`. It writes a tiny ONNX graph, a tokenizer, and a
manifest, patches the fp32 pin to the graph's digest, and replaces `onnxruntime.InferenceSession`
with a stub. Then it asserts that `OnnxEmbedder.load(...).model_sha256` equals the sha256 of the
graph file.

With the wrong resolution (`fd, _ = ...` plus `graph_sha = verified.digests.get(filename)`), the
test fails: `AssertionError: None != 'c0c67da9…'`. On this machine the model is in `/cache`, so
the existing `RealOnnxTests.test_fp32_directory_without_int8_loads` fails as well
(`None != '3861025a…'`). That test is skipped wherever the model is missing, which is how the
merged tree passed the suite. The new test does not depend on `/cache`.

### Docs (should-fix)
`docs/DEPLOY.md`:
- Hardening section: `model/` and its files must be owned by the service user (or root) and must
  not be group- or world-writable. `check_servable` does not check `model/`. The ONNX loader
  refuses such a graph, and the server logs it and falls back to BM25-only. A tar extracted under
  `umask 002` is enough to cause that.
- Go-live step 3 extracts under `umask 022`. Step 6 now says that `dense: false`, or a
  `model_sha256` that is null or not the pin, is a failed go-live even though `ok` is true.

### Checks on the merged tree
- Full suite: 692 tests OK, 0 skipped (`uv run python -m unittest discover -s tests`).
- `uv lock --check`: OK (Resolved 79 packages).
- Live server: `PREACHED_HOST=127.0.0.1 PREACHED_PORT=8765 PREACHED_HOSTS=127.0.0.1,localhost
  PREACHED_LIBRARY=wesley PREACHED_ORT_THREADS=1 scripts/serve.sh`, then `GET /healthz`:
  `ok: true`, `dense: true`, `backend: onnx`, `fallback: false`,
  `model_sha256: 3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` (the fp32
  pin), and `index_version: 198339132f68…`. A hybrid Wesley search returned results. RSS after
  load was 761212928 bytes (726 MiB).
- Head: merge commit `2cc3bf7`, followed by the commit that adds this report section.
- Not deployed.
