"""Measure transcript holes for one audio file under named Whisper settings.

  uv run --extra transcribe --extra youtube python scripts/asr_holes.py AUDIO \
      --device cpu --variant product --variant fixed

Prints uncovered non-silent spans (preached.youtube.coverage) per variant.
Not part of the product; it is how reports/W3-ASR-COVERAGE.md was measured.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import preached.env  # noqa: F401
from preached.cpu_guard import avoid_amx
from preached.youtube import transcribe as T
from preached.youtube.coverage import check_coverage, decode_audio, sound_spans
from preached.youtube.words import Word

VARIANTS = {
    # What import/youtube.py ran before this change.
    "product": {},
    "novad": {"vad_filter": False},
    "vad-low": {"vad_parameters": {"threshold": 0.3, "min_silence_duration_ms": 1000, "speech_pad_ms": 400}},
    "lowthresh": {"no_speech_threshold": 0.9, "log_prob_threshold": -2.0, "compression_ratio_threshold": 2.8},
    "vad-low-thresh": {
        "vad_parameters": {"threshold": 0.3, "min_silence_duration_ms": 1000, "speech_pad_ms": 400},
        "no_speech_threshold": 0.9, "log_prob_threshold": -2.0,
    },
    "temp0": {"temperature": 0.0},
}


def run(audio, model, kwargs):
    base = dict(language="en", word_timestamps=True, vad_filter=True, beam_size=5,
                condition_on_previous_text=False, initial_prompt=T.INITIAL_PROMPT)
    base.update(kwargs)
    segs, info = model.transcribe(audio, **base)
    words = []
    for s in segs:
        for w in s.words or []:
            if (w.word or "").strip():
                words.append(Word(float(w.start), float(w.end), w.word.strip()))
    return words


def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio", type=Path)
    p.add_argument("--device", default="cpu")
    p.add_argument("--model", default=T.GPU_MODEL)
    p.add_argument("--compute", default=None)
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--variant", action="append", default=[])
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    avoid_amx()
    if a.device == "cuda":
        T._preload_cuda_libs()
    from faster_whisper import WhisperModel
    compute = a.compute or ("int8_float16" if a.device == "cuda" else "int8")
    model = WhisperModel(a.model, device=a.device, compute_type=compute, cpu_threads=a.threads)
    audio = decode_audio(a.audio)
    sound = sum(s.length_s for s in sound_spans(audio))
    print(f"audio={len(audio)/16000:.1f}s sound={sound:.1f}s model={a.model} device={a.device} compute={compute}", flush=True)
    results = {}
    for name in a.variant or ["product"]:
        t0 = time.perf_counter()
        words = run(audio, model, VARIANTS[name])
        wall = time.perf_counter() - t0
        holes = check_coverage(a.audio, words, audio=audio)
        total = sum(h.length_s for h in holes)
        print(f"[{name}] words={len(words)} wall={wall:.0f}s holes={len(holes)} uncovered={total:.1f}s", flush=True)
        for h in holes:
            print(f"    {h.start_s:7.2f}-{h.end_s:7.2f} ({h.length_s:.1f}s)", flush=True)
        results[name] = {"words": len(words), "wall_s": round(wall), "holes": [[h.start_s, h.end_s] for h in holes],
                         "uncovered_s": round(total, 1)}
    if a.out:
        a.out.write_text(json.dumps(results, indent=1))


main()
