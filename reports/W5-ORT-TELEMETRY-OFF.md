# W5-ORT-TELEMETRY-OFF

## 1. What was done
onnxruntime 1.31.1, observed Linux wheels ship Microsoft 1DS telemetry, on by default (persistent device ID plus an event DB under `$XDG_CACHE_HOME/Microsoft/DeveloperTools/.onnxruntime/`, uploads to OneCollector). Preached now turns it off:
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
- Full suite on the branch: 1122 tests, OK, 12 skipped, 0 failures.
- DEPLOY cites: no `app/server.py` or other CITED file touched; `CITED` holds only `app/server.py` lines, so nothing to re-pin; `test_every_cited_file_line_holds_its_string` passes.
- Cache safety: all caches were temp dirs. A before/after listing of `/cache` (paths, sizes, mtimes) shows no difference.

## 4. Open issues
- `disable_telemetry_events()` is only a backup and does not stop the device ID or DB write; the environment variable is what works.
- The backup call stays in `OnnxEmbedder.load`, right after its lazy `import onnxruntime`, not at module level: a module-level import would make `onnx_embed` (and the import guard) load onnxruntime eagerly. The unconditional variable in `src/preached/__init__.py` is what covers every import path.
- No upload to Microsoft was observed; the OneCollector endpoint is per ORT's `docs/Privacy.md`.

## 5. Dependencies added
None.

## R2 (fix of CTO r1 CONDITIONAL, reviewed head 420eefb; origin/main merged in, no conflicts)
Key finding (CTO): on ORT 1.31.1 telemetry starts at `import onnxruntime`, so the variable must be set before it.
- MF1: `src/preached/__init__.py:5-11` sets `os.environ["ORT_DISABLE_TELEMETRY"] = "1"` unconditionally, before any submodule import (covers `scripts/export_onnx.py:228` and `tests/test_embed_backend.py:1114`, which import `preached.*` first). `src/preached/onnx_embed.py` lost its `setdefault`; the `hasattr`-guarded `disable_telemetry_events()` stays in `load` (see open issues for why not module level). `docs/DEPLOY.md` and this report dropped `setdefault` and the "`=0` re-enables it" issue.
- MF2: `tests/test_ort_telemetry_off.py`: `test_inherited_zero_is_overridden` (child inherits `=0`, imports `preached.onnx_embed`, makes a session) and `test_other_submodule_then_onnxruntime_writes_nothing` (imports `preached.models`, then onnxruntime, with and without inherited `=0`). On a detached worktree of 420eefb with the new test copied in: both FAIL; on this head: all 4 pass.
- MF3: `docs/DEPLOY.md` Privacy section has the exact sentence "events include device/OS/CPU/memory, the python executable path, and ORT session/EP info; no query text observed"; the "direct start ... covered by the code alone" sentence is gone; OneCollector is attributed to ORT's Privacy.md, with "no upload was observed here".
- S1: "1.31.1, observed" in DEPLOY, this report, the test docstring and the code comment.
- S2: `tests/test_ort_telemetry_off.py` uses `importlib.util.find_spec`; `serve.sh` test moved to its own class so it no longer skips without ORT.
- S3: the dead `PYTHONPATH` line is gone; the child puts the checkout's `src` on `sys.path` itself (the test is `-I`).
- S4: DEPLOY's `serve.sh` allow-list sentence (about line 463) names `ORT_DISABLE_TELEMETRY`. No `app/server.py` or CITED file touched, so no pins moved; `test_every_cited_file_line_holds_its_string` passes.
- S5: full suite on host `preached-sandbox` (24 cores), with the merge of origin/main at the commit that adds this section (parent 420eefb + origin/main 5b85e89): 1140 tests, OK, 12 skipped, 0 failures, `PREACHED_REQUIRE_DENO=1`. All seven cache env vars were temp dirs and `ORT_DISABLE_TELEMETRY=1`. A before/after listing of `/cache` (132725 entries, paths, sizes, mtimes) is identical.
