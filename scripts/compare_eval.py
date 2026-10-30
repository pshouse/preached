"""Compare two search/bench.py JSON files for one model.

Prints Recall@5, MRR@10, and nDCG@10 deltas, and how many questions
kept the same top-10 chunk ids. Used for the W3 ONNX vs torch check.

  python scripts/compare_eval.py eval/results/torch.json eval/results/onnx.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

METRICS = ("recall@5", "mrr@10", "ndcg@10")
MODES = ("dense", "hybrid_rrf")


def load(path: Path, model: str) -> dict:
    report = json.loads(path.read_text())
    entry = report["models"][model]
    if entry.get("status") != "ok":
        raise SystemExit(f"{path}: {model} status is {entry.get('status')}")
    return entry


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: compare_eval.py REFERENCE.json OTHER.json")
    model = "granite-english-r2"
    reference = load(Path(sys.argv[1]), model)
    other = load(Path(sys.argv[2]), model)
    print(f"reference {sys.argv[1]}")
    print(f"other     {sys.argv[2]}")
    for mode in MODES:
        print(f"\n{mode}")
        ref_summary = reference["summary"][mode]
        other_summary = other["summary"][mode]
        for metric in METRICS:
            ref_mean = ref_summary[metric]["mean"]
            other_mean = other_summary[metric]["mean"]
            delta = other_mean - ref_mean
            print(f"  {metric:10} ref={ref_mean:.4f} other={other_mean:.4f} delta={delta:+.4f}")
        ref_pq = reference["per_query"][mode]
        other_pq = other["per_query"][mode]
        ids = sorted(set(ref_pq) & set(other_pq))
        same = 0
        changed = []
        for qid in ids:
            if ref_pq[qid].get("top10") == other_pq[qid].get("top10"):
                same += 1
            else:
                changed.append(qid)
        print(f"  top10 identical {same}/{len(ids)}")
        if changed:
            print("  changed:", ", ".join(changed))


if __name__ == "__main__":
    main()
