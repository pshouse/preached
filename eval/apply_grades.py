"""Check and apply wider-grading judgments (EVAL-GRADE) to eval/questions.jsonl.

Judgments are one JSON file per pool family (see eval/pool.py), written by a
reader of /cache/eval-pool/<date>/<family>.md:

  {"family": "q-worry",
   "grade1": [{"chunk_id": "...", "quote": "exact span of that chunk", "reason": "one line"}],
   # plain-blind candidates only:
   "answerable": true, "grade2": {"chunk_id": ..., "quote": ..., "reason": ...},
   "unanswerable_reason": "...", "excluded": null}

--check validates files without writing: each chunk exists, each quote is in
its chunk (normalized as in preached.metrics), quotes are 6-60 words, and no
two labels of a family share a chunk (an existing label's chunk included).

Without --check it rewrites eval/questions.jsonl: previously applied proposals
(status "proposed") and plain-blind items are removed first, so it is
idempotent. Every label it adds has status "proposed" until Patrick confirms
it in the review sheet. Existing labels are never changed. A rewrite and its
original get identical label lists.

  uv run python eval/apply_grades.py --check [DIR_OR_FILES...]
  uv run python eval/apply_grades.py [DIR]      # default /cache/eval-pool/<today>/grades
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.corpus import read_jsonl  # noqa: E402
from preached.metrics import contains_quote  # noqa: E402
from preached.paths import INDEX_PATH, questions_path  # noqa: E402

CANDIDATES = ROOT / "eval" / "plain_candidates.jsonl"


def load_chunks(index: Path) -> dict[str, dict]:
    connection = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT chunk_id, sermon_id, sermon_number, sermon_title, source_url, text FROM chunks ORDER BY rowid")
    return {r["chunk_id"]: dict(r) for r in rows}


def containing(chunks: dict[str, dict], quote: str, sermon_id: str | None = None) -> list[str]:
    return [cid for cid, c in chunks.items()
            if (sermon_id is None or c["sermon_id"] == sermon_id) and contains_quote(c["text"], quote)]


def check_file(data: dict, chunks: dict[str, dict], existing: list[dict]) -> tuple[list[str], list[dict]]:
    """Problems, and the labels (grade-2 first, then grade-1) with chunk_ids filled in."""
    problems: list[str] = []
    labels: list[dict] = []
    taken: dict[str, str] = {}
    for p in existing:
        for cid in p.get("chunk_ids") or containing(chunks, p["quote"]):
            taken[cid] = f"existing {p.get('passage_id', '?')}"
    entries = []
    if data.get("grade2"):
        entries.append((2, data["grade2"]))
    entries += [(1, e) for e in data.get("grade1", [])]
    for grade, entry in entries:
        cid, quote, reason = entry.get("chunk_id"), entry.get("quote", ""), entry.get("reason", "")
        where = f"{data['family']} grade {grade} {cid}"
        if cid not in chunks:
            problems.append(f"{where}: unknown chunk")
            continue
        if not contains_quote(chunks[cid]["text"], quote):
            problems.append(f"{where}: quote not in chunk: {quote[:60]!r}")
            continue
        n_words = len(quote.split())
        if not 6 <= n_words <= 60:
            problems.append(f"{where}: quote has {n_words} words (6-60)")
        if not reason.strip() or "\n" in reason:
            problems.append(f"{where}: reason must be one non-empty line")
        hits = containing(chunks, quote, chunks[cid]["sermon_id"])
        clash = sorted({taken[h] for h in hits if h in taken})
        if clash:
            problems.append(f"{where}: shares a chunk with {', '.join(clash)}")
            continue
        for h in hits:
            taken[h] = f"{where}"
        labels.append({"grade": grade, "chunk": chunks[cid], "quote": quote, "reason": reason.strip(),
                       "chunk_ids": hits})
    if data["family"].startswith("p-"):
        if data.get("excluded"):
            pass
        elif data.get("answerable") is True and not data.get("grade2"):
            problems.append(f"{data['family']}: answerable needs grade2")
        elif data.get("answerable") is False and (data.get("grade2") or data.get("grade1")
                                                   or not data.get("unanswerable_reason")):
            problems.append(f"{data['family']}: unanswerable needs a reason and no labels")
        elif data.get("answerable") not in (True, False):
            problems.append(f"{data['family']}: answerable must be true or false")
    elif data.get("grade2"):
        problems.append(f"{data['family']}: existing questions keep their grade-2 labels; use grade1 only")
    return problems, labels


def label_record(family: str, n: int, label: dict, pool: str) -> dict:
    """One proposed label. ``pool`` names the pool file; ``found_by`` names the LLM that proposed it."""
    del pool  # retained so ``--pool`` still selects the file the run read; not stored on the label
    c = label["chunk"]
    return {
        "passage_id": f"{family}-g{label['grade']}-{n:02d}",
        "sermon_id": c["sermon_id"],
        "sermon_number": c["sermon_number"],
        "sermon_title": c["sermon_title"],
        "grade": label["grade"],
        "quote": label["quote"],
        "source_url": c["source_url"],
        "chunk_ids": label["chunk_ids"],
        "status": "proposed",
        "reason": label["reason"],
        "found_by": "llm-proposed:claude",
    }


def strip_applied(questions: list[dict]) -> list[dict]:
    out = []
    for q in questions:
        if q.get("group") == "plain-blind":
            continue
        out.append({**q, "relevant": [p for p in q["relevant"] if p.get("status") != "proposed"]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--pool", default=f"eval/pool/pool-{dt.date.today().isoformat()}.jsonl")
    args = parser.parse_args()
    paths = args.paths or [Path("/cache/eval-pool") / dt.date.today().isoformat() / "grades"]
    files = sorted(f for p in paths for f in (p.glob("*.json") if p.is_dir() else [p]))
    chunks = load_chunks(args.index)
    questions = strip_applied(read_jsonl(questions_path()))
    by_id = {q["id"]: q for q in questions}
    families: dict[str, list[dict]] = {}
    for q in questions:
        if q["relevant"]:
            families.setdefault(q.get("rewrite_of") or q["id"], []).append(q)
    candidates = {q["id"]: q for q in read_jsonl(CANDIDATES)}

    problems: list[str] = []
    applied: dict[str, tuple[dict, list[dict]]] = {}
    for f in files:
        data = json.loads(f.read_text())
        family = data.get("family")
        if family not in families and family not in candidates:
            problems.append(f"{f.name}: unknown family {family!r}")
            continue
        existing = families[family][0]["relevant"] if family in families else []
        found, labels = check_file(data, chunks, existing)
        problems += found
        applied[family] = (data, labels)
        n1 = sum(lb["grade"] == 1 for lb in labels)
        print(f"{family}: grade-2 {sum(lb['grade'] == 2 for lb in labels)}, grade-1 {n1}"
              + (f", excluded: {data['excluded']}" if data.get("excluded") else "")
              + (", unanswerable" if data.get("answerable") is False else ""))
    for line in problems:
        print("PROBLEM", line)
    if args.check or problems:
        return 1 if problems else 0

    for family, (data, labels) in applied.items():
        records = []
        counters = {1: 0, 2: 0}
        for lb in labels:
            counters[lb["grade"]] += 1
            records.append(label_record(family, counters[lb["grade"]], lb, args.pool))
        if family in families:
            for q in families[family]:
                by_id[q["id"]]["relevant"] = q["relevant"] + records
        else:
            cand = candidates[family]
            item = {"id": family, "query": cand["question"],
                    "type": "unanswerable" if data.get("answerable") is False else "conceptual",
                    "group": "plain-blind",
                    # Grok wrote the blind questions before reading the corpus. Unconfirmed by a human.
                    "provenance": cand.get("provenance", "llm-written:grok"),
                    "relevant": [] if data.get("excluded") else records,
                    "answerable_guess": cand.get("answerable_guess")}
            if data.get("answerable") is False:
                item["unanswerable_reason"] = data["unanswerable_reason"]
            if data.get("excluded"):
                item["excluded"] = data["excluded"]
            questions.append(item)
    path = questions_path()
    with path.open("w", encoding="utf-8") as handle:
        for q in questions:
            handle.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"wrote {path}: {len(questions)} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
