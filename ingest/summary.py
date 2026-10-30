"""Per-transcript verification table, small enough to commit (stdlib only).

    uv run ingest/summary.py            # writes reports/W1-A-transcripts.tsv

One row per manifest entry with the transcript's sha256 and structure, so the
full transcript set under $PREACHED_CACHE/transcripts/wesley can be checked
(or a re-run compared) without the data itself. `revision_source` is `meta`
when the transcript records its Whisper revision, else `hf-cache`: transcripts
written before the pin was recorded used the only snapshot in the HF cache,
which is transcribe.MODEL_REVISION (see reports/W1-A.md §2).
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest  # noqa: E402
import transcribe  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "reports" / "W1-A-transcripts.tsv"
COLUMNS = [
    "id", "duration_s", "segments", "words", "first_word_s", "last_word_s",
    "searchable_start", "searchable_end", "gaps_filled", "repaired_segments",
    "gap_filled_segs", "redecoded_segs", "asr_suspect_segs", "boilerplate_segs",
    "created", "timestamps", "model_repo", "model_revision", "revision_source", "sha256",
]


def row_for(path: Path) -> dict:
    raw = path.read_bytes()
    t = json.loads(raw)
    meta, segs = t["meta"], t["segments"]
    words = [w for s in segs for w in s["words"]]
    rt = meta.get("runtime", {})
    rev = meta.get("model_revision") or rt.get("model_revision")
    count = lambda flag: sum(bool(s.get(flag)) for s in segs)  # noqa: E731
    return {
        "id": meta["id"],
        "duration_s": f"{meta['duration_s']:.2f}",
        "segments": len(segs),
        "words": len(words),
        "first_word_s": f"{words[0][0]:.2f}" if words else "",
        "last_word_s": f"{words[-1][1]:.2f}" if words else "",
        "searchable_start": f"{t['searchable_start']:.2f}",
        "searchable_end": f"{t['searchable_end']:.2f}",
        "gaps_filled": meta.get("gaps_filled", ""),
        "repaired_segments": meta.get("repaired_segments", ""),
        "gap_filled_segs": count("gap_filled"),
        "redecoded_segs": count("redecoded"),
        "asr_suspect_segs": count("asr_suspect"),
        "boilerplate_segs": count("boilerplate"),
        "created": meta.get("created", ""),
        "timestamps": rt.get("timestamps", ""),
        "model_repo": meta.get("model_repo") or rt.get("model_repo") or transcribe.MODEL_REPO,
        "model_revision": rev or transcribe.MODEL_REVISION,
        "revision_source": "meta" if rev else "hf-cache",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> int:
    lines = ["\t".join(COLUMNS)]
    missing = []
    for r in manifest.load():
        p = transcribe.TRANSCRIPT_DIR / f"{r['id']}.json"
        if not p.exists():
            missing.append(r["id"])
            continue
        row = row_for(p)
        lines.append("\t".join(str(row[c]) for c in COLUMNS))
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(lines) - 1} rows -> {OUT}" + (f"; missing {missing}" if missing else ""), file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
