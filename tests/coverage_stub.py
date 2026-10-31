"""``--audio-dir`` for church-path tests that stub the coverage check.

The church path checks coverage only when ``<sermon id>.<ext>`` is in
``--audio-dir`` (missing audio stores NULL and approval refuses). Tests that
inject a stub ``coverage`` still need that file; the stub never decodes it.
"""

from __future__ import annotations

import json
from pathlib import Path


def stub_audio(*transcripts) -> list[str]:
    """``["--audio-dir", DIR]`` with an empty ``<id>.wav`` for each transcript file."""
    paths = [Path(p) for p in transcripts]
    folder = paths[0].parent / "stub-audio"
    folder.mkdir(exist_ok=True)
    for path in paths:
        (folder / f"{json.loads(path.read_text())['meta']['id']}.wav").touch()
    return ["--audio-dir", str(folder)]
