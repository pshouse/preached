# Tests

Run the suite with the rule-5 temp caches in `AGENTS.md` section 7.

## Child processes

An allow-listed child env (a dict that starts from `{"PATH": ...}` plus a few
names) still inherits `HOME` when it copies it from `os.environ`, and a child
that imports onnxruntime writes ORT telemetry under `$XDG_CACHE_HOME`
(default `$HOME/.cache`). That is how a test child once wrote
`~/.cache/Microsoft` in the real home.

Allow-listed children inherit `HOME` only when they copy `os.environ`, so they must use the shared helper:
`tests/subproc_env.py::child_env`. It sets `ORT_DISABLE_TELEMETRY=1` and
scratch `HOME` and `XDG_CACHE_HOME` temp directories.
`tests/test_subproc_env_guard.py` fails any child-starting call with an env
(`subprocess.*`, `os.exec*e`/`os.spawn*e`/`os.posix_spawn*`,
`asyncio.create_subprocess_*`, under any import alias) that does not go through
it: a `child_env` that is not imported from `subproc_env`, a function that can
return a plain dict, an env passed through `**kwargs`, or one whose flag is
popped, deleted or overwritten afterwards is flagged. A test that drops the flag
on purpose is listed by (file, function) in `ALLOW` in that module. In `scripts/`
the call itself must set `ORT_DISABLE_TELEMETRY=1` for its env. `tests/test_child_home_guard.py` runs the hybrid server
and an import-onnxruntime-first child in a fresh `HOME` with a real model; it
needs `PREACHED_GUARD_REAL_SRC` (a read-only copy or bind mount of a cache root, never a writable live cache; the guard refuses a writable source, a non-empty `-wal` or any `-journal`, a dangling symlink counting as present, and checks again after the copy that no `-wal`/`-journal` appeared and no source size or mtime changed; only `PREACHED_GUARD_ALLOW_RW_SRC=1` lifts the writable refusal, no other value does)
and skips with that reason otherwise.

Under root every file is writable, so a `chmod a-w` copy is still refused there; use a read-only bind mount, or set `PREACHED_GUARD_ALLOW_RW_SRC=1` to accept the copy.
