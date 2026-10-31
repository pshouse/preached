"""Scratch: Granite R2 query-prefix probe, dense only, document vectors unchanged (card says no prefix).
Usage (from the worktree root): uv run --group bench python reports/w3-retrieval-diag/prefixes.py
Index path: $PREACHED_CACHE/index/wesley.sqlite (default /cache), via preached.paths, opened mode=ro&immutable=1 (scratch only)."""
import json, sys
from pathlib import Path
root = Path.cwd(); sys.path.insert(0, str(root / "src")); sys.path.insert(0, str(root / "search"))
from preached import env  # noqa
from preached.models import MODELS
from preached.embed import load_model, _encode
from preached.search import Searcher
from preached.paths import INDEX_PATH
from preached.rank import dense_scores
import bench, numpy as np


def open_immutable(path):
    """Scratch only: mode=ro&immutable=1 never touches -shm/-wal (the product's open_readonly does).
    Uses store.sqlite3, not its own import: tests/test_hard_conditions.py lists the files that import sqlite3."""
    from preached import store
    con = store.sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    con.row_factory = store.sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con

qs = [q for q in bench.load_questions() if q["relevant"]]
spec = MODELS["granite-english-r2"]; loaded = load_model(spec, device="cpu", batch_size=1)
s = Searcher(open_immutable(INDEX_PATH), model=spec.key)
P = {"none (card)": "", "query: ": "query: ", "arctic-style": "Represent this sentence for searching relevant passages: ",
     "question: ": "question: "}
for name, p in P.items():
    res = {}
    for q in qs:
        v = _encode(loaded, [p + q["query"]], "", 1)[0]
        sc = dense_scores(v, s._matrix); idx = np.argsort(-sc)[:50]
        hits = s._pack([(s._rowids[i], float(sc[i])) for i in idx], 50, None)
        res[q["id"]] = bench.score(hits[:10], q["relevant"], hits)
    line = []
    for g in ("plain", "plain-blind", "names-topic"):
        ids = [q["id"] for q in qs if q["group"] == g]
        line.append(f"{g}: hit@10_len {np.mean([res[i]['hit@10_lenient'] for i in ids]):.3f} ndcg_len {np.mean([res[i]['ndcg@10_lenient'] for i in ids]):.3f}")
    print(f"{name:14s}", " | ".join(line))
