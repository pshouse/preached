"""Write a synthetic sermon that passes the ASR coverage gate honestly.

The YouTube end-to-end and adjacent-chunk probes used transcripts with no
audio behind them. Since #20 the library refuses to approve a sermon whose
words do not cover the sound in its recording, so those transcripts stopped at
``--ack-review``. This writes a matching pair: a WAV with a noise burst under
each word and room tone between words, and a church-path transcript JSON
whose word times are those bursts. ``check_coverage`` then finds no open span
because there is none. Nothing in the product is relaxed: the gate runs as
shipped. (Never pad a real transcript with placeholder words to get past it.)

Run the probe flow against a scratch cache, never /cache (PREACHED_CACHE
moves INDEX_DIR, which --ack-review reads):

  export PREACHED_CACHE=/tmp/probe-cache PREACHED_PRIVACY=privacy.toml
  uv run python scripts/synthetic_sermon.py /tmp/probe --id probe-1 --text-file words.txt
  uv run python align/asr_chunks.py /tmp/probe/probe-1.json --out /tmp/probe/c.jsonl \
      --library church --index /tmp/probe-cache/index/church.sqlite --audio-dir /tmp/probe
  uv run --extra youtube python import/youtube.py --library church --ack-review probe-1
  uv run python app/server.py --index /tmp/probe-cache/index/church.sqlite --library church

(``--text`` or ``--text-file`` is the sermon text, one word per beat; the
default is a short fixed phrase repeated.) ``--seconds`` sets the length.

The default rhythm is a fixed half second with no pauses, so most results come
back withheld and adjacent-chunk margin edge cases do not occur. Two flags,
both off by default (default output is unchanged), change that:

  --jitter-seed N   random word lengths and gaps, plus a pause of 1 to 4 s
                    every 15 to 40 words; the same N always writes the same pair
  --timings FILE    JSON list of [start_s, end_s] or [start_s, end_s, word]
                    taken as the word times (words from the text when omitted);
                    must be ordered, non-overlapping, inside the recording
tests/test_synthetic_sermon.py shows the same pair clearing the gate.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

SR = 16000
STEP_S = 0.5  # one word per half second, 0.3 s of it audible
WORD_S = 0.3
DEFAULT_TEXT = "grace abides in the quiet heart today"


def _fixed_times(seconds: float) -> list[tuple[float, float]]:
    times, cursor = [], 1.0
    while cursor + STEP_S <= seconds - 1.0:
        times.append((cursor, cursor + WORD_S))
        cursor += STEP_S
    return times


def _jitter_times(seconds: float, seed: int) -> list[tuple[float, float]]:
    """Word lengths 0.15-0.6 s, gaps 0.05-0.5 s, a 1-4 s pause every 15-40 words."""
    rng = np.random.default_rng(seed)
    times, cursor = [], 1.0
    until_pause = int(rng.integers(15, 41))
    while True:
        length = float(rng.uniform(0.15, 0.6))
        if cursor + length > seconds - 1.0:
            return times
        times.append((round(cursor, 3), round(cursor + length, 3)))
        cursor += length + float(rng.uniform(0.05, 0.5))
        until_pause -= 1
        if until_pause == 0:
            cursor += float(rng.uniform(1.0, 4.0))
            until_pause = int(rng.integers(15, 41))


def build(
    seconds: float, text: str, jitter_seed: int | None = None, timings: list[list] | None = None
) -> tuple[np.ndarray, list[list]]:
    """(audio, words). Default: a word every STEP_S from 1 s to seconds - 1 s."""
    tokens = text.split() or DEFAULT_TEXT.split()
    rng = np.random.default_rng(7)
    audio = rng.normal(0, 3e-5, int(seconds * SR)).astype(np.float32)  # room tone, about -90 dBFS
    if timings is not None:
        if not isinstance(timings, list):
            raise ValueError("timings must be a JSON list of [start_s, end_s] or [start_s, end_s, word]")
        for t in timings:
            if (
                not isinstance(t, list)
                or len(t) not in (2, 3)
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in t[:2])
                or (len(t) == 3 and not (isinstance(t[2], str) and t[2].strip()))
            ):
                raise ValueError(f"word time {t!r} is not [start_s, end_s] or [start_s, end_s, word]")
        times = [(float(t[0]), float(t[1])) for t in timings]
        tokens_for = [t[2] if len(t) > 2 else None for t in timings]
        last = 0.0
        for a, b in times:
            if not 0.0 <= last <= a < b <= seconds:
                raise ValueError(f"word time {a}-{b} is out of order or outside 0-{seconds} s")
            last = b
    else:
        times = _fixed_times(seconds) if jitter_seed is None else _jitter_times(seconds, jitter_seed)
        tokens_for = [None] * len(times)
    words: list[list] = []
    for index, ((a, b), word) in enumerate(zip(times, tokens_for)):
        audio[int(a * SR) : int(b * SR)] += rng.normal(0, 0.08, int(b * SR) - int(a * SR)).astype(np.float32)
        words.append([round(a, 3), round(b, 3), word or tokens[index % len(tokens)]])
    return audio, words


def write(
    folder: Path,
    sermon_id: str,
    seconds: float,
    text: str,
    title: str = "Synthetic sermon",
    jitter_seed: int | None = None,
    timings: list[list] | None = None,
) -> tuple[Path, Path]:
    audio, words = build(seconds, text, jitter_seed, timings)  # bad timings raise before anything is written
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / f"{sermon_id}.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    transcript = folder / f"{sermon_id}.json"
    transcript.write_text(json.dumps({
        "meta": {"id": sermon_id, "title": title, "audio_url": f"https://archive.org/download/synthetic/{sermon_id}.mp3",
                 "duration_s": seconds},
        "segments": [{"words": words}],
    }))
    return wav, transcript


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--id", default="probe-1")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--text-file", type=Path)
    parser.add_argument("--jitter-seed", type=int, default=None, help="random word lengths, gaps and pauses (deterministic per seed)")
    parser.add_argument("--timings", type=Path, help="JSON list of [start_s, end_s(, word)] to use as the word times")
    args = parser.parse_args(argv)
    if args.jitter_seed is not None and args.timings:
        parser.error("--jitter-seed and --timings are exclusive")
    text = args.text_file.read_text() if args.text_file else args.text
    try:
        timings = json.loads(args.timings.read_text()) if args.timings else None
    except (OSError, ValueError) as exc:
        parser.error(f"--timings: {exc}")
    try:
        wav, transcript = write(args.folder, args.id, args.seconds, text, jitter_seed=args.jitter_seed, timings=timings)
    except ValueError as exc:
        if timings is None:
            raise
        parser.error(f"--timings: {exc}")
    print(f"{wav}\n{transcript}")


if __name__ == "__main__":
    main()
