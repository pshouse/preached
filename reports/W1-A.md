# W1-A: Wesley ingest + transcription

Branch `feat/w1-ingest`. Code in `ingest/`. Report written 2026-10-30.

## 1. What was done

- **Manifest** `ingest/manifest/wesley.jsonl`: 143 files (54 + 1 preface in the
  First Series, 55 in the Second, 33 in the Third–Fifth), **71.1 h**, built by
  `ingest/manifest.py` from exactly three hand-picked archive.org items
  (hard-coded `SOURCES`; nothing imported by tag) joined with the LibriVox API.
  Per row: `id` (`wesley-<series>-<nn>`), series number, **Wesley's standard
  sermon number (1–141)**, title, **scripture reference + verse text**,
  **reader** (from LibriVox section data), duration, audio URL, md5/size,
  archive.org item URL, LibriVox catalog URL, CCEL text URL, license URL + note.
  - Audio file: the **64 kbps MP3** derivative for every row. It's the only
    format present for every track in all three items, it's what LibriVox
    itself links as `listen_url`, and it's half the size of the 128k/VBR files.
    Whisper resamples to 16 kHz mono, so the extra bitrate buys nothing.
  - Scripture isn't in archive.org/LibriVox metadata. It's parsed from each
    sermon heading in the CCEL plain text. Six hand-checked overrides are in
    `SCRIPTURE_OVERRIDES` with reasons. The CCEL *title index* has several
    wrong references (e.g. "Heavenly Treasure" listed as 2 Cor 9:7, but the
    text is 2 Cor 4:7), so it isn't used.
  - Wesley numbering: First Series tracks map 1:1 except that LibriVox splits
    *Christian Perfection* (40) into two tracks, so tracks 41–54 map to 40–53.
    Second Series = 53 + n, Third–Fifth = 108 + n. Both duplicate titles
    ("What is Man?" 103/109, "On Faith" 106/122) were checked against their
    scripture texts.
  - License: LibriVox recordings are public domain in the US (item license
    URLs: CC0 / PD mark); Wesley's text (d. 1791) is public domain.
  - Every row and every transcript says the voice is a **volunteer LibriVox
    reader, not Wesley** (`reader`, `license_note`, `voice_note`).
- **Download** (`ingest/fetch.py`, stdlib): to `/cache/audio/wesley/` (143
  files, ~1.9 GB). Skips files already present with the right size, resumes
  `.part` files with HTTP Range, verifies **size + md5** against archive.org
  metadata, renames atomically, and retries 4×.
- **Transcription** (`ingest/transcribe.py`): faster-whisper **large-v3-turbo**,
  fp16, per file:
  1. **Main pass**: `BatchedInferencePipeline` (Silero VAD chunks), batch 8,
     beam 5, `word_timestamps=True`, **`without_timestamps=False`**, English, and a
     one-line prompt `"<work title>, by John Wesley."`.
  2. **Gap fill**: every untranscribed stretch > 4 s (including the file head
     and tail) is re-decoded sequentially, with VAD, so true silence yields
     nothing. Words outside the gap are discarded, and segments that look
     hallucinated (span < 0.5 s, > 6 words/s, `no_speech_prob` > 0.6 or
     `avg_logprob` < −1) are dropped. Kept segments are flagged `gap_filled`.
  3. **Loop repair**: a segment with an n-gram (n ≤ 4) repeated 4+ times
     back-to-back is re-decoded sequentially. That mode has Whisper's
     temperature/compression-ratio fallback, which batched mode lacks. If the
     loop survives, repeats are collapsed and the segment is flagged
     `asr_suspect`. Flagged `redecoded`.
  - **CUDA OOM back-off**: steps down `(fp16, 8) → (fp16, 4) → (int8_float16, 4)
    → (int8_float16, 1)`, waits 10 s, reloads the model if the compute type
    changes, and retries. Tested by injecting OOM errors. The lower setting is
    kept for the rest of the run.
- **Transcript JSON** `/cache/transcripts/wesley/<id>.json`, compact:
  `meta` (all manifest fields, reader, voice note, duration, model, runtime
  versions/settings, `gaps_filled`, `repaired_segments`, created),
  `searchable_start`, `searchable_end`, `boilerplate_intro`,
  `boilerplate_outro`, and `segments[]` with `start, end, text,
  words: [[start, end, word], ...]`, plus optional flags `boilerplate`,
  `gap_filled`, `redecoded`, `asr_suspect`. Times are seconds on the
  **original file timeline**; no audio is cut and no timestamps are shifted.
  **Indexers should keep words with `searchable_start <= start < searchable_end`.**
  - Boilerplate is marked by regex at word level: the LibriVox disclaimer and
    reader credit in the first 120 s, and "End of section N… Recording by …"
    in the last 120 s. So "…Amen. End of section two." keeps its sermon words,
    and a Wesley dateline ("Preached at Balham, February 19th, 1790") right
    before "End of section 11" stays searchable. Segments wholly outside the
    window get `boilerplate: true`.
  - Sample: `ingest/samples/<id>.json` (one full transcript, < 200 KB).
- **One command**, resumable and idempotent (`ingest/run.py`): skips finished
  transcripts, writes each one atomically (`.tmp` + rename, so a crash loses
  at most the file in flight), prefetches the next download while the GPU
  works, logs a line per file to `/cache/transcripts/wesley/progress.log`
  (wall time, speed, VRAM peak, setting, ETA), keeps going past a failed
  file, and exits non-zero if any file failed.
- **QA** (`ingest/qa.py`: gaps > 8 s, surviving loops, prompt leakage,
  boilerplate counts) and a **WER spot-check** against CCEL
  (`ingest/wer_check.py`), both stdlib.

### How the design got here (findings worth knowing for church audio too)

1. **Without a prompt, batched Whisper outputs all-lowercase, unpunctuated
   text** (both large-v3 and turbo). A short punctuated prompt fixes it.
   Batched mode applies the prompt to every chunk, so leakage is checked:
   "Several Occasions" appears only where readers say it (`qa.py` flags more
   than 3 occurrences).
2. **The batched default `without_timestamps=True` corrupts word timestamps
   when Whisper skips speech.** Whisper routinely drops the spoken LibriVox
   disclaimer, and sometimes a sentence or a Scripture reading. With no
   timestamp tokens, the aligner smeared the next words over the skipped
   audio: the first chunk was up to **18 s early**, and one file lost **25 s**
   of Scripture. QA caught this in the first full run (sermons "starting" at
   2 s). I stopped it, tried an intro-probe/cut heuristic (fragile: readers
   order the intro differently), and then found the root cause.
   Timestamp tokens fix it, at ~15% lower speed. Word starts agree with an
   independent sequential decode of sermon 1 to a **median 0.01 s, p90
   0.05 s, p99 0.33 s** (4,065 matched words).
3. **Batched decoding still skips speech occasionally and can loop**, e.g.
   "Toe, Toe, Toe…" ×50 where a reader voices Wesley's Greek, or a dropped
   sentence in s1-32. Sequential decoding is better at recovering these but
   worse overall: 3.9% vs 1.4% WER on sermon 1, because it dropped a whole
   sentence itself, and it runs at half the speed. So the pipeline is batched
   first, with targeted sequential re-decodes of gaps and loops.
4. **Gap-fill hallucinations**: decoding near-silent tails produced "We'll be
   right back.", "Next slide, please.", "Beans." All of them had impossible
   spans (0.1–0.4 s for several words), which the filter rejects. Real
   recoveries pass it, e.g. the 7.4 s dropped sentence and a Latin quotation
   from Persius.

## 2. How to run

```bash
cd /work/preached/.worktrees/feat/w1-ingest
uv sync --extra transcribe                         # GPU deps (optional extra)
uv run ingest/manifest.py                          # rebuild manifest (already committed)
uv run --extra transcribe ingest/run.py --limit 3  # first 3 rows end-to-end
uv run --extra transcribe ingest/run.py --all      # everything; rerun = resume
uv run --extra transcribe ingest/run.py --ids wesley-s2-06 --redo
uv run --extra transcribe ingest/run.py --all --download-only
uv run ingest/qa.py                                # sanity report over transcripts
uv run ingest/wer_check.py /cache/transcripts/wesley/wesley-s1-01.json
tail -f /cache/transcripts/wesley/progress.log
```

Weights download on first use to `$HF_HOME` (`/cache/huggingface`):
`mobiuslabsgmbh/faster-whisper-large-v3-turbo`, a CTranslate2 conversion of
OpenAI's `whisper-large-v3-turbo` by Mobius Labs (Berlin). OpenAI Whisper is
allowed under AGENTS.md §3. `Systran/faster-whisper-large-v3` (~3 GB) is also
in the cache from the model comparison and can be deleted.

## 3. Results

RESULTS_PLACEHOLDER

## 4. Open issues / risks

- **The intro disclaimer is often missing from transcripts**: Whisper drops
  it, and the gap fill only sometimes recovers it. Nothing depends on it:
  where it's absent, `searchable_start` is the first transcribed word; where
  present, it's marked. The title/scripture announcement ("Sermon 7. The Way
  to the Kingdom.") stays searchable. It's the reader voicing Wesley's
  heading, which is harmless and useful.
- **Untranscribed stretches of 4–8 s** that the gap fill couldn't recover
  (VAD found no speech) aren't listed by QA; > 8 s ones are. See §3.
- **WER is a reader + ASR number**: readers don't voice inline references
  like "Luke 4:34" and sometimes paraphrase. `wer_check.py` drops paragraph
  numbers, but inline references still count as errors, so this is an upper
  bound on ASR error.
- **Spelling**: archaic and British forms follow Whisper ("favour"/"favor"
  varies). Search should normalise spelling.
- **Heuristics are tuned on LibriVox**: the boilerplate regex and the
  hallucination thresholds. Church recordings (W2+) will need their own
  boilerplate rules (announcements, music), though the gap fill and loop
  repair are general.
- **OOM ladder is sticky** for the rest of a run after a back-off
  (conservative). Restarting the command returns to fp16/batch 8.
- **CCEL scripture**: six overrides are hand-checked. Other CCEL headings were
  parsed automatically and spot-checked, not proofread line by line.
- **Preface**: `wesley-s1-00` is included with `kind: "preface"` and
  `wesley_sermon_number: null`. The UI may want to label or filter it.
- **Reader names** are public LibriVox credits (the readers' chosen display
  names), kept for attribution as the task requires. There are no church
  members' names anywhere in this data.
- **Shared GPU**: the run peaks at ~3.3 GB. When another tenant was busy,
  throughput fell from ~78× to ~50× with no errors.

## 5. Dependencies added

All are in the optional extra **`transcribe`**, so the search app / Sprite
never installs them (`dependencies = []` for the app so far). Versions are
pinned in `uv.lock`.

| Package | Why | Footprint |
|---|---|---|
| `faster-whisper` 1.2.1 | Whisper on CTranslate2: word timestamps, batched VAD pipeline, int8/fp16 | small; pulls `ctranslate2` (~40 MB), `tokenizers`, `huggingface-hub`, `onnxruntime` (Silero VAD), `av` |
| `av` 18.1 (pinned `<19`) | audio decode (FFmpeg bindings) used by faster-whisper; **av 19 removed `metadata_errors=`, which faster-whisper 1.2.1 passes**, so it breaks decoding | ~35 MB wheel |
| `nvidia-cublas-cu12` 12.9, `nvidia-cudnn-cu12` 9.x (+ `nvidia-cuda-nvrtc-cu12`) | CTranslate2 needs CUDA 12 cuBLAS + cuDNN 9; this box has the driver but no system CUDA. `transcribe.py` preloads them from the venv, so no `LD_LIBRARY_PATH` | ~2.2 GB in `.venv` (not in repo) |

**Runtime choice: faster-whisper over whisper.cpp.** whisper.cpp would need a
CUDA build toolchain (absent here, and on Sprites) plus its own model files.
Its Python bindings are third-party, and its word timestamps come from
token-level timestamps rather than faster-whisper's cross-attention DTW
alignment. faster-whisper is one `uv add` and has word timestamps, a batched
pipeline and int8_float16 for OOM back-off. Measured on sermon 1 (28 min,
RTX 3060), before the timestamp-token change:

| Setup | Speed (×realtime) | VRAM peak | WER vs CCEL* |
|---|---|---|---|
| **large-v3-turbo, batched b8 fp16, prompt** | **~78×** | **3.3 GB** | **1.40%** |
| large-v3, batched b8 fp16, prompt | 42× | 6.8 GB | 1.47% |
| large-v3-turbo, sequential, prompt | 39× | — | 3.87% (dropped a sentence) |

\* first 1,500 words of the sermon body, paragraph numbers removed.
large-v3 gives no measurable gain here, takes twice as long, and comes within
200 MB of the 7 GB VRAM budget, so turbo is the choice. With timestamp
tokens + gap fill + loop repair the final pipeline runs at ~65×; see §3.
