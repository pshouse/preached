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


def build(seconds: float, text: str) -> tuple[np.ndarray, list[list]]:
    """(audio, words) with a word every STEP_S from 1 s to seconds - 1 s."""
    tokens = text.split() or DEFAULT_TEXT.split()
    rng = np.random.default_rng(7)
    audio = rng.normal(0, 3e-5, int(seconds * SR)).astype(np.float32)  # room tone, about -90 dBFS
    words: list[list] = []
    cursor, index = 1.0, 0
    while cursor + STEP_S <= seconds - 1.0:
        a, b = cursor, cursor + WORD_S
        audio[int(a * SR) : int(b * SR)] += rng.normal(0, 0.08, int(b * SR) - int(a * SR)).astype(np.float32)
        words.append([round(a, 3), round(b, 3), tokens[index % len(tokens)]])
        cursor += STEP_S
        index += 1
    return audio, words


def write(folder: Path, sermon_id: str, seconds: float, text: str, title: str = "Synthetic sermon") -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    audio, words = build(seconds, text)
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
    args = parser.parse_args(argv)
    text = args.text_file.read_text() if args.text_file else args.text
    wav, transcript = write(args.folder, args.id, args.seconds, text)
    print(f"{wav}\n{transcript}")


if __name__ == "__main__":
    main()
