"""One ASR word on the original video timeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str
