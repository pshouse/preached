"""Whisper transcription with word timestamps (faster-whisper / CTranslate2)."""

import ctypes
import gc
import glob
import os
import re
import sys
import time
from pathlib import Path

TRANSCRIPT_DIR = Path("/cache/transcripts/wesley")
MODEL = "large-v3-turbo"  # OpenAI Whisper, CTranslate2 conversion (mobiuslabsgmbh)

# (compute_type, batch_size) tried in order; on CUDA OOM we step down the ladder.
LADDER = [("float16", 8), ("float16", 4), ("int8_float16", 4), ("int8_float16", 1)]


def _preload_cuda_libs() -> None:
    """Load cuBLAS/cuDNN from the nvidia-* wheels so no LD_LIBRARY_PATH is needed."""
    site = Path(__file__).resolve().parent.parent / ".venv"
    for base in [*sys.path, str(site)]:
        libs = sorted(glob.glob(os.path.join(base, "**/nvidia/*/lib/lib*.so.*"), recursive=True))
        if libs:
            break
    # cublasLt before cublas, cudnn sublibs after libcudnn: order by dependency.
    order = ["cublasLt", "cublas", "nvrtc", "cudnn.so", "cudnn_"]
    for key in order:
        for lib in libs:
            if key in os.path.basename(lib) and "alt" not in lib and "nvblas" not in lib:
                try:
                    ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


def is_oom(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "out of memory" in msg or "alloc_failed" in msg or "cudaerrormemoryallocation" in msg


class Transcriber:
    def __init__(self, model: str = MODEL, rung: int = 0):
        _preload_cuda_libs()
        import faster_whisper  # noqa: F401  (after preload)

        self.model_name = model
        self.rung = rung
        self._model = None
        self._pipe = None

    @property
    def compute_type(self) -> str:
        return LADDER[self.rung][0]

    @property
    def batch_size(self) -> int:
        return LADDER[self.rung][1]

    def _load(self) -> None:
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        if self._model is None:
            self._model = WhisperModel(self.model_name, device="cuda", compute_type=self.compute_type)
            self._pipe = BatchedInferencePipeline(self._model)

    def _step_down(self) -> None:
        old_ct = self.compute_type
        self.rung += 1
        if self.rung >= len(LADDER):
            raise RuntimeError("CUDA OOM even at the smallest setting")
        if self.compute_type != old_ct:
            self._model = self._pipe = None
            gc.collect()
        print(f"[oom] backing off to {LADDER[self.rung]}", file=sys.stderr, flush=True)
        time.sleep(10)  # let the other GPU tenant's spike pass

    def transcribe(self, audio_path: Path, prompt: str | None = None) -> tuple[list[dict], dict]:
        """`prompt`: a short punctuated line. Without one, batched Whisper (both
        large-v3 and turbo) emits lowercase unpunctuated text and silently drops
        the spoken LibriVox disclaimer; with one, both are transcribed."""
        from faster_whisper import decode_audio

        audio = decode_audio(str(audio_path))
        while True:
            self._load()
            try:
                segs, info = self._pipe.transcribe(
                    audio,
                    language="en",
                    batch_size=self.batch_size,
                    word_timestamps=True,
                    beam_size=5,
                    initial_prompt=prompt,
                )
                segments = [
                    {
                        "start": round(s.start, 2),
                        "end": round(s.end, 2),
                        "text": s.text.strip(),
                        "words": [[round(w.start, 2), round(w.end, 2), w.word.strip()] for w in s.words or []],
                    }
                    for s in segs  # generator: errors surface here
                ]
                return segments, {"duration_s": round(info.duration, 2), "language": info.language}
            except RuntimeError as e:
                if not is_oom(e):
                    raise
                self._step_down()

    def runtime_info(self) -> dict:
        import ctranslate2
        import faster_whisper

        return {
            "name": "faster-whisper",
            "version": faster_whisper.__version__,
            "ctranslate2": ctranslate2.__version__,
            "compute_type": self.compute_type,
            "batch_size": self.batch_size,
            "beam_size": 5,
            "vad": "silero (BatchedInferencePipeline default)",
        }


# --- LibriVox boilerplate -------------------------------------------------------
# Intro: "Section 1 of Sermons on Several Occasions. This is a LibriVox recording.
# All LibriVox recordings are in the public domain. For more information or to
# volunteer, please visit librivox.org. Recording by X."
# Outro: "End of section 1. Recording by X, <place>. This recording is in the public domain."
# Batched Whisper usually drops these phrases itself; when it does transcribe
# them we mark them. We never cut audio or shift timestamps: we only mark the
# searchable window [searchable_start, searchable_end) on the original timeline.

_BOILER = re.compile(
    r"libri ?vox|public domain|to volunteer|for more information|please visit|"
    r"\b(read|recorded|recording) (by|for)\b|"
    r"\bend of (the )?(sermon|section|chapter|preface|discourse|book)\b|"
    r"\b(sermon|section|chapter) \S+ of sermons on several occasions\b",
    re.I,
)
INTRO_WINDOW_S = 120.0
OUTRO_WINDOW_S = 120.0
MAX_CREDIT_WORDS = 12  # "Recording by <name, place>" tail after a match


def _ends_sentence(word: str) -> bool:
    return bool(re.search(r"[.!?][\"')\]]*$", word))


def mark_boilerplate(segments: list[dict], duration: float) -> dict:
    words = [w for seg in segments for w in seg["words"]]
    if not words:
        return {"searchable_start": 0.0, "searchable_end": round(duration, 2),
                "boilerplate_intro": "", "boilerplate_outro": ""}
    # Character offset of each word in the joined text, to map regex hits to words.
    offs, pos = [], 0
    for w in words:
        offs.append(pos)
        pos += len(w[2]) + 1
    text = " ".join(w[2] for w in words)

    def word_at(char: int) -> int:
        lo, hi = 0, len(offs) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offs[mid] <= char:
                lo = mid
            else:
                hi = mid - 1
        return lo

    hits = [(word_at(m.start()), word_at(max(m.end() - 1, m.start()))) for m in _BOILER.finditer(text)]

    # Intro ends at the sentence end after the last hit inside the intro window.
    first = 0
    intro_hits = [h for h in hits if words[h[0]][0] <= INTRO_WINDOW_S]
    if intro_hits:
        k = intro_hits[-1][1]
        limit = min(k + MAX_CREDIT_WORDS, len(words) - 1)
        while k < limit and not _ends_sentence(words[k][2]):
            k += 1
        first = k + 1
    # Outro starts at the first hit inside the outro window (after the intro).
    last = len(words)
    outro_hits = [h for h in hits if words[h[0]][0] >= duration - OUTRO_WINDOW_S and h[0] >= first]
    if outro_hits:
        last = outro_hits[0][0]

    start = words[first][0] if first < len(words) else words[-1][1]
    end = words[last - 1][1] if last > first else start
    for seg in segments:
        if seg["end"] <= start or seg["start"] >= end:
            seg["boilerplate"] = True
    return {
        "searchable_start": round(start, 2),
        "searchable_end": round(end, 2),
        "boilerplate_intro": " ".join(w[2] for w in words[:first]),
        "boilerplate_outro": " ".join(w[2] for w in words[last:]),
    }
