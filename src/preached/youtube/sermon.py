"""Pick the sermon inside a livestream.

A Sunday video is worship, announcements, the sermon, and prayer. There is
no music model and no LLM. The rule is:

1. A TOML override for the video id wins. Times are seconds on the video.
2. Otherwise split words where the gap between one word's end and the next
   word's start is more than 15 seconds. A band, a prayer pause that long,
   or a transition usually leaves a gap Whisper does not fill.
3. A run of at least 20 seconds is treated as singing when either the most
   common word is at least a quarter of the words, or the most common
   4-word phrase accounts for at least a quarter of the tokens (its count
   times 4, divided by the length). A chorus does that. A sermon does not:
   "the" is common, but not that common, and no 4-word line repeats through
   a quarter of the sermon.
4. The sermon is the longest remaining run. Length is the last word's end
   minus the first word's start. A tie keeps the earlier run.
5. If every run looks like singing, keep the longest run anyway so the
   video is not dropped, and the caller logs that the filter rejected all.

Words outside the window are not indexed.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from preached.youtube.words import Word

BREAK_S = 15.0
MIN_RUN_S = 20.0
HOOK_RATIO = 0.25
PHRASE_RATIO = 0.25


def load_windows(path: Path | None) -> dict[str, tuple[float, float]]:
    """Read ``[videos.<id>] start_s`` / ``end_s`` from a TOML file.

    Missing file means there are no overrides. An empty file is the same.
    """
    if path is None or not path.is_file():
        return {}
    import tomllib

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    videos = data.get("videos") or {}
    if not isinstance(videos, dict):
        raise RuntimeError(f"{path} videos must be a table")
    windows: dict[str, tuple[float, float]] = {}
    for video_id, row in videos.items():
        if not isinstance(row, dict) or "start_s" not in row or "end_s" not in row:
            raise RuntimeError(f"{path} [{video_id}] needs start_s and end_s")
        start = float(row["start_s"])
        end = float(row["end_s"])
        if end <= start:
            raise RuntimeError(f"{path} [{video_id}] end_s must be after start_s")
        windows[str(video_id)] = (start, end)
    return windows


def _tokens(words: list[Word]) -> list[str]:
    tokens = []
    for word in words:
        token = "".join(ch for ch in word.text.lower() if ch.isalnum() or ch == "'")
        if token:
            tokens.append(token)
    return tokens


def is_sung(words: list[Word]) -> bool:
    """True when a long run looks like a repeated chorus rather than speech."""
    if len(words) < 2:
        return False
    duration = words[-1].end - words[0].start
    if duration < MIN_RUN_S:
        return False
    tokens = _tokens(words)
    if len(tokens) < 8:
        return False
    top = Counter(tokens).most_common(1)[0][1] / len(tokens)
    if top >= HOOK_RATIO:
        return True
    if len(tokens) >= 12:
        grams = [tuple(tokens[index : index + 4]) for index in range(len(tokens) - 3)]
        count = Counter(grams).most_common(1)[0][1]
        # Non-overlapping coverage: four tokens per hit. A line repeated
        # every few words clears a quarter of the run. A sermon 4-gram does not.
        if count * 4 / len(tokens) >= PHRASE_RATIO:
            return True
    return False


def speech_runs(words: list[Word], break_s: float = BREAK_S) -> list[list[Word]]:
    """Split on gaps strictly longer than ``break_s``. A 15.0s gap stays one run."""
    if not words:
        return []
    ordered = sorted(words, key=lambda word: (word.start, word.end))
    runs: list[list[Word]] = [[ordered[0]]]
    for word in ordered[1:]:
        gap = word.start - runs[-1][-1].end
        if gap > break_s:
            runs.append([word])
        else:
            runs[-1].append(word)
    return runs


def _duration(run: list[Word]) -> float:
    return run[-1].end - run[0].start


def sermon_span(
    words: list[Word],
    override: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """Return ``(start_s, end_s)`` of the sermon window on the video timeline.

    The override is returned as written, even when it sits outside the words.
    With no words and no override, the window is empty.
    """
    if override is not None:
        return override
    runs = speech_runs(words)
    if not runs:
        return (0.0, 0.0)
    spoken = [run for run in runs if not is_sung(run)]
    pool = spoken or runs
    best = max(pool, key=lambda run: (_duration(run), -run[0].start))
    return (best[0].start, best[-1].end)


def words_in_span(words: list[Word], start_s: float, end_s: float) -> list[Word]:
    """Words whose start falls inside ``[start_s, end_s)``."""
    return [word for word in words if word.start >= start_s and word.start < end_s]
