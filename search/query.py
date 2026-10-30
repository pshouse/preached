"""Search Wesley's sermons and print his words, not a paraphrase.

Examples:
  uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
  uv run search/query.py "Romans 8:16" --mode bm25 -k 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preached import env  # noqa: F401, E402
from preached.embed import encode_query, load_model, unload  # noqa: E402
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import CHUNKS_JSONL, INDEX_PATH  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.store import chunk_count, connect, replace_chunks  # noqa: E402


def ensure_chunks(connection) -> None:
    from preached.corpus import read_jsonl

    if not CHUNKS_JSONL.exists():
        raise SystemExit(
            f"missing {CHUNKS_JSONL}. Run: uv run corpus/fetch_wesley.py && uv run corpus/chunk_sermons.py"
        )
    have = chunk_count(connection)
    chunks = read_jsonl(CHUNKS_JSONL)
    if have != len(chunks):
        replace_chunks(connection, chunks)


def fmt_time(value) -> str:
    if value is None:
        return "null"
    return f"{float(value):.1f}"


def print_hits(query: str, mode: str, model: str | None, hits) -> None:
    print(f"query: {query}")
    print(f"mode: {mode}" + (f"  model: {model}" if model else ""))
    if not hits:
        print("Nothing strong found in the indexed sermons.")
        return
    for rank, hit in enumerate(hits, start=1):
        print(
            f"\n[{rank}] score={hit.score:.4f}  {hit.sermon_title}\n"
            f"    {hit.chunk_id}  sermon={hit.sermon_id}  "
            f"start_s={fmt_time(hit.start_s)}  end_s={fmt_time(hit.end_s)}\n"
            f"    {hit.source_url or ''}\n"
            f"    {hit.text}"
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
    parser.add_argument("--device", default="cpu", help="device for the query embedding")
    args = parser.parse_args()

    connection = connect(args.index)
    ensure_chunks(connection)
    model_name = None
    loaded = None
    vector = None
    try:
        if args.mode == "bm25":
            hits = Searcher(connection).bm25(args.query, args.k)
        else:
            model_name = args.model
            spec = MODELS[model_name]
            loaded = load_model(spec, device=args.device, batch_size=1)
            vector = encode_query(loaded, args.query)
            searcher = Searcher(connection, model=model_name)
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
    print_hits(args.query, args.mode if args.fusion == "rrf" or args.mode != "hybrid" else f"hybrid-{args.fusion}", model_name, hits)


if __name__ == "__main__":
    main()
