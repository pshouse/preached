"""W3-RETRIEVAL-DIAG scratch: per-question dump for plain + plain-blind (exploratory, not product code).
Usage (from the worktree root): uv run --group bench python reports/w3-retrieval-diag/diag.py OUT.json
Index path: $PREACHED_CACHE/index/wesley.sqlite (default /cache), via preached.paths, opened read-only."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from preached import env  # noqa
from preached.models import MODELS
from preached.embed import load_model, encode_query
from preached.search import Searcher
from preached.store import open_readonly  # mode=ro + query_only: no WAL pragma, DDL or ALTER
from preached.paths import INDEX_PATH, questions_path
from preached.metrics import contains_quote
from preached.fts import to_fts_query

qs = [json.loads(l) for l in open(questions_path())]
qs = [q for q in qs if q.get("group") in ("plain", "plain-blind")]
spec = MODELS["granite-english-r2"]
loaded = load_model(spec, device="cpu", batch_size=1)
con = open_readonly(INDEX_PATH)
s = Searcher(con, model=spec.key)
print("tokenizer:", con.execute("select sql from sqlite_master where name='chunks_fts'").fetchone()[0], file=sys.stderr)
out = []
for q in qs:
    v = encode_query(loaded, q["query"])
    lists = {"bm25": s.bm25(q["query"], 100), "dense": s.dense(v, 100),
             "hybrid": s.hybrid(q["query"], v, 100, fusion="rrf", rrf_k=60)}
    rel = q["relevant"]
    g2sermons = {r["sermon_id"] for r in rel if int(r["grade"]) == 2}
    rec = {"id": q["id"], "group": q["group"], "query": q["query"], "type": q["type"],
           "fts": to_fts_query(q["query"]), "n_bm25_hits": len(lists["bm25"]),
           "labels": [{"g": r["grade"], "sid": r["sermon_id"], "title": r["sermon_title"], "status": r.get("status"),
                       "quote": r["quote"], "chunks": r.get("chunk_ids", [])} for r in rel],
           "runs": {}}
    for name, hits in lists.items():
        rows = []
        for i, h in enumerate(hits, 1):
            gr = max([int(r["grade"]) for r in rel if contains_quote(h.text, r["quote"])] or [0])
            rows.append({"rank": i, "chunk": h.chunk_id, "sid": h.sermon_id, "title": h.sermon_title,
                         "grade": gr, "g2sermon": h.sermon_id in g2sermons, "score": round(h.score, 4),
                         "words": len(h.text.split()), "text": h.text if i <= 5 else None})
        first = lambda pred: next((r["rank"] for r in rows if pred(r)), None)
        rec["runs"][name] = {"top5": rows[:5],
                             "first_g2": first(lambda r: r["grade"] == 2),
                             "first_any": first(lambda r: r["grade"] >= 1),
                             "first_g2sermon": first(lambda r: r["g2sermon"])}
    out.append(rec)
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(len(out), "questions", file=sys.stderr)
