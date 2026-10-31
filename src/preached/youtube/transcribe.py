"""Thin faster-whisper adapter.

``transcribe(audio_path) -> list[Word]`` with ``start``, ``end``, and ``text``
in seconds on the file timeline. W1-A's ingest package is not on this branch.
That pipeline (batched large-v3-turbo, gap fill, loop repair) should replace
this adapter once ``feat/w1-ingest`` merges. This file does not copy it.

The 3060 is shared. If ``nvidia-smi`` reports more than 6 GB in use, or it
cannot be read, transcription stays on CPU with the small English ``tiny.en``
model. Otherwise it uses the cached OpenAI large-v3-turbo conversion
(Mobius Labs, Berlin), the same weights W1-A already checked.
"""

from __future__ import annotations

import gc
import subprocess
import sys
from pathlib import Path

from preached import env as _env  # noqa: F401  (HF_HOME=/cache before weights download)
from preached.cpu_guard import avoid_amx
from preached.youtube.words import Word

# More than this much GPU memory already in use means leave the card alone.
GPU_BUSY_MIB = 6 * 1024
GPU_MODEL = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
CPU_MODEL = "tiny.en"
INITIAL_PROMPT = "English speech, with punctuation."


def gpu_used_mib() -> int | None:
    """Current GPU memory in MiB, or None when nvidia-smi cannot be read."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    line = result.stdout.strip().splitlines()
    if not line:
        return None
    try:
        return int(line[0].strip())
    except ValueError:
        return None


def transcribe(audio_path: Path) -> list[Word]:
    """Word timestamps for one audio file. English. No generated summary."""
    used = gpu_used_mib()
    if used is not None and used <= GPU_BUSY_MIB:
        print(
            f"transcribe device=cuda model={GPU_MODEL} gpu_used_mib={used}",
            file=sys.stderr,
            flush=True,
        )
        try:
            return _run(audio_path, device="cuda", compute_type="int8_float16", model_name=GPU_MODEL)
        except RuntimeError as exc:
            message = str(exc).lower()
            if "memory" not in message and "cuda" not in message:
                raise
            print(f"transcribe cuda failed ({exc}); falling back to CPU", file=sys.stderr, flush=True)
    else:
        print(
            f"transcribe device=cpu model={CPU_MODEL} gpu_used_mib={used}",
            file=sys.stderr,
            flush=True,
        )
    return _run(audio_path, device="cpu", compute_type="int8", model_name=CPU_MODEL)


def _preload_cuda_libs() -> None:
    """Load cuBLAS and cuDNN from the nvidia wheels.

    This machine has no driver-side CUDA toolkit on the library path.
    ctranslate2 asks for ``libcublas.so.12`` by soname. The wheel ships the
    file, but Python does not add that directory to the loader path.
    """
    import ctypes
    import glob

    roots: list[Path] = []
    for name in ("nvidia.cublas", "nvidia.cuda_nvrtc", "nvidia.cudnn"):
        try:
            module = __import__(name, fromlist=["_"])
        except ImportError:
            continue
        for location in getattr(module, "__path__", ()):
            roots.append(Path(location) / "lib")
    libs: list[str] = []
    for root in roots:
        libs.extend(glob.glob(str(root / "lib*.so*")))
    loaded: set[str] = set()
    for key in ("cublasLt", "cublas", "nvrtc", "cudnn.so", "cudnn_"):
        for lib in libs:
            base = Path(lib).name
            if key not in base or "nvblas" in base or lib in loaded:
                continue
            loaded.add(lib)
            try:
                ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                continue


def _run(audio_path: Path, *, device: str, compute_type: str, model_name: str) -> list[Word]:
    # Before ctranslate2 loads: MKL's AMX int8 kernels corrupt the output (preached.cpu_guard).
    avoid_amx()
    if device == "cuda":
        _preload_cuda_libs()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: uv sync --extra transcribe"
        ) from exc

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    try:
        segments, _info = model.transcribe(
            str(audio_path),
            language="en",
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
            # A short punctuated prompt. Batched mode is not used here.
            # W1-A found batched decoding without a prompt drops punctuation.
            initial_prompt=INITIAL_PROMPT,
        )
        words: list[Word] = []
        for segment in segments:
            for token in segment.words or []:
                text = (token.word or "").strip()
                if not text:
                    continue
                start = float(token.start)
                end = float(token.end)
                if end < start:
                    end = start
                words.append(Word(start, end, text))
        words.sort(key=lambda word: (word.start, word.end))
        return words
    finally:
        del model
        gc.collect()
