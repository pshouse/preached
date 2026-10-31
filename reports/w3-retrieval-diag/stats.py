"""Per-question signals from diag.json (scratch). python3 stats.py diag.json [chunks.jsonl] [out_stats.json]
chunks.jsonl defaults to $PREACHED_CACHE/corpus/wesley/chunks.jsonl (/cache by default); out defaults to stats.json in cwd."""
import json, os, re, sys, statistics as st
d = json.load(open(sys.argv[1]))
chunks = {}
chunks_path = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("PREACHED_CACHE", "/cache") + "/corpus/wesley/chunks.jsonl"
for l in open(chunks_path):
    r = json.loads(l); chunks[r["chunk_id"]] = r["text"]
lens = [len(t.split()) for t in chunks.values()]
STOP = set("a an the of to and or in on for with from by at as is are was were be been being it its this that these those i me my we our you your he she they them their his her do does did what which who when where why how should would could can will shall may might must about into over than then there here if but not no so too very just say said".split())
def stem(w):
    w = w.lower().strip("'")
    for suf in ("ing", "ed", "es", "s", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 3: return w[: -len(suf)]
    return w
def terms(t): return {stem(w) for w in re.findall(r"[A-Za-z']+", t) if w.lower() not in STOP and len(w) > 2}
rows = []
for r in d:
    if not r["labels"]: continue
    gold = {c for l in r["labels"] for c in l["chunks"]}
    qt = terms(r["query"])
    best = max((len(qt & terms(chunks[c])) / max(len(qt), 1) for c in gold if c in chunks), default=0)
    h, de, b = (r["runs"][k]["first_any"] for k in ("hybrid", "dense", "bm25"))
    rows.append(dict(id=r["id"], group=r["group"], n_labels=len(r["labels"]), overlap=round(best, 2),
                     gold_words=st.median([len(chunks[c].split()) for c in gold if c in chunks]),
                     bm25=b, dense=de, hybrid=h, fusion_loss=bool(de and de <= 10 and not (h and h <= 10)),
                     fusion_gain=bool(h and h <= 10 and not (de and de <= 10)), nbm25=r["n_bm25_hits"]))
json.dump(rows, open(sys.argv[3] if len(sys.argv) > 3 else "stats.json", "w"), indent=1)
print("corpus chunk words median", st.median(lens))
for g in ("plain", "plain-blind"):
    R = [x for x in rows if x["group"] == g]
    hit = lambda k: sum(1 for x in R if x[k] and x[k] <= 10)
    print(g, len(R), "lenient hit@10 bm25/dense/hybrid", hit("bm25"), hit("dense"), hit("hybrid"),
          "fusion_loss", sum(x["fusion_loss"] for x in R), "fusion_gain", sum(x["fusion_gain"] for x in R),
          "median best overlap", st.median(x["overlap"] for x in R), "zero-overlap", sum(x["overlap"] == 0 for x in R),
          "median gold words", st.median(x["gold_words"] for x in R), "median n_labels", st.median(x["n_labels"] for x in R))
for x in rows: print(x)
