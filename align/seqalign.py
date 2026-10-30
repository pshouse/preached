"""Carry Whisper word timestamps onto a reference text. Stdlib only.

Generic: nothing here knows about Wesley or LibriVox. Inputs are two lists
of normalized tokens (``textnorm``); outputs are anchors and per-token times.

1. ``difflib.SequenceMatcher`` (no autojunk) finds matching runs.
2. Short runs stranded between large unmatched regions are dropped: a lone
   "of the" in the middle of a passage the reader skipped is a coincidence,
   not an anchor.
3. Inside the small gaps between kept runs, equal-length substitutions that
   are spelled alike ("Saviour"/"Savior" after normalization misses) are
   paired as fuzzy anchors.
4. Reference tokens with no anchor get times interpolated between their
   anchored neighbours, in proportion to their length in characters.
"""

from __future__ import annotations

from difflib import SequenceMatcher

EXACT, FUZZY, INTERPOLATED = 1, 2, 0

MIN_RUN = 4  # runs this long are always trusted
ISOLATION = 15  # a shorter run with gaps this large on both sides is dropped
FUZZY_MAX_GAP = 4
FUZZY_RATIO = 0.7


def _gap(left: tuple[int, int, int] | None, right: tuple[int, int, int] | None) -> int:
    """Largest unmatched stretch (in either sequence) between two runs."""
    a_end = left[0] + left[2] if left else 0
    b_end = left[1] + left[2] if left else 0
    if right is None:
        return 10**9
    return max(right[0] - a_end, right[1] - b_end)


def match_runs(ref: list[str], hyp: list[str]) -> list[tuple[int, int, int]]:
    """Matching runs ``(ref_i, hyp_j, size)`` after dropping stranded short runs."""
    blocks = [b for b in SequenceMatcher(None, ref, hyp, autojunk=False).get_matching_blocks() if b.size]
    runs = [tuple(b) for b in blocks]
    changed = True
    while changed:
        changed = False
        kept: list[tuple[int, int, int]] = []
        for index, run in enumerate(runs):
            if run[2] >= MIN_RUN:
                kept.append(run)
                continue
            left = kept[-1] if kept else None
            right = runs[index + 1] if index + 1 < len(runs) else None
            left_gap = _gap(left, run) if left else max(run[0], run[1])
            right_gap = _gap(run, right)
            if left_gap > ISOLATION and right_gap > ISOLATION:
                changed = True
                continue
            kept.append(run)
        runs = kept
    return runs


def _similar(a: str, b: str) -> bool:
    if min(len(a), len(b)) < 3:
        return False
    return SequenceMatcher(None, a, b).ratio() >= FUZZY_RATIO


def align_tokens(ref: list[str], hyp: list[str]) -> dict[int, tuple[int, int]]:
    """Map ref token index -> (hyp token index, EXACT | FUZZY)."""
    runs = match_runs(ref, hyp)
    anchors: dict[int, tuple[int, int]] = {}
    previous = (0, 0, 0)
    for run in runs + [(len(ref), len(hyp), 0)]:
        a0, b0 = previous[0] + previous[2], previous[1] + previous[2]
        a_len, b_len = run[0] - a0, run[1] - b0
        if a_len == b_len and 0 < a_len <= FUZZY_MAX_GAP:
            for offset in range(a_len):
                if _similar(ref[a0 + offset], hyp[b0 + offset]):
                    anchors[a0 + offset] = (b0 + offset, FUZZY)
        for offset in range(run[2]):
            anchors[run[0] + offset] = (run[1] + offset, EXACT)
        previous = run
    return anchors


def interpolate(
    times: list[tuple[int, float, float] | None],
    weights: list[int],
    part_ends: list[float],
) -> list[tuple[int, float, float]]:
    """Fill ``None`` entries between anchored ``(part, start, end)`` times.

    ``part`` indexes the audio file (a sermon can span two files). A gap
    whose anchors are in the same part is spread across the silence between
    them by ``weights`` (characters). A gap that crosses parts stays in the
    earlier part, spread up to that part's end (``part_ends``). Tokens before
    the first anchor collapse onto it, and tokens after the last one onto it.
    """
    count = len(times)
    out: list[tuple[int, float, float] | None] = list(times)
    anchored = [i for i, t in enumerate(times) if t is not None]
    if not anchored:
        return [(0, 0.0, 0.0)] * count
    first, last = anchored[0], anchored[-1]
    for i in range(first):
        part, start, _ = times[first]
        out[i] = (part, start, start)
    for i in range(last + 1, count):
        part, _, end = times[last]
        out[i] = (part, end, end)
    for left, right in zip(anchored, anchored[1:]):
        if right - left < 2:
            continue
        lpart, _, lend = times[left]
        rpart, rstart, _ = times[right]
        span_end = rstart if rpart == lpart else max(lend, part_ends[lpart])
        span_end = max(span_end, lend)
        gap = range(left + 1, right)
        total = sum(max(1, weights[i]) for i in gap)
        cursor = lend
        for i in gap:
            step = (span_end - lend) * max(1, weights[i]) / total
            out[i] = (lpart, round(cursor, 3), round(cursor + step, 3))
            cursor += step
    return out  # type: ignore[return-value]
