"""CLI for ``uv run --extra youtube import/youtube.py``."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from preached.libraries import PUBLIC_DOMAIN
from preached.paths import CACHE_ROOT, INDEX_DIR
from preached.privacy import required_config
from preached.youtube.fetch import download_audio, fetch_metadata, list_channel
from preached.youtube.listing import SLUG, BadChannelUrl, ChannelRefused, assert_youtube_url
from preached.youtube.pipeline import Settings, acknowledge, privacy_config, run
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
    parser.add_argument("channel_url", nargs="?", help="Channel, playlist, or single watch URL")
    parser.add_argument(
        "--library",
        required=True,
        help="Church library slug. The index is /cache/index/<slug>.sqlite. Not wesley and not a public-domain "
        f"library ({', '.join(PUBLIC_DOMAIN)}): those are never redacted or gated.",
    )
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
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep the downloaded audio after a successful import. By default that file is deleted. A failed video always keeps its file.",
    )
    parser.add_argument(
        "--privacy",
        type=Path,
        default=None,
        help="Privacy TOML (see privacy.example.toml). Defaults to $PREACHED_PRIVACY. Required: with neither, "
        "nothing is listed, downloaded or approved. Names are always redacted.",
    )
    parser.add_argument(
        "--ack-review",
        action="append",
        default=None,
        metavar="VIDEO_ID",
        help="Approve a sermon after reading <index dir>/<library>/review/<id>.review.jsonl and skimming its transcript. "
        "Repeat per video. Run without a channel URL, under the same --privacy (or $PREACHED_PRIVACY) as the import. "
        "Imports are unpublished until approved. The review file is read once, at approval.",
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
    if args.library in PUBLIC_DOMAIN:
        # Those files are served without the publish gate, so church audio must never land in one.
        print(f"library {args.library} is a public-domain classic (search/build_library.py); choose another slug", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("limit must be at least 1", file=sys.stderr)
        return 2
    index_root = index_dir or INDEX_DIR
    if args.ack_review:
        if args.channel_url:
            print("--ack-review runs on its own: omit the channel URL", file=sys.stderr)
            return 2
        try:
            config = required_config(args.privacy)
        except (OSError, ValueError) as exc:
            print(f"privacy: {exc.__class__.__name__}: {exc}", file=sys.stderr)
            return 2
        return acknowledge(index_root / f"{args.library}.sqlite", index_root / args.library / "review", args.ack_review, config)
    if not args.channel_url:
        print("channel_url is required unless --ack-review is given", file=sys.stderr)
        return 2
    try:
        assert_youtube_url(args.channel_url)
    except BadChannelUrl as exc:
        print(str(exc), file=sys.stderr)
        return 2
    audio_base = audio_root or (CACHE_ROOT / "youtube")
    settings = Settings(
        channel_url=args.channel_url,
        library=args.library,
        limit=args.limit,
        since=args.since,
        dry_run=args.dry_run,
        require_cc=args.require_cc,
        redo=args.redo,
        keep_audio=args.keep_audio,
        index_path=index_root / f"{args.library}.sqlite",
        audio_dir=audio_base / args.library,
        windows_path=args.windows,
        privacy_path=args.privacy,
        review_dir=index_root / args.library / "review",
    )
    try:
        privacy_config(settings)
    except (OSError, ValueError) as exc:
        print(f"privacy: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 2
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
