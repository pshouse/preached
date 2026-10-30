"""Search Wesley's sermons and print his words, not a paraphrase.

Examples:
  uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
  uv run search/query.py "Romans 8:16" --mode bm25 -k 5
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

from preached import env  # noqa: F401, E402
from preached.abstain import compute_signals, decide, floor_for  # noqa: E402
from preached.audio_policy import public_times, resolve_flagged_audio  # noqa: E402
from preached.privacy import default_config  # noqa: E402
from preached.embed import encode_query, load_model, unload  # noqa: E402
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import INDEX_DIR, INDEX_PATH, StaleChunks, index_chunks_jsonl  # noqa: E402
from preached.search import PREROLL_S, Searcher, play_start, touches_flagged  # noqa: E402
from preached.store import EmbeddingMismatch, connect, open_readonly, sync_chunks  # noqa: E402
from preached.youtube.listing import chunk_video_id, policy_watch_url, youtube_watch_url  # noqa: E402
from manifest import check_audio_url  # noqa: E402

# C0 (incl. ESC, newline), DEL and C1 controls: none belong in one terminal line.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
UNSAFE_URL = "n/a (unsafe URL hidden)"


def clean(value: object) -> str:
    """Printable text for the terminal: control characters become one space."""
    return CONTROL_RE.sub(" ", str(value))


def is_library_file(path: Path) -> bool:
    """A per-library index (YouTube import or build_library.py), not Wesley's.

    Both writers create a ``videos`` table; build_library.py also records
    ``library`` in meta. Read-only, so checking never changes the file.
    """
    if not path.is_file():
        return False
    connection = open_readonly(path)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "videos" in tables:
            return True
        return "meta" in tables and connection.execute(
            "SELECT 1 FROM meta WHERE key = 'library'"
        ).fetchone() is not None
    finally:
        connection.close()


def open_index(index: Path | None, library: str | None):
    """Connect to the index to search. Only the Wesley index file gets the chunk sync.

    --library opens /cache/index/<slug>.sqlite as built. --index must not be a
    library file: the Wesley sync would replace its chunks and drop its
    vectors. Any other --index path is searched as it is.
    """
    if library is not None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", library) or not (INDEX_DIR / f"{library}.sqlite").is_file():
            raise SystemExit(f"error: no library {library!r} under {INDEX_DIR}")
        return connect(INDEX_DIR / f"{library}.sqlite")
    path = index if index is not None else INDEX_PATH
    if is_library_file(path):
        raise SystemExit(
            f"error: {path} is a library index, not the Wesley index. "
            f"Search it with --library {path.stem} (it is never synced with Wesley chunks)."
        )
    connection = connect(path)
    if path.resolve() == INDEX_PATH.resolve():
        ensure_chunks(connection)
    return connection


def ensure_chunks(connection) -> None:
    try:
        chunks_path = index_chunks_jsonl()
    except StaleChunks as exc:
        raise SystemExit(f"error: {exc}") from exc
    if not chunks_path.exists():
        raise SystemExit(
            f"missing {chunks_path}. Run: uv run corpus/fetch_wesley.py && uv run corpus/chunk_sermons.py"
        )
    sync_chunks(connection, chunks_path)


def fmt_time(value) -> str:
    """h:mm:ss, the same as the page's formatTime (whole seconds, floored)."""
    if value is None:
        return "n/a"
    total = int(float(value))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


WITHHELD = "n/a (audio withheld: this passage has a redacted name)"


def play_url(audio_url, start_s) -> str:
    """Where to play this hit.

    A validated YouTube watch URL is rebuilt as
    ``https://www.youtube.com/watch?v=<id>`` plus ``&t=<int>s`` when that
    seek is one whole number of seconds. Extra parameters are not printed.
    Nothing here adds ``#t=``. An archive.org URL still gets ``#t=<seek>``
    where seek is max(0, start_s - PREROLL_S). Anything else is hidden,
    including a URL whose parser raises. Control characters are stripped
    after a URL passes validation.
    """
    if not audio_url:
        return "n/a"
    youtube = youtube_watch_url(audio_url)
    if youtube is not None:
        return clean(youtube)
    try:
        # Same rule as the manifest: https on archive.org, no credentials,
        # no control characters. Every refusal is UnsafeRow, a ValueError
        # (check_audio_url also wraps urlsplit's own ValueError).
        check_audio_url(audio_url)
    except ValueError:
        return UNSAFE_URL
    audio_url = clean(audio_url)
    seek = play_start(start_s)
    if seek is None:
        return audio_url
    return f"{audio_url.split('#')[0]}#t={seek:g}"


def hit_play(hit, policy: str, near_flag: bool = False) -> str:
    """The play line for a hit. A chunk with ``[name]`` or a review flag follows the flagged-audio policy.

    A flagged YouTube chunk gets a link rebuilt from validated parts (the
    stored one may point at the name): ``t=`` is the shifted start under
    ``shifted``. If it cannot be rebuilt, audio is withheld. ``near_flag``
    (``search.touches_flagged``) withholds audio under ``none``, as the API does.
    """
    flag_end_s = getattr(hit, "flag_end_s", None)
    if near_flag and policy == "none":
        return WITHHELD
    _, _, play_from, allowed = public_times(hit.start_s, getattr(hit, "end_s", None), flag_end_s, policy)
    if not allowed:
        return WITHHELD
    if flag_end_s is not None:
        source_url = getattr(hit, "source_url", None)
        vid = chunk_video_id(getattr(hit, "video_id", None), hit.audio_url, source_url)
        if vid is not None or youtube_like(hit.audio_url) or youtube_like(source_url):
            url = policy_watch_url(vid, hit.start_s, getattr(hit, "end_s", None), flag_end_s, policy)
            if url is None:
                return WITHHELD
            note = "starts after the redacted name" if play_from is not None else f"{PREROLL_S:g} s pre-roll"
            return f"{clean(url)}  ({note})"
    if play_from is not None:
        return f"{play_url(hit.audio_url, play_from + PREROLL_S)}  (starts after the redacted name)"
    return f"{play_url(hit.audio_url, hit.start_s)}  ({PREROLL_S:g} s pre-roll)"


def youtube_like(url) -> bool:
    """Any string naming a YouTube host, valid or not (fail closed)."""
    return isinstance(url, str) and ("youtube" in url.lower() or "youtu.be" in url.lower())


def hit_text_link(hit, policy: str, near_flag: bool = False) -> str:
    """The text line. A flagged passage's YouTube source link is a watch link, so it is hidden unless the policy is play."""
    source_url = getattr(hit, "source_url", None)
    flagged = near_flag or getattr(hit, "flag_end_s", None) is not None
    if youtube_like(source_url) and flagged and policy != "play":
        # A watch link from 0:00 would play the name (same rule as the API).
        return "n/a"
    return clean(source_url or "")


def print_hits(query: str, mode: str, model: str | None, hits, policy: str = "none", connection=None) -> None:
    """``connection`` (the index) lets a card that touches a flagged chunk be withheld under ``none``."""
    print(f"query: {query}")
    print(f"mode: {mode}" + (f"  model: {model}" if model else ""))
    if not hits:
        print("Nothing found in the indexed sermons.")
        return
    for rank, hit in enumerate(hits, start=1):
        # A flagged chunk under none/shifted shows no exact chunk start (see audio_policy.public_times).
        start_s, _, _, _ = public_times(hit.start_s, getattr(hit, "end_s", None), getattr(hit, "flag_end_s", None), policy)
        near = connection is not None and policy == "none" and touches_flagged(connection, hit)
        if near:
            start_s = None
        print(
            f"\n[{rank}] {clean(hit.sermon_title)}  (score {hit.score:.4f}, {clean(hit.chunk_id)})\n"
            f"    at {fmt_time(start_s)} (start_s={start_s})  read by {clean(hit.reader or 'n/a')}\n"
            f"    play: {hit_play(hit, policy, near)}\n"
            f"    text: {hit_text_link(hit, policy, near)}\n"
            f"    \"{clean(hit.text)}\""
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Wesley's sermons.")
    parser.add_argument("query")
    parser.add_argument("--mode", choices=("bm25", "dense", "hybrid"), default="hybrid")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument("--fusion", choices=("rrf", "weighted"), default="rrf")
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-weight", type=float, default=0.5)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--index", type=Path, default=None,
                        help=f"SQLite index (default {INDEX_PATH}, synced with the Wesley chunks; "
                        "any other path is searched as it is; library files are refused)")
    target.add_argument("--library", help="search /cache/index/<slug>.sqlite (e.g. spurgeon, edwards); "
                        "built by search/build_library.py, so no Wesley chunk sync")
    parser.add_argument("--device", default="cpu", help="device for the query embedding")
    parser.add_argument("--hide-low-confidence", action="store_true",
                        help="hide the passages when the (heuristic) abstain rule rates them low confidence")
    args = parser.parse_args()
    try:
        # Always none (Patrick's decision); a stale shifted/play setting stops here.
        policy = resolve_flagged_audio(default_config().flagged_audio)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"error: {exc}") from exc

    connection = open_index(args.index, args.library)
    # Same gate as the server: any --library but wesley is gated unless it is an
    # allow-listed public-domain library's own file (store.public_domain_file).
    gate = {"gated": args.library not in (None, "wesley"), "library": args.library}
    model_name = None
    loaded = None
    vector = None
    try:
        if args.mode == "bm25":
            searcher = Searcher(connection, **gate)
            hits = searcher.bm25(args.query, args.k)
        else:
            model_name = args.model
            spec = MODELS[model_name]
            loaded = load_model(spec, device=args.device, batch_size=1)
            vector = encode_query(loaded, args.query)
            try:
                searcher = Searcher(connection, model=model_name, **gate)
            except EmbeddingMismatch as exc:
                raise SystemExit(f"error: {exc}\nOr search without vectors: --mode bm25") from exc
            if args.mode == "dense":
                hits = searcher.dense(vector, args.k)
            else:
                hits = searcher.hybrid(
                    args.query,
                    vector,
                    args.k,
                    fusion=args.fusion,
                    rrf_k=args.rrf_k,
                    dense_weight=args.dense_weight,
                )
    finally:
        if loaded is not None:
            unload(loaded)
    # Same abstain rule and per-model floor as GET /api/search (preached.abstain).
    floor = floor_for(model_name) if vector is not None else None
    confidence = decide(compute_signals(searcher, args.query, vector, hits), floor, has_results=bool(hits))
    mode_label = args.mode if args.fusion == "rrf" or args.mode != "hybrid" else f"hybrid-{args.fusion}"
    if confidence.abstain and hits and args.hide_low_confidence:
        print_hits(args.query, mode_label, model_name, [], policy)
        print(f"({len(hits)} low-confidence passages hidden by --hide-low-confidence.)")
        return
    print_hits(args.query, mode_label, model_name, hits, policy, connection)
    if confidence.note and hits:
        print(f"\nnote: {confidence.note}")


if __name__ == "__main__":
    main()
