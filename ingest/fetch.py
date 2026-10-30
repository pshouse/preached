"""Resumable, verified audio download (stdlib only).

Hardened against a bad manifest row or a misbehaving server:
- the destination must resolve directly inside AUDIO_DIR (manifest.safe_child);
- only https URLs on archive.org (or a subdomain) are fetched, before the
  request, on every redirect, and on the final URL; http/ftp/file are refused;
- a download stops (and its .part file is deleted) as soon as it exceeds the
  manifest size, so a server can't fill the disk before the md5 check;
- size + md5 are verified before the atomic rename, and again when an existing
  file is reused.
"""

import hashlib
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest  # noqa: E402
from preached.paths import CACHE_ROOT  # noqa: E402

AUDIO_DIR = CACHE_ROOT / "audio" / "wesley"
USER_AGENT = "preached-ingest/0.1"


class DownloadRefused(IOError):
    """Not worth retrying: unsafe URL/redirect or a body larger than the manifest says."""


def md5sum(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audio_path(row: dict, audio_dir: Path | None = None) -> Path:
    return manifest.safe_child(AUDIO_DIR if audio_dir is None else audio_dir, row["file_name"])


def check_url(url: str) -> str:
    try:
        return manifest.check_audio_url(url)
    except manifest.UnsafeRow as e:
        raise DownloadRefused(str(e)) from None


class HttpsArchiveRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https on archive.org (no downgrade to http)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> urllib.request.OpenerDirector:
    # Only the https handler: no file:, ftp:, data: or plain http: handlers at all.
    opener = urllib.request.OpenerDirector()
    for h in (urllib.request.HTTPSHandler(), HttpsArchiveRedirects(),
              urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        opener.add_handler(h)
    return opener


_OPENER = _build_opener()


def _open(req: urllib.request.Request, timeout: float):
    return _OPENER.open(req, timeout=timeout)


def ensure_audio(row: dict, retries: int = 4, audio_dir: Path | None = None) -> Path:
    """Return the local path, downloading if missing/wrong. Verifies size + md5.

    audio_dir defaults to Wesley's AUDIO_DIR; ingest/run.py --library passes its own.
    """
    dest = audio_path(row, audio_dir)
    url = check_url(row["audio_url"])
    if dest.exists():
        if dest.stat().st_size == row["size"] and md5sum(dest) == row["md5"]:
            return dest
        dest.unlink()  # wrong size or corrupt: fetch again
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, retries + 1):
        try:
            # Resume a partial download with a Range request.
            have = part.stat().st_size if part.exists() else 0
            if have > row["size"]:
                part.unlink()
                have = 0
            headers = {"User-Agent": USER_AGENT}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(url, headers=headers)
            with _open(req, timeout=60) as r:
                check_url(r.geturl())  # final URL after redirects
                mode = "ab" if have and r.status == 206 else "wb"
                total = have if mode == "ab" else 0
                with part.open(mode) as fh:
                    while chunk := r.read(1 << 20):
                        total += len(chunk)
                        if total > row["size"]:
                            fh.close()
                            part.unlink(missing_ok=True)
                            raise DownloadRefused(
                                f"{row['file_name']}: server sent more than {row['size']} bytes")
                        fh.write(chunk)
            if part.stat().st_size != row["size"] or md5sum(part) != row["md5"]:
                part.unlink()
                raise IOError(f"size/md5 mismatch for {row['file_name']}")
            os.replace(part, dest)
            return dest
        except DownloadRefused:
            part.unlink(missing_ok=True)
            raise
        except Exception:
            if attempt == retries:
                raise
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")
