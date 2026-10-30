"""Measure the `shifted` margin: how far past a redacted name the shifted seek lands.

    uv run scripts/measure_shift_margin.py [--library wesley spurgeon edwards]

Runs the frozen redaction rules (privacy.Config(), no library names) over the
public-domain ASR transcripts in /cache/transcripts/<library> and chunks them
as the church ASR path does (align/asr_chunks.py). For every flagged chunk it
computes the shifted seek exactly as the product would (audio_policy.flagged_play
for an audio file, listing.watch_url for a YouTube t=) and reports, against
Whisper's recorded end of the last [name] word in the chunk:

- margin: seek - name end (seconds), for the audio-file seek and the YouTube t=;
- gap: start of the next spoken word - name end;
- skipped: words after the name that start before the seek (speech the
  listener loses);
- withheld: chunks where the shift leaves no audio (the policy gives no link).

Prints numbers only, never a word. Not church audio (none is permitted yet),
and measured against Whisper's word times, not the acoustic end of the name:
W1-C's spot check put Whisper word onsets |delta| median 0.42 s, max 0.76 s.
`shifted` is not selectable in the product (Patrick chose `none`).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "align"))

from asr_chunks import asr_chunks, transcript_words  # noqa: E402
from preached.audio_policy import SHIFT_MARGIN_S, flagged_play  # noqa: E402
from preached.corpus import load_chunk_config  # noqa: E402
from preached.paths import CACHE_ROOT  # noqa: E402
from preached.privacy import Config, redact  # noqa: E402
from preached.youtube.listing import watch_url  # noqa: E402

VIDEO = "aaaaaaaaaaa"  # any valid 11-character id; only t= is read


def summary(values: list[float]) -> str:
    if not values:
        return "n=0"
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
    return (f"n={len(values)} min={ordered[0]:.2f} median={statistics.median(ordered):.2f} "
            f"p90={p90:.2f} max={ordered[-1]:.2f}")


def measure(path: Path, config: dict, privacy: Config, out: dict) -> None:
    transcript = json.loads(path.read_text())
    sermon_id = transcript.get("meta", {}).get("id") or path.stem
    transcript.setdefault("meta", {})["id"] = sermon_id
    words = redact(transcript_words(transcript), config=privacy, source=sermon_id)
    for chunk in asr_chunks(transcript, config, privacy=privacy):
        flag_end = chunk["flag_end_s"]
        if flag_end is None:
            continue
        out["flagged"] += 1
        allowed, seek = flagged_play(chunk["start_s"], chunk["end_s"], flag_end, "shifted")
        if not allowed:
            out["withheld"] += 1
            continue
        url = watch_url(VIDEO, chunk["start_s"], end_s=chunk["end_s"], flag_end_s=flag_end, policy="shifted")
        t = int(parse_qs(urlsplit(url).query)["t"][0].rstrip("s")) if url else None
        later = [w for w in words if w[0] >= flag_end - 1e-9]
        out["margin_audio"].append(seek - flag_end)
        if t is not None:
            out["margin_youtube"].append(t - flag_end)
            out["skipped_youtube"].append(sum(1 for w in later if w[0] < t))
        if later:
            out["gap"].append(later[0][0] - flag_end)
        out["skipped_audio"].append(sum(1 for w in later if w[0] < seek))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--library", nargs="+", default=["wesley", "spurgeon", "edwards"])
    args = ap.parse_args()
    config = load_chunk_config(ROOT / "corpus" / "chunk_config.json")
    privacy = Config()
    out = {"flagged": 0, "withheld": 0, "margin_audio": [], "margin_youtube": [], "gap": [],
           "skipped_audio": [], "skipped_youtube": []}
    files = 0
    for library in args.library:
        for path in sorted((CACHE_ROOT / "transcripts" / library).glob("*.json")):
            measure(path, config, privacy, out)
            files += 1
    print(f"transcripts: {files} ({', '.join(args.library)}); SHIFT_MARGIN_S={SHIFT_MARGIN_S}")
    print(f"flagged chunks: {out['flagged']}; withheld by the shift (no audio left): {out['withheld']}")
    print(f"margin, audio-file seek (s):  {summary(out['margin_audio'])}")
    print(f"margin, YouTube t= (s):       {summary(out['margin_youtube'])}")
    print(f"gap to the next word (s):     {summary(out['gap'])}")
    print(f"words skipped, audio seek:    {summary([float(x) for x in out['skipped_audio']])}")
    print(f"words skipped, YouTube t=:    {summary([float(x) for x in out['skipped_youtube']])}")
    for label, key, limit in (("audio", "margin_audio", 0.76), ("YouTube", "margin_youtube", 0.76)):
        values = out[key]
        if values:
            short = sum(1 for v in values if v < limit)
            print(f"{label}: {short}/{len(values)} seeks land less than {limit} s (W1-C max onset error) past the name end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
