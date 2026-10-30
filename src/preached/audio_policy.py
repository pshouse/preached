"""What a play link may do for a chunk that holds a redacted or flagged name.

Redaction changes text only. A chunk's ``start_s`` and a YouTube ``t=`` still
point at the recording, where the name is spoken.

**Patrick chose ``none`` for church libraries** (2026-10-30): no play link, no
YouTube link and no exact start/end on a passage that holds a name.
Announcements, prayer requests and testimonies are excluded (see W3-PRIV-SKIP).
``resolve_flagged_audio`` therefore always returns ``none``. The privacy TOML
key ``flagged_audio`` and ``PREACHED_FLAGGED_AUDIO`` are still read so an old
setting is not silently ignored, but anything other than ``none`` is refused.
There is no command-line flag.

The other values stay in the code because they are tested and the functions
take ``policy`` as an argument, but no configuration selects them:

- ``play``: the normal link with the usual pre-roll.
- ``shifted``: start just after the last flagged word of the chunk. If that
  leaves no audio in the chunk, behave as ``none``. Clients get the play
  position as ``start_s`` and no ``end_s`` (``public_times``).
- ``none``: no play link and no times; the page shows text only.

Unflagged chunks are never affected. Patrick also decided against withholding
a whole sermon: an unflagged card keeps its link, and a listener can scrub
from it to a flagged moment elsewhere in the same recording. He accepted that
residual risk; human review and the W3-PRIV-SKIP exclusions are the
mitigation. No heavy imports here.
"""

from __future__ import annotations

import math
import os

FLAGGED_AUDIO = ("play", "shifted", "none")
# Patrick's decision for church libraries; the only value configuration may give.
CHURCH_FLAGGED_AUDIO = "none"
DEFAULT_FLAGGED_AUDIO = CHURCH_FLAGGED_AUDIO
ENV = "PREACHED_FLAGGED_AUDIO"
# ASR word times can be late by up to ~0.76 s (W1-C), so start a little after
# the flagged word's recorded end. 0.5 s is a guess, not measured on real
# church audio. Only reachable by passing policy="shifted" in code (tests).
SHIFT_MARGIN_S = 0.5


def check_flagged_audio(value: object) -> str:
    if value not in FLAGGED_AUDIO:
        raise ValueError(f"flagged_audio must be one of {', '.join(FLAGGED_AUDIO)} (got {value!r})")
    return str(value)


def check_church_policy(value: object, source: str = "flagged_audio") -> str:
    """``value`` when it is ``none``; any other value raises ``ValueError``.

    Patrick chose ``none`` for church libraries, so a stale ``shifted`` or
    ``play`` setting stops the program instead of being silently ignored.
    """
    check_flagged_audio(value)
    if value != CHURCH_FLAGGED_AUDIO:
        raise ValueError(
            f"{source} = {value!r} refused: Patrick chose 'none' for church libraries "
            "(no play link on name passages); play and shifted cannot be selected"
        )
    return CHURCH_FLAGGED_AUDIO


def resolve_flagged_audio(config_value: str | None = None) -> str:
    """The policy for church libraries: always ``none`` (Patrick's decision).

    ``PREACHED_FLAGGED_AUDIO`` and the privacy TOML key may say ``none``;
    anything else raises ``ValueError`` (``check_church_policy``).
    """
    for source, value in ((ENV, os.environ.get(ENV) or None), ("flagged_audio", config_value)):
        if value is not None:
            check_church_policy(value, source)
    return CHURCH_FLAGGED_AUDIO


def flagged_play(
    start_s: float | None,
    end_s: float | None,
    flag_end_s: float | None,
    policy: str,
) -> tuple[bool, float | None]:
    """Return ``(allowed, play_from_s)`` for one chunk.

    ``flag_end_s`` is when the last flagged word in the chunk ends (None: the
    chunk is not flagged). ``play_from_s`` None means "use ``start_s`` with the
    normal pre-roll"; a number is an exact seek with no pre-roll.
    """
    check_flagged_audio(policy)
    if flag_end_s is None or policy == "play":
        return True, None
    if policy == "none":
        return False, None
    if start_s is None or end_s is None or not math.isfinite(flag_end_s):
        return False, None
    seek = max(float(start_s), float(flag_end_s) + SHIFT_MARGIN_S)
    if seek >= float(end_s):
        return False, None
    # Round up, never down: the excluded span [start, seek) may only widen.
    seek = math.ceil(round(seek * 100, 6)) / 100
    if seek >= float(end_s):
        return False, None
    return True, seek


def public_times(
    start_s: float | None,
    end_s: float | None,
    flag_end_s: float | None,
    policy: str,
) -> tuple[float | None, float | None, float | None, bool]:
    """What a client may see for one chunk: ``(start_s, end_s, play_from_s, allowed)``.

    Unflagged chunks and ``play`` keep the exact times. Under ``none`` (or a
    ``shifted`` chunk with no audio left) both times are dropped and audio is
    withheld. Under ``shifted`` the start becomes the play position and the
    end is dropped, so no pair of fields brackets the spoken name.
    """
    allowed, play_from = flagged_play(start_s, end_s, flag_end_s, policy)
    if flag_end_s is None or policy == "play":
        return start_s, end_s, None, allowed
    if not allowed:
        return None, None, None, False
    return play_from, None, play_from, True
