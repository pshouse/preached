"""Print EVAL-GRADE tables from a bench results JSON.

Per group and model x mode: nDCG@10 strict / pre-grading / lenient,
hit@10 strict / lenient, sermon@5 / @10 / @50. Also counts over a fixed id
list (default: the 25 `plain` ids of EVAL-DELEAK) so the CTO's sermon@10 and
sermon@50 cross-check can be compared on the same questions.

  uv run python scripts/grade_summary.py eval/results/2026-10-30-grade.json
"""

from __future__ import annotations

import json
import sys

DELEAK_PLAIN = [
    "q-worry", "q-assurance", "q-prayer", "q-forgiveness", "q-faith-works",
    *(f"{q}-plain" for q in ("q-money", "q-riches", "q-perfection", "q-heaviness", "q-mourning", "q-satan",
                             "q-temptation", "q-communion", "q-means", "q-salvation", "q-justification",
                             "q-new-birth", "q-sin-believers", "q-original-sin", "q-catholic-spirit",
                             "q-backsliders", "q-self-denial", "q-wandering-thoughts", "q-wilderness",
                             "q-evil-speaking")),
]
COLS = ("ndcg@10_strict", "ndcg@10", "ndcg@10_lenient", "hit@10_strict", "hit@10_lenient",
        "sermon@5", "sermon@10", "sermon@50")


def rows(report: dict):
    yield "BM25", "bm25", report["bm25"]["per_query"]
    for key, entry in report["models"].items():
        if entry.get("status") == "ok":
            for mode, pq in entry["per_query"].items():
                yield key, mode, pq


def main() -> None:
    report = json.loads(open(sys.argv[1]).read())
    groups = {g: ids for g, ids in report["groups"].items()}
    groups["overall"] = [i for ids in report["groups"].values() for i in ids]
    groups["deleak-plain-25 (old set)"] = DELEAK_PLAIN
    for name, ids in groups.items():
        print(f"\n### {name}")
        print("| model | mode | n | " + " | ".join(COLS) + " |")
        print("| --- | --- | --- | " + " | ".join("---" for _ in COLS) + " |")
        for key, mode, pq in rows(report):
            sub = [pq[i] for i in ids if i in pq]
            if not sub:
                continue
            cells = [f"{sum(r[c] for r in sub) / len(sub):.3f}" for c in COLS]
            print(f"| {key} | {mode} | {len(sub)} | " + " | ".join(cells) + " |")
    print("\n### CTO cross-check on the old 25 plain ids (counts)")
    for key, mode, pq in rows(report):
        sub = [pq[i] for i in DELEAK_PLAIN if i in pq]
        print(f"{key} {mode}: sermon@10 {int(sum(r['sermon@10'] for r in sub))}/{len(sub)}, "
              f"sermon@50 {int(sum(r['sermon@50'] for r in sub))}/{len(sub)}, "
              f"lenient hit@10 {int(sum(r['hit@10_lenient'] for r in sub))}/{len(sub)}")


if __name__ == "__main__":
    main()
