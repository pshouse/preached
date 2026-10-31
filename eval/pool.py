"""Build the judging pool for wider grading (EVAL-GRADE).

For every answerable question in eval/questions.jsonl and every question in
eval/plain_candidates.jsonl (excluded items skipped), take the top POOL_K
chunks from BM25 and from every enabled model in search/models.toml in each
bench mode (dense, hybrid RRF, hybrid weighted), with the same query vectors
and search calls as search/bench.py. A `-plain` rewrite and its original are
one family and share one pool (the union of both), because they share labels.

Writes eval/pool/pool-YYYY-MM-DD.jsonl (chunk ids and ranks only; committed)
and, for the human or agent judging it, /cache/eval-pool/YYYY-MM-DD/<family>.md
with each pooled chunk's text, plus every chunk of the grade-2 sermon(s) for
the "own reading" pass. The pool section is shuffled and does not name the
ranker or the rank, so a grader cannot see which system returned a chunk.
Judging is done by reading; no model scores relevance.

  uv run --group bench eval/pool.py [--k 20] [--models ...] [--family ID ...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "search"))

import bench  # noqa: E402  (sets up src/ on sys.path)
from preached.corpus import read_jsonl  # noqa: E402
from preached.models import MODELS  # noqa: E402
from preached.paths import INDEX_PATH, questions_path  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.store import open_readonly  # noqa: E402

POOL_K = 20
CANDIDATES = ROOT / "eval" / "plain_candidates.jsonl"


def load_items() -> list[dict]:
    """Questions to pool: answerable eval items plus the blind candidates, with a family key."""
    items = []
    for q in read_jsonl(questions_path()):
        if q["relevant"] and not q.get("excluded"):
            items.append({"id": q["id"], "family": q.get("rewrite_of") or q["id"], "query": q["query"],
                          "group": q["group"], "relevant": q["relevant"]})
    if CANDIDATES.exists():
        ids = {i["id"] for i in items}
        for q in read_jsonl(CANDIDATES):
            if q["id"] not in ids and not q.get("excluded"):
                items.append({"id": q["id"], "family": q["id"], "query": q["question"],
                              "group": q.get("group", "plain-blind"), "relevant": []})
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int, default=POOL_K)
    parser.add_argument("--models", nargs="*", default=[k for k, s in MODELS.items() if s.enabled])
    parser.add_argument("--family", nargs="*", default=None,
                        help="re-pool only these families, replacing their records in the existing --out file")
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--texts", type=Path, default=None, help="default /cache/eval-pool/YYYY-MM-DD")
    args = parser.parse_args()
    today = dt.date.today().isoformat()
    out = args.out or ROOT / "eval" / "pool" / f"pool-{today}.jsonl"
    texts_dir = args.texts or Path("/cache/eval-pool") / today

    try:
        connection = open_readonly(args.index)
    except FileNotFoundError as error:
        sys.exit(f"pool.py: {error}. Build the index first (see reports/ for the ingest commands) or pass --index PATH.")
    items = load_items()
    if args.family:
        items = [i for i in items if i["family"] in args.family]
        if not items:
            sys.exit(f"pool.py: no questions in families {args.family}")
    rankers: dict[str, dict[str, list[str]]] = {i["id"]: {} for i in items}
    lexical = Searcher(connection)
    for item in items:
        rankers[item["id"]]["bm25"] = [h.chunk_id for h in lexical.bm25(item["query"], args.k)]
    for key in args.models:
        spec = MODELS[key]
        loaded = bench.load_model(spec, device="cpu", batch_size=1)
        try:
            searcher = Searcher(connection, model=key, allow_eval_only=True)
            for item in items:
                vector = bench.encode_query(loaded, item["query"])
                for mode in bench.MODES:
                    hits = _run_k(searcher, item["query"], vector, mode, args.k)
                    rankers[item["id"]][f"{key}:{mode}"] = [h.chunk_id for h in hits]
        finally:
            bench.unload(loaded)
        print(f"pooled {key}", flush=True)

    chunks = {r["chunk_id"]: dict(r) for r in connection.execute(
        "SELECT chunk_id, sermon_id, sermon_title, sermon_number, text FROM chunks ORDER BY rowid")}
    by_sermon: dict[str, list[str]] = {}
    for cid, row in chunks.items():
        by_sermon.setdefault(row["sermon_id"], []).append(cid)

    families: dict[str, list[dict]] = {}
    for item in items:
        families.setdefault(item["family"], []).append(item)
    out.parent.mkdir(parents=True, exist_ok=True)
    texts_dir.mkdir(parents=True, exist_ok=True)
    # --family: replace those records in place, keep every other line as it is.
    lines = out.read_text(encoding="utf-8").splitlines() if args.family and out.exists() else []
    position = {json.loads(line)["family"]: n for n, line in enumerate(lines)}
    for family, members in families.items():
        pooled: dict[str, list[str]] = {}
        for item in members:
            for ranker, ids in rankers[item["id"]].items():
                for rank, cid in enumerate(ids, start=1):
                    pooled.setdefault(cid, []).append(f"{item['id']}|{ranker}@{rank}")
        gold_sermons = sorted({p["sermon_id"] for p in members[0]["relevant"] if int(p["grade"]) == 2})
        record = {
            "family": family,
            "ids": [m["id"] for m in members],
            "queries": {m["id"]: m["query"] for m in members},
            "k": args.k,
            "models": args.models,
            "rankers": {m["id"]: rankers[m["id"]] for m in members},
            "pooled": sorted(pooled, key=lambda c: chunks[c]["sermon_number"] * 10000 + int(c.rsplit("c", 1)[1])),
            "gold_sermons": gold_sermons,
        }
        line = json.dumps(record, ensure_ascii=False)
        if family in position:
            lines[position[family]] = line
        else:
            lines.append(line)
        _write_texts(texts_dir / f"{family}.md", record, members, pooled, chunks, by_sermon)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(families)} families) and {texts_dir}")


def _run_k(searcher, query, vector, mode, k):
    """bench.run_mode's raw-ranker calls with limit k (each call's top 10 is bench's list)."""
    if mode == "dense":
        return searcher.dense(vector, k)
    if mode == "hybrid_rrf":
        return searcher.hybrid(query, vector, k, fusion="rrf", rrf_k=60)
    if mode == "hybrid_weighted":
        return searcher.hybrid(query, vector, k, fusion="weighted", dense_weight=0.5)
    raise RuntimeError(mode)


def _write_texts(path, record, members, pooled, chunks, by_sermon) -> None:
    lines = [f"# family {record['family']}", ""]
    for m in members:
        lines.append(f"- `{m['id']}` ({m['group']}): {m['query']}")
    lines.append("")
    if members[0]["relevant"]:
        lines.append("## Existing labels (do not change)")
        for p in members[0]["relevant"]:
            lines.append(f"- grade {p['grade']} {p['sermon_id']} {p['sermon_title']} {p.get('chunk_ids')}: «{p['quote']}»")
        lines.append("")
    # Shuffle, and do not print ranker or rank. Sermon order and "ranker@rank"
    # both tell a grader which system surfaced the chunk.
    order = list(record["pooled"])
    random.Random(record["family"]).shuffle(order)
    lines.append(f"## Pool ({len(pooled)} chunks)")
    for cid in order:
        row = chunks[cid]
        lines += ["", f"### {cid} — {row['sermon_title']} (#{row['sermon_number']})", "", row["text"]]
    for sid in record["gold_sermons"]:
        rest = [c for c in by_sermon.get(sid, []) if c not in pooled]
        lines += ["", f"## Rest of grade-2 sermon {sid} (chunks not in the pool, for the reading pass)"]
        for cid in rest:
            lines += ["", f"### {cid}", "", chunks[cid]["text"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
