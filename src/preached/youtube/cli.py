"""CLI for ``uv run import/youtube.py``."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from preached.paths import CACHE_ROOT, INDEX_DIR
from preached.youtube.fetch import download_audio, fetch_metadata, list_channel
from preached.youtube.listing import SLUG, BadChannelUrl, ChannelRefused, assert_youtube_url
from preached.youtube.pipeline import Settings, run
from preached.youtube.transcribe import transcribe


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("since must be YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a YouTube channel into a Preached library. Audio stays on YouTube; the index stores excerpts and timestamps.",
    )
    parser.add_argument("channel_url", help="Channel, playlist, or single watch URL")
    parser.add_argument("--library", required=True, help="Library slug. The index is /cache/index/<slug>.sqlite")
    parser.add_argument("--limit", type=int, default=None, help="Import at most N videos after filters")
    parser.add_argument("--since", type=_date, default=None, help="Keep videos published on or after YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="List id, title, date, and duration. Write nothing.")
    parser.add_argument(
        "--windows",
        type=Path,
        default=None,
        help="TOML file of per-video start_s/end_s overrides. See import/sermon_windows.example.toml",
    )
    parser.add_argument(
        "--require-cc",
        action="store_true",
        help="Skip a video unless yt-dlp's license field names Creative Commons. For the public test run.",
    )
    parser.add_argument(
        "--redo",
        action="store_true",
        help="Import again even when the video id is already marked ok.",
    )
    return parser


def main(argv: list[str] | None = None, *, lister=None, transcriber=None, embedder=None, downloader=None, metadata=None, index_dir: Path | None = None, audio_root: Path | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not SLUG.fullmatch(args.library):
        print("library must be a short slug: lowercase letters, digits, and hyphens", file=sys.stderr)
        return 2
    if args.library == "wesley":
        print("library wesley is the built-in text index; choose another slug", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("limit must be at least 1", file=sys.stderr)
        return 2
    try:
        assert_youtube_url(args.channel_url)
    except BadChannelUrl as exc:
        print(str(exc), file=sys.stderr)
        return 2
    index_root = index_dir or INDEX_DIR
    audio_base = audio_root or (CACHE_ROOT / "youtube")
    settings = Settings(
        channel_url=args.channel_url,
        library=args.library,
        limit=args.limit,
        since=args.since,
        dry_run=args.dry_run,
        require_cc=args.require_cc,
        redo=args.redo,
        index_path=index_root / f"{args.library}.sqlite",
        audio_dir=audio_base / args.library,
        windows_path=args.windows,
    )
    try:
        return run(
            settings,
            lister=lister or list_channel,
            transcriber=transcriber or transcribe,
            embedder=embedder,
            downloader=downloader or download_audio,
            metadata=metadata or fetch_metadata,
        )
    except (ChannelRefused, BadChannelUrl) as exc:
        print(str(exc), file=sys.stderr)
        return 2
