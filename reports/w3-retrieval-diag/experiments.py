"""W3-RETRIEVAL-DIAG exploratory variants (scratch, NOT product code; nothing here is in src/).
Raw ranker top 10, Granite English R2 on CPU, same labels/metrics as search/bench.py (bench.score).
Usage (from the worktree root):
  uv run --group bench python reports/w3-retrieval-diag/experiments.py OUT.json
Index path: $PREACHED_CACHE/index/wesley.sqlite (default /cache), via preached.paths, opened read-only.
"""
import json, re, sys
from pathlib import Path
root = Path.cwd()
sys.path.insert(0, str(root / "src")); sys.path.insert(0, str(root / "search"))
from preached import env  # noqa
import preached.fts as fts
from preached.models import MODELS
from preached.embed import load_model, encode_query
from preached.search import Searcher
from preached.store import open_readonly, bm25_search  # mode=ro + query_only: no WAL pragma, DDL or ALTER
from preached.paths import INDEX_PATH
from preached.rank import dense_scores, reciprocal_rank_fusion
from preached.stats import bootstrap_ci, paired_bootstrap
import bench
import numpy as np

# Colloquial filler that is not doctrine (written for this diagnosis; generic, not taken from labels).
FILLER = set("""keep keeps keeping get gets getting got feel feels feeling felt like really actually just still
something anything everything someone anyone everyone stuff thing things want wants know way kinda
im ive dont cant wont isnt havent shouldnt theres i'm i've don't can't won't isn't it's what's we'll i'll
okay ok even ever also now back up down off much many lot whole being have has had""".split())

# Modern -> 18th-century wording. Generic thesaurus-style list written AFTER reading the questions,
# so it is contaminated by them; numbers from it are optimistic. Applied to the BM25 query only.
ARCHAIC = {
    "anxious": "care uneasy fear", "anxiety": "care uneasy fear", "worry": "care uneasy", "worrying": "care uneasy",
    "fretting": "care uneasy", "panicking": "fear care uneasy", "panic": "fear", "stress": "care",
    "scared": "fear afraid", "scary": "fear", "terrified": "fear",
    "sad": "sorrow grief", "crying": "sorrow tears grief", "depressed": "sorrow heaviness", "low": "sorrow",
    "jealous": "envy", "jealousy": "envy", "angry": "anger passion", "yelled": "anger passion",
    "lonely": "solitary society", "alone": "solitary society",
    "drinking": "drunkenness drunkard", "job": "employment business calling", "work": "labour employment business",
    "broke": "poverty poor", "paycheck": "gain wages", "guilty": "guilt condemnation", "dirty": "guilt condemnation",
    "doubting": "doubt", "dying": "death", "die": "death", "died": "death",
    "forgive": "pardon", "forgiven": "pardon", "kids": "children", "mom": "mother parent", "dad": "father parent",
    "marry": "marriage", "dating": "marriage", "numb": "insensible hardness", "medicine": "physic",
    "habits": "custom", "gossip": "backbiting", "coworker": "neighbour",
}

def expand(q):
    extra = []
    for t in fts.TOKEN_RE.findall(q):
        extra += ARCHAIC.get(t.lower(), "").split()
    return q + (" " + " ".join(extra) if extra else "")

questions = bench.load_questions()
groups = bench.question_groups(questions)
spec = MODELS["granite-english-r2"]
loaded = load_model(spec, device="cpu", batch_size=1)
con = open_readonly(INDEX_PATH)
s = Searcher(con, model=spec.key)
rowids, M = s._rowids, s._matrix
cid = {int(r[0]): r[1] for r in con.execute("select rowid, chunk_id from chunks")}
pos = {r: i for i, r in enumerate(rowids)}
# neighbour index for context smoothing (same sermon, chunk number +-1)
key = {}
for r in rowids:
    m = re.match(r"(.*)-c(\d+)$", cid[r]); key[(m.group(1), int(m.group(2)))] = pos[r]
prev_i = np.array([key.get((re.match(r"(.*)-c(\d+)$", cid[r]).group(1), int(cid[r][-4:]) - 1), -1) for r in rowids])
next_i = np.array([key.get((re.match(r"(.*)-c(\d+)$", cid[r]).group(1), int(cid[r][-4:]) + 1), -1) for r in rowids])

def top(scores, n=100):
    idx = np.argsort(-scores)[:n]
    return [(rowids[i], float(scores[i])) for i in idx]

def lex(q, n=100, filler=False, expansion=False):
    saved = set(fts.STOP)
    try:
        if filler: fts.STOP |= FILLER
        return bm25_search(con, expand(q) if expansion else q, n)
    finally:
        fts.STOP.clear(); fts.STOP |= saved

def rrf(dense, lexical, wd=1.0, wl=1.0):
    return reciprocal_rank_fusion([[r for r, _ in dense], [r for r, _ in lexical]], k=60, weights=[wd, wl])

def smooth(sc, a=0.5):
    p = np.where(prev_i >= 0, sc[np.maximum(prev_i, 0)], sc); n = np.where(next_i >= 0, sc[np.maximum(next_i, 0)], sc)
    return sc + a * (p + n) / 2

VARIANTS = {
    "V0 hybrid_rrf (shipped)":         lambda q, d: rrf(top(d), lex(q)),
    "V1 dense only":                   lambda q, d: top(d),
    "V2 bm25 only":                    lambda q, d: lex(q),
    "V3 rrf, bm25 weight 0.5":         lambda q, d: rrf(top(d), lex(q), 1, 0.5),
    "V4 rrf, bm25 weight 0.25":        lambda q, d: rrf(top(d), lex(q), 1, 0.25),
    "V5 rrf, bm25 filler stopwords":   lambda q, d: rrf(top(d), lex(q, filler=True)),
    "V6 V5 + bm25 weight 0.5":         lambda q, d: rrf(top(d), lex(q, filler=True), 1, 0.5),
    "V7 rrf, bm25 archaic expansion*": lambda q, d: rrf(top(d), lex(q, filler=True, expansion=True)),
    "V8 rrf, dense neighbour-smoothed": lambda q, d: rrf(top(smooth(d)), lex(q)),
    "V9 dense neighbour-smoothed only": lambda q, d: top(smooth(d)),
    # bm25 weight 0.5 only when fts builds an OR query (natural-language); AND/NEAR keyword queries keep 1.0
    "V10 rrf, bm25 0.5 on OR-queries":  lambda q, d: rrf(top(d), lex(q), 1, 0.5 if " OR " in fts.to_fts_query(q) and "NEAR(" not in fts.to_fts_query(q) else 1.0),
    "V12 V10 + archaic expansion*":     lambda q, d: rrf(top(d), lex(q, filler=True, expansion=True), 1, 0.5 if " OR " in fts.to_fts_query(q) and "NEAR(" not in fts.to_fts_query(q) else 1.0),
    "V11 rrf, bm25 0.25 on OR-queries": lambda q, d: rrf(top(d), lex(q), 1, 0.25 if " OR " in fts.to_fts_query(q) and "NEAR(" not in fts.to_fts_query(q) else 1.0),
}
METRICS = ["hit@10_lenient", "ndcg@10_lenient", "ndcg@10_strict", "hit@10_strict", "sermon@10"]
per = {v: {} for v in VARIANTS}
for q in questions:
    if not q["relevant"]:
        continue
    d = dense_scores(encode_query(loaded, q["query"]), M)
    for v, f in VARIANTS.items():
        ranked = f(q["query"], d)
        hits = s._pack(ranked, 50, None)
        per[v][q["id"]] = bench.score(hits[:10], q["relevant"], hits)
out = {"groups": {}, "vs_V0": {}}
for g, ids in list(groups.items()) + [("all", [q["id"] for q in questions if q["relevant"]])]:
    ids = [i for i in ids if i in per["V0 hybrid_rrf (shipped)"]]
    if not ids: continue
    out["groups"][g] = {"n": len(ids), **{v: {m: float(np.mean([per[v][i][m] for i in ids])) for m in METRICS} for v in VARIANTS}}
    out["vs_V0"][g] = {v: {m: paired_bootstrap([per[v][i][m] for i in ids], [per["V0 hybrid_rrf (shipped)"][i][m] for i in ids]) for m in ("hit@10_lenient", "ndcg@10_lenient")} for v in VARIANTS}
out["per_query"] = per
json.dump(out, open(sys.argv[1], "w"), indent=1, default=float)
for g in ("plain", "plain-blind", "names-topic", "title-keyword", "scripture-keyword", "all"):
    r = out["groups"][g]; print(f"\n## {g} (n={r['n']})  " + " | ".join(METRICS))
    for v in VARIANTS:
        diff = out["vs_V0"][g][v]["hit@10_lenient"]
        print(f"{v:34s} " + " ".join(f"{r[v][m]:.3f}" for m in METRICS) + f"   d_hit_len={diff}")
