"""Sanity checks over finished transcripts (stdlib only).

    uv run ingest/qa.py

Reports per-file and total: coverage gaps (long untranscribed stretches),
repetition loops, prompt leakage, and boilerplate detection counts.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest  # noqa: E402
import transcribe  # noqa: E402

GAP_S = 20.0  # silence/untranscribed stretch inside the searchable window worth a look
LOOP_N = 8  # an 8-gram repeated 3+ times suggests a decoding loop


def main() -> None:
    rows = manifest.load()
    tot = Counter()
    audio_s = 0.0
    for r in rows:
        p = transcribe.TRANSCRIPT_DIR / f"{r['id']}.json"
        if not p.exists():
            tot["missing"] += 1
            continue
        t = json.loads(p.read_text())
        tot["files"] += 1
        audio_s += t["meta"]["duration_s"]
        words = [w for s in t["segments"] for w in s["words"]]
        tot["words"] += len(words)
        tot["intro_marked"] += bool(t["boilerplate_intro"])
        tot["outro_marked"] += bool(t["boilerplate_outro"])
        notes = []
        inside = [w for w in words if t["searchable_start"] <= w[0] < t["searchable_end"]]
        gaps = [(round(a[1]), round(b[0] - a[1])) for a, b in zip(inside, inside[1:]) if b[0] - a[1] > GAP_S]
        if gaps:
            notes.append(f"gaps(at,len)={gaps}")
        toks = [re.sub(r"\W", "", w[2].lower()) for w in words]
        grams = Counter(tuple(toks[i : i + LOOP_N]) for i in range(len(toks) - LOOP_N))
        loops = [" ".join(g) for g, c in grams.items() if c >= 3]
        if loops:
            notes.append(f"repeats={loops[:2]}")
        text = " ".join(s["text"] for s in t["segments"]).lower()
        if text.count("several occasions") > 2:
            notes.append(f"prompt_leak={text.count('several occasions')}")
        lead = t["searchable_start"]
        tail = t["meta"]["duration_s"] - t["searchable_end"]
        if notes:
            tot["flagged"] += 1
            print(f"{r['id']}: lead={lead:.0f}s tail={tail:.0f}s " + " ".join(notes))
    print(json.dumps({**tot, "audio_h": round(audio_s / 3600, 2)}))


if __name__ == "__main__":
    main()
