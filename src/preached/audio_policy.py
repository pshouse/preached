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

A ``shifted`` policy (start just after the flagged word) was deleted in
W3-PRIV-WIRE round 6: it could seek into the next chunk's name. A config that
names it is refused like any other unknown value.

The other value stays in the code because it is tested and the functions
take ``policy`` as an argument, but no configuration selects it:

- ``play``: the normal link with the usual pre-roll.
- ``none``: no play link and no times; the page shows text only.

Unflagged chunks are never affected. Patrick also decided against withholding
a whole sermon: an unflagged card keeps its link, and a listener can scrub
from it to a flagged moment elsewhere in the same recording. He accepted that
residual risk; human review and the W3-PRIV-SKIP exclusions are the
mitigation. No heavy imports here.
"""

from __future__ import annotations

import os

FLAGGED_AUDIO = ("play", "none")
# Patrick's decision for church libraries; the only value configuration may give.
CHURCH_FLAGGED_AUDIO = "none"
DEFAULT_FLAGGED_AUDIO = CHURCH_FLAGGED_AUDIO
ENV = "PREACHED_FLAGGED_AUDIO"


def check_flagged_audio(value: object) -> str:
    if value not in FLAGGED_AUDIO:
        raise ValueError(f"flagged_audio must be one of {', '.join(FLAGGED_AUDIO)} (got {value!r})")
    return str(value)


def check_church_policy(value: object, source: str = "flagged_audio") -> str:
    """``value`` when it is ``none``; any other value raises ``ValueError``.

    Patrick chose ``none`` for church libraries, so a stale ``play`` (or unknown,
    e.g. ``shifted``) setting stops the program instead of being silently ignored.
    """
    check_flagged_audio(value)
    if value != CHURCH_FLAGGED_AUDIO:
        raise ValueError(
            f"{source} = {value!r} refused: Patrick chose 'none' for church libraries "
            "(no play link on name passages); no other value can be selected"
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
) -> bool:
    """Whether a play link is allowed for one chunk.

    ``flag_end_s`` is when the last flagged word in the chunk ends (None: the
    chunk is not flagged). Only unflagged chunks and ``play`` are allowed.
    """
    check_flagged_audio(policy)
    return flag_end_s is None or policy == "play"


def public_times(
    start_s: float | None,
    end_s: float | None,
    flag_end_s: float | None,
    policy: str,
) -> tuple[float | None, float | None, bool]:
    """What a client may see for one chunk: ``(start_s, end_s, allowed)``.

    Unflagged chunks and ``play`` keep the exact times. Under ``none`` both
    times are dropped and audio is withheld.
    """
    if flagged_play(start_s, end_s, flag_end_s, policy):
        return start_s, end_s, True
    return None, None, False
