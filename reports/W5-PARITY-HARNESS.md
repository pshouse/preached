# 99-XE-PARITY-HARNESS: commit the response-parity hash harness

Branch `chore/w5-parity-harness` from `origin/main` `d4c2e99`, which is the merge of #88. **Precondition:** `gh` is not installed on this host, so `gh pr view 88` could not run. #88 is shown MERGED by `d4c2e99 Merge pull request #88 from pshouse/feat/w5-why-this-result`, at the tip of `origin/main` after `git fetch origin`. `git status` was clean before branching and before editing.

## 1. What was done

- **`scripts/parity_hash.py`** builds a church app and a no-church app the way `app/server.py` does (`build_app`, read-only index, `check_servable`). It serves each on an ephemeral `127.0.0.1` port, and it also calls the church app's methods directly. It prints one hash per set: `http`, `no-church`, `in-process`, `in-process-no-health`, `search+sermon`, `side`, `church`. `--strip FIELD` can be repeated and drops that key at any depth (`took_ms` is always dropped). `--expect SET=HASH` exits 1 on a mismatch. stderr gets `index_version`, `model_sha256` and the harness hash. Canonical JSON is sorted keys, compact separators, UTF-8, `allow_nan=False`, and the hash is the first 16 hex digits of SHA-256. The set definitions and the serialisation are in the script's docstring and in `docs/PARITY.md`.
- **Inputs, `eval/parity/requests.json`:** the 93 frozen queries from `eval/questions.jsonl` (blob `f8d8de3c`) and the `scripts/compare_responses.py` `PATHS` probes, minus `/healthz`. The church queries are `tests/test_church_wire.QUERIES`.
- **Church fixture:** `tests/test_church_wire.build_church`, written to a temp dir. The path is resolved and asserted to be under `tempfile.gettempdir()` before the `rmtree`. It is not a hand-copied file.
- **`tests/test_parity_hash.py`** (imports `cache_guard`) builds a synthetic index with `test_side.build_library` plus a `chunks_sha256` meta row and uses a fixture encoder loader. No model and no `/cache` are involved. It checks that two runs print identical output, that the hashes equal the pins `PINNED` (and `PINNED_NO_WHY` with `--strip why`), that every set moves under `--strip why`, the stderr line, `--expect` exit codes, env restore, the canonical form, the inputs, and that `docs/PARITY.md` names the current harness hash.
- **`docs/PARITY.md`** records the CTO's Wesley+ONNX refs, both the current set and the pre-#88 `why`-stripped set, and says they come from the CTO's box index. It gives omarchy's different `index_version` (`198339132f68…`, from `docs/DEMO-SCRIPT.md`; `/cache` was not read), the harness hash `9bbe1a503f36136f`, and the exact host-gate command.

## 2. How to run it

```bash
# CI test (temp caches)
PREACHED_CACHE=$(mktemp -d) HF_HOME=$(mktemp -d) PREACHED_ONNX_DIR=$(mktemp -d) DENO_DIR=$(mktemp -d) XDG_CACHE_HOME=$(mktemp -d) UV_CACHE_DIR=$(mktemp -d) TORCH_HOME=$(mktemp -d) ORT_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 uv run python -m unittest discover -s tests -p test_parity_hash.py
# full suite
PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=$(mktemp -d) HF_HOME=$(mktemp -d) PREACHED_ONNX_DIR=$(mktemp -d) DENO_DIR=$(mktemp -d) XDG_CACHE_HOME=$(mktemp -d) UV_CACHE_DIR=$(mktemp -d) TORCH_HOME=$(mktemp -d) ORT_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 uv run python -m unittest discover -s tests
```

The host-gate command (real `/cache`, host gate only) is in `docs/PARITY.md`. It was not run here.

## 3. Results

- Synthetic pins: with `why`, `http 76a5bfb9d9c51956`, `no-church f8ae652ee227960c`, `in-process 2c4e3d735333a6b2`, `in-process-no-health 126e6bde69f9049a`, `search+sermon 8a7e7554637ecc80`, `side 3a734e17aff1638d`, `church 0783e6ef1d4a916b`. Byte-identical output under `PYTHONHASHSEED=0` and `7`.
- Synthetic run: 1 page, 1 `app.js`, 106 searches, 105 sides, sermons and 404 probes, all served with no 429. Church searches return only the approved fixture passages. On the no-church app, `library=sample` is the 400 `library must be wesley`.
- Full suite: `Ran 1148 tests`, `OK (skipped=12)`, with `PREACHED_REQUIRE_DENO=1`, all seven cache variables on fresh `mktemp -d` dirs, and `ORT_DISABLE_TELEMETRY=1`. No `test_every_cited_file_line_holds_its_string` failure.
- `/cache` listing (paths, sizes, mtimes; `find /cache -printf '%p\t%s\t%T@\n'`, 132,725 entries) before and after all runs: no difference (132,725 entries before and after; `diff` printed nothing).

## 4. Open issues

- **The refs are not verified against this harness.** The CTO's HTTP query list and hashing harness were never committed, so neither can be reproduced exactly. This harness is a documented new definition. Its hashes on the CTO's box may differ from `d3fe8813…` and the other refs with no change in behaviour. The first host-gate run decides, and `docs/PARITY.md` says how to re-baseline.
- The CTO's box `index_version` and `model_sha256`, and the CTO harness sha, were not supplied. The doc marks them as such and expects `model_sha256` to be the fp32 pin `3861025a…`, which is not confirmed. There is no `in-process-no-health` value for the pre-#88 set.
- The church fixture's vectors are not the server model's, so the church side runs keyword only and logs one expected `church vectors do not match` traceback per run.
- Importing the test builders arms `tests/cache_guard` in the script process, which sends tool caches to a temp dir. A change to `build_church` or `QUERIES` moves the hashes without moving the harness hash.
- Rule 4: no file cited in `docs/DEPLOY.md` was edited (only new files were added), so there are no re-pins.

## 5. Dependencies

None.

## R2 (CTO r1 CONDITIONAL on #97, head reviewed `eec05cd`)

| Item | Change | Where |
|---|---|---|
| MF1 | `--strip NAME` exits 1 with `--strip NAME: no such key in any response` when NAME is a dict key in no record of any set (`took_ms` exempt) | `scripts/parity_hash.py` `keys_in`, `check_strip` (called in `compute` before hashing); test `RefusalTests.test_strip_of_a_key_no_response_has_exits_nonzero_naming_it` in `tests/test_parity_hash.py` |
| nit | request loader rejects a string, bool or non-positive `k`/`side_k`, and duplicate queries | `load_inputs` in the script; `test_loader_rejects_string_k_zero_k_and_duplicate_queries` |
| nit | `--expect` needs exactly 16 lowercase hex digits | `parse_args` in the script; `test_expect_wants_exactly_16_hex_digits` |
| nit | `/` and `/static/app.js` hashes mean a UI-only change moves `http` and `no-church` | `docs/PARITY.md`, "Reference hashes", after the pre-#88 paragraph |
| MF2 | "Reference hashes" through "First run" replaced by the CTO's text verbatim (canonical definition, baseline table, host gate command); only the harness hash changed | `docs/PARITY.md` from `## Reference hashes` to the end of `## Host gate command` |
| harness hash | `8af46977119c0dde` -> `9bbe1a503f36136f` (script changed), updated in `docs/PARITY.md` (both places) and above | |

The pinned synthetic hashes (`PINNED`, `PINNED_NO_WHY`) did not move, and none of the reference hashes moved.

Results on `preached-sandbox` (base `eec05cd`): `test_parity_hash.py` 16 tests OK; full suite with `PREACHED_REQUIRE_DENO=1` and seven fresh `mktemp -d` cache dirs plus `ORT_DISABLE_TELEMETRY=1`: `Ran 1152 tests`, `OK (skipped=12)`, zero `test_every_cited_file_line_holds_its_string` failures. Real `/cache` listing (132,823 entries; paths, sizes, mtimes) before and after: no difference. The harness was not run against `/cache` or the live demo. No DEPLOY.md-cited file was edited.

Left as is: `docs/PARITY.md` "Not a copy of the CTO's list" (in "Inputs") still says the reference hashes "below" came from the CTO's list. It is now history-only wording under the CTO ruling; the CTO's replacement text did not cover it.

## PR BODY

Parity harness for the response gate (`scripts/parity_hash.py`, frozen inputs, synthetic pinned test, `docs/PARITY.md`). R2 addresses the r1 review: `--strip` of an unknown key now fails, stricter request and `--expect` validation, and the reference section is the CTO's canonical-definition text (harness `9bbe1a503f36136f`). No dependencies. Full suite 1152 tests OK (12 skipped).

 docs/PARITY.md               |  94 ++++++++++
 eval/parity/requests.json    | 399 ++++++++++++++++++++++++++++++++++++++++++
 reports/W5-PARITY-HARNESS.md |  69 ++++++++
 scripts/parity_hash.py       | 404 +++++++++++++++++++++++++++++++++++++++++++
 tests/test_parity_hash.py    | 199 +++++++++++++++++++++
 5 files changed, 1165 insertions(+)
