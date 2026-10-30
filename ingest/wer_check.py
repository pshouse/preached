"""Spot-check WER of a transcript against the CCEL text of the same sermon.

    uv run ingest/wer_check.py /cache/transcripts/wesley/wesley-s1-01.json [--words 1500]

Measures reader + ASR together: LibriVox readers sometimes skip footnotes,
read paragraph numbers, or misread, and those count as errors here.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest  # noqa: E402

NUM = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
       "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten"}


def norm(text: str) -> list[str]:
    text = re.sub(r"\[\d+\]", " ", text)  # footnote markers
    text = text.lower().replace("favor", "favour").replace("honor", "honour")
    text = re.sub(r"[^a-z0-9' ]+", " ", text.replace("-", " "))
    return [NUM.get(w, w) for w in (w.strip("'") for w in text.split()) if w]


def ccel_body(n: int) -> str:
    # Same CCEL file as the search corpus, sha256-checked against corpus/catalog.json.
    body = manifest.ccel_text().split("First Series\n     ___", 1)[1]
    m = re.search(rf"\nSermon {n}(?: \[\d+\])?\n(.*?)(?=\nSermon {n + 1}(?: \[\d+\])?\n|\Z)", body, re.S)
    blocks = re.split(r"\n\s*\n", re.sub(r"\n\s*_{5,}.*", "", m.group(1), flags=re.S))
    # Skip the heading (title, epigraph, reference): readers voice it in varying ways.
    skip = 1
    for i, b in enumerate(blocks[:8]):
        if re.match(r"[1-3]?\s?[A-Z][a-z]+\.? ?\d+[:.]", b.strip()):
            skip = i + 1
            break
    body = "\n".join(blocks[skip:])
    # Paragraph numbers ("1.", "II.") are printed but rarely read aloud.
    return re.sub(r"(?m)^\s*(\d+|[IVXL]+)\.\s", " ", body)


def wer(ref: list[str], hyp: list[str]) -> tuple[float, int]:
    """Levenshtein with free start/end gaps on hyp: the ref window may sit anywhere
    inside hyp (hyp includes the read title/scripture and runs past the window)."""
    prev = [0] * (len(hyp) + 1)
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    errs = min(prev)
    return errs / len(ref), errs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--words", type=int, default=1500)
    a = ap.parse_args()
    t = json.loads(a.transcript.read_text())
    n = t["meta"]["wesley_sermon_number"]
    ref = norm(ccel_body(n))[: a.words]
    s, e = t["searchable_start"], t["searchable_end"]
    hyp_words = [w[2] for seg in t["segments"] for w in seg["words"] if s <= w[0] < e]
    hyp = norm(" ".join(hyp_words))[: int(a.words * 1.3)]
    rate, errs = wer(ref, hyp)
    print(json.dumps({"id": t["meta"]["id"], "ref_words": len(ref), "errors": errs, "wer": round(rate, 4)}))


if __name__ == "__main__":
    main()
