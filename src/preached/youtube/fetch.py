"""List a channel and download audio with yt-dlp.

yt-dlp is the one new dependency. YouTube's player changes, and the standard
library cannot list a channel or fetch the audio stream. Calls shell out to
``python -m yt_dlp`` in this environment so the pinned package is the one
that runs. Audio is written only under the directory the caller passes,
which the CLI sets to ``/cache/youtube/<slug>/``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from preached.youtube.listing import Video, assert_allowed, assert_youtube_url, parse_listing

# Channel tabs omit upload_date unless this is set. The date is approximate
# until the full video metadata is fetched at import time.
_LIST_ARGS = (
    "--flat-playlist",
    "--dump-single-json",
    "--skip-download",
    "--no-warnings",
    "--no-progress",
    "--extractor-args",
    "youtubetab:approximate_date",
)


def _run(args: list[str], url: str, *, capture: bool) -> subprocess.CompletedProcess:
    """Run yt-dlp. ``--`` keeps a user-supplied URL from being read as an option."""
    assert_youtube_url(url)
    command = [sys.executable, "-m", "yt_dlp", *args, "--", url]
    return subprocess.run(
        command,
        check=False,
        capture_output=capture,
        text=capture,
    )


def _json_from_stdout(stdout: str) -> dict:
    text = stdout.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("yt-dlp did not return JSON")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise RuntimeError("yt-dlp JSON was not an object")
    return payload


def list_channel(url: str) -> list[Video]:
    """Metadata only. No media. Refuses a blocked channel before the call."""
    assert_youtube_url(url)
    assert_allowed(url)
    result = _run(list(_LIST_ARGS), url, capture=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"yt-dlp exited {result.returncode}")
    return parse_listing(_json_from_stdout(result.stdout))


def fetch_metadata(video: Video) -> dict:
    """Full video JSON without downloading media. Includes ``license``."""
    url = video.watch_url()
    assert_youtube_url(url)
    assert_allowed(url)
    result = _run(
        ["--skip-download", "--dump-single-json", "--no-warnings", "--no-playlist", "--no-progress"],
        url,
        capture=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"yt-dlp exited {result.returncode}")
    payload = _json_from_stdout(result.stdout)
    assert_allowed(
        " ".join(
            str(payload.get(key) or "")
            for key in ("title", "channel", "uploader", "channel_id", "webpage_url", "channel_url")
        )
    )
    return payload


def download_audio(video: Video, dest: Path) -> Path:
    """Audio stream only, resumed if a file for this id is already there."""
    url = video.watch_url()
    assert_youtube_url(url)
    assert_allowed(url)
    dest.mkdir(parents=True, exist_ok=True)
    existing = _audio_file(dest, video.id)
    if existing is not None:
        return existing
    template = str(dest / f"{video.id}.%(ext)s")
    result = _run(
        [
            "-f",
            "bestaudio/best",
            "--no-playlist",
            "--no-progress",
            "--continue",
            "--no-overwrites",
            "-o",
            template,
        ],
        url,
        capture=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp audio download failed for {video.id} (exit {result.returncode})")
    saved = _audio_file(dest, video.id)
    if saved is None:
        raise RuntimeError(f"yt-dlp wrote no audio file for {video.id}")
    return saved


def _audio_file(dest: Path, video_id: str) -> Path | None:
    skip = {".part", ".ytdl", ".json"}
    found = [
        path
        for path in dest.glob(f"{video_id}.*")
        if path.is_file() and path.suffix not in skip and path.stat().st_size > 0
    ]
    if not found:
        return None
    return sorted(found)[0]
