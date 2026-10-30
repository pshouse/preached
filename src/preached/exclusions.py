"""Excluded stretches: in the review file, at import and at approval.

For a church library, announcements, prayer requests and testimonies are
never indexed (Patrick's decision; ``preached.skip`` proposes them). How:

**Import.** ``preached.skip.propose`` marks stretches of the sermon's words.
Those words are never chunked, embedded or stored: each run of kept words is
chunked on its own, so a chunk that would span a boundary is cut at it. The
review file gets one ``{"field": "exclusions", ...}`` line and one
``{"field": "exclude", ...}`` line per stretch (word range, times, matched
cues, and the opening and closing words so a person can find it in the
recording). The kept words, already redacted, go into a second owner-only
file next to it (``<id>.words.review.jsonl``) whose sha256 is on the
``exclusions`` line, so the review file's sha256 covers it.

**Review.** The approving person reads the ``exclude`` lines with the
recording. They may leave a line as it is (confirm), lower ``start_word``
or raise ``end_word`` (or the ``start_s``/``end_s`` times) to widen it, or
add a line ``{"field": "exclude", "start_s": 1200, "end_s": 1310}`` (or
``start_word``/``end_word``) for a stretch the rules missed. A line's word
range and time range both count (their union is excluded). A proposed
stretch cannot be narrowed or removed: its words were never stored, so
there is nothing to restore. Every other line must stay byte-identical.

**Approval** (``--ack-review``, ``approve``) excludes exactly what the
reviewed file lists. An unchanged file is approved as before. A file whose
``exclude`` lines add words rebuilds that sermon's chunks from the kept-words
file minus the new stretches, re-embeds them, replaces the old rows with
SQLite ``secure_delete`` on, merges the FTS index and checkpoints the WAL,
so the newly excluded words leave the chunks, FTS, vectors and the file.
Then the approval is stored against the edited file's sha256, and the
kept-words file is deleted. After approval the file is frozen: any edit is
refused (re-import with ``--redo`` to review again).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from preached.skip import Stretch

HEADER = "exclusions"
FIELD = "exclude"
PREVIEW_WORDS = 12
HOW = (
    "Each exclude line is a stretch that is never indexed. Confirm it, widen it (lower start_word / raise "
    "end_word, or the start_s/end_s times), or add a line {\"field\": \"exclude\", \"start_s\": S, \"end_s\": E}. "
    "A proposed stretch cannot be narrowed or removed. Change nothing else. Editing after approval is refused."
)


def words_file(review_file: str | os.PathLike[str]) -> Path:
    """The kept-words file next to a review file: ``<id>.words.review.jsonl``."""
    path = Path(review_file)
    stem = path.name[: -len(".review.jsonl")] if path.name.endswith(".review.jsonl") else path.stem
    return path.with_name(f"{stem}.words.review.jsonl")


def excluded_indexes(stretches: Sequence[Stretch]) -> set[int]:
    return {i for s in stretches for i in range(s.start, s.end)}


def kept_runs(indexes: Sequence[int]) -> list[list[int]]:
    """Consecutive runs of the kept word indexes."""
    runs: list[list[int]] = []
    for index in sorted(indexes):
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def boundary_flags(runs: Sequence[Sequence[dict]], count: int) -> list[tuple[float | None, float | None]]:
    """``(head, tail)`` ``flag_end_s`` for the first and last chunk of each kept run.

    A chunk next to an excluded stretch is flagged like a chunk holding a name
    (CTO round on #19): under ``none`` it gets no link, its sermon loses the
    untimed links (``search.sermon_flagged``), and ``search.touches_flagged``
    (the one rule, SEEK_SLACK_S) withholds the link of any later chunk whose
    seek could reach back into the stretch. Without this the chunk right
    after a stretch seeks back into it by its pre-roll.

    ``head`` is the start of the run's first word (the stretch before it ends
    there or earlier); ``tail`` is the start of the next run's first word (the
    stretch after it ends there or earlier), or the run's own end when the
    stretch runs to the end of the sermon. None: no stretch on that side.
    """
    out = []
    for number, run in enumerate(runs):
        head = float(run[0]["s"]) if run and run[0]["i"] > 0 else None
        tail = None
        if run and run[-1]["i"] < count - 1:
            following = runs[number + 1] if number + 1 < len(runs) else None
            tail = float(following[0]["s"]) if following else float(run[-1]["e"])
        out.append((head, tail))
    return out


def merge_flag(*values: float | None) -> float | None:
    """The latest of the given ``flag_end_s`` values, or None when all are None."""
    present = [v for v in values if v is not None]
    return max(present) if present else None


def word_rows(texts: Sequence[str], starts: Sequence[float], ends: Sequence[float], tokens: Sequence[int] | None = None) -> list[dict]:
    """``{"i", "s", "e", "t", "k"}`` per word (``k``: first token offset, ASR only)."""
    return [
        {"i": i, "s": float(starts[i]), "e": float(ends[i]), "t": texts[i], **({"k": tokens[i]} if tokens is not None else {})}
        for i in range(len(texts))
    ]


def review_lines(stretches: Sequence[Stretch], rows: Sequence[dict], words_sha256: str) -> list[dict]:
    """The ``exclusions`` line and one ``exclude`` line per proposed stretch."""
    lines: list[dict] = [{"field": HEADER, "words": len(rows), "words_file_sha256": words_sha256, "how": HOW}]
    for stretch in stretches:
        inside = rows[stretch.start : stretch.end]
        lines.append({
            "field": FIELD,
            **stretch.as_dict(),
            "start_s": inside[0]["s"],
            "end_s": inside[-1]["e"],
            "opening": " ".join(r["t"] for r in inside[:PREVIEW_WORDS]),
            "closing": " ".join(r["t"] for r in inside[-PREVIEW_WORDS:]),
            "proposed_by": "preached.skip",
        })
    return lines


def words_file_lines(kind: str, meta: dict, rows: Sequence[dict], excluded: set[int]) -> list[dict]:
    """The kept-words file: a header with what a rebuild needs, then each kept word."""
    return [{"field": "words", "kind": kind, "count": len(rows), "meta": meta}, *(r for r in rows if r["i"] not in excluded)]


# ---------------------------------------------------------------- approval


class Refused(RuntimeError):
    """The review file cannot be approved as it stands."""


def _split(data: bytes) -> tuple[bytes, list[dict], dict | None]:
    """``(bytes of every non-exclude line, exclude lines, exclusions header)``."""
    base, excludes, header = [], [], None
    for number, line in enumerate(data.splitlines(keepends=True), 1):
        if not line.strip():
            raise Refused(f"review file line {number} is blank")
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise Refused(f"review file line {number} is not JSON") from exc
        if isinstance(item, dict) and item.get("field") == FIELD:
            excludes.append(item)
            continue
        if isinstance(item, dict) and item.get("field") == HEADER:
            header = item
        base.append(line if line.endswith(b"\n") else line + b"\n")
    return b"".join(base), excludes, header


def base_sha256(lines: Sequence[dict]) -> str:
    """sha256 of the review file's lines other than ``exclude``, as the writer emits them."""
    data = b"".join(
        (json.dumps(dict(item), ensure_ascii=False) + "\n").encode("utf-8")
        for item in lines
        if not (isinstance(item, dict) and item.get("field") == FIELD)
    )
    return hashlib.sha256(data).hexdigest()


def _number(item: dict, key: str, kind: type) -> Any:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind is int and not isinstance(value, int)):
        raise Refused(f"exclude line: {key} must be a {'whole number' if kind is int else 'number'}")
    if value != value or value in (float("inf"), float("-inf")):
        raise Refused(f"exclude line: {key} is not finite")
    return value


def resolve(excludes: Sequence[dict], count: int, times: dict[int, tuple[float, float]]) -> set[int]:
    """Word indexes the ``exclude`` lines name: each line's word range plus its time range.

    ``times`` maps the stored (kept) words to ``(start, end)``; a word is in a
    time range when its midpoint is.
    """
    out: set[int] = set()
    for item in excludes:
        a, b = _number(item, "start_word", int), _number(item, "end_word", int)
        s, e = _number(item, "start_s", float), _number(item, "end_s", float)
        if (a is None) != (b is None) or (s is None) != (e is None) or (a is None and s is None):
            raise Refused("exclude line needs start_word and end_word, or start_s and end_s")
        if a is not None:
            if not 0 <= a < b <= count:
                raise Refused(f"exclude line: word range {a}-{b} is outside 0-{count}")
            out.update(range(a, b))
        if s is not None:
            if e <= s:
                raise Refused(f"exclude line: end_s {e} is not after start_s {s}")
            out.update(i for i, (ws, we) in times.items() if s <= (ws + we) / 2 < e)
    return out


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def approve(
    connection: sqlite3.Connection,
    video_id: str,
    review_file: str | os.PathLike[str],
    privacy_sha256: str,
    *,
    token: str,
    embedder: Callable[[list[str], list[str]], Any] | None = None,
) -> str:
    """Approve one sermon, excluding exactly what its review file lists; return the file's sha256.

    See the module docstring. ``embedder`` is only called when the reviewer
    added words to the exclusions (the chunks are rebuilt).
    """
    from preached.youtube.library import approve_review

    row = connection.execute(
        "SELECT status, review_sha256, privacy_sha256, approved_sha256, review_base_sha256 FROM videos WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    if row is None or row[0] != "ok":
        raise Refused(f"{video_id}: not imported")
    try:
        data = Path(review_file).read_bytes()
    except OSError as exc:
        raise Refused(f"{video_id}: review file is missing ({exc.__class__.__name__})") from exc
    digest = hashlib.sha256(data).hexdigest()
    if row[3] is not None and row[3] != digest:
        raise Refused(f"{video_id}: review file changed after approval; re-import with --redo to review it again")
    if digest == row[1] or row[4] is None:
        # Unchanged since import (or an import from before exclusions): the stored chunks already match it.
        approved = approve_review(connection, video_id, review_file, privacy_sha256)
        _delete_words(review_file)
        return approved
    if row[2] is None or row[2] != privacy_sha256:
        raise Refused(
            f"{video_id}: privacy config changed since import; re-import with --redo under the config you mean, "
            "or pass the same --privacy"
        )
    base, excludes, header = _split(data)
    if hashlib.sha256(base).hexdigest() != row[4] or header is None:
        raise Refused(f"{video_id}: review file changed since import outside its exclude lines; re-import before approving")
    words_path = words_file(review_file)
    try:
        words_data = words_path.read_bytes()
    except OSError as exc:
        raise Refused(f"{video_id}: kept-words file is missing ({exc.__class__.__name__}); re-import with --redo") from exc
    if hashlib.sha256(words_data).hexdigest() != header.get("words_file_sha256"):
        raise Refused(f"{video_id}: kept-words file does not match the review file; re-import with --redo")
    lines = [json.loads(line) for line in words_data.splitlines()]
    info, kept = lines[0], lines[1:]
    count = int(info["count"])
    times = {w["i"]: (w["s"], w["e"]) for w in kept}
    wanted = resolve(excludes, count, times)
    already = set(range(count)) - set(times)
    if not already <= wanted:
        raise Refused(
            f"{video_id}: the exclude lines leave out {len(already - wanted)} words excluded at import; "
            "a proposed stretch can be confirmed or widened, not narrowed or removed"
        )
    remaining = [w for w in kept if w["i"] not in wanted]
    if len(remaining) == len(kept):
        connection.execute(
            "UPDATE videos SET review_sha256 = ?, approved_sha256 = ?, approved_at = ? WHERE video_id = ?",
            (digest, digest, _now(), video_id),
        )
        connection.commit()
    else:
        _rebuild(connection, video_id, info, remaining, data, digest, hashlib.sha256(base).hexdigest(), token, embedder)
    _delete_words(review_file)
    return digest


def _delete_words(review_file: str | os.PathLike[str]) -> None:
    words_file(review_file).unlink(missing_ok=True)


def _review_items(data: bytes) -> list[dict]:
    """The name items of a review file (lines with a ``reason`` and no ``field``)."""
    items = []
    for line in data.splitlines():
        item = json.loads(line)
        if isinstance(item, dict) and "field" not in item and "reason" in item:
            items.append(item)
    return items


def _rebuild(connection, video_id, info, remaining, data, digest, base, token, embedder) -> None:
    import numpy as np

    from preached.youtube.library import index_video

    kind, meta = info["kind"], info["meta"]
    runs: list[list[dict]] = []
    for word in remaining:
        if runs and word["i"] == runs[-1][-1]["i"] + 1:
            runs[-1].append(word)
        else:
            runs.append([word])
    items = _review_items(data)
    if kind == "youtube":
        from preached.youtube.pipeline import youtube_records

        records = youtube_records(meta, runs, items, token, count=int(info["count"]))
    elif kind == "asr":
        from preached.asr import church_records
        from preached.corpus import load_chunk_config

        records = church_records(
            runs, load_chunk_config(), sermon_id=video_id, title=meta["title"], meta=meta["source"],
            token=token, items=items, pause_s=float(meta["pause_s"]), count=int(info["count"]),
        )
    else:
        raise Refused(f"{video_id}: unknown kept-words kind {kind!r}")
    video = connection.execute(
        "SELECT title, published, duration_s, license, uploader FROM videos WHERE video_id = ?", (video_id,)
    ).fetchone()
    title = video[0] or ""
    if records:
        if embedder is None:
            from preached.youtube.pipeline import _embed_on_cpu

            embedder = _embed_on_cpu
        matrix = np.asarray(embedder([title] * len(records), [r["text"] for r in records]), dtype=np.float32)
    else:
        matrix = np.zeros((0, 1), dtype=np.float32)
    old = connection.execute("SELECT sermon_number, librivox_id, reader FROM chunks WHERE video_id = ? LIMIT 1", (video_id,)).fetchone()
    connection.execute("PRAGMA secure_delete = ON")
    index_video(
        connection,
        video_id=video_id,
        title=title,
        published=date.fromisoformat(video[1]) if video[1] else None,
        duration_s=video[2],
        license_text=video[3],
        uploader=video[4],
        chunks=records,
        matrix=matrix,
        review_sha256=digest,
        privacy_sha256=connection.execute("SELECT privacy_sha256 FROM videos WHERE video_id = ?", (video_id,)).fetchone()[0],
        review_base_sha256=base,
        reader=old[2] if old else None,
        sermon_number=old[0] if old else None,
        librivox_id=old[1] if old else None,
    )
    connection.execute("UPDATE videos SET approved_sha256 = ?, approved_at = ? WHERE video_id = ?", (digest, _now(), video_id))
    connection.commit()
    # Old FTS segments still hold the removed words until they are merged;
    # secure_delete zeroes the freed pages, and the checkpoint moves the
    # zeroed pages into the main file.
    connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
