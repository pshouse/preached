# Tests

Run the suite with the rule-5 temp caches in `AGENTS.md` section 7.

## Child processes

An allow-listed child env (a dict that starts from `{"PATH": ...}` plus a few
names) still inherits `HOME` when it copies it from `os.environ`, and a child
that imports onnxruntime writes ORT telemetry under `$XDG_CACHE_HOME`
(default `$HOME/.cache`). That is how a test child once wrote
`~/.cache/Microsoft` in the real home.

Allow-listed children inherit `HOME`, so they must use the shared helper:
`tests/subproc_env.py::child_env`. It sets `ORT_DISABLE_TELEMETRY=1` and
scratch `HOME` and `XDG_CACHE_HOME` temp directories.
`tests/test_subproc_env_guard.py` fails any `subprocess` call with `env=` that
does not go through it. `tests/test_child_home_guard.py` runs the hybrid server
and an import-onnxruntime-first child in a fresh `HOME` with a real model; it
needs `PREACHED_GUARD_REAL_SRC` (a read-only copy or bind mount of a cache root)
and skips with that reason otherwise.
