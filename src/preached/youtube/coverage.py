"""ASR coverage gate: did the transcript cover the audio that has sound in it?

An ASR run can silently drop stretches of speech: on one CPU the int8 path
returned corrupted encoder output (MKL's AMX kernels; see
``preached.cpu_guard``) and turbo left 15-30 s holes, sometimes with one junk
word stretched across the hole. A name spoken inside a hole is never
transcribed, so it is never flagged or redacted. This module compares word
time against sound time and lists every stretch longer than
``MAX_UNCOVERED_S`` that the transcript does not really cover:

- **gaps**: non-silent audio no word covers. A word covers at most
  ``WORD_MAX_COVER_S`` (half at each end), so one junk word stretched over
  28 s does not hide a hole;
- **sparse stretches**: windows of ``DENSITY_WINDOW_S`` where the words per
  second of sound fall under ``MIN_WORDS_PER_S`` (stray words every few
  seconds over continuous speech). Words that share one start time count
  once: corrupted runs emit several words on the same timestamp;
- **stretched words**: any word longer than ``LONG_WORD_S`` with sound in
  the part its capped cover leaves open. Clean Whisper words never ran past
  2.12 s; a 7 s word over speech hides about 5 s, which is under
  ``MAX_UNCOVERED_S`` and could not open a gap on its own (CTO round 2:
  the corrupted run c01.tiny.1t-b passed whole).

The library refuses to approve a sermon while any span is open
(``preached.exclusions.approve``) and never serves one whose stored spans are
not ``[]`` (``preached.store.visible_sql``).

Sound is energy based, on the decoded audio. The stack's Silero VAD is not
used: a check that shares the transcriber's VAD cannot see what that VAD
threw away. Sound that is not speech (a song, applause, intro music) is also
non-silent, so it opens a span too. The reverse is a known blind spot:
speech within about ``NOISE_MARGIN_DB`` (6 dB) of a steady hum or a music
bed under it cannot be told from that bed by level, so a hole there is not
found. Such a recording needs a human listen before approval.

The check fails closed (``Unchecked``, stored as NULL, so approval is
refused) when the audio cannot be decoded, or when the decoded audio is
shorter than the last word or the stated duration by more than
``LENGTH_TOLERANCE_S``: a truncated file has no sound to compare against
the part that is missing.

**Clearing a span** (CTO ruling: re-import for now). Listen to it first.
YouTube path: re-import with ``--redo`` and a ``--windows`` entry for the
video that starts or ends outside the span (music before or after the
sermon), or after re-transcribing. Church path (``align/asr_chunks.py``):
fix the transcript, or set its ``searchable_start``/``searchable_end``
around the sermon, then re-run it with ``--audio-dir``. There is no
per-span "acknowledged" flag. **Never add placeholder words** (``...``,
``[music]``, made-up text) to a transcript to clear a span: that hides the
very speech the check exists to find, and a name in it is never flagged.
"""

from __future__ import annotations

import bisect
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

SR = 16000
# A stretch the transcript does not cover, longer than this, blocks approval.
MAX_UNCOVERED_S = 5.0

FRAME_S = 0.03
# A frame is sound when it is within this many dB of the loud end (98th
# percentile) of the file, above an absolute floor (dBFS), and at least
# NOISE_MARGIN_DB above the noise floor (the NOISE_PERCENTILE level), so a
# steady hiss within REL_DB of the speech is not sound.
REL_DB = 40.0
ABS_FLOOR_DB = -58.0
NOISE_PERCENTILE = 5
NOISE_MARGIN_DB = 6.0
# Sound separated by less than this is one stretch (a breath, a comma).
MERGE_S = 0.6
# Shorter sound is a click, not a word.
MIN_SOUND_S = 0.25
# Words are padded by this much; Whisper word times are loose at the edges.
WORD_PAD_S = 0.3
# One word covers at most this much time, half at its start and half at its end.
WORD_MAX_COVER_S = 2.0
# A span must hold at least this share of sound; mostly-silent spans are noise.
MIN_SOUND_FRACTION = 0.5
# Word density: a window with at least DENSITY_MIN_SOUND_S of sound needs
# MIN_WORDS_PER_S words per second of sound. Speech runs at 2-3 words/s.
DENSITY_WINDOW_S = 15.0
DENSITY_STEP_S = 1.0
DENSITY_MIN_SOUND_S = 7.5
MIN_WORDS_PER_S = 0.5
# A word longer than this, with sound under its uncovered middle, is a span.
# Clean runs never went past 2.12 s.
LONG_WORD_S = 4.0
# Decoded audio may be this much shorter than the last word or the stated duration.
LENGTH_TOLERANCE_S = 2.0


class Unchecked(RuntimeError):
    """The coverage check could not run; the sermon stays unchecked (NULL) and approval is refused."""


@dataclass(frozen=True)
class Span:
    start_s: float
    end_s: float

    @property
    def length_s(self) -> float:
        return self.end_s - self.start_s


def decode_audio(path: Path) -> np.ndarray:
    """Mono 16 kHz float32 via ffmpeg (already needed by yt-dlp). Raises ``Unchecked`` on failure."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise Unchecked(f"could not run ffmpeg on {path.name}: {exc.__class__.__name__}") from exc
    if result.returncode != 0 or not result.stdout:
        raise Unchecked(f"could not decode {path.name}: {result.stderr.decode(errors='replace')[:200]}")
    return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def frame_db(audio: np.ndarray) -> np.ndarray:
    """RMS level of each ``FRAME_S`` frame, in dBFS."""
    frame = int(FRAME_S * SR)
    count = len(audio) // frame
    frames = audio[: count * frame].reshape(count, frame)
    return 20 * np.log10(np.sqrt(np.mean(frames**2, axis=1)) + 1e-10)


def sound_spans(audio: np.ndarray) -> list[Span]:
    """Stretches of non-silent audio, in seconds."""
    return sound_spans_from_db(frame_db(audio))


def sound_spans_from_db(db: np.ndarray) -> list[Span]:
    if len(db) == 0:
        return []
    threshold = max(
        float(np.percentile(db, 98)) - REL_DB,
        float(np.percentile(db, NOISE_PERCENTILE)) + NOISE_MARGIN_DB,
        ABS_FLOOR_DB,
    )
    spans: list[Span] = []
    start = last = None
    for index in np.flatnonzero(db > threshold):
        t = float(index) * FRAME_S
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


def word_cuts(words: Iterable) -> list[tuple[float, float]]:
    """The time each word covers: padded, and at most ``WORD_MAX_COVER_S`` per word."""
    half = WORD_MAX_COVER_S / 2
    cuts: list[tuple[float, float]] = []
    for w in words:
        start, end = float(w.start), float(w.end)
        if end - start <= WORD_MAX_COVER_S:
            cuts.append((start - WORD_PAD_S, end + WORD_PAD_S))
        else:
            cuts.append((start - WORD_PAD_S, start + half + WORD_PAD_S))
            cuts.append((end - half - WORD_PAD_S, end + WORD_PAD_S))
    return sorted(cuts)


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


def _covered(words: Iterable) -> list[tuple[float, float]]:
    """Union of the time words cover, unpadded, each word capped at ``WORD_MAX_COVER_S``."""
    half = WORD_MAX_COVER_S / 2
    pieces: list[tuple[float, float]] = []
    for w in words:
        start, end = float(w.start), float(w.end)
        if end - start <= WORD_MAX_COVER_S:
            pieces.append((start, end))
        else:
            pieces.extend(((start, start + half), (end - half, end)))
    out: list[list[float]] = []
    for a, b in sorted(pieces):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def uncovered_spans(
    sound: list[Span],
    words: Iterable,
    *,
    max_gap_s: float = MAX_UNCOVERED_S,
) -> list[Span]:
    """Stretches longer than ``max_gap_s`` where the transcript is silent but the audio is not.

    ``words`` need ``.start`` and ``.end``. A stretch is the time between two
    word covers (a hole is measured by the transcript, so its pauses count).
    Before the first word and after the last it starts and ends at sound. It
    counts when at least ``MIN_SOUND_FRACTION`` of it is sound that no padded
    word touches.
    """
    if not sound:
        return []
    words = list(words)
    cuts = word_cuts(words)
    edges = [(-float("inf"), sound[0].start_s), *_covered(words), (sound[-1].end_s, float("inf"))]
    out: list[Span] = []
    for (_, a), (b, _) in zip(edges, edges[1:]):
        if b - a <= max_gap_s:
            continue
        inside = [Span(max(s.start_s, a), min(s.end_s, b)) for s in sound if s.end_s > a and s.start_s < b]
        if not inside:
            continue
        if a == sound[0].start_s:
            a = inside[0].start_s
        if b == sound[-1].end_s:
            b = inside[-1].end_s
        loose = sum(p.length_s for p in _subtract(inside, cuts))
        if b - a > max_gap_s and loose / (b - a) >= MIN_SOUND_FRACTION:
            out.append(Span(a, b))
    return out


def sparse_spans(sound: list[Span], words: Iterable) -> list[Span]:
    """Windows with sound but too few words per second of it, merged and trimmed to their sound.

    Words are counted by distinct start time: several words on one
    timestamp are one word (they are a corrupted run's filler, not speech).
    """
    if not sound:
        return []
    # One entry per start time, ending where the longest of its words ends,
    # so "some word with this start overlaps the window" stays one test.
    latest: dict[float, float] = {}
    for w in words:
        start = float(w.start)
        latest[start] = max(latest.get(start, start), float(w.end))
    starts = sorted(latest)
    ends = sorted(latest.values())
    end_s = sound[-1].end_s
    # Cumulative sound time before each span, for window overlap lookups.
    sound_starts = [s.start_s for s in sound]
    cum = np.concatenate([[0.0], np.cumsum([s.length_s for s in sound])])

    def sound_before(t: float) -> float:
        i = bisect.bisect_right(sound_starts, t)
        if i == 0:
            return 0.0
        s = sound[i - 1]
        return float(cum[i - 1]) + min(max(t - s.start_s, 0.0), s.length_s)

    flagged: list[list[float]] = []
    t = 0.0
    while t < end_s:
        a, b = t, t + DENSITY_WINDOW_S
        sound_s = sound_before(b) - sound_before(a)
        if sound_s >= DENSITY_MIN_SOUND_S:
            # Words overlapping the window: started before b, ended after a.
            count = bisect.bisect_left(starts, b) - bisect.bisect_right(ends, a)
            if count < MIN_WORDS_PER_S * sound_s:
                if flagged and a <= flagged[-1][1]:
                    flagged[-1][1] = b
                else:
                    flagged.append([a, b])
        t += DENSITY_STEP_S
    out: list[Span] = []
    for a, b in flagged:
        inside = [Span(max(s.start_s, a), min(s.end_s, b)) for s in sound if s.end_s > a and s.start_s < b]
        if inside:
            out.append(Span(inside[0].start_s, inside[-1].end_s))
    return out


def stretched_spans(sound: list[Span], words: Iterable) -> list[Span]:
    """Words longer than ``LONG_WORD_S`` whose uncovered middle holds sound.

    ``word_cuts`` lets such a word cover ``WORD_MAX_COVER_S`` at its ends;
    if at least ``MIN_SOUND_S`` of sound sits in the rest, the whole word is
    a span: something was said there that the transcript did not write.
    """
    half = WORD_MAX_COVER_S / 2
    out: list[Span] = []
    for w in words:
        start, end = float(w.start), float(w.end)
        if end - start <= LONG_WORD_S:
            continue
        a, b = start + half, end - half
        heard = sum(min(s.end_s, b) - max(s.start_s, a) for s in sound if s.end_s > a and s.start_s < b)
        if heard >= MIN_SOUND_S:
            out.append(Span(start, end))
    return out


def _union(spans: Iterable[Span]) -> list[Span]:
    out: list[list[float]] = []
    for s in sorted(spans, key=lambda s: s.start_s):
        if out and s.start_s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], s.end_s)
        else:
            out.append([s.start_s, s.end_s])
    return [Span(round(float(a), 2), round(float(b), 2)) for a, b in out]


def open_spans(sound: list[Span], words: list, *, max_gap_s: float = MAX_UNCOVERED_S) -> list[Span]:
    """Gaps, sparse stretches and stretched words together, merged where they overlap."""
    words = list(words)
    return _union([
        *uncovered_spans(sound, words, max_gap_s=max_gap_s),
        *sparse_spans(sound, words),
        *stretched_spans(sound, words),
    ])


def check_coverage(
    audio_path: Path,
    words: list,
    *,
    duration_s: float | None = None,
    max_gap_s: float = MAX_UNCOVERED_S,
    audio: np.ndarray | None = None,
) -> list[Span]:
    """Open spans for one transcript. Raises ``Unchecked`` when the audio cannot back the check.

    ``duration_s`` is the length the source states (YouTube metadata, the
    transcript's ``meta.duration_s``); the decoded audio must reach it and
    the last word, within ``LENGTH_TOLERANCE_S``.
    """
    if audio is None:
        audio = decode_audio(audio_path)
    audio_s = len(audio) / SR
    need = max([float(w.end) for w in words] + [float(duration_s or 0.0)])
    if audio_s + LENGTH_TOLERANCE_S < need:
        raise Unchecked(f"decoded audio is {audio_s:.1f}s but the transcript or stated duration reaches {need:.1f}s")
    return open_spans(sound_spans(audio), words, max_gap_s=max_gap_s)


def clip_to_window(spans: list[Span], window: tuple[float, float] | None, *, max_gap_s: float = MAX_UNCOVERED_S) -> list[Span]:
    """Spans inside a hand-set sermon window, clipped to it; shorter ones drop.

    A ``--windows`` entry (or a transcript's searchable range) is a human's
    statement of where the sermon is, so music or announcements outside it
    need no clearing. A span wholly inside the window is kept whatever its
    length (a stretched word can be under ``max_gap_s``); one the window cut
    is kept only if more than ``max_gap_s`` of it is left inside.
    """
    if window is None:
        return spans
    out = []
    for s in spans:
        clipped = Span(max(s.start_s, window[0]), min(s.end_s, window[1]))
        if clipped == s or clipped.length_s > max_gap_s:
            out.append(clipped)
    return out
