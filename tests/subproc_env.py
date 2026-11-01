"""Child-process environments for tests and scripts that spawn Python.

`src/preached/__init__.py` turns ONNX Runtime telemetry off for children that
import preached. A child that imports onnxruntime directly, or that gets a
stripped env, does not go through it, and ORT then writes a device ID and an
event DB under $XDG_CACHE_HOME/Microsoft/DeveloperTools/. ``child_env`` always
sets ORT_DISABLE_TELEMETRY=1 and points HOME and XDG_CACHE_HOME at scratch
temp directories that are removed when the process exits.

``tests/test_subproc_env_guard.py`` fails on any subprocess call with env=
whose value does not come through ``child_env``.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

_scratch: list[Path] = []


def _cleanup() -> None:
    temp = Path(tempfile.gettempdir()).resolve()
    for path in _scratch:
        resolved = path.resolve()
        if temp in resolved.parents:  # never delete outside the temp root
            shutil.rmtree(resolved, ignore_errors=True)
    _scratch.clear()


atexit.register(_cleanup)


def child_env(
    base: Mapping[str, str] | None = None, /, *, keep: Iterable[str] = (), **extra: str
) -> dict[str, str]:
    """A child env: ``base`` (default: only PATH) plus ``extra``.

    ORT_DISABLE_TELEMETRY=1 is always set and cannot be overridden. HOME and
    XDG_CACHE_HOME are fresh scratch directories unless ``extra`` names them or
    ``keep`` lists a name that ``base`` already sets (a test that placed it on purpose).
    """
    env = {"PATH": os.environ.get("PATH", os.defpath)} if base is None else dict(base)
    scratch = Path(tempfile.mkdtemp(prefix="preached-childenv-")).resolve()
    _scratch.append(scratch)
    (scratch / "home").mkdir()
    (scratch / "xdg").mkdir()
    env.update(HOME=str(scratch / "home"), XDG_CACHE_HOME=str(scratch / "xdg"))
    env.update({name: base[name] for name in keep if base is not None and name in base})
    env.update(extra)
    env["ORT_DISABLE_TELEMETRY"] = "1"
    return env
