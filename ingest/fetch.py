"""Resumable, verified audio download (stdlib only)."""

import hashlib
import os
import time
import urllib.request
from pathlib import Path

AUDIO_DIR = Path("/cache/audio/wesley")


def md5sum(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audio_path(row: dict) -> Path:
    return AUDIO_DIR / row["file_name"]


def ensure_audio(row: dict, retries: int = 4) -> Path:
    """Return the local path, downloading if missing/wrong. Verifies size + md5."""
    dest = audio_path(row)
    if dest.exists() and dest.stat().st_size == row["size"]:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            # Resume a partial download with a Range request.
            have = part.stat().st_size if part.exists() else 0
            if have > row["size"]:
                part.unlink()
                have = 0
            headers = {"User-Agent": "preached-ingest/0.1"}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(row["audio_url"], headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                mode = "ab" if have and r.status == 206 else "wb"
                with part.open(mode) as fh:
                    while chunk := r.read(1 << 20):
                        fh.write(chunk)
            if part.stat().st_size != row["size"] or md5sum(part) != row["md5"]:
                part.unlink()
                raise IOError(f"size/md5 mismatch for {row['file_name']}")
            os.replace(part, dest)
            return dest
        except Exception:
            if attempt == retries:
                raise
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")
