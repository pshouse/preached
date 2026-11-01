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

The output does not depend on `PYTHONHASHSEED`: sermon ids are sorted and dict keys are sorted. The script prints `SET HASH` lines in the order of the table above. On stderr it prints `index_version=… model_sha256=… harness=… strip=…`, with the first two read from `App.health()`.

**Harness hash:** the first 16 hex digits of the SHA-256 of `scripts/parity_hash.py`, a NUL byte, then `eval/parity/requests.json`. For the harness in this commit it is `8af46977119c0dde`. `tests/test_parity_hash.py` checks that this page names the current value. The church builder is imported from `tests/`, so a change to `build_church` or `QUERIES` can move the hashes without changing the harness hash.

## Inputs

`eval/parity/requests.json` (sources are recorded in the file):

- **Queries:** all 93 `id` and `query` pairs from `eval/questions.jsonl`, in file order (blob `f8d8de3c`, `origin/main` `d4c2e99`). The list is frozen. A later edit to the eval file does not change it.
- **Probes:** the `PATHS` list from `scripts/compare_responses.py` at `d4c2e99`, minus `/healthz`, because every set that includes health asks for it first.
- **Church queries:** `QUERIES` from `tests/test_church_wire.py`, read when the script runs.

**Not a copy of the CTO's list.** The reference hashes below came from an HTTP query list that existed only as uncommitted scratch on the CTO's machine. That list, and the harness that hashed it, were never committed, and earlier reports describe only uncommitted `/tmp` parity scripts. So the exact list cannot be reproduced. The list above is a new definition, rebuilt from the frozen eval queries and the in-repo probe list. Nothing in this repo shows that this harness reproduces the reference hashes.

## Reference hashes (Wesley + ONNX)

These were computed by the CTO with the CTO's uncommitted harness on the **CTO's box index**. They were not computed with this harness. The CTO's harness hash is not known.

| Field | Value |
|---|---|
| index | the CTO's box `wesley.sqlite` |
| `index_version` | the CTO's box value, not supplied with the refs (to be recorded on the first host-gate run) |
| `model_sha256` | not supplied with the refs; expected to be the fp32 graph pin `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` (`src/preached/artifacts.py`), not confirmed |
| harness | the CTO's uncommitted harness (sha unknown) |

**Current** (in effect since #88 merged; responses include `why`):

| Set | Hash |
|---|---|
| `http` | `d3fe8813830860a1` |
| `no-church` | `313ac936f1811fbf` |
| `in-process` | `b3e434a21913b4cd` |
| `in-process-no-health` | `fe4fdf509d56a137` |
| `search+sermon` | `dc560eb5a85dd9e6` |
| `side` | `62cd3faaa859af26` |
| `church` | `2b50990e34509d44` |

**Pre-#88, `why` stripped:**

| Set | Hash |
|---|---|
| `http` | `61da36467ca1042b` |
| `no-church` | `1d128a7f66432c67` |
| `in-process` | `cb0fb974bcf7cc81` |
| `in-process-no-health` | not given |
| `search+sermon` | `c67732e881e24dca` |
| `side` | `51fd70ee78f12981` |
| `church` | `faea2e776c6112de` |

**Other hosts.** omarchy's index differs: its `index_version` is `198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2` (`docs/DEMO-SCRIPT.md`). These refs do not apply there. A gate on omarchy needs its own baseline.

## Host gate command

Only the host gate runs this against the real `/cache`. Agents and CI must not. On the CTO's box, from the checkout under test:

```
uv run python scripts/parity_hash.py --index /cache/index/wesley.sqlite \
  --expect http=d3fe8813830860a1 --expect no-church=313ac936f1811fbf \
  --expect in-process=b3e434a21913b4cd --expect in-process-no-health=fe4fdf509d56a137 \
  --expect search+sermon=dc560eb5a85dd9e6 --expect side=62cd3faaa859af26 \
  --expect church=2b50990e34509d44
```

To check that #88 changed only `why`, use the same command with `--strip why` and the pre-#88 values (with no `in-process-no-health` expectation). The script exits 1 and prints a `MISMATCH` line for each set that differs. Record the stderr `index_version`, `model_sha256` and `harness` values next to any new baseline.

**First run.** The refs came from a different harness, so the first host-gate run of this script may differ on every set without any change in behaviour. If it does, the CTO decides whether to re-baseline to this harness's values on the same index and code. Record the new values here with their `index_version`, `model_sha256` and harness hash. Keep the old refs for history.

## CI check

`tests/test_parity_hash.py` builds a synthetic index with the side tests' builders and searches it with the fixture encoder (no model, no `/cache`). It checks that two runs print the same hashes and that they equal the pins `PINNED` and `PINNED_NO_WHY`. It also checks the canonical form, `--expect`, the stderr line, and that this page names the current harness hash. A change to any served response moves those pins. Re-pin only when the change is meant, and say so in the PR.
