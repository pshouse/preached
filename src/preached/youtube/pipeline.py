"""Import the videos a channel listing names into one library file.

Re-running skips video ids already marked ``ok``. A failure on one video is
recorded and the rest continue. ``--dry-run`` prints id, title, date, and
duration, and does not download, transcribe, or write the index. A successful
import deletes the working audio file. ``--keep-audio`` leaves it. A failed
video keeps the file so the next run can resume the download.
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np

from preached.audio_policy import resolve_flagged_audio
from preached.corpus import load_chunk_config
from preached.exclusions import approve, base_sha256, boundary_flags, carried_stretches, excluded_indexes, kept_runs, merge_flag, previous_excludes, review_lines, word_rows, words_file, words_file_lines
from preached.privacy import Config, ReviewList, apply_drops, config_sha256, default_config, redact_metadata, required_config, review, review_metadata, write_review_file_sha256
from preached.youtube import privacy
from preached.youtube.coverage import check_coverage, clip_to_window
from preached.skip import propose
from preached.youtube.chunking import chunk_words
from preached.youtube.library import imported_ok, index_video, mark_video, open_library
from preached.youtube.listing import Video, creative_commons, parse_date, watch_url
from preached.youtube.sermon import is_sung, load_windows, sermon_span, speech_runs, words_in_span
from preached.youtube.words import Word


@dataclass
class Settings:
    channel_url: str
    library: str
    limit: int | None
    since: date | None
    dry_run: bool
    require_cc: bool
    redo: bool
    keep_audio: bool
    index_path: Path
    audio_dir: Path
    windows_path: Path | None
    privacy_path: Path | None = None
    review_dir: Path | None = None

    def review_root(self) -> Path:
        """Where review files go: ``<index dir>/<library>/review``, owner-only, never in the repo."""
        return self.review_dir or self.index_path.with_suffix("") / "review"


def select_videos(
    videos: list[Video],
    *,
    imported: set[str],
    since: date | None,
    limit: int | None,
) -> list[Video]:
    """Keep listing order. ``--since`` drops unknown dates and older ones."""
    chosen: list[Video] = []
    for video in videos:
        if video.id in imported:
            continue
        if since is not None and (video.published is None or video.published < since):
            continue
        chosen.append(video)
        if limit is not None and len(chosen) >= limit:
            break
    return chosen


def format_dry_run(videos: list[Video]) -> str:
    """One TSV line per video: id, title, YYYY-MM-DD, duration seconds."""
    lines = []
    for video in videos:
        title = video.title.replace("\t", " ").replace("\r", " ").replace("\n", " ")
        published = video.published.isoformat() if video.published else ""
        duration = "" if video.duration_s is None else str(int(video.duration_s))
        lines.append(f"{video.id}\t{title}\t{published}\t{duration}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _embed_on_cpu(titles: list[str], texts: list[str]) -> np.ndarray:
    """Granite ONNX on CPU. The lean runtime does not install torch.

    ``load_embedder(..., "onnx")`` returns float32 L2-normalized vectors.
    Granite's document template is empty, so titles do not change the text
    that is encoded. The library writer stores this matrix as-is.
    """
    import os

    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from preached.backends import load_embedder

    started = time.perf_counter()
    embedder = load_embedder("granite-english-r2", "onnx", device="cpu", batch_size=8)
    loaded_s = time.perf_counter() - started
    encoded = time.perf_counter()
    matrix = np.asarray(embedder.encode_documents(texts, titles), dtype=np.float32)
    print(
        f"embed load_s={loaded_s:.1f} encode_s={time.perf_counter() - encoded:.1f} chunks={len(texts)}",
        file=sys.stderr,
        flush=True,
    )
    return matrix


def _apply_metadata(video: Video, meta: dict) -> Video:
    published = (
        parse_date(meta.get("upload_date"))
        or parse_date(meta.get("timestamp"))
        or video.published
    )
    title = video.title
    if isinstance(meta.get("title"), str) and meta.get("title"):
        title = meta["title"]
    duration = meta.get("duration")
    duration_s = video.duration_s
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
        duration_s = float(duration)
    return replace(video, title=title, published=published, duration_s=duration_s)


REPO_ROOT = Path(__file__).resolve().parents[3]
# A video id becomes a file name; keep it to one path segment.
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _flag_end(piece_words: list[Word], start_s: float, end_s: float, token: str, items) -> float | None:
    """End of the last ``[name]`` word in the chunk or review flag overlapping it."""
    ends = [w.end for w in piece_words if token in w.text]
    ends += [item["end"] for item in items if item["start"] < end_s and item["end"] > start_s]
    return max(ends) if ends else None


@dataclass
class Plan:
    """One sermon after redaction and exclusions. ``items`` and ``rows`` hold real words: keep private."""

    records: list[dict]
    items: list
    stretches: list
    rows: list[dict]  # every sermon word (redacted) as preached.exclusions.word_rows
    excluded: set[int]
    meta: dict  # what a rebuild at approval needs


def youtube_records(meta: dict, runs: list[list[dict]], items, token: str, policy: str = "none", *, count: int) -> list[dict]:
    """Chunk each kept run on its own; ``word_start``/``word_end`` index the sermon's words.

    ``runs`` are consecutive kept words (``{"i", "s", "e", "t"}``), so a chunk
    never spans an excluded stretch; ``count`` is the sermon's word count. The
    chunks on either side of a stretch are flagged (``boundary_flags``). Also
    used to rebuild at approval.
    """
    config = load_chunk_config()
    records = []
    for run, (head, tail) in zip(runs, boundary_flags(runs, count)):
        run_words = [Word(w["s"], w["e"], w["t"]) for w in run]
        offset = run[0]["i"]
        pieces = chunk_words(run_words, config)
        for number, piece in enumerate(pieces):
            local = run_words[piece["word_start"] : piece["word_end"]]
            flag_end = merge_flag(
                _flag_end(local, piece["start_s"], piece["end_s"], token, items),
                head if number == 0 else None,
                tail if number == len(pieces) - 1 else None,
            )
            records.append(
                {
                    **piece,
                    "word_start": piece["word_start"] + offset,
                    "word_end": piece["word_end"] + offset,
                    "chunk_id": f"{meta['video_id']}-c{len(records):04d}",
                    "audio_url": watch_url(
                        meta["video_id"],
                        piece["start_s"],
                        duration_s=meta.get("duration_s"),
                        end_s=piece["end_s"],
                        flag_end_s=flag_end,
                        policy=policy,
                    ),
                    "flag_end_s": flag_end,
                    "source_url": meta.get("source_url"),
                }
            )
    return records


def _plan(
    video: Video,
    words: list[Word],
    windows: dict[str, tuple[float, float]],
    config: Config | None = None,
    policy: str = "none",
    previous: tuple[list[dict], int | None] = ([], None),
) -> Plan:
    """Redact the sermon window, drop the stretches ``preached.skip`` proposes, chunk the rest.

    ``previous`` is the old review file's ``exclude`` lines and word count
    (``exclusions.previous_excludes``): on ``--redo`` they stay excluded.
    """
    config = default_config() if config is None else config
    override = windows.get(video.id)
    runs = speech_runs(words)
    if override is None and runs and all(is_sung(run) for run in runs):
        print(
            f"sermon {video.id}: every speech run looks like singing; indexing the longest",
            file=sys.stderr,
            flush=True,
        )
    start_s, end_s = sermon_span(words, override)
    span = words_in_span(words, start_s, end_s)
    sermon_words = privacy.redact(span, config=config, source=video.id)
    if not sermon_words:
        raise RuntimeError(f"no words in the sermon window {start_s:.1f}-{end_s:.1f}")
    stretches = propose([w.text for w in sermon_words])
    rows = word_rows([w.text for w in sermon_words], [w.start for w in sermon_words], [w.end for w in sermon_words])
    stretches += carried_stretches(*previous, rows, excluded_indexes(stretches))
    excluded = excluded_indexes(stretches)
    kept = [r for r in rows if r["i"] not in excluded]
    # Names inside an excluded stretch are not indexed, so they need no review line.
    items = [
        item
        for item in review(apply_drops(span, config, video.id), config=config)
        if any(r["s"] < item["end"] and r["e"] > item["start"] for r in kept)
    ]
    meta = {"video_id": video.id, "duration_s": video.duration_s, "source_url": video.watch_url()}
    kept_by_run = [[rows[i] for i in run] for run in kept_runs([r["i"] for r in kept])]
    records = youtube_records(meta, kept_by_run, items, config.token, policy, count=len(rows))
    if not records:
        raise RuntimeError("nothing left to index after the excluded stretches")
    return Plan(records, ReviewList(items), stretches, rows, excluded, meta)


def _chunks_for(
    video: Video,
    words: list[Word],
    windows: dict[str, tuple[float, float]],
    config: Config | None = None,
    policy: str = "none",
) -> tuple[list[dict], list]:
    """Return the chunk records and the sermon's ``review()`` items (real names: keep private)."""
    plan = _plan(video, words, windows, config, policy)
    return plan.records, plan.items


def metadata_review_lines(title: str | None, description: str | None, original_title: str | None, original_description: str | None, config: Config) -> list[dict]:
    """The review file's first lines: each stored field and its ``review()`` items.

    ``stored`` is exactly what is stored, embedded and shown (the redacted
    title); a description is never stored, so its line shows the redacted
    text it would have had. ``review`` items hold the original words.
    Covered by the review file's sha256, so approval covers them.
    """
    return [
        {
            "field": "title",
            "stored": title,
            "review": [dict(item) for item in review_metadata(original_title, config=config)],
        },
        {
            "field": "description",
            "stored": None,
            "redacted": description,
            "review": [dict(item) for item in review_metadata(original_description, config=config)],
        },
    ]


def write_private_review(items, path: Path) -> tuple[int, str]:
    """Write one sermon's review file (owner-only) and return ``(count, sha256)``.

    The items hold real names. Refuses a path inside this repository. Never
    resolves ``path``: a symlink planted there, or anywhere above it, must
    not redirect the write (``privacy.write_review_file_sha256``). The sha256
    is of the bytes written.
    """
    absolute = Path(os.path.abspath(path))
    repo = REPO_ROOT.resolve()
    for candidate in (absolute, Path(os.path.realpath(absolute.parent))):
        if candidate == repo or candidate.is_relative_to(repo) or candidate.is_relative_to(REPO_ROOT):
            raise RuntimeError("review files must not be written inside the repository")
    return write_review_file_sha256(items, absolute)


def acknowledge(index_path: Path, review_root: Path, video_ids: list[str], config: Config | None = None, embedder=None) -> int:
    """Record a human's approval for each id. Returns 0 when every id was approved.

    Approval excludes exactly the stretches the review file lists
    (``preached.exclusions.approve``). ``embedder`` is used only when the
    reviewer widened or added one and the chunks are rebuilt.

    ``config`` is the privacy config in effect now (``--privacy`` or
    ``PREACHED_PRIVACY``); it must hash the same as the one the import used.
    """
    config = default_config() if config is None else config
    privacy_sha = config_sha256(config)
    connection = open_library(index_path)
    failures = 0
    try:
        for video_id in video_ids:
            if not SAFE_ID.fullmatch(video_id):
                print(f"not a video id: {video_id[:20]!r}", file=sys.stderr)
                failures += 1
                continue
            try:
                approve(connection, video_id, review_root / f"{video_id}.review.jsonl", privacy_sha, token=config.token, embedder=embedder)
            except RuntimeError as exc:
                print(f"not approved: {exc}", file=sys.stderr)
                failures += 1
            else:
                print(f"approved {video_id}; a running server serves it from its next request", file=sys.stderr)
    finally:
        connection.close()
    return 1 if failures else 0


def privacy_config(settings: Settings) -> tuple[Config, str]:
    """``--privacy`` wins, then ``PREACHED_PRIVACY``; neither raises ``MissingConfig``.

    Also returns the flagged-audio policy, which is always ``none`` for a
    church library (Patrick's decision; see ``preached.audio_policy``).
    """
    config = required_config(settings.privacy_path)
    return config, resolve_flagged_audio(config.flagged_audio)


def run(
    settings: Settings,
    *,
    lister,
    transcriber,
    embedder=None,
    downloader,
    metadata,
    coverage=check_coverage,
) -> int:
    """Return 0 when every selected video was imported or skipped on purpose.

    A download, transcribe, or index error on one video returns 1 after the
    others have been attempted. A refused channel raises ``ChannelRefused``
    before any of those calls.
    """
    from preached.youtube.listing import assert_allowed

    assert_allowed(settings.channel_url)
    config, policy = privacy_config(settings)
    videos = [
        replace(video, title=redact_metadata(video.title, config=config)[0] or "")
        for video in lister(settings.channel_url)
    ]
    imported: set[str] = set()
    if not settings.redo and settings.index_path.is_file():
        connection = open_library(settings.index_path)
        try:
            imported = imported_ok(connection)
        finally:
            connection.close()
    pending = select_videos(videos, imported=imported, since=settings.since, limit=settings.limit)
    if settings.dry_run:
        sys.stdout.write(format_dry_run(pending))
        return 0

    windows = load_windows(settings.windows_path)
    embed = embedder or _embed_on_cpu
    connection = open_library(settings.index_path)
    failures = 0
    try:
        for video in pending:
            started = time.perf_counter()
            try:
                _import_one(
                    connection,
                    video,
                    settings=settings,
                    windows=windows,
                    transcriber=transcriber,
                    embedder=embed,
                    downloader=downloader,
                    metadata=metadata,
                    coverage=coverage,
                    started=started,
                    config=config,
                    policy=policy,
                )
            except Exception as exc:
                failures += 1
                print(f"fail {video.id} {exc}", file=sys.stderr, flush=True)
                if settings.redo:
                    print(
                        f"sermon {video.id} is now offline until re-reviewed (--redo failed, so it is marked error)",
                        file=sys.stderr,
                        flush=True,
                    )
                try:
                    mark_video(
                        connection,
                        video_id=video.id,
                        title=video.title,
                        published=video.published,
                        duration_s=video.duration_s,
                        license_text=None,
                        uploader=None,
                        status="error",
                        error=str(exc)[:500],
                    )
                    connection.commit()
                except Exception as mark_exc:
                    print(f"fail {video.id} could not record error: {mark_exc}", file=sys.stderr, flush=True)
                    connection.rollback()
    finally:
        connection.close()
    return 1 if failures else 0


def _import_one(
    connection,
    video: Video,
    *,
    settings: Settings,
    windows: dict[str, tuple[float, float]],
    transcriber,
    embedder,
    downloader,
    metadata,
    started: float,
    coverage=check_coverage,
    config: Config | None = None,
    policy: str = "none",
) -> None:
    config = default_config() if config is None else config
    meta = metadata(video) if metadata is not None else {}
    if not isinstance(meta, dict):
        raise RuntimeError("metadata was not an object")
    original_title = meta["title"] if isinstance(meta.get("title"), str) and meta.get("title") else None
    original_description = meta.get("description") if isinstance(meta.get("description"), str) else None
    video = _apply_metadata(video, meta)
    # Titles (and descriptions, which are never stored) are redacted before they
    # are stored, embedded or shown. Both go into the review file below.
    title, description = redact_metadata(video.title, original_description, config=config)
    video = replace(video, title=title or "")
    if settings.since is not None and video.published is not None and video.published < settings.since:
        print(f"skip {video.id} published {video.published.isoformat()} before {settings.since.isoformat()}", file=sys.stderr)
        return
    license_text = meta.get("license") if isinstance(meta.get("license"), str) else None
    if settings.require_cc and not creative_commons(license_text):
        shown = license_text or "missing"
        mark_video(
            connection,
            video_id=video.id,
            title=video.title,
            published=video.published,
            duration_s=video.duration_s,
            license_text=license_text,
            uploader=meta.get("uploader") if isinstance(meta.get("uploader"), str) else None,
            status="skipped",
            error=f"license is not Creative Commons ({shown})",
        )
        connection.commit()
        print(f"skip {video.id} license is not Creative Commons ({shown})", file=sys.stderr, flush=True)
        return

    download_started = time.perf_counter()
    audio_path = downloader(video, settings.audio_dir)
    download_s = time.perf_counter() - download_started
    transcribe_started = time.perf_counter()
    words = list(transcriber(audio_path))
    transcribe_s = time.perf_counter() - transcribe_started
    if not words:
        raise RuntimeError("transcript was empty")
    # Sound with no word in it is a stretch the ASR dropped: approval refuses while it is open.
    gaps = clip_to_window(coverage(audio_path, words, duration_s=video.duration_s), windows.get(video.id))
    for gap in gaps:
        print(f"coverage {video.id}: no transcript for sound at {gap.start_s:.1f}-{gap.end_s:.1f}s", file=sys.stderr, flush=True)
    if not SAFE_ID.fullmatch(video.id):
        raise RuntimeError("video id is not usable as a file name")
    review_file = settings.review_root() / f"{video.id}.review.jsonl"
    plan = _plan(video, words, windows, config, policy, previous_excludes(review_file))
    records, items = plan.records, plan.items
    flagged = sum(1 for record in records if record["flag_end_s"] is not None)
    header = metadata_review_lines(video.title, description, original_title or video.title, original_description, config)
    header.extend({"field": "coverage", "gap_start_s": gap.start_s, "gap_end_s": gap.end_s} for gap in gaps)
    # The kept words (already redacted) let approval rebuild the chunks when the
    # reviewer widens or adds an excluded stretch; excluded words are not in it.
    _, words_sha = write_private_review(words_file_lines("youtube", plan.meta, plan.rows, plan.excluded), words_file(review_file))
    lines = [*header, *review_lines(plan.stretches, plan.rows, words_sha), *items]
    _, review_sha = write_private_review(lines, review_file)
    titles = [video.title for _ in records]
    texts = [record["text"] for record in records]
    index_started = time.perf_counter()
    matrix = np.asarray(embedder(titles, texts), dtype=np.float32)
    uploader = meta.get("uploader") if isinstance(meta.get("uploader"), str) else None
    index_video(
        connection,
        video_id=video.id,
        title=video.title,
        published=video.published,
        duration_s=video.duration_s,
        license_text=license_text,
        uploader=uploader,
        chunks=records,
        matrix=matrix,
        review_sha256=review_sha,
        privacy_sha256=config_sha256(config),
        coverage_gaps=[(gap.start_s, gap.end_s) for gap in gaps],
        review_base_sha256=base_sha256(lines),
    )
    index_s = time.perf_counter() - index_started
    if not settings.keep_audio:
        _discard_audio(audio_path, settings.audio_dir)
    audio_s = video.duration_s or (words[-1].end - words[0].start)
    print(
        "TIMING "
        f"video_id={video.id} download_s={download_s:.1f} transcribe_s={transcribe_s:.1f} "
        f"index_s={index_s:.1f} audio_s={audio_s:.1f} chunks={len(records)} "
        f"license={license_text or ''} uploader={uploader or ''} title={video.title}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"imported {video.id} in {time.perf_counter() - started:.1f}s; UNPUBLISHED until its review file is "
        f"acknowledged ({len(items)} review items, {flagged} flagged chunks, "
        f"{len(plan.stretches)} excluded stretches of {len(plan.excluded)} words, {len(gaps)} coverage gaps"
        f"{': approval is blocked' if gaps else ''})",
        file=sys.stderr,
        flush=True,
    )


def _discard_audio(path: Path, audio_dir: Path) -> None:
    """Delete the working file the downloader returned.

    The name is removed only when it lives inside ``audio_dir`` and the
    resolved file does too. A ``..`` path or a symlink that leaves the
    directory is left alone. A delete error does not undo the committed index.
    """
    try:
        audio = Path(path)
        root = Path(audio_dir).resolve()
        parent = audio.parent.resolve()
        resolved = audio.resolve()
    except (OSError, TypeError, ValueError) as exc:
        print(f"keep audio {path}: {exc}", file=sys.stderr, flush=True)
        return
    parent_inside = parent == root or parent.is_relative_to(root)
    if not parent_inside or resolved == root or not resolved.is_relative_to(root):
        return
    if not audio.is_file():
        return
    try:
        audio.unlink(missing_ok=True)
    except OSError as exc:
        print(f"keep audio {audio}: {exc}", file=sys.stderr, flush=True)
