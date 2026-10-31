"""Run the abstain rule on eval/nl-questions-w3polish.jsonl.

Those 18 short questions were written by the W3-POLISH coding agent (an
LLM), not reviewed by a person, to probe the abstain floor with questions
that do not borrow sermon-title words. Each names the sermon(s) the agent
expects to answer it, checked only against sermon titles and a text grep.

For each model (hybrid, k=10, the API path) it prints the level, the
signals, and whether an expected sermon is in the top 5 / top 10. Then it
reports what the floor would be if these questions were added to the fit
as answerable (the guard in ``fit_floor``). It writes nothing.
Usage: uv run --group bench scripts/check_nl_questions.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached import env  # noqa: F401, E402
from preached.abstain import Signals, decide, fit_floor, floor_for, search_with_confidence  # noqa: E402
from preached.corpus import read_jsonl  # noqa: E402
from preached.embed import encode_query, load_model, unload  # noqa: E402
from preached.models import MODELS  # noqa: E402
from preached.paths import INDEX_PATH  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.store import open_readonly_or_exit  # noqa: E402

QUESTIONS = ROOT / "eval" / "nl-questions-w3polish.jsonl"
ABSTAIN_RUN = ROOT / "eval" / "results" / "2026-10-30-w3polish-abstain.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="*", default=["granite-english-r2", "embeddinggemma-2"])
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    args = parser.parse_args()

    questions = read_jsonl(QUESTIONS)
    fitted = json.loads(ABSTAIN_RUN.read_text())["models"]
    connection = open_readonly_or_exit(args.index, check_same_thread=False)
    for key in args.models:
        floor = floor_for(key)
        searcher = Searcher(connection, model=key, allow_eval_only=True)
        loaded = load_model(MODELS[key], device="cpu", batch_size=1)
        rows = []
        try:
            print(f"\n== {key} (floor {floor}) ==")
            print("| id | query | level | dense top | agreement | BM25 hits | expected in top 5 | top 10 |")
            print("| --- | --- | --- | --- | --- | --- | --- | --- |")
            for q in questions:
                vector = encode_query(loaded, q["query"])
                hits, conf = search_with_confidence(searcher, q["query"], vector, "hybrid", 10, floor)
                numbers = [hit.sermon_number for hit in hits]
                top5 = any(n in q["expected_sermons"] for n in numbers[:5])
                top10 = any(n in q["expected_sermons"] for n in numbers[:10])
                s = conf.signals
                rows.append((q, conf, top10))
                print(f"| {q['id']} | {q['query']} | {conf.level} | {s.dense_top:.4f} | {s.agreement} | "
                      f"{s.bm25_hits} | {top5} | {top10} |")
        finally:
            unload(loaded)
        levels = [conf.level for _, conf, _ in rows]
        found = [conf.level for _, conf, top10 in rows if top10]
        print(f"levels: " + ", ".join(f"{lv} {levels.count(lv)}" for lv in ("strong", "weak", "none")))
        print(f"low confidence (none) with an expected sermon in the top 10: {found.count('none')} of {len(found)}")
        # Refit with these as answerable, as fit_floor would (its guard).
        base = [(Signals(r["bm25_hits"], r["dense_top"], r["agreement"]), r["answerable"])
                for r in fitted[key]["rows"]]
        extra = [(conf.signals, True) for _, conf, _ in rows]
        refit = fit_floor(base + extra)
        negatives = [s for s, answerable in base if not answerable]
        caught = sum(decide(s, refit).level == "none" for s in negatives)
        print(f"refit with these as answerable: floor {floor} -> {refit}; "
              f"labelled unanswerable still 'none': {caught} of {len(negatives)} "
              f"(was {sum(decide(s, floor).level == 'none' for s in negatives)})")


if __name__ == "__main__":
    main()
