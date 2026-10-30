"""What a play link may do for a chunk that holds a redacted or flagged name.

Redaction changes text only. A chunk's ``start_s`` and a YouTube ``t=`` still
point at the recording, where the name is spoken. Patrick has not chosen the
policy, so it is configurable (``flagged_audio`` in the privacy TOML, the
``PREACHED_FLAGGED_AUDIO`` variable, or a ``--flagged-audio`` flag):

- ``play``: the normal link with the usual pre-roll.
- ``shifted``: start just after the last flagged word of the chunk. If that
  leaves no audio in the chunk, behave as ``none``.
- ``none``: no play link; the page shows text only.

Default ``none``. Unflagged chunks are never affected. No heavy imports here.
"""

from __future__ import annotations

import math
import os

FLAGGED_AUDIO = ("play", "shifted", "none")
DEFAULT_FLAGGED_AUDIO = "none"
ENV = "PREACHED_FLAGGED_AUDIO"
# ASR word times can be late by up to ~0.76 s (W1-C), so start a little after
# the flagged word's recorded end.
SHIFT_MARGIN_S = 0.5


def check_flagged_audio(value: object) -> str:
    if value not in FLAGGED_AUDIO:
        raise ValueError(f"flagged_audio must be one of {', '.join(FLAGGED_AUDIO)} (got {value!r})")
    return str(value)


def resolve_flagged_audio(explicit: str | None = None, config_value: str | None = None) -> str:
    """Explicit flag, then ``PREACHED_FLAGGED_AUDIO``, then the config key, then ``none``."""
    for value in (explicit, os.environ.get(ENV) or None, config_value):
        if value is not None:
            return check_flagged_audio(value)
    return DEFAULT_FLAGGED_AUDIO


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
    return True, round(seek, 2)
