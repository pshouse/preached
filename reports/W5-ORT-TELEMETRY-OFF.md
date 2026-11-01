# W5-ORT-TELEMETRY-OFF

## 1. What was done
onnxruntime 1.29+ Linux wheels ship Microsoft 1DS telemetry, on by default (persistent device ID plus an event DB under `$XDG_CACHE_HOME/Microsoft/DeveloperTools/.onnxruntime/`, uploads to OneCollector). Preached now turns it off:
- `src/preached/onnx_embed.py`: `os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")` at import, before onnxruntime is imported; `onnxruntime.disable_telemetry_events()` right after the import in `OnnxEmbedder.load`, guarded with `hasattr`.
- `scripts/serve.sh`: `ORT_DISABLE_TELEMETRY=1`, and added to the `env -i` allow-list (`pass ORT_DISABLE_TELEMETRY`), without which the server would never see it.
- `docs/DEPLOY.md`: new "Privacy: ONNX Runtime telemetry is off" section (what it is, that it is disabled, how to verify).
- `tests/test_ort_telemetry_off.py` (new, imports `cache_guard`).

## 2. How to run it
Full suite: the AGENTS.md section 7 command, with `TORCH_HOME` also a temp dir.
Just this test: same temp-cache env, `uv run python -m unittest tests.test_ort_telemetry_off -v`.

## 3. Results
- Test: a fresh interpreter, `HOME` and `XDG_CACHE_HOME` in a scratch dir, `ORT_DISABLE_TELEMETRY` removed from its env, imports `preached.onnx_embed`, creates an `InferenceSession` on a hand-built Identity model (no model download), asserts no `Microsoft/DeveloperTools`, `deviceid` or `onnxruntime.db` appears. A second test checks `serve.sh`.
- RED on main (onnx_embed.py reverted to origin/main, ORT 1.31.1): FAILED, ORT created `xdg/Microsoft/DeveloperTools/.onnxruntime/deviceid` and `onnxruntime.db`. So this build does emit it in tests.
- GREEN on the branch.
- Full suite on the branch: 1122 tests, OK, 12 skipped, 0 failures.
- DEPLOY cites: no `app/server.py` or other CITED file touched; `CITED` holds only `app/server.py` lines, so nothing to re-pin; `test_every_cited_file_line_holds_its_string` passes.
- Cache safety: all caches were temp dirs. A before/after listing of `/cache` (paths, sizes, mtimes) shows no difference.

## 4. Open issues
- The `disable_telemetry_events()` call only runs inside `OnnxEmbedder.load`; any other code that imports onnxruntime without importing `onnx_embed` is covered only by the environment variable (set by `serve.sh`).
- `setdefault` means an operator who exports `ORT_DISABLE_TELEMETRY=0` re-enables it.

## 5. Dependencies added
None.
