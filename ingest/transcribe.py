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

    def transcribe(self, audio_path: Path) -> tuple[list[dict], dict]:
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
# Intro: "Sermon 1 of Sermons on Several Occasions. This is a LibriVox recording.
# All LibriVox recordings are in the public domain. For more information or to
# volunteer, please visit librivox.org. [Read/Recording by X.]"
# Outro: "End of sermon 1. [Read by X.] This recording is in the public domain."
# We never cut audio or shift timestamps; we only mark the searchable window.

_BOILER = re.compile(
    r"libri ?vox|public domain|to volunteer|for more information|"
    r"\b(read|recorded|recording) (by|for)\b|\bend of (the )?(sermon|section|chapter|preface|discourse|book)\b|"
    r"\b(sermon|section|chapter)s? \w+ of sermons on several occasions\b|"
    r"please visit|dot org",
    re.I,
)
INTRO_WINDOW_S = 120.0
OUTRO_WINDOW_S = 120.0


def _sentences(segments: list[dict]) -> list[tuple[float, float, str]]:
    """Split the word stream into sentences on terminal punctuation."""
    out, cur = [], []
    for seg in segments:
        for w in seg["words"]:
            cur.append(w)
            if re.search(r"[.!?][\"')\]]*$", w[2]):
                out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
                cur = []
    if cur:
        out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
    return out


def mark_boilerplate(segments: list[dict], duration: float) -> dict:
    sents = _sentences(segments)
    start, end = 0.0, duration
    intro, outro = [], []
    if sents:
        # Last boilerplate sentence within the intro window ends the intro.
        last = None
        for i, (s, e, t) in enumerate(sents):
            if s > INTRO_WINDOW_S:
                break
            if _BOILER.search(t):
                last = i
        if last is not None:
            intro = sents[: last + 1]
            start = sents[last + 1][0] if last + 1 < len(sents) else sents[last][1]
        # First boilerplate sentence within the outro window starts the outro.
        first = None
        for i in range(len(sents) - 1, -1, -1):
            s, e, t = sents[i]
            if e < duration - OUTRO_WINDOW_S or (intro and i <= last):
                break
            if _BOILER.search(t):
                first = i
        if first is not None:
            outro = sents[first:]
            end = sents[first - 1][1] if first > 0 else sents[first][0]
    for seg in segments:
        if seg["end"] <= start or seg["start"] >= end:
            seg["boilerplate"] = True
    return {
        "searchable_start": round(start, 2),
        "searchable_end": round(end, 2),
        "boilerplate_intro": " ".join(t for _, _, t in intro),
        "boilerplate_outro": " ".join(t for _, _, t in outro),
    }
