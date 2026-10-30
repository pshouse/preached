"""Score ``preached.privacy.redact`` on a marked-up sentence set.

Each line of a set is ``{"id", "category", "text"}``. In ``text``,
``[[...]]`` wraps private names (must become ``[name]``) and ``{{...}}``
wraps biblical, historical or public names (must stay). The markup is
removed, the sentence is split on spaces into Whisper-style word records
(0.3 s apart) and passed to ``redact``. Scoring is per word:

- recall = private words redacted / private words
- false-redaction rate = kept-name words redacted / kept-name words
- other-word rate = unmarked words redacted / unmarked words

    python3 eval/privacy/evaluate.py eval/privacy/dev.jsonl eval/privacy/heldout.jsonl
    python3 eval/privacy/evaluate.py eval/privacy/heldout.jsonl --errors
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from preached.privacy import Config, TOKEN, lists, redact  # noqa: E402

MARK = re.compile(r"\[\[(.+?)\]\]|\{\{(.+?)\}\}")


def parse(text: str) -> list[tuple[str, str]]:
    """[(word, label)] with label 'private', 'public' or 'other'."""
    labels: list[str] = []
    plain: list[str] = []
    position = 0
    for match in MARK.finditer(text):
        plain.append(text[position : match.start()])
        labels.extend(["other"] * len(text[position : match.start()]))
        inner = match.group(1) or match.group(2)
        plain.append(inner)
        labels.extend(["private" if match.group(1) else "public"] * len(inner))
        position = match.end()
    plain.append(text[position:])
    labels.extend(["other"] * len(text[position:]))
    flat = "".join(plain)
    words = []
    for found in re.finditer(r"\S+", flat):
        word_labels = {labels[i] for i in range(found.start(), found.end()) if flat[i].isalpha()}
        label = "private" if "private" in word_labels else "public" if "public" in word_labels else "other"
        words.append((found.group(), label))
    return words


def score(path: Path, config: Config, show: bool) -> dict:
    counts = defaultdict(lambda: [0, 0])  # label -> [redacted, total]
    by_category = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    errors = []
    sentences = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sentences += 1
        words = parse(row["text"])
        records = [{"start": i * 0.3, "end": i * 0.3 + 0.25, "text": w} for i, (w, _) in enumerate(words)]
        out = redact(records, config=config)
        if len(out) != len(records) or any(
            (a["start"], a["end"]) != (b["start"], b["end"]) for a, b in zip(records, out)
        ):
            raise SystemExit(f"{row['id']}: timing or word count changed")
        wrong = []
        for (word, label), result in zip(words, out):
            hidden = TOKEN in result["text"]
            counts[label][0] += hidden
            counts[label][1] += 1
            by_category[row["category"]][label][0] += hidden
            by_category[row["category"]][label][1] += 1
            if (label == "private") != hidden:
                wrong.append(f"{'MISS' if label == 'private' else 'OVER'}:{word}")
        if wrong:
            errors.append((row["id"], row["category"], " ".join(wrong), " ".join(r["text"] for r in out)))
    if show:
        for error in errors:
            print("  ".join(error))
    private, public, other = counts["private"], counts["public"], counts["other"]
    return {
        "set": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sentences": sentences,
        "private_words": private[1],
        "private_redacted": private[0],
        "recall": round(private[0] / private[1], 4) if private[1] else None,
        "public_words": public[1],
        "public_redacted": public[0],
        "false_redaction_rate": round(public[0] / public[1], 4) if public[1] else None,
        "other_words": other[1],
        "other_redacted": other[0],
        "other_rate": round(other[0] / other[1], 4) if other[1] else None,
        "by_category": {
            category: {
                label: f"{values[0]}/{values[1]}" for label, values in sorted(labels.items())
            }
            for category, labels in sorted(by_category.items())
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sets", nargs="+", type=Path)
    parser.add_argument("--errors", action="store_true", help="print every sentence with a miss or over-redaction")
    parser.add_argument("--json", type=Path, help="write results here")
    args = parser.parse_args()
    started = time.perf_counter()
    lists()
    load_s = time.perf_counter() - started
    results = []
    for path in args.sets:
        result = score(path.resolve(), Config(), args.errors)
        results.append(result)
        print(
            f"{result['set']}: {result['sentences']} sentences  "
            f"recall {result['private_redacted']}/{result['private_words']} = {result['recall']}  "
            f"false-redaction {result['public_redacted']}/{result['public_words']} = {result['false_redaction_rate']}  "
            f"other words {result['other_redacted']}/{result['other_words']} = {result['other_rate']}"
        )
        for category, labels in result["by_category"].items():
            print(f"    {category:20s} " + "  ".join(f"{k} {v}" for k, v in labels.items()))
    print(f"list load {load_s * 1000:.0f} ms")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
