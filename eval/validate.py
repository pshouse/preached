"""Check that every graded quote is a real span of the chunked corpus.

No model is involved in this check. A quote matches when its normalized text is contained
in a chunk. Grade-2 and grade-1 quotes must match at least one chunk.
Unanswerable items must have an empty relevant list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preached.corpus import read_jsonl  # noqa: E402
from preached.metrics import contains_quote  # noqa: E402
from preached.paths import CHUNKS_JSONL, questions_path  # noqa: E402


def load_questions(path: Path) -> list[dict]:
    return read_jsonl(path)


def main() -> None:
    write_back = "--write" in sys.argv
    path = questions_path()
    questions = load_questions(path)
    chunks = read_jsonl(CHUNKS_JSONL)
    by_type: dict[str, int] = {}
    missing = []
    for question in questions:
        by_type[question["type"]] = by_type.get(question["type"], 0) + 1
        if question.get("excluded"):
            continue  # kept for the record; not scored
        relevant = question["relevant"]
        if question["type"] == "unanswerable" and relevant:
            missing.append(f"{question['id']} is unanswerable but has relevant passages")
        if question["type"] != "unanswerable" and not relevant:
            missing.append(f"{question['id']} has no relevant passages")
        for passage in relevant:
            hits = [chunk["chunk_id"] for chunk in chunks if contains_quote(chunk["text"], passage["quote"])]
            passage_id = passage.get("passage_id", "?")
            if not hits:
                missing.append(f"{question['id']} {passage_id} quote not found in any chunk")
            else:
                passage["chunk_ids"] = hits
    print(json.dumps({"questions": len(questions), "by_type": by_type, "chunks": len(chunks)}, indent=2))
    if missing:
        print("FAILED")
        for line in missing:
            print(" -", line)
        raise SystemExit(1)
    if write_back:
        with path.open("w", encoding="utf-8") as handle:
            for question in questions:
                handle.write(json.dumps(question, ensure_ascii=False) + "\n")
        print(f"wrote chunk_ids back to {path}")
    print("all graded quotes match at least one chunk")


if __name__ == "__main__":
    main()
