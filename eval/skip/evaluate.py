"""Score ``preached.skip.propose`` on hand-marked synthetic service transcripts.

Each line of a set is ``{"id", "text"}`` (plus an optional ``note``). In
``text``, ``[[announcements]]``, ``[[prayer]]`` or ``[[testimony]]`` opens a
gold stretch and ``[[/]]`` closes it; the markers are separate words and are
removed before scoring. Words are split on spaces.

- stretch recall (full): gold stretches whose every word is excluded
- stretch recall (>= 90%, any): at least 90% / at least one word excluded
- word recall: gold words excluded / gold words
- over-exclusion: non-gold words excluded / non-gold words
- false stretches: proposed stretches with under 10% of their words in gold

    python3 eval/skip/evaluate.py eval/skip/dev.jsonl eval/skip/test.jsonl [--show]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from preached.skip import propose  # noqa: E402

OPEN = re.compile(r"^\[\[(announcements|prayer|testimony)\]\]$")
CLOSE = "[[/]]"


def parse(text: str) -> tuple[list[str], list[tuple[int, int, str]]]:
    words: list[str] = []
    gold: list[tuple[int, int, str]] = []
    current: tuple[int, str] | None = None
    for token in text.split():
        match = OPEN.match(token)
        if match:
            if current is not None:
                raise ValueError("nested gold stretch")
            current = (len(words), match.group(1))
        elif token == CLOSE:
            if current is None:
                raise ValueError("close without open")
            gold.append((current[0], len(words), current[1]))
            current = None
        else:
            words.append(token)
    if current is not None:
        raise ValueError("unclosed gold stretch")
    return words, gold


def score(path: Path, show: bool) -> dict:
    totals = defaultdict(int)
    by_category = defaultdict(lambda: [0, 0])  # full, count
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        words, gold = parse(doc["text"])
        stretches = propose(words)
        excluded = {i for s in stretches for i in range(s.start, s.end)}
        gold_words = {i for a, b, _ in gold for i in range(a, b)}
        totals["docs"] += 1
        totals["words"] += len(words)
        totals["gold_words"] += len(gold_words)
        totals["gold_hit_words"] += len(gold_words & excluded)
        totals["other_words"] += len(words) - len(gold_words)
        totals["other_excluded"] += len(excluded - gold_words)
        for a, b, category in gold:
            covered = sum(1 for i in range(a, b) if i in excluded) / (b - a)
            totals["gold_stretches"] += 1
            totals["full"] += covered == 1.0
            totals["ninety"] += covered >= 0.9
            totals["any"] += covered > 0
            by_category[category][1] += 1
            by_category[category][0] += covered == 1.0
            if show and covered < 1.0:
                missed = [words[i] for i in range(a, b) if i not in excluded]
                print(f"  MISS {doc['id']} {category} {covered:.0%} covered; missed: {' '.join(missed)[:200]}")
        for s in stretches:
            totals["proposed"] += 1
            inside = sum(1 for i in range(s.start, s.end) if i in gold_words) / (s.end - s.start)
            if inside < 0.1:
                totals["false_stretches"] += 1
            if show and s.end - s.start and inside < 1.0:
                extra = [words[i] for i in range(s.start, s.end) if i not in gold_words]
                print(f"  OVER {doc['id']} {s.category} {len(extra)} words: {' '.join(extra)[:200]}")
    totals["by_category"] = {k: {"full": v[0], "stretches": v[1]} for k, v in sorted(by_category.items())}
    return dict(totals)


def report(name: str, t: dict) -> None:
    g = t["gold_stretches"]
    print(f"{name}: {t['docs']} docs, {t['words']} words, {g} gold stretches ({t['gold_words']} words)")
    print(f"  stretch recall: full {t['full']}/{g} = {t['full'] / g:.3f}; >=90% {t['ninety']}/{g}; any {t['any']}/{g}")
    for category, v in t["by_category"].items():
        print(f"    {category}: full {v['full']}/{v['stretches']}")
    print(f"  word recall: {t['gold_hit_words']}/{t['gold_words']} = {t['gold_hit_words'] / t['gold_words']:.3f}")
    print(f"  over-exclusion: {t['other_excluded']}/{t['other_words']} non-gold words = {t['other_excluded'] / t['other_words']:.3f}")
    print(f"  proposed stretches: {t['proposed']}, of which false (<10% gold): {t.get('false_stretches', 0)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sets", nargs="+", type=Path)
    parser.add_argument("--show", action="store_true", help="print misses and over-excluded words (synthetic text only)")
    parser.add_argument("--json", type=Path, default=None, help="write the totals as JSON")
    args = parser.parse_args()
    results = {}
    for path in args.sets:
        totals = score(path, args.show)
        report(path.name, totals)
        results[path.name] = totals
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
