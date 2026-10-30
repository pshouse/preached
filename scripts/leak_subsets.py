"""Split a bench results file by where each question came from.

Columns: the original 35 answerable questions (old headline set), the 20
"-plain" rewrites, the 5 plain questions that were already title-free, and
the 20 originals that were rewritten. Each cell is nDCG@10 / R@5 / MRR@10 /
sermon@5. Reads only the JSON; embeds nothing.
Usage: uv run python scripts/leak_subsets.py eval/results/2026-10-30-deleak.json
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
d = json.load(open(sys.argv[1]))
qs = [json.loads(l) for l in open(ROOT / 'eval' / 'questions.jsonl')]
orig = [q['id'] for q in qs if 'rewrite_of' not in q and q['relevant']]
rew = [q['id'] for q in qs if 'rewrite_of' in q]
clean = [q['id'] for q in qs if q['group'] == 'plain' and 'rewrite_of' not in q]
pairs = [(q['rewrite_of'], q['id']) for q in qs if 'rewrite_of' in q]
rows = [('BM25', 'bm25', d['bm25']['per_query'])] + [(k, m, e['per_query'][m]) for k, e in d['models'].items() if e['status'] == 'ok' for m in e['per_query']]
M = ('ndcg@10', 'recall@5', 'mrr@10', 'sermon@5')
def cell(pq, ids):
    return ' / '.join(f"{sum(pq[i][m] for i in ids)/len(ids):.3f}" for m in M)
print(f"| model | mode | original 35 (n={len(orig)}) | plain rewrites (n={len(rew)}) | plain clean originals (n={len(clean)}) | their 20 originals | sermon@5 by group: plain / names-topic |")
print("| --- | --- | --- | --- | --- | --- | --- |")
grp = {}
for q in qs: grp.setdefault(q['group'], []).append(q['id'])
for k, m, pq in rows:
    s5 = lambda g: sum(pq[i]['sermon@5'] for i in grp[g]) / len(grp[g])
    print(f"| {k} | {m} | {cell(pq, orig)} | {cell(pq, rew)} | {cell(pq, clean)} | {cell(pq, [a for a,_ in pairs])} | {s5('plain'):.3f} / {s5('names-topic'):.3f} |")
