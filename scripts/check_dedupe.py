"""Check dedupe_adjacent on real queries: overlaps, idempotence, card lengths.

For every eval question, the bench probes and a few extra queries, in each
API mode (bm25, dense, hybrid) and model, it runs the API path (top 100,
dedupe_adjacent, k=10) and counts:

- same-sermon result pairs whose word ranges overlap (words shown twice),
- lists that change when de-duped again (not idempotent),
- words per result, merged results, and the same for the drop-only rule
  (origin/main before W3-POLISH: every overlapping neighbour dropped).

Read-only on the index. Embeds queries on CPU like search/bench.py.
Usage: uv run --group bench scripts/check_dedupe.py
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "search"))

from preached import env  # noqa: F401, E402
from preached import search as search_module  # noqa: E402
from preached.corpus import read_jsonl  # noqa: E402
from preached.embed import encode_query, load_model, unload  # noqa: E402
from preached.models import MODELS  # noqa: E402
from preached.paths import INDEX_PATH, questions_path  # noqa: E402
from preached.search import SEARCH_POOL, Searcher, dedupe_adjacent, ranked  # noqa: E402

EXTRA = ("catholic spirit", "worry", "How do I stop worrying?", '"')
API_MODES = ("bm25", "dense", "hybrid")
K = 10


def overlapping_pairs(hits) -> int:
    pairs = 0
    for i, first in enumerate(hits):
        for second in hits[i + 1:]:
            if first.sermon_id != second.sermon_id or None in (first.word_start, second.word_start):
                continue
            if min(first.word_end, second.word_end) > max(first.word_start, second.word_start):
                pairs += 1
    return pairs


def drop_only(pool, k):
    """The pre-W3-POLISH rule: never merge, drop every overlapping neighbour."""
    with mock.patch.object(search_module, "merge_overlapping", return_value=None):
        return dedupe_adjacent(pool, k)


def lengths(lists) -> str:
    words = [len(hit.text.split()) for hits in lists for hit in hits]
    if not words:
        return "n/a"
    return f"median {statistics.median(words):g}, mean {statistics.mean(words):.0f}, max {max(words)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="*", default=["granite-english-r2", "embeddinggemma-2"])
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    args = parser.parse_args()

    from bench import PROBES

    queries = [q["query"] for q in read_jsonl(questions_path())] + list(PROBES) + list(EXTRA)
    connection = sqlite3.connect(f"file:{args.index}?mode=ro", uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    print(f"{len(queries)} queries, k={K}, pool={SEARCH_POOL}, index {args.index}")
    totals = {"lists": 0, "pair_lists": 0, "pairs": 0, "non_idempotent": 0}
    for key in args.models:
        searcher = Searcher(connection, model=key)
        loaded = load_model(MODELS[key], device="cpu", batch_size=1)
        try:
            vectors = {q: encode_query(loaded, q) for q in queries}
        finally:
            unload(loaded)
        for mode in API_MODES:
            if mode == "bm25" and key != args.models[0]:
                continue  # BM25 lists do not depend on the model
            label = "bm25" if mode == "bm25" else f"{key} {mode}"
            after, before = [], []
            pair_lists = pairs = non_idempotent = 0
            examples = []
            for q in queries:
                pool = ranked(searcher, q, vectors[q], mode, max(SEARCH_POOL, K))
                hits = dedupe_adjacent(pool, K)
                after.append(hits)
                before.append(drop_only(pool, K))
                found = overlapping_pairs(hits)
                if found:
                    pair_lists += 1
                    pairs += found
                    examples.append(q)
                if dedupe_adjacent(hits, K) != hits:
                    non_idempotent += 1
            merged = [hit for hits in after for hit in hits if len(hit.chunk_ids) > 1]
            print(
                f"{label}: {len(queries)} lists; overlapping same-sermon pairs {pairs} in {pair_lists} lists"
                f"{' (' + '; '.join(examples[:3]) + ')' if examples else ''}; non-idempotent {non_idempotent}; "
                f"merged {len(merged)}/{sum(map(len, after))} results, 3+ chunks "
                f"{sum(len(hit.chunk_ids) >= 3 for hit in merged)}; words/result drop-only {lengths(before)} "
                f"-> merge {lengths(after)}",
                flush=True,
            )
            totals["lists"] += len(queries)
            totals["pair_lists"] += pair_lists
            totals["pairs"] += pairs
            totals["non_idempotent"] += non_idempotent
    print(
        f"total: {totals['lists']} lists; overlapping pairs {totals['pairs']} in {totals['pair_lists']} lists; "
        f"non-idempotent {totals['non_idempotent']}"
    )


if __name__ == "__main__":
    main()
