# Response parity hashes

`scripts/parity_hash.py` hashes what the server answers for a fixed list of requests, one hash per set. The gate compares those hashes with the reference values below. A change that is not meant to change any response must leave them equal.

## What is hashed

The script builds two apps the way `app/server.py` builds them (`build_app`, read-only index, `check_servable` first): one with a church side and one without. The church file is the synthetic fixture from the tests (`tests/test_church_wire.build_church`). It is written to a new temp dir and removed afterwards, after a check that the path is under `tempfile.gettempdir()`. No real church file is opened. Its fixture vectors are not the server model's, so the church side runs keyword only and logs one `church vectors do not match` traceback. That traceback is expected.

| Set | Requests |
|---|---|
| `search+sermon` | `/api/search?q=Q&k=10` for each query, then `/api/sermon/ID` for every sermon id in those results (sorted) |
| `side` | `/api/side?q=Q&k=5` for each query |
| `church` | for each church query: `/api/search?q=C&library=sample&k=10` and `/api/side?q=C&k=10` |
| `http` | `/healthz`, the probes, then the `search+sermon`, `side` and `church` requests |
| `no-church` | the `http` list against the app with no church side (sermon ids from its own results) |
| `in-process` | `App.health()`, then `App.search`, `App.sermon` and `App.side` for the `http` requests minus the probes, called directly on the church app |
| `in-process-no-health` | `in-process` without `App.health()` |

All but the two in-process sets go over HTTP to the app served on an ephemeral `127.0.0.1` port. Rate limits are lifted, and `PREACHED_DISABLED`, `PREACHED_KILL_FILE` and `PREACHED_TRUSTED_PROXIES` are unset for the run (and restored after it).

Records:

- **HTTP:** `{"request", "status", "type", "body"}`. `type` is the Content-Type. `body` is the parsed JSON, or `{"sha256": hex}` of the bytes when the body is not JSON (the page and `app.js`). Date and the other headers are not hashed.
- **In-process:** `{"call", "args", "result"}`. A `BadRequest` result is `{"error", "status"}`.

## Canonical serialisation

1. `took_ms`, and every `--strip FIELD` name, is removed as a dict key at any depth.
2. The set's list of records is serialised with `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` and encoded as UTF-8. Floats use Python's shortest round-trip `repr`.
3. The set's hash is the first 16 hex digits of the SHA-256 of those bytes.

The output does not depend on `PYTHONHASHSEED`: sermon ids are sorted and dict keys are sorted. A `--strip` name that is a dict key in no record of any set exits 1 with `--strip NAME: no such key in any response`, so a misspelt strip cannot silently compare unstripped hashes. `--expect` takes exactly 16 hex digits. The request file is refused if `k` or `side_k` is not a positive integer or a query is duplicated.

The script prints `SET HASH` lines in the order of the table above. On stderr it prints `index_version=… model_sha256=… harness=… strip=…`, with the first two read from `App.health()`.

**Harness hash:** the first 16 hex digits of the SHA-256 of `scripts/parity_hash.py`, a NUL byte, then `eval/parity/requests.json`. For the harness in this commit it is `9bbe1a503f36136f`. `tests/test_parity_hash.py` checks that this page names the current value. The church builder is imported from `tests/`, so a change to `build_church` or `QUERIES` can move the hashes without changing the harness hash.

## Inputs

`eval/parity/requests.json` (sources are recorded in the file):

- **Queries:** all 93 `id` and `query` pairs from `eval/questions.jsonl`, in file order (blob `f8d8de3c`, `origin/main` `d4c2e99`). The list is frozen. A later edit to the eval file does not change it.
- **Probes:** the `PATHS` list from `scripts/compare_responses.py` at `d4c2e99`, minus `/healthz`, because every set that includes health asks for it first.
- **Church queries:** `QUERIES` from `tests/test_church_wire.py`, read when the script runs.

**Not a copy of the CTO's list.** The earlier refs (`d3fe8813…` and the rest) were a box example: they came from an HTTP query list and harness that existed only as uncommitted scratch on the CTO's machine, were never committed, and cannot be reproduced. That set is retired and kept only in the gate history. The list above is a new definition, rebuilt from the frozen eval queries and the in-repo probe list. The reference hashes below were generated with this harness, on the machine, index, model and main sha recorded with them; each host takes its own baseline the same way.

## Reference hashes (canonical definition, Wesley + ONNX)

This harness is the canonical parity definition (CTO ruling, #97). The refs computed earlier with the CTO's uncommitted harness (`d3fe8813…` and the rest, and the pre-#88 `why`-stripped set) are retired: they stay in the gate history and are not compared against this harness.

Baseline computed with this harness on the reviewer box (machine `grok-bot-vm`; these are reviewer-box values, not from the machine that edited this page):

| Field | Value |
|---|---|
| main | `3aef7cacf1907fa7ed57a5251b3894dec6618f00` |
| machine | `grok-bot-vm-181711960` (8× Intel Xeon, Python 3.12.16, onnxruntime 1.31.1) |
| index | box-built Wesley classic index (8383 chunks, 141 sermons; placeholder `audio_url`/`reader`), not `/cache` |
| `index_version` | `154875b509d6dc22d326d8386f1751b449be4c97f7aa69149d5aa48cc88f8a93` |
| `model_sha256` | `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` (fp32 ONNX graph, read from the model file and `/healthz`) |
| church side | synthetic `tests/test_church_wire.build_church` fixture, keyword only |
| harness | `9bbe1a503f36136f` |

| Set | With `why` | `--strip why` |
|---|---|---|
| `http` | `29e0c0786acacc68` | `b72c4dec54111ca1` |
| `no-church` | `218d30828042a711` | `f76209cb54d87862` |
| `in-process` | `b2acb9b6b450a470` | `1ea2b8a087d9f371` |
| `in-process-no-health` | `17be2c66569fab1e` | `72d157b749864101` |
| `search+sermon` | `e38ec8cba9ddca3e` | `8f6508ffaf72af35` |
| `side` | `026f0ce37111e4ec` | `e6f28abb5f3866f7` |
| `church` | `43dd3d71a14c50bf` | `94ddac6334e3c2fb` |

These were identical across 3 runs and under `PYTHONHASHSEED=0` and `12345`. With `--strip why`, pre-#88 `e434539` gives the same `in-process`, `in-process-no-health`, `search+sermon`, `side` and `church`. Its `http` (`e691bd2fc5678ce9`) and `no-church` (`3d82fdb5538a768e`) differ only in the `/` and `/static/app.js` byte hashes, which #88 changed (`1da012a`, `e6bec88`).

The `/` and `/static/app.js` byte hashes are in `http` and `no-church`, so any UI-only change moves those two sets.

**History: the `83121da` baseline.** On main `83121da314137c4d611d1725a814374c7d2bb6fb` (Python 3.12.15, same box, index, model and harness) `http` was `27d7cb2bbe8a82d3` / `5aa8821e0ecc7d22` (`--strip why`) and `no-church` was `e1fa9ccca05c5aec` / `b393295f9ae9b309`; the other five rows were the same as above. Main `3aef7ca` moved only these two because #96 (`5244dc9`) added `slots_stuck` to HTTP `/healthz`; `--strip slots_stuck` gives back the `83121da` values exactly.

**omarchy host, main 484e682, index 198339132f68…, model 3861025a…, harness 9bbe1a503f36136f, Python 3.12.16, ORT 1.31.1**

| Field | Value |
|---|---|
| main | `484e68298b514b8489a359602f4340e7662b7615` |
| machine | `omarchy` (12th Gen Intel Core i9-12900K, Python 3.12.16, onnxruntime 1.31.1) |
| index | omarchy `/cache/index/wesley.sqlite` (sha256 `909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b`), hashed from a byte copy, never opened in place |
| `index_version` | `198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2` |
| `model_sha256` | `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` (fp32 ONNX graph) |
| church side | synthetic `tests/test_church_wire.build_church` fixture, keyword only |
| harness | `9bbe1a503f36136f` |

| Set | With `why` | `--strip why` |
|---|---|---|
| `http` | `7d0e6ba49fe8628c` | `2185fbe08c600a0a` |
| `no-church` | `85c8322489268a44` | `514aaa45710f9854` |
| `in-process` | `38348854d2174db3` | `cd1e87e6cf1df21a` |
| `in-process-no-health` | `6b584c8f512f52fc` | `f04c1154aef1c232` |
| `search+sermon` | `706af7bccf0ce3e3` | `e8dc6bf53ca4a967` |
| `side` | `839941f9bb77e43a` | `f9e8df6ddc959fce` |
| `church` | `25872f35ebd97d27` | `b05573c7b06e0198` |

Taken by the host operator on byte copies of the index and model (sha256 of source and copy equal), sandboxed, `PYTHONHASHSEED=12345`; the `/cache` listing was identical before and after.

**Other hosts.** The hashes hold only for the `index_version` and `model_sha256` above. omarchy (`index_version` `198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2`) now has its baseline recorded above (the omarchy host block). A host with a different index (the CTO box `/cache/index/wesley.sqlite`) still needs its own baseline from this harness on its own main, recorded here with the same fields.

## Host gate command

From the checkout under test, against the index the baseline was taken on:

    uv run python scripts/parity_hash.py --index PATH/TO/wesley.sqlite \
      --expect http=29e0c0786acacc68 --expect no-church=218d30828042a711 \
      --expect in-process=b2acb9b6b450a470 --expect in-process-no-health=17be2c66569fab1e \
      --expect search+sermon=e38ec8cba9ddca3e --expect side=026f0ce37111e4ec \
      --expect church=43dd3d71a14c50bf

The script exits 1 and prints a `MISMATCH` line for each set that differs. Check that the stderr `index_version`, `model_sha256` and `harness` equal the table first. If any differs, the refs do not apply. A change meant to alter responses re-baselines here, recording all fields and keeping the old rows for history.

## CI check

`tests/test_parity_hash.py` builds a synthetic index with the side tests' builders and searches it with the fixture encoder (no model, no `/cache`). It checks that two runs print the same hashes and that they equal the pins `PINNED` and `PINNED_NO_WHY`. It also checks the canonical form, `--expect`, the stderr line, and that this page names the current harness hash. A change to any served response moves those pins. Re-pin only when the change is meant, and say so in the PR.
