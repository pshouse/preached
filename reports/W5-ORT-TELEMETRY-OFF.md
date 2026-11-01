# W5-ORT-TELEMETRY-OFF

## 1. What was done
onnxruntime 1.31.1, observed Linux wheels ship Microsoft 1DS telemetry, on by default (persistent device ID plus an event DB under `$XDG_CACHE_HOME/Microsoft/DeveloperTools/.onnxruntime/`, uploads to OneCollector per ORT's `docs/Privacy.md`; no upload was observed here). Preached now turns it off:
- `src/preached/onnx_embed.py`: `onnxruntime.disable_telemetry_events()` right after the import in `OnnxEmbedder.load`, guarded with `hasattr`.
- `scripts/serve.sh`: `ORT_DISABLE_TELEMETRY=1`, and added to the `env -i` allow-list (`pass ORT_DISABLE_TELEMETRY`), without which the server would never see it.
- `docs/DEPLOY.md`: new "Privacy: ONNX Runtime telemetry is off" section (what it is, that it is disabled, how to verify).
- `tests/test_ort_telemetry_off.py` (new, imports `cache_guard`).

## 2. How to run it
Full suite: the AGENTS.md section 7 command, with `TORCH_HOME` also a temp dir.
Just this test: same temp-cache env, `uv run python -m unittest tests.test_ort_telemetry_off -v`.

## 3. Results
- Test (r1): a fresh interpreter, `HOME` and `XDG_CACHE_HOME` in a scratch dir, `ORT_DISABLE_TELEMETRY` removed from its env, imports `preached.onnx_embed`, creates an `InferenceSession` on a hand-built Identity model (no model download), asserts no `Microsoft/DeveloperTools`, `deviceid` or `onnxruntime.db` appears. A second test checks `serve.sh`.
- RED on main (onnx_embed.py reverted to origin/main, ORT 1.31.1): FAILED, ORT created `xdg/Microsoft/DeveloperTools/.onnxruntime/deviceid` and `onnxruntime.db`. So this build does emit it in tests.
- GREEN on the branch.
- Full suite on the branch (r1 head, host `preached-sandbox`): 1122 tests, OK, 12 skipped, 0 failures.
- DEPLOY cites: no `app/server.py` or other CITED file touched; `CITED` pins `app/server.py` plus `scripts/build-bundle.sh`, `src/preached/library.py`, `src/preached/youtube/library.py` and `src/preached/youtube/pipeline.py`; none of those was touched, so nothing to re-pin; `test_every_cited_file_line_holds_its_string` passes.
- Cache safety: all caches were temp dirs. A before/after listing of `/cache` (paths, sizes, mtimes) shows no difference.

## 4. Open issues
- `disable_telemetry_events()` is only a backup and does not stop the device ID or DB write; the environment variable is what works.
- The backup call stays in `OnnxEmbedder.load`, right after its lazy `import onnxruntime`, not at module level: a module-level import would make `onnx_embed` (and the import guard) load onnxruntime eagerly. The unconditional variable in `src/preached/__init__.py` is what covers every import path.
- No upload to Microsoft was observed; the OneCollector endpoint is per ORT's `docs/Privacy.md`.
- Limit: a process that imports onnxruntime before any preached module is not covered by `__init__.py`; only the environment (e.g. `serve.sh`) covers it. No product or serve path does this (grep at 7b523c6). (CTO measured `import onnxruntime; import preached` with `=0` inherited writing `deviceid` and `onnxruntime.db`.)
- The `/proc/<pid>/environ` check in DEPLOY only proves the setting for `serve.sh` starts; a direct start gets it from `__init__.py`.

## 5. Dependencies added
None.

## R2 (fix of CTO r1 CONDITIONAL, reviewed head 420eefb; origin/main 83121da merged in as 974f1a9, no conflicts)
Key finding (CTO): on ORT 1.31.1 telemetry starts at `import onnxruntime`, so the variable must be set before it.
- MF1: `src/preached/__init__.py:5-10` sets `os.environ["ORT_DISABLE_TELEMETRY"] = "1"` unconditionally, before any submodule import (covers `scripts/export_onnx.py:228` and `tests/test_embed_backend.py:1114`, which import `preached.*` first). `src/preached/onnx_embed.py` lost its `setdefault`; the `hasattr`-guarded `disable_telemetry_events()` stays in `load` (see open issues for why not module level). `docs/DEPLOY.md` and this report dropped `setdefault` and the "`=0` re-enables it" issue.
- MF2: `tests/test_ort_telemetry_off.py`: `test_inherited_zero_is_overridden` (child inherits `=0`, imports `preached.onnx_embed`, makes a session) and `test_other_submodule_then_onnxruntime_writes_nothing` (imports `preached.models`, then onnxruntime, with and without inherited `=0`). On a detached worktree of 420eefb with the new test copied in: both FAIL; on this head: all 4 pass.
- MF3: `docs/DEPLOY.md` Privacy section has the exact sentence "events include device/OS/CPU/memory, the python executable path, and ORT session/EP info; no query text observed"; the "direct start ... covered by the code alone" sentence is gone; OneCollector is attributed to ORT's Privacy.md, with "no upload was observed here".
- S1: "1.31.1, observed" in DEPLOY, this report, the test docstring and the code comment.
- S2: `tests/test_ort_telemetry_off.py` uses `importlib.util.find_spec`; `serve.sh` test moved to its own class so it no longer skips without ORT.
- S3: the dead `PYTHONPATH` line is gone; the child puts the checkout's `src` on `sys.path` itself (the test is `-I`).
- S4: DEPLOY's `serve.sh` allow-list sentence (about line 463) names `ORT_DISABLE_TELEMETRY`. No `app/server.py` or CITED file touched, so no pins moved; `test_every_cited_file_line_holds_its_string` passes.
- S5: full suite on host `preached-sandbox` (24 cores), with the merge of origin/main at the commit that adds this section (merge commit 974f1a9: parents 420eefb and 83121da, the latter being origin/main's PR #90 merge; 5b85e89 exists only on `docs/w4-report-stat-nit` and was never merged here), run on that merged tree: 1140 tests, OK, 12 skipped, 0 failures, `PREACHED_REQUIRE_DENO=1`. All seven cache env vars were temp dirs and `ORT_DISABLE_TELEMETRY=1`. A before/after listing of `/cache` (132725 entries, paths, sizes, mtimes) is identical.

## R3 (fix of CTO r2 CONDITIONAL, reviewed head 7b523c6; text fixes only, code accepted)
- MF1-r2: the Limit sentence is in `docs/DEPLOY.md` (Privacy section, last paragraph) and in section 4 above, grep sha 7b523c6. No DEPLOY cite moved (no CITED file touched; `onnx_embed.py` is not cited).
- MF2-r2 (1): section 1 now reads "uploads to OneCollector per ORT's `docs/Privacy.md`; no upload was observed here".
- MF2-r2 (2): R2 S5 and the PR BODY below now say merge commit 974f1a9 (parents 420eefb and 83121da), and that the 1140 OK / 12 skipped run used that merged tree. 5b85e89 is gone from the report.
- MF2-r2 (3): section 3 lists all five CITED files; the "1122 tests, 12 skipped" figure is labeled r1 head, host `preached-sandbox`.
- MF2-r2 (4): `__init__.py:5-10` in R2 MF1 above and in DEPLOY.
- Nit E302: two blank lines before `_open_hashed_graph` in `src/preached/onnx_embed.py`.
- Nit DEPLOY wrap: the `env -i` allow-list paragraph (about line 463) is re-wrapped under 80 columns.
- Nit environ: DEPLOY and section 4 say the `/proc/<pid>/environ` check proves the setting only for `serve.sh` starts.
- Checks: `python -m py_compile src/preached/onnx_embed.py` only; no suite rerun, so no cache env was touched.

## PR BODY
Turns off ONNX Runtime 1DS telemetry (1.31.1, observed): `ORT_DISABLE_TELEMETRY=1` set unconditionally in `src/preached/__init__.py:5-10` and in `scripts/serve.sh` (added to the `env -i` allow-list), plus a `hasattr`-guarded `disable_telemetry_events()` backup in `OnnxEmbedder.load`. DEPLOY gets a Privacy section. Uploads to OneCollector are per ORT's `docs/Privacy.md`; no upload was observed here.
- Limit: a process that imports onnxruntime before any preached module is not covered by `__init__.py`; only the environment (e.g. `serve.sh`) covers it. No product or serve path does this (grep at 7b523c6).
- Tests: r1 head 1122 OK / 12 skipped; R2 run on merge commit 974f1a9 (parents 420eefb and 83121da) tree: 1140 OK / 12 skipped. R3 is text-only plus an E302 blank line.
- No dependencies added. No CITED file touched, so no pins moved.
