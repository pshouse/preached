"""Write the label review sheet for Patrick: eval/review/review-YYYY-MM-DD.csv.

One row per question in eval/questions.jsonl (excluded items included, so
they can be confirmed). The grade-2 cell is the whole chunk with the
labelled quote marked « »; the grade-1 cell lists each proposed passage as
sermon, short excerpt, and the grader's reason. Verdict and Notes are blank
for the reviewer. Reads chunk text from the index (read-only).

  uv run python scripts/review_sheet.py [--out PATH]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.corpus import read_jsonl  # noqa: E402
from preached.paths import INDEX_PATH, questions_path  # noqa: E402

COLUMNS = ["#", "question id", "group", "rewrite_of", "question", "original question", "expected sermon",
           "grade-2 passage", "proposed grade-1 passages", "answerable?", "Verdict", "Notes"]


def mark(text: str, quote: str) -> str:
    """``text`` with ``quote`` wrapped in « », matching case, whitespace and curly quotes loosely."""
    words = quote.split()
    pattern = r"\s+".join(re.escape(w).replace("'", "['‘’]").replace('"', '["“”]')
                          for w in words)
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return f"{text} [quote: «{quote}»]"
    return f"{text[:m.start()]}«{text[m.start():m.end()]}»{text[m.end():]}"


def sermon(p: dict) -> str:
    return f"#{p['sermon_number']} {p['sermon_title']}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    args = parser.parse_args()
    out = args.out or ROOT / "eval" / "review" / f"review-{dt.date.today().isoformat()}.csv"
    connection = sqlite3.connect(f"file:{args.index}?mode=ro", uri=True)
    text = dict(connection.execute("SELECT chunk_id, text FROM chunks"))
    questions = read_jsonl(questions_path())
    by_id = {q["id"]: q for q in questions}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for n, q in enumerate(questions, start=1):
            rel = q["relevant"]
            gold = [p for p in rel if int(p["grade"]) == 2]
            old_g1 = [p for p in rel if int(p["grade"]) == 1 and p.get("status") != "proposed"]
            new_g1 = [p for p in rel if int(p["grade"]) == 1 and p.get("status") == "proposed"]
            gold_cells = []
            for p in gold:
                chunk = (p.get("chunk_ids") or [None])[0]
                status = " (proposed)" if p.get("status") == "proposed" else ""
                why = f" Reason: {p['reason']}" if p.get("reason") else ""
                gold_cells.append(f"{sermon(p)}, {chunk}{status}: {mark(text.get(chunk, ''), p['quote'])}{why}")
            if old_g1:
                gold_cells.append("Already labelled grade 1 (unchanged): " + " | ".join(
                    f"{sermon(p)}: «{p['quote']}»" for p in old_g1))
            proposed = "\n".join(
                f"{i}. {sermon(p)} ({p['chunk_ids'][0]}): «{p['quote']}» Reason: {p['reason']}"
                for i, p in enumerate(new_g1, start=1))
            if q.get("excluded"):
                answerable = f"excluded: {q['excluded']}"
            elif rel:
                answerable = "yes" + (" (proposed)" if q.get("group") == "plain-blind" else "")
            else:
                answerable = "no" + (f" (proposed): {q['unanswerable_reason']}" if q.get("unanswerable_reason") else "")
            original = by_id[q["rewrite_of"]]["query"] if q.get("rewrite_of") else ""
            expected = "; ".join(dict.fromkeys(sermon(p) for p in gold))
            writer.writerow([n, q["id"], q.get("group", ""), q.get("rewrite_of", ""), q["query"], original, expected,
                             "\n".join(gold_cells), proposed, answerable, "", ""])
    print(f"wrote {out}: {len(questions)} rows")


if __name__ == "__main__":
    main()
