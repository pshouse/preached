"""Sanity checks over finished transcripts (stdlib only).

    uv run ingest/qa.py

Reports per-file and total: coverage gaps (untranscribed stretches > 8 s),
unrepaired repetition loops, prompt leakage, and boilerplate detection counts.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest  # noqa: E402
import transcribe  # noqa: E402

GAP_S = 8.0  # silence/untranscribed stretch inside the searchable window worth a look


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
        loops = [" ".join(seg["text"].split()[:12]) for seg in t["segments"]
                 if not seg.get("boilerplate") and transcribe.has_loop(seg["words"])]
        if loops:
            notes.append(f"repeats={loops[:2]}")
        text = " ".join(s["text"] for s in t["segments"]).lower()
        # Readers say the work title in intro + outro; more may be prompt leakage.
        if text.count("several occasions") > 3:
            notes.append(f"prompt_leak={text.count('several occasions')}")
        lead = t["searchable_start"]
        tail = t["meta"]["duration_s"] - t["searchable_end"]
        if notes:
            tot["flagged"] += 1
            print(f"{r['id']}: lead={lead:.0f}s tail={tail:.0f}s " + " ".join(notes))
    print(json.dumps({**tot, "audio_h": round(audio_s / 3600, 2)}))


if __name__ == "__main__":
    main()
