"""ASR coverage gate: did the transcript cover the audio that has sound in it?

On CPU, large-v3-turbo silently dropped 22-75 s of a 240 s file in 15-30 s
holes. A name spoken inside a hole is never transcribed, so it is never
flagged or redacted. This module compares word time against speech time and
lists every stretch of non-silent audio, longer than ``MAX_UNCOVERED_S``, that
no word covers. The library refuses to approve a sermon while any such span is
open (``preached.exclusions.approve``).

Speech time is energy based, on the decoded audio. The stack's Silero VAD is
not used: it is the first suspect for the holes, and a check that shares the
transcriber's VAD cannot see what that VAD threw away. Energy has no model to
share a blind spot. Sound that is not speech (a song, applause) is also
non-silent, so it opens a span too; a reviewer clears it after a listen.

If the audio cannot be decoded the fallback is the audio length: everything
from 0 to the duration counts as speech. With neither, the check raises.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

SR = 16000
# A non-silent stretch with no transcript word in it, longer than this, blocks approval.
MAX_UNCOVERED_S = 5.0

FRAME_S = 0.03
# A frame is sound when it is within this many dB of the loud end (98th percentile)
# of the file and above an absolute floor (dBFS). Speech sits well inside 30 dB.
REL_DB = 30.0
ABS_FLOOR_DB = -58.0
# Sound separated by less than this is one stretch (a breath, a comma).
MERGE_S = 0.6
# Shorter sound is a click, not a word.
MIN_SOUND_S = 0.25
# Words are padded by this much; Whisper word times are loose at the edges.
WORD_PAD_S = 0.3
# A span must hold at least this share of sound; mostly-silent spans are noise.
MIN_SOUND_FRACTION = 0.5


@dataclass(frozen=True)
class Span:
    start_s: float
    end_s: float

    @property
    def length_s(self) -> float:
        return self.end_s - self.start_s


def decode_audio(path: Path) -> np.ndarray:
    """Mono 16 kHz float32 via ffmpeg (already needed by yt-dlp). Raises on failure."""
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"could not decode {path}: {result.stderr.decode(errors='replace')[:200]}")
    return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def sound_spans(audio: np.ndarray) -> list[Span]:
    """Stretches of non-silent audio, in seconds."""
    frame = int(FRAME_S * SR)
    count = len(audio) // frame
    if count == 0:
        return []
    frames = audio[: count * frame].reshape(count, frame)
    db = 20 * np.log10(np.sqrt(np.mean(frames**2, axis=1)) + 1e-10)
    threshold = max(float(np.percentile(db, 98)) - REL_DB, ABS_FLOOR_DB)
    loud = db > threshold
    spans: list[Span] = []
    start = None
    last = None
    for index in np.flatnonzero(loud):
        t = index * FRAME_S
        if start is None:
            start, last = t, t + FRAME_S
        elif t - last <= MERGE_S:
            last = t + FRAME_S
        else:
            spans.append(Span(start, last))
            start, last = t, t + FRAME_S
    if start is not None:
        spans.append(Span(start, last))
    return [s for s in spans if s.length_s >= MIN_SOUND_S]


def _subtract(spans: Iterable[Span], cuts: list[tuple[float, float]]) -> list[Span]:
    out: list[Span] = []
    for span in spans:
        pieces = [(span.start_s, span.end_s)]
        for c0, c1 in cuts:
            if c0 >= span.end_s:
                break
            nxt = []
            for a, b in pieces:
                if c1 <= a or c0 >= b:
                    nxt.append((a, b))
                    continue
                if c0 > a:
                    nxt.append((a, c0))
                if c1 < b:
                    nxt.append((c1, b))
            pieces = nxt
        out.extend(Span(a, b) for a, b in pieces if b > a)
    return out


def uncovered_spans(
    sound: list[Span],
    words: Iterable,
    *,
    max_gap_s: float = MAX_UNCOVERED_S,
) -> list[Span]:
    """Sound no word covers, merged across short silences, longer than ``max_gap_s``.

    ``words`` need ``.start`` and ``.end``. Uncovered pieces closer than
    ``MERGE_S`` merge, so a hole with breaths in it is one span. A merged span
    counts only when at least ``MIN_SOUND_FRACTION`` of it is sound.
    """
    cuts = sorted((w.start - WORD_PAD_S, w.end + WORD_PAD_S) for w in words)
    pieces = _subtract(sound, cuts)
    pieces.sort(key=lambda s: s.start_s)
    merged: list[list[float]] = []
    for piece in pieces:
        if merged and piece.start_s - merged[-1][1] <= MERGE_S * 2 and not _word_between(cuts, merged[-1][1], piece.start_s):
            merged[-1][1] = piece.end_s
            merged[-1][2] += piece.length_s
        else:
            merged.append([piece.start_s, piece.end_s, piece.length_s])
    return [
        Span(round(a, 2), round(b, 2))
        for a, b, sound_s in merged
        if b - a > max_gap_s and sound_s / (b - a) >= MIN_SOUND_FRACTION
    ]


def _word_between(cuts: list[tuple[float, float]], a: float, b: float) -> bool:
    return any(c0 < b and c1 > a for c0, c1 in cuts)


def check_coverage(
    audio_path: Path,
    words: list,
    *,
    duration_s: float | None = None,
    max_gap_s: float = MAX_UNCOVERED_S,
    audio: np.ndarray | None = None,
) -> list[Span]:
    """Uncovered non-silent spans over ``max_gap_s`` for one transcript."""
    if audio is None:
        try:
            audio = decode_audio(audio_path)
        except (OSError, RuntimeError):
            if duration_s is None:
                raise
            return uncovered_spans([Span(0.0, float(duration_s))], words, max_gap_s=max_gap_s)
    return uncovered_spans(sound_spans(audio), words, max_gap_s=max_gap_s)


def clip_to_window(spans: list[Span], window: tuple[float, float] | None, *, max_gap_s: float = MAX_UNCOVERED_S) -> list[Span]:
    """Spans inside a hand-set sermon window, clipped to it; shorter ones drop.

    ``--windows`` is a human's statement of where the sermon is, so music or
    announcements outside it need no clearing.
    """
    if window is None:
        return spans
    clipped = [Span(max(s.start_s, window[0]), min(s.end_s, window[1])) for s in spans]
    return [s for s in clipped if s.length_s > max_gap_s]
