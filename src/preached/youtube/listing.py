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
from urllib.parse import parse_qs, urlsplit

from preached.search import PREROLL_S

# A YouTube video id is 11 characters. That is also the form /api/sermon/<id> accepts.
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Gaston Community Church is named in BRIEF.md. Permission is still pending.
# Match the channel title and the public @handle before any video download.
BLOCKED_CHANNEL = re.compile(r"gaston\s*community\s*church|gastoncommunitychurch", re.I)


class ChannelRefused(RuntimeError):
    """The URL or the listing names a channel this task must not fetch."""


class BadChannelUrl(ValueError):
    """The channel URL is not https on a YouTube host."""


# yt-dlp will treat a leading dash as an option. Only these hosts, over https.
YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
# Watch links use the importer's hosts except youtu.be, which is not /watch?v=.
WATCH_HOSTS = YOUTUBE_HOSTS - {"youtu.be"}
# A seek longer than a day is not a t= we will emit. 86400 is 24 h.
MAX_T_S = 24 * 60 * 60
_T_RE = re.compile(r"^([0-9]+)s?$")
_URL_MESSAGE = (
    "channel URL must be https on youtube.com, www.youtube.com, m.youtube.com, or youtu.be"
)


def assert_youtube_url(url: str) -> None:
    """Reject a URL before it is passed to yt-dlp.

    Anything that is not ``https`` on an allowed host is refused, including a
    value that starts with ``-``. Userinfo and a non-443 port are refused too,
    so the host the checker saw is the host yt-dlp will open.
    """
    if (
        not isinstance(url, str)
        or not url
        or url.startswith("-")
        or "\\" in url
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url)
    ):
        raise BadChannelUrl(_URL_MESSAGE)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in YOUTUBE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise BadChannelUrl(_URL_MESSAGE)


def _watch_link(video_id: str, seconds: int | None) -> str:
    """The only place a watch link's string is built.

    ``https://www.youtube.com/watch?v=<11-char id>`` and, when ``seconds`` is
    not None, ``&t=<int>s``. No other parameter, port, or fragment.
    """
    base = f"https://www.youtube.com/watch?v={video_id}"
    if seconds is None:
        return base
    return f"{base}&t={seconds}s"


def _t_seconds(values: list[str]) -> int | None:
    """One whole-second ``t`` in ``0..MAX_T_S``, or None.

    A second ``t`` (blank or not), a sign, a fraction, or a non-numeric value
    is not a seek. The caller then omits ``t=`` rather than copying it.
    """
    if len(values) != 1:
        return None
    match = _T_RE.fullmatch(values[0])
    if not match:
        return None
    digits = match.group(1).lstrip("0") or "0"
    if len(digits) > len(str(MAX_T_S)):
        return None
    seconds = int(digits)
    if seconds > MAX_T_S:
        return None
    return seconds


def youtube_watch_url(url: object) -> str | None:
    """A canonical YouTube watch URL, or None when ``url`` is not one.

    Same host rule as the importer (https, no credentials, port 443 or the
    default) limited to ``WATCH_HOSTS``, path ``/watch``, and one ``v`` of
    11 characters. A blank ``v`` counts, so ``v=<id>&v=`` is rejected. The
    result is rebuilt: ``https://www.youtube.com/watch?v=<id>`` plus
    ``&t=<int>s`` when ``t`` is one non-negative whole number of seconds up
    to 24 h (a trailing ``s`` is accepted). Every other query parameter and
    any fragment is dropped. Nothing here adds ``#t=``.

    Never raises. ``urlsplit`` raises ``ValueError`` for an invalid IPv6
    netloc, and ``.port`` raises ``ValueError`` for a non-numeric or
    out-of-range port. Those, and anything else the parser rejects, are None.
    """
    if (
        not isinstance(url, str)
        or not url
        or url.startswith("-")
        or "\\" in url
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url)
    ):
        return None
    try:
        parsed = urlsplit(url)
        # Read these inside the try. A matching host with a bad port used to
        # raise from ``.port`` before the function could return None.
        hostname = parsed.hostname
        port = parsed.port
        username = parsed.username
        password = parsed.password
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or hostname not in WATCH_HOSTS
        or username is not None
        or password is not None
        or port not in (None, 443)
    ):
        return None
    if parsed.path != "/watch":
        return None
    # keep_blank_values so a second empty v= is counted. parse_qs drops it
    # otherwise, and the page's URLSearchParams.getAll("v") does not.
    params = parse_qs(parsed.query, keep_blank_values=True)
    ids = params.get("v", [])
    if len(ids) != 1 or not VIDEO_ID.fullmatch(ids[0]):
        return None
    return _watch_link(ids[0], _t_seconds(params.get("t", [])))


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
    """YouTube watch URL. ``t=`` is the play position, not the stored onset.

    ``start_s`` is the first word. The player starts ``PREROLL_S`` earlier.
    YouTube's ``t=`` parameter is a whole number of seconds.
    """
    base = f"https://www.youtube.com/watch?v={video_id}"
    if start_s is None:
        return base
    seconds = int(max(0, start_s - PREROLL_S))
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
