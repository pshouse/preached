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
SQLite ``secure_delete`` on, merges the FTS index and checkpoints the WAL
(checked and retried: ``youtube.library.scrub``), so the newly excluded
words leave the chunks, FTS, vectors and the file. For the ASR path the
``--out`` JSONL is rewritten with the rebuilt chunks too. Every approval
runs that scrub first; if the checkpoint cannot finish (a reader holds the
WAL), nothing is approved and ``--ack-review`` exits non-zero. Then the
approval is stored, the ``opening``/``closing`` previews are purged from
the review file (the stored sha256s follow the purged file), and the
kept-words file is zeroed and deleted. After approval the file is frozen:
any edit is refused (re-import with ``--redo`` to review again).

**Re-import** (``--redo``, or re-running ``align/asr_chunks.py``): every
``exclude`` line of the previous review file is carried onto the new words
(``carried_stretches``), so a stretch a reviewer added or widened stays
excluded. Its time range always counts; its word range only when the word
count is unchanged.

**The human check is the real control** (CTO ruling, 2026-10-30): the cue
rules found 0.870 of the excluded words on the synthetic test set, so they
are not enough alone. The reviewer must listen through the whole recording
before approving; the review file's header line says so (``REVIEWER_MUST``).
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from preached.privacy import read_private_file, replace_private_bytes, wipe_private_file
from preached.skip import Stretch

HEADER = "exclusions"
FIELD = "exclude"
PREVIEW_WORDS = 12
HOW = (
    "Each exclude line is a stretch that is never indexed. Confirm it, widen it (lower start_word / raise "
    "end_word, or the start_s/end_s times), or add a line {\"field\": \"exclude\", \"start_s\": S, \"end_s\": E}. "
    "A proposed stretch cannot be narrowed or removed. Change nothing else. Editing after approval is refused."
)
# CTO ruling (2026-10-30): word recall 0.870 means the cues are not enough alone.
REVIEWER_MUST = (
    "Listen through the whole recording, start to end, before approving. The proposed stretches are a "
    "starting point only: on the synthetic test set the rules caught 87% of the words that should be "
    "excluded (word recall 0.870), so they miss some. Your listening is the real control; add an exclude "
    "line for every announcement, prayer request, prayer list or testimony they missed."
)
PREVIEW_KEYS = ("opening", "closing")
CARRIED = "kept from the previous review file"


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
    lines: list[dict] = [{
        "field": HEADER, "reviewer_must": REVIEWER_MUST, "words": len(rows), "words_file_sha256": words_sha256, "how": HOW,
    }]
    for stretch in stretches:
        inside = rows[stretch.start : stretch.end]
        lines.append({
            "field": FIELD,
            **stretch.as_dict(),
            "start_s": inside[0]["s"],
            "end_s": inside[-1]["e"],
            "opening": " ".join(r["t"] for r in inside[:PREVIEW_WORDS]),
            "closing": " ".join(r["t"] for r in inside[-PREVIEW_WORDS:]),
            "proposed_by": "previous review" if stretch.category == "reviewer" else "preached.skip",
        })
    return lines


def previous_excludes(review_file: str | os.PathLike[str]) -> tuple[list[dict], int | None]:
    """The ``exclude`` lines of an existing review file and its word count (``[]`` if there is none).

    Read with no symlink followed. A symlink at the file's name is not a
    review file we wrote (those are regular files): it is ignored here and
    replaced by the writer. An unparsable file stops the re-import: a
    reviewer's additions must not be dropped silently.
    """
    try:
        data = read_private_file(review_file)
    except FileNotFoundError:
        return [], None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return [], None
        raise
    try:
        lines = [json.loads(line) for line in data.splitlines() if line.strip()]
    except ValueError as exc:
        raise RuntimeError(
            "the previous review file is not JSON lines; fix it or move it aside before re-importing "
            "(its exclude lines are carried over)"
        ) from exc
    header = next((x for x in lines if isinstance(x, dict) and x.get("field") == HEADER), None) or {}
    count = header.get("words") if isinstance(header.get("words"), int) else None
    return [x for x in lines if isinstance(x, dict) and x.get("field") == FIELD], count


def carried_stretches(excludes: Sequence[dict], count_then: int | None, rows: Sequence[dict], proposed: set[int]) -> list[Stretch]:
    """Old ``exclude`` lines mapped onto the new words, minus what is already proposed.

    A line's time range always counts (``resolve``: word midpoints). Its word
    range counts only when the sermon has the same number of words as when
    it was written; otherwise a line with only a word range cannot be placed
    and the re-import is refused (fail closed).
    """
    usable = []
    for item in excludes:
        item = dict(item)
        if count_then != len(rows):
            if item.get("start_s") is None or item.get("end_s") is None:
                raise RuntimeError(
                    "the previous review file has an exclude line with only a word range, and the new transcript "
                    "has a different word count; give that line start_s and end_s before re-importing"
                )
            item.pop("start_word", None)
            item.pop("end_word", None)
        usable.append(item)
    times = {r["i"]: (r["s"], r["e"]) for r in rows}
    try:
        indexes = resolve(usable, len(rows), times) - set(proposed)
    except Refused as exc:
        raise RuntimeError(f"the previous review file cannot be carried over: {exc}") from exc
    return [Stretch(run[0], run[-1] + 1, "reviewer", reasons=[CARRIED]) for run in kept_runs(sorted(indexes))]


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
    added words to the exclusions (the chunks are rebuilt). The review and
    kept-words files are opened with no symlink followed. Raises ``Refused``
    or ``youtube.library.CheckpointBusy`` (both ``RuntimeError``) and then
    approves nothing.
    """
    from preached.youtube.library import scrub

    row = connection.execute(
        "SELECT status, review_sha256, privacy_sha256, approved_sha256, review_base_sha256, coverage_gaps FROM videos WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    if row is None or row[0] != "ok":
        raise Refused(f"{video_id}: not imported")
    # Sound with no transcript is a stretch the ASR dropped: a name in it was never flagged or redacted.
    if row[5] is None:
        raise Refused(f"{video_id}: ASR coverage was never checked; re-import with --redo")
    gaps = json.loads(row[5])
    if gaps:
        shown = ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in gaps[:6])
        raise Refused(
            f"{video_id}: {len(gaps)} stretch(es) of sound have no transcript ({shown}). Listen, then "
            "re-import with --redo (a --windows entry limits the check to the sermon)"
        )
    try:
        data = read_private_file(review_file)
    except (OSError, RuntimeError) as exc:
        raise Refused(f"{video_id}: review file is missing or not a plain file ({exc.__class__.__name__})") from exc
    digest = hashlib.sha256(data).hexdigest()
    if row[3] is not None and row[3] != digest:
        raise Refused(f"{video_id}: review file changed after approval; re-import with --redo to review it again")
    if row[2] is None or row[2] != privacy_sha256:
        raise Refused(
            f"{video_id}: privacy config changed since import (or the import predates the config hash); "
            "re-import with --redo under the config you mean, or pass the same --privacy"
        )
    if digest == row[1] or row[4] is None:
        # Unchanged since import (or an import from before exclusions): the stored chunks already match it.
        if digest != row[1]:
            raise Refused(f"{video_id}: review file changed since import; re-import before approving")
        scrub(connection)
        _record(connection, video_id, digest)
    else:
        base, excludes, header = _split(data)
        if hashlib.sha256(base).hexdigest() != row[4] or header is None:
            raise Refused(f"{video_id}: review file changed since import outside its exclude lines; re-import before approving")
        words_path = words_file(review_file)
        try:
            words_data = read_private_file(words_path)
        except (OSError, RuntimeError) as exc:
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
            connection.execute("UPDATE videos SET review_sha256 = ? WHERE video_id = ?", (digest, video_id))
            connection.commit()
        else:
            # index_video replaces the rows and scrubs (secure_delete, FTS merge, checked checkpoint).
            _rebuild(connection, video_id, info, remaining, data, digest, hashlib.sha256(base).hexdigest(), token, embedder, row[5])
        scrub(connection)
        _record(connection, video_id, digest)
    approved = _purge_previews(connection, video_id, review_file, data, digest)
    wipe_private_file(words_file(review_file))
    return approved


def _record(connection: sqlite3.Connection, video_id: str, digest: str) -> None:
    connection.execute(
        "UPDATE videos SET approved_sha256 = ?, approved_at = ? WHERE video_id = ? AND review_sha256 = ?",
        (digest, _now(), video_id, digest),
    )
    connection.commit()


def _purge_previews(connection: sqlite3.Connection, video_id: str, review_file, data: bytes, digest: str) -> str:
    """Drop the ``opening``/``closing`` words from the approved file; return its new sha256.

    Those previews are words of the excluded stretches, there only so the
    reviewer can find them in the recording. After approval they go: the
    file is rewritten without them (the old bytes zeroed,
    ``privacy.replace_private_bytes``), and the stored review and approved
    sha256 move to the new file in one statement, so the sermon stays
    published and any later edit is still refused. A file whose other lines
    would not survive the rewrite byte for byte is left as it is.
    """
    lines = [json.loads(line) for line in data.splitlines()]
    if not any(isinstance(x, dict) and x.get("field") == FIELD and any(k in x for k in PREVIEW_KEYS) for x in lines):
        return digest
    purged = [
        {k: v for k, v in x.items() if k not in PREVIEW_KEYS} if isinstance(x, dict) and x.get("field") == FIELD else x
        for x in lines
    ]
    new = b"".join((json.dumps(x, ensure_ascii=False) + "\n").encode("utf-8") for x in purged)
    if _split(new)[0] != _split(data)[0]:
        return digest
    replace_private_bytes(review_file, new)
    new_digest = hashlib.sha256(new).hexdigest()
    connection.execute(
        "UPDATE videos SET review_sha256 = ?, approved_sha256 = ? WHERE video_id = ? AND approved_sha256 = ?",
        (new_digest, new_digest, video_id, digest),
    )
    connection.commit()
    return new_digest


def _review_items(data: bytes) -> list[dict]:
    """The name items of a review file (lines with a ``reason`` and no ``field``)."""
    items = []
    for line in data.splitlines():
        item = json.loads(line)
        if isinstance(item, dict) and "field" not in item and "reason" in item:
            items.append(item)
    return items


def _rebuild(connection, video_id, info, remaining, data, digest, base, token, embedder, coverage_gaps=None) -> None:
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
    if kind == "asr" and meta.get("out"):
        # Before index_video: if its checkpoint is refused, the retry takes the unchanged path.
        replace_out_rows(Path(meta["out"]), video_id, records)
    old = connection.execute("SELECT sermon_number, librivox_id, reader FROM chunks WHERE video_id = ? LIMIT 1", (video_id,)).fetchone()
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
        coverage_gaps=json.loads(coverage_gaps) if coverage_gaps else [],
        reader=old[2] if old else None,
        sermon_number=old[0] if old else None,
        librivox_id=old[1] if old else None,
    )


def replace_out_rows(path: Path, sermon_id: str, records: list[dict]) -> None:
    """Put the rebuilt chunks in place of a sermon's rows in the ASR ``--out`` JSONL.

    Without this the file written at import keeps the words a reviewer
    excluded. The other sermons' rows are kept as they are, in order; the
    file is replaced atomically and its old bytes zeroed
    (``privacy.replace_private_bytes``, no symlink followed). A missing file,
    or one without this sermon, is left alone.
    """
    try:
        data = read_private_file(path)
    except FileNotFoundError:
        return
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    at = next((i for i, row in enumerate(rows) if isinstance(row, dict) and row.get("sermon_id") == sermon_id), None)
    if at is None:
        return
    others = [row for row in rows if not (isinstance(row, dict) and row.get("sermon_id") == sermon_id)]
    rows = others[:at] + list(records) + others[at:]
    replace_private_bytes(path, b"".join((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8") for row in rows))
