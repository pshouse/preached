"""Search Wesley's sermons and print his words, not a paraphrase.

Examples:
  uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
  uv run search/query.py "Romans 8:16" --mode bm25 -k 5
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

from preached import env  # noqa: F401, E402
from preached.backends import DEFAULT_EMBED_BACKEND, load_embedder  # noqa: E402
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import INDEX_PATH  # noqa: E402
from preached.search import PREROLL_S, Searcher, play_start  # noqa: E402
from preached.store import EmbeddingMismatch, check_query_variant, open_readonly  # noqa: E402
from manifest import UnsafeRow, check_audio_url  # noqa: E402

# C0 (incl. ESC, newline), DEL and C1 controls: none belong in one terminal line.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
UNSAFE_URL = "n/a (unsafe URL hidden)"


def clean(value: object) -> str:
    """Printable text for the terminal: control characters become one space."""
    return CONTROL_RE.sub(" ", str(value))


def fmt_time(value) -> str:
    """h:mm:ss, the same as the page's formatTime (whole seconds, floored)."""
    if value is None:
        return "n/a"
    total = int(float(value))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def play_url(audio_url, start_s) -> str:
    """The URL the page's player builds: the audio URL with #t=<seek>, where
    seek = max(0, start_s - PREROLL_S). start_s itself stays exact."""
    if not audio_url:
        return "n/a"
    try:
        # Same rule as the manifest: https on archive.org, no credentials.
        check_audio_url(audio_url)
    except UnsafeRow:
        return UNSAFE_URL
    audio_url = clean(audio_url)
    seek = play_start(start_s)
    if seek is None:
        return audio_url
    return f"{audio_url.split('#')[0]}#t={seek:g}"


def print_hits(query: str, mode: str, model: str | None, hits) -> None:
    print(f"query: {query}")
    print(f"mode: {mode}" + (f"  model: {model}" if model else ""))
    if not hits:
        print("Nothing strong found in the indexed sermons.")
        return
    for rank, hit in enumerate(hits, start=1):
        print(
            f"\n[{rank}] {clean(hit.sermon_title)}  (score {hit.score:.4f}, {clean(hit.chunk_id)})\n"
            f"    at {fmt_time(hit.start_s)} (start_s={hit.start_s})  read by {clean(hit.reader or 'n/a')}\n"
            f"    play: {play_url(hit.audio_url, hit.start_s)}  ({PREROLL_S:g} s pre-roll)\n"
            f"    text: {clean(hit.source_url or '')}\n"
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
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--device", default="cpu", help="device for the torch query embedding")
    parser.add_argument(
        "--embed-backend",
        choices=("onnx", "torch"),
        default=None,
        help=f"query embedder (default {DEFAULT_EMBED_BACKEND}, or PREACHED_EMBED_BACKEND)",
    )
    parser.add_argument("--onnx-variant", choices=("fp32", "int8"), default=None)
    parser.add_argument("--ort-threads", type=int, default=None, help="ONNX Runtime intra-op threads")
    args = parser.parse_args()

    # Read-only, and it does not sync. A text-only chunks.jsonl matches the
    # aligned index on ids and text; syncing it would null every start_s,
    # end_s, audio_url, and reader.
    try:
        connection = open_readonly(args.index)
    except FileNotFoundError as exc:
        raise SystemExit(f"error: {exc}") from exc
    model_name = None
    embedder = None
    vector = None
    try:
        if args.mode == "bm25":
            hits = Searcher(connection).bm25(args.query, args.k)
        else:
            model_name = args.model
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            embedder = load_embedder(
                model_name,
                args.embed_backend,
                variant=args.onnx_variant,
                ort_threads=args.ort_threads,
                device=args.device,
                batch_size=1,
            )
            check_query_variant(connection, model_name, getattr(embedder, "variant", None))
            vector = embedder.encode_queries([args.query])[0]
            try:
                searcher = Searcher(connection, model=model_name)
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
        if embedder is not None and hasattr(embedder, "close"):
            embedder.close()
    print_hits(args.query, args.mode if args.fusion == "rrf" or args.mode != "hybrid" else f"hybrid-{args.fusion}", model_name, hits)


if __name__ == "__main__":
    main()
