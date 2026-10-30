"""Turn a yt-dlp JSON dump into the videos an import would consider.

Channel tabs are nested playlists. A flat tab often has ``duration`` and an
approximate ``upload_date`` (pass ``youtubetab:approximate_date``) and omits
the license. The exact upload date and the license are on the full video
metadata, which the import fetches only for videos it is about to keep.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Gaston Community Church is named in BRIEF.md. Permission is still pending.
# Match the channel title and the public @handle before any video download.
BLOCKED_CHANNEL = re.compile(r"gaston\s*community\s*church|gastoncommunitychurch", re.I)


class ChannelRefused(RuntimeError):
    """The URL or the listing names a channel this task must not fetch."""


def assert_allowed(text: str) -> None:
    if text and BLOCKED_CHANNEL.search(text):
        raise ChannelRefused(
            "Refusing Gaston Community Church until the pastor's permission is confirmed."
        )


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    duration_s: float | None
    published: date | None
    url: str

    def watch_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


def watch_url(video_id: str, start_s: float | None = None) -> str:
    """YouTube watch URL. ``t=<seconds>s`` opens the player at that second."""
    base = f"https://www.youtube.com/watch?v={video_id}"
    if start_s is None:
        return base
    seconds = max(0, int(start_s))
    return f"{base}&t={seconds}s"


def parse_date(value) -> date | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value), timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text or text.upper() == "NA":
        return None
    if re.fullmatch(r"\d{8}", text):
        try:
            return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    return None


def _duration(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return float(value)


def _blob(*parts) -> str:
    return " ".join(str(part) for part in parts if part)


def _live(entry: dict) -> bool:
    if entry.get("is_live") is True:
        return True
    return entry.get("live_status") in {"is_live", "is_upcoming"}


def parse_listing(payload: dict) -> list[Video]:
    """Flatten a channel, a playlist, or one video. Skip live and bad ids.

    The first time an id appears wins. YouTube repeats a video across tabs.
    """
    if not isinstance(payload, dict):
        raise RuntimeError("listing is not a JSON object")
    assert_allowed(
        _blob(
            payload.get("title"),
            payload.get("channel"),
            payload.get("uploader"),
            payload.get("channel_id"),
            payload.get("uploader_id"),
            payload.get("webpage_url"),
            payload.get("channel_url"),
            payload.get("uploader_url"),
        )
    )
    videos: list[Video] = []
    seen: set[str] = set()

    def add(entry: dict) -> None:
        if not isinstance(entry, dict):
            return
        if entry.get("entries"):
            for child in entry["entries"]:
                add(child)
            return
        if _live(entry):
            return
        video_id = entry.get("id")
        if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
            return
        assert_allowed(
            _blob(entry.get("channel"), entry.get("uploader"), entry.get("channel_url"), entry.get("title"))
        )
        if video_id in seen:
            return
        seen.add(video_id)
        title = entry.get("title") if isinstance(entry.get("title"), str) else ""
        published = (
            parse_date(entry.get("upload_date"))
            or parse_date(entry.get("timestamp"))
            or parse_date(entry.get("release_timestamp"))
        )
        raw_url = entry.get("url") or entry.get("webpage_url")
        if isinstance(raw_url, str) and raw_url.startswith("http"):
            url = raw_url
        else:
            url = watch_url(video_id)
        videos.append(
            Video(
                id=video_id,
                title=title,
                duration_s=_duration(entry.get("duration")),
                published=published,
                url=url,
            )
        )

    entries = payload.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            add(entry)
    else:
        add(payload)
    return videos


def creative_commons(license_text) -> bool:
    """True only when yt-dlp's ``license`` field names Creative Commons."""
    return isinstance(license_text, str) and "creative commons" in license_text.lower()
