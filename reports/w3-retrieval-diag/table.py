"""Render the per-question table and category counts for reports/W3-RETRIEVAL-DIAG.md (scratch).
Usage: python3 table.py [WORKDIR]  (WORKDIR holds diag.json, categories.json, flags.json; default $TMPDIR/w3-retrieval-diag, never the repo; table.md and legend.md are written there)"""
import json, collections, os, sys, tempfile
W = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "w3-retrieval-diag")
d = json.load(open(os.path.join(W, "diag.json"))); cat = json.load(open(os.path.join(W, "categories.json"))); flags = json.load(open(os.path.join(W, "flags.json")))
titles = {}
def short(c): return c.split("-")[1] + "·" + str(int(c.split("-c")[1]))
def cell(r, run, qid):
    out = []
    for h in r["runs"][run]["top5"]:
        s = short(h["chunk"]); titles[h["sid"]] = h["title"]
        if h["grade"] == 2: s = f"**{s}**²"
        elif h["grade"] == 1: s = f"**{s}**¹"
        elif h["chunk"] in flags.get(qid, []): s += "⚑"
        elif h["g2sermon"]: s += "†"
        out.append(s)
    return " ".join(out) if out else "(no rows)"
lines = ["| id | question | expected | BM25 top 5 | dense top 5 | hybrid top 5 | 1st label B/D/H | category | note |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
counts = collections.defaultdict(collections.Counter)
for r in d:
    g2 = [l for l in r["labels"] if l["g"] == 2]; g1 = [l for l in r["labels"] if l["g"] == 1]
    for l in r["labels"]: titles[l["sid"]] = l["title"]
    exp = "none (unanswerable)" if not r["labels"] else ", ".join(f"²{l['sid'][-3:]}" for l in g2) + (f" +{len(g1)}¹ ({' '.join(sorted({l['sid'][-3:] for l in g1}))})" if g1 else "")
    f = "/".join(str(r["runs"][k]["first_any"] or "–") for k in ("bm25", "dense", "hybrid"))
    c, note = cat[r["id"]]
    counts[r["group"]][c] += 1
    q = r["query"].replace("|", "/")
    lines.append(f"| {r['id']} | {q} | {exp} | {cell(r,'bm25',r['id'])} | {cell(r,'dense',r['id'])} | {cell(r,'hybrid',r['id'])} | {f} | {c} | {note} |")
open(os.path.join(W, "table.md"), "w").write("\n".join(lines) + "\n")
legend = ["| no. | title |", "| --- | --- |"] + [f"| {k[-3:]} | {v} |" for k, v in sorted(titles.items())]
open(os.path.join(W, "legend.md"), "w").write("\n".join(legend) + "\n")
print({g: dict(c) for g, c in counts.items()})
