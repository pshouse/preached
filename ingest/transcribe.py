"""Whisper transcription with word timestamps (faster-whisper / CTranslate2)."""

import ctypes
import gc
import glob
import os
import re
import sys
import time
from pathlib import Path

import preached.env  # noqa: F401  (HF_HOME under PREACHED_CACHE before any HF import)
from preached.paths import CACHE_ROOT

TRANSCRIPT_DIR = CACHE_ROOT / "transcripts" / "wesley"
# OpenAI Whisper large-v3-turbo, CTranslate2 conversion. Pinned to a commit
# (PR #2 rule). The repo was created by Mobius Labs and has since moved to
# dropbox-dash/faster-whisper-large-v3-turbo; the old id redirects, and we keep
# it because it is the id the weights are cached under in /cache/huggingface
# (models--mobiuslabsgmbh--faster-whisper-large-v3-turbo). The revision is the
# only snapshot in that cache and the one all 143 Wesley transcripts used.
MODEL = "large-v3-turbo"
MODEL_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
MODEL_REVISION = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"

SR = 16000
GAP_FILL_S = 4.0  # re-decode untranscribed stretches longer than this

# (compute_type, batch_size) tried in order; on CUDA OOM we step down the ladder.
LADDER = [("float16", 8), ("float16", 4), ("int8_float16", 4), ("int8_float16", 1)]


def _preload_cuda_libs() -> None:
    """Load cuBLAS/cuDNN from the nvidia-* wheels so no LD_LIBRARY_PATH is needed."""
    site = Path(__file__).resolve().parent.parent / ".venv"
    libs: list[str] = []
    # Glob the wheel layout directly; a recursive glob of every sys.path entry is slow.
    for pattern in [os.path.join(b, "nvidia/*/lib/lib*.so.*") for b in sys.path if b] + [
        str(site / "lib/python*/site-packages/nvidia/*/lib/lib*.so.*")
    ]:
        libs = sorted(glob.glob(pattern))
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


def _word(w, offset: float) -> list:
    return [round(w.start + offset, 2), round(w.end + offset, 2), w.word.strip()]


def _segment(s, offset: float) -> dict:
    return {
        "start": round(s.start + offset, 2),
        "end": round(s.end + offset, 2),
        "text": s.text.strip(),
        "words": [_word(w, offset) for w in s.words or []],
    }


LOOP_MAX_N = 4
LOOP_MIN_REPS = 4  # "Holy, holy, holy" (3) and "Lord, Lord" are legitimate


def _loop_at(toks: list[str], i: int) -> int:
    """Length n of an n-gram starting at i repeated LOOP_MIN_REPS+ times back-to-back, else 0."""
    for n in range(1, LOOP_MAX_N + 1):
        if i + n * LOOP_MIN_REPS > len(toks):
            break
        if all(toks[i + k * n : i + (k + 1) * n] == toks[i : i + n] for k in range(1, LOOP_MIN_REPS)):
            return n
    return 0


def has_loop(words: list[list]) -> bool:
    toks = [_norm(w[2]) for w in words]
    return any(_loop_at(toks, i) for i in range(len(toks)))


def collapse_loops(words: list[list]) -> list[list]:
    """Keep the first two repeats of any looping n-gram, drop the rest."""
    toks = [_norm(w[2]) for w in words]
    out, i = [], 0
    while i < len(words):
        n = _loop_at(toks, i)
        if not n:
            out.append(words[i])
            i += 1
            continue
        j = i
        while toks[j : j + n] == toks[i : i + n]:
            j += n
        out.extend(words[i : i + 2 * n])
        i = j
    return out


def _hallucinated(seg: dict) -> bool:
    """Whisper invents stock phrases on near-silence ("We'll be right back.",
    "Next slide, please.", "Thank you.") when re-decoding near-silence, always
    with an impossible span/speaking rate or low confidence."""
    span = seg["words"][-1][1] - seg["words"][0][0]
    rate = len(seg["words"]) / max(span, 1e-3)
    return span < 0.5 or rate > 6.0 or seg["_nsp"] > 0.6 or seg["_lp"] < -1.0


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def is_oom(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "out of memory" in msg or "alloc_failed" in msg or "cudaerrormemoryallocation" in msg


class Transcriber:
    def __init__(self, model: str = MODEL, rung: int = 0,
                 repo: str = MODEL_REPO, revision: str = MODEL_REVISION):
        _preload_cuda_libs()
        import faster_whisper  # noqa: F401  (after preload)

        self.model_name = model
        self.model_repo = repo
        self.revision = revision
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
            self._model = WhisperModel(self.model_repo, revision=self.revision,
                                       device="cuda", compute_type=self.compute_type)
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
        """One batched pass over the whole file, with Whisper timestamp tokens on.

        `without_timestamps=False` matters: faster-whisper's batched default
        decodes without timestamp tokens, and when Whisper skips speech (it
        routinely drops the spoken LibriVox disclaimer, and sometimes a
        Scripture reading) the word aligner smears the remaining words over the
        skipped audio: up to ~18 s early, plus 25 s of lost content in one file.
        `prompt` is a short punctuated line: without one, batched Whisper emits
        lowercase, unpunctuated text.
        """
        from faster_whisper import decode_audio

        audio = decode_audio(str(audio_path))

        def run():
            segs, info = self._pipe.transcribe(
                audio,
                language="en",
                batch_size=self.batch_size,
                word_timestamps=True,
                without_timestamps=False,
                beam_size=5,
                initial_prompt=prompt,
            )
            segments = [_segment(s, 0.0) for s in segs]  # generator: errors surface here
            return segments, {"duration_s": round(len(audio) / SR, 2), "language": info.language}

        segments, info = self._oom_retry(run)
        info["gaps_filled"] = self.fill_gaps(audio, segments, prompt)
        info["repaired"] = self.repair_loops(audio, segments, prompt)
        for seg in segments:
            seg.pop("_nsp", None)
            seg.pop("_lp", None)
        return segments, info

    def _decode(self, audio, t0: float, t1: float, prompt: str | None, vad: bool) -> list[dict]:
        """Sequential decode of audio[t0:t1] (has temperature/compression fallback)."""

        def run():
            out, _ = self._model.transcribe(
                audio[int(t0 * SR) : int(t1 * SR)],
                language="en",
                word_timestamps=True,
                beam_size=5,
                vad_filter=vad,
                condition_on_previous_text=False,
                initial_prompt=prompt,
            )
            return [{**_segment(s, t0), "_nsp": s.no_speech_prob, "_lp": s.avg_logprob} for s in out]

        return [s for s in self._oom_retry(run) if s["words"]]

    def fill_gaps(self, audio, segments: list[dict], prompt: str | None) -> int:
        """Re-decode untranscribed stretches longer than GAP_FILL_S (incl. the head
        and tail of the file). Batched Whisper occasionally skips speech: a
        sentence or two mid-sermon, and nearly always the LibriVox disclaimer.
        VAD is on here, so a real pause yields nothing; only words inside the
        gap are inserted. Filled segments are flagged `gap_filled`. Edits
        `segments` in place; returns the number of gaps that yielded words."""
        duration = len(audio) / SR
        segments.sort(key=lambda seg: seg["start"])
        bounds = [0.0] + [x for seg in segments for x in (seg["start"], seg["end"])] + [duration]
        gaps = [(bounds[k], bounds[k + 1]) for k in range(0, len(bounds), 2)
                if bounds[k + 1] - bounds[k] > GAP_FILL_S]
        filled = 0
        for t0, t1 in gaps:
            new = []
            for seg in self._decode(audio, t0, t1, prompt, vad=True):
                seg["words"] = [w for w in seg["words"] if w[0] >= t0 - 0.05 and w[1] <= t1 + 0.05]
                if seg["words"] and not _hallucinated(seg):
                    seg.update(start=seg["words"][0][0], end=seg["words"][-1][1],
                               text=" ".join(w[2] for w in seg["words"]), gap_filled=True)
                    new.append(seg)
            if new:
                filled += 1
                segments.extend(new)
        segments.sort(key=lambda seg: seg["start"])
        return filled

    def repair_loops(self, audio, segments: list[dict], prompt: str | None) -> int:
        """Re-decode segments caught in a repetition loop (e.g. "Toe, Toe, Toe, ..."
        where a reader voices Greek). Batched decoding has no temperature
        fallback; sequential decoding does (compression-ratio check). The span
        runs to the next segment's start so words cut off by the loop are
        recovered. If the loop survives, repeats are collapsed and the segment is
        flagged `asr_suspect`. Edits `segments` in place; returns segments fixed."""
        fixed = 0
        i = 0
        while i < len(segments):
            seg = segments[i]
            if seg.get("boilerplate") or not has_loop(seg["words"]):
                i += 1
                continue
            t1 = segments[i + 1]["start"] if i + 1 < len(segments) else len(audio) / SR
            new = [x for x in self._decode(audio, seg["start"], t1, prompt, vad=False)
                   if not _hallucinated(x)]
            for s in new:
                s["redecoded"] = True
                if has_loop(s["words"]):
                    s["words"] = collapse_loops(s["words"])
                    s["text"] = " ".join(w[2] for w in s["words"])
                    s["asr_suspect"] = True
            segments[i : i + 1] = new
            fixed += 1
            i += max(len(new), 1)
        return fixed

    def _oom_retry(self, fn):
        while True:
            self._load()
            try:
                return fn()
            except RuntimeError as e:
                if not is_oom(e):
                    raise
                self._step_down()

    def runtime_info(self) -> dict:
        import ctranslate2
        import faster_whisper

        return {
            "name": "faster-whisper",
            "model_repo": self.model_repo,
            "model_revision": self.revision,
            "version": faster_whisper.__version__,
            "ctranslate2": ctranslate2.__version__,
            "compute_type": self.compute_type,
            "batch_size": self.batch_size,
            "beam_size": 5,
            "vad": "silero (BatchedInferencePipeline default)",
            "timestamps": "without_timestamps=False",
        }


# --- LibriVox boilerplate -------------------------------------------------------
# Intro: "Section 1 of Sermons on Several Occasions. This is a LibriVox recording.
# All LibriVox recordings are in the public domain. For more information or to
# volunteer, please visit librivox.org. Recording by X."
# Outro: "End of section 1. Recording by X, <place>. This recording is in the public domain."
# Whisper usually drops the intro itself (and often the outro); whatever it
# does transcribe we mark. We never cut audio or shift timestamps: we only mark the
# searchable window [searchable_start, searchable_end) on the original timeline.

_BOILER = re.compile(
    r"libri ?vox|public domain|to volunteer|for more information|please visit|"
    r"\b(read|reading|recorded|recording) (by|for)\b|"
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
