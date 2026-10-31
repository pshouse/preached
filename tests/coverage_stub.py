"""``--audio-dir`` for church-path tests that stub the coverage check.

The church path checks coverage only when ``<sermon id>.<ext>`` is in
``--audio-dir`` (missing audio stores NULL and approval refuses). Tests that
inject a stub ``coverage`` still need that file; the stub never decodes it.
A transcript without ``meta.duration_s`` is unchecked too (CTO round 2 S-d),
so one is written in from the last word when the test left it out.
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
        transcript = json.loads(path.read_text())
        meta = transcript["meta"]
        if "duration_s" not in meta:
            ends = [float(w[1]) for seg in transcript.get("segments", []) for w in seg.get("words", [])]
            meta["duration_s"] = max(ends, default=0.0) + 1.0
            path.write_text(json.dumps(transcript))
        (folder / f"{meta['id']}.wav").touch()
    return ["--audio-dir", str(folder)]
