"""Privacy hook for transcript words.

W3-PRIV replaces ``redact``. This module stays an identity function so the
import path always calls it and a later change cannot be skipped by accident.
Do not add a name list or a redaction rule here.
"""

from __future__ import annotations

from preached.youtube.words import Word


def redact(words: list[Word]) -> list[Word]:
    """privacy.redact(words) -> words. Identity until W3-PRIV."""
    return words
