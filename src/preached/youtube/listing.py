"""Turn a yt-dlp JSON dump into the videos an import would consider.

Channel tabs are nested playlists. A flat tab often has ``duration`` and an
approximate ``upload_date`` (pass ``youtubetab:approximate_date``) and omits
the license. The exact upload date and the license are on the full video
metadata, which the import fetches only for videos it is about to keep.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

from preached.search import PREROLL_S

from preached.audio_policy import flagged_play

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


def _same_origin_path(url: str) -> bool:
    """A path the page's safeUrl treats as this origin. Not protocol-relative."""
    if not url.startswith("/") or url.startswith("//") or "\\" in url:
        return False
    path = url.split("?", 1)[0].split("#", 1)[0]
    return ".." not in path.split("/")


def public_audio_url(url: object) -> str | None:
    """The ``audio_url`` the page may receive. Same allow-list as the client.

    A YouTube watch URL is rebuilt from the video id and an integer ``t=``.
    A watch host that fails those rules is dropped, so ``t=javascript:`` and
    extra parameters are not forwarded raw. Any other ``https`` URL is kept,
    matching ``safeUrl``, as is a same-origin path. Userinfo (``user@host``
    or ``user:pass@host``) is dropped, so ``evil.com@ccel.org`` is not a
    CCEL URL. ``javascript:``, ``data:``, and ``http:`` are dropped. Never
    raises.
    """
    rebuilt = youtube_watch_url(url)
    if rebuilt is not None:
        return rebuilt
    if (
        not isinstance(url, str)
        or not url
        or url.startswith("-")
        or "\\" in url
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url)
    ):
        return None
    if _same_origin_path(url):
        return url
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
        # .port raises ValueError for a non-numeric or out-of-range port.
        parsed.port
    except ValueError:
        return None
    if username is not None or password is not None:
        return None
    if parsed.scheme != "https" or not hostname:
        return None
    if hostname in WATCH_HOSTS and parsed.path == "/watch":
        return None
    return url


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
        return _watch_link(self.id, None)


def _seek_cap(duration_s: float | None) -> int:
    """Whole seconds the seek may reach: the sermon length, and never past 24 h.

    A missing, non-positive, or non-finite duration leaves the 24 h ceiling.
    """
    if (
        duration_s is None
        or isinstance(duration_s, bool)
        or not isinstance(duration_s, (int, float))
        or not math.isfinite(duration_s)
        or duration_s <= 0
    ):
        return MAX_T_S
    if duration_s >= MAX_T_S:
        return MAX_T_S
    return int(duration_s)


def watch_url(
    video_id: str,
    start_s: float | None = None,
    *,
    duration_s: float | None = None,
    end_s: float | None = None,
    flag_end_s: float | None = None,
    policy: str = "none",
) -> str | None:
    """YouTube watch URL. ``t=`` is the play position, not the stored onset.

    ``start_s`` is the first word. The player starts ``PREROLL_S`` earlier.
    YouTube's ``t=`` parameter is a whole number of seconds. A non-finite or
    negative ``start_s`` is omitted (no ``t=``), which is also what ``inf``
    and ``1e300`` used to do badly: ``int(inf)`` raises ``OverflowError`` and
    ``int(1e300)`` is a huge ``t=``. The seek is capped at ``duration_s`` when
    that is a positive finite sermon length, and always at 24 h.

    ``flag_end_s`` (end of the last redacted or review-flagged word in the
    chunk) applies the flagged-audio policy: ``none`` returns None, ``shifted``
    seeks just after that word (rounded up), ``play`` is the normal link.
    Without ``flag_end_s`` nothing changes. A shifted seek that is not finite
    or that the cap would pull back onto the name returns None (no link).

    This is the only function that turns a start time into a watch link, and
    the string itself comes from ``_watch_link``: an 11-character
    ``video_id`` and an integer ``t``. Any other id returns None.
    """
    if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
        return None
    allowed, play_from = flagged_play(start_s, end_s, flag_end_s, policy)
    if not allowed:
        return None
    cap = _seek_cap(duration_s)
    if play_from is not None:
        if not math.isfinite(play_from) or play_from < 0:
            return None
        seconds = math.ceil(play_from)
        if seconds > cap:
            return None
        return _watch_link(video_id, int(seconds))
    if start_s is None:
        return _watch_link(video_id, None)
    if isinstance(start_s, bool) or not isinstance(start_s, (int, float)):
        return _watch_link(video_id, None)
    if not math.isfinite(start_s) or start_s < 0:
        return _watch_link(video_id, None)
    # Cap in float before int(). int(1e300) succeeds and is enormous;
    # int(inf) raises OverflowError.
    seconds = start_s - PREROLL_S
    if seconds < 0:
        seconds = 0.0
    if seconds > cap:
        seconds = float(cap)
    return _watch_link(video_id, int(seconds))


def watch_video_id(url: object) -> str | None:
    """The ``v`` of a validated YouTube watch URL (``youtube_watch_url``), else None."""
    rebuilt = youtube_watch_url(url)
    if rebuilt is None:
        return None
    return parse_qs(urlsplit(rebuilt).query)["v"][0]


def chunk_video_id(video_id: object, audio_url: object, source_url: object) -> str | None:
    """The YouTube id of a chunk, from validated parts only, or None.

    Taken from the ``v`` of the stored ``audio_url`` or, when that is empty
    (an import under ``none`` stores no link), of ``source_url``; both must
    be valid watch URLs. If the chunk's ``video_id`` is a YouTube id it must
    agree, and when the URLs disagree with each other the answer is None.
    """
    ids = {vid for vid in (watch_video_id(audio_url), watch_video_id(source_url)) if vid is not None}
    if len(ids) != 1:
        return None
    vid = ids.pop()
    if isinstance(video_id, str) and VIDEO_ID.fullmatch(video_id) and video_id != vid:
        return None
    return vid


def policy_watch_url(
    vid: str | None,
    start_s: float | None,
    end_s: float | None,
    flag_end_s: float | None,
    policy: str,
) -> str | None:
    """Rebuild a chunk's YouTube link under ``policy`` (``vid`` from ``chunk_video_id``).

    The stored ``audio_url`` was built at import time, possibly under another
    policy, so its ``t=`` may sit on the name; callers must use this instead.
    It goes through ``watch_url``, so the id and ``t`` are validated the same
    way. None when there is no id or the policy withholds audio.
    """
    if vid is None:
        return None
    return watch_url(vid, start_s, end_s=end_s, flag_end_s=flag_end_s, policy=policy)


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
