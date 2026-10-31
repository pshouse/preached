"""Run the ASR coverage gate over every Wesley transcript, at one or more REL_DB values.

The false-positive check for ``preached.youtube.coverage``: Wesley's GPU
transcripts are complete apart from what Whisper is known to drop, so every
span flagged here should be speech the ASR really dropped. Frame levels are
cached in ``--levels`` so trying another threshold does not decode again.

    uv run python scripts/coverage_sweep.py --rel-db 40 45 --json /cache/w3-asr/sweep.json

Prints, per threshold: files and spans flagged, spans inside the searchable
window, spans not explained by a stretched word, and the density margin
(words per second of sound) of unflagged windows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import preached.youtube.coverage as coverage  # noqa: E402
from preached.youtube.words import Word  # noqa: E402


def levels(transcript: dict, audio_dir: Path, cache: Path) -> np.ndarray:
    name = Path(transcript["meta"]["audio_url"]).name
    cached = cache / f"{transcript['meta']['id']}.npy"
    if cached.exists():
        return np.load(cached)
    db = coverage.frame_db(coverage.decode_audio(audio_dir / name)).astype(np.float32)
    np.save(cached, db)
    return db


def density_margin(sound, words, flagged) -> list[float]:
    """Words per second of sound in every window the density rule checks and did not flag.

    Words are counted as ``coverage.sparse_spans`` counts them: one per
    distinct start time, when that start's longest word overlaps the window.
    """
    latest: dict[float, float] = {}
    for w in words:
        latest[float(w.start)] = max(latest.get(float(w.start), float(w.start)), float(w.end))
    out = []
    t = 0.0
    total = sound[-1].end_s if sound else 0.0
    while t < total:
        a, b = t, t + coverage.DENSITY_WINDOW_S
        t += coverage.DENSITY_STEP_S
        if any(s.start_s < b and s.end_s > a for s in flagged):
            continue
        heard = sum(min(s.end_s, b) - max(s.start_s, a) for s in sound if s.end_s > a and s.start_s < b)
        if heard >= coverage.DENSITY_MIN_SOUND_S:
            count = sum(1 for start, end in latest.items() if start < b and end > a)
            out.append(count / heard)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--transcripts", type=Path, default=Path("/cache/transcripts/wesley"))
    parser.add_argument("--audio", type=Path, default=Path("/cache/audio/wesley"))
    parser.add_argument("--levels", type=Path, default=Path("/cache/w3-asr/levels"))
    parser.add_argument("--rel-db", type=float, nargs="+", default=[coverage.REL_DB])
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    args.levels.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in args.transcripts.glob("wesley-*.json"))
    loaded = []
    for path in files:
        transcript = json.loads(path.read_text())
        words = [Word(float(a), float(b), t) for seg in transcript["segments"] for a, b, t in seg["words"]]
        loaded.append((transcript, words, levels(transcript, args.audio, args.levels)))
    print(f"{len(loaded)} transcripts", file=sys.stderr)

    report = {}
    for rel_db in args.rel_db:
        rows = []
        margins: list[float] = []
        with patch.object(coverage, "REL_DB", rel_db):
            for transcript, words, db in loaded:
                sound = coverage.sound_spans_from_db(db)
                spans = coverage.open_spans(sound, words)
                stretched = coverage.stretched_spans(sound, words)
                window = (transcript.get("searchable_start"), transcript.get("searchable_end"))
                for span in spans:
                    inside = window[0] is not None and span.end_s > window[0] and span.start_s < window[1]
                    long_words = [
                        (w.start, w.end, w.text) for w in words
                        if w.end - w.start > coverage.LONG_WORD_S and w.end > span.start_s and w.start < span.end_s
                    ]
                    rows.append({
                        "id": transcript["meta"]["id"],
                        "start_s": span.start_s,
                        "end_s": span.end_s,
                        "inside_window": inside,
                        "long_words": long_words,
                        "stretched_rule": any(s.start_s < span.end_s and s.end_s > span.start_s for s in stretched),
                    })
                margins.extend(density_margin(sound, words, spans))
        inside = [r for r in rows if r["inside_window"]]
        unexplained = [r for r in inside if not r["long_words"]]
        summary = {
            "rel_db": rel_db,
            "files_flagged": len({r["id"] for r in rows}),
            "spans": len(rows),
            "spans_inside_window": len(inside),
            "inside_without_long_word": len(unexplained),
            "spans_from_stretched_rule": sum(r["stretched_rule"] for r in rows),
            "density_p5": round(float(np.percentile(margins, 5)), 2) if margins else None,
            "density_min": round(float(min(margins)), 2) if margins else None,
            "rows": rows,
        }
        report[str(rel_db)] = summary
        print(json.dumps({k: v for k, v in summary.items() if k != "rows"}))
        for r in inside:
            print(f"  {r['id']} {r['start_s']:.1f}-{r['end_s']:.1f} long_words={r['long_words']}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
