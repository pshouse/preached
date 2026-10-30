"""Run eval/classics_questions.jsonl against the per-preacher libraries (hybrid, top 5).

    uv run scripts/classics_check.py [--library spurgeon]

A question passes when an expected sermon is in the top 5 and that hit has a start_s and an
archive.org play URL. The questions were written by an agent and are not human-reviewed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "search"))

import query  # noqa: E402
from preached.embed import encode_query, load_model, unload  # noqa: E402
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import INDEX_DIR  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.store import connect  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()
    questions = [json.loads(line) for line in (ROOT / "eval" / "classics_questions.jsonl").read_text().splitlines() if line.strip()]
    model = load_model(MODELS[DEFAULT_MODEL], device="cpu", batch_size=1)
    passed = total = 0
    try:
        for lib in sorted({q["library"] for q in questions}):
            if args.library and lib != args.library:
                continue
            searcher = Searcher(connect(INDEX_DIR / f"{lib}.sqlite"), model=DEFAULT_MODEL)
            for q in (q for q in questions if q["library"] == lib):
                hits = searcher.hybrid(q["question"], encode_query(model, q["question"]), args.k)
                rank = next((i for i, h in enumerate(hits, 1) if h.sermon_id in q["expect"]), None)
                hit = hits[rank - 1] if rank else None
                playable = bool(hit and hit.start_s is not None and query.play_url(hit.audio_url, hit.start_s).startswith("https://archive.org/"))
                ok = rank is not None and playable
                passed += ok
                total += 1
                where = f"{hit.sermon_id} @ {query.fmt_time(hit.start_s)} {query.play_url(hit.audio_url, hit.start_s)}" if hit else "-"
                print(f"{'PASS' if ok else 'FAIL'} [{lib}] rank={rank} {q['question']!r} -> {where}")
    finally:
        unload(model)
    print(f"{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
