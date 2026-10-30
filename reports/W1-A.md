# W1-A: Wesley ingest + transcription

Branch `feat/w1-ingest`. Code in `ingest/`.

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
  - License: LibriVox recordings are public domain in the US (item license
    URLs: CC0 / PD mark); Wesley's text (d. 1791) is public domain.
  - Every row and every transcript says the voice is a **volunteer LibriVox
    reader, not Wesley** (`license_note`, `voice_note`, `reader`).
  - Wesley numbering: First Series tracks map 1:1 except that LibriVox splits
    *Christian Perfection* (40) into two tracks, so tracks 41–54 map to 40–53.
    Second Series = 53 + n, Third–Fifth = 108 + n. Both duplicate titles
    ("What is Man?" 103/109, "On Faith" 106/122) were checked against their
    scripture texts.
- **Download** (`ingest/fetch.py`, stdlib): to `/cache/audio/wesley/`. Skips
  files already present with the right size, resumes `.part` files with HTTP
  Range, verifies **size + md5** against archive.org metadata, renames
  atomically, and retries 4×.
- **Transcription** (`ingest/transcribe.py`): faster-whisper **large-v3-turbo**,
  two passes per file, both on the original timeline:
  1. **Intro probe**: the first 60 s, sequential, no VAD, no prompt. This
     mode does transcribe the LibriVox disclaimer. It finds the cut where the
     sermon starts: just before the reader's last announcement of the work
     title ("Sermons on Several Occasions, … by John Wesley"), with a
     boilerplate-regex + pause fallback. Probe words before the cut become a
     `boilerplate: true` segment.
  2. **Main pass**: `BatchedInferencePipeline` (Silero VAD chunks), fp16,
     batch 8, beam 5, `word_timestamps=True`, `language="en"`, a one-line
     prompt `"<work title>, by John Wesley."`, run on `audio[cut:]`, with `cut`
     added back to every timestamp (`meta.intro_cut_s`).
  - **CUDA OOM back-off**: steps down `(fp16, 8) → (fp16, 4) → (int8_float16, 4)
    → (int8_float16, 1)`, waits 10 s, reloads the model if the compute type
    changes, and retries the same file. Tested by injecting OOM errors. The
    lower setting is kept for the rest of the run.
- **Transcript JSON** `/cache/transcripts/wesley/<id>.json`, compact:
  `meta` (all manifest fields, reader, voice note, duration, model, runtime
  versions/settings, created), `searchable_start`, `searchable_end`,
  `boilerplate_intro`, `boilerplate_outro`, and `segments[]` with
  `start, end, text, words: [[start, end, word], ...]` (+ `boilerplate: true` on
  segments wholly outside the window). Times are seconds on the **original
  file timeline**; no audio is cut and no timestamps are shifted.
  **Indexers should keep words with `searchable_start <= start < searchable_end`.**
  The window is computed at word level, so a segment that ends with "...Amen.
  End of section two." keeps its sermon words but loses the outro.
  Sample: `ingest/samples/wesley-s1-07.json` (136 KB; intro + outro both marked).
- **One command**, resumable and idempotent (`ingest/run.py`): skips finished
  transcripts, writes each one atomically (`.tmp` + rename, so a crash loses
  at most the file in flight), prefetches the next download while the GPU
  works, logs a line per file to `/cache/transcripts/wesley/progress.log`
  (wall time, speed, VRAM peak, setting, ETA), keeps going past a failed
  file, and exits non-zero if any file failed.
- **QA** (`ingest/qa.py`) and a **WER spot-check** against CCEL
  (`ingest/wer_check.py`), both stdlib.

### Findings that shaped the design

1. **Batched Whisper without a prompt outputs all-lowercase, unpunctuated text**
   (both large-v3 and turbo on this audio), and it drops the spoken LibriVox
   disclaimer. A short punctuated prompt restores normal casing and
   punctuation. Batched mode applies the prompt to every chunk, so I checked
   for leakage: "Several Occasions" appears only where readers say it
   (`qa.py` flags files with more than 2 occurrences).
2. **Batched Whisper skips the LibriVox disclaimer, and that shifted
   timestamps.** It drops "This is a LibriVox recording…" even when the
   prompt mentions LibriVox (it was likely trained on LibriVox text with the
   disclaimers stripped). The word aligner then spread the next words
   ("Sermons on Several Occasions…") back over the disclaimer audio, putting
   the first ~30 s chunk up to **18 s early**. QA caught this in the first
   full run (sermons starting at 2 s), so I stopped the run, added the intro
   probe + cut above, and restarted from scratch. Check after the fix: word
   start times agree with an independent sequential decode of sermon 1 to a
   **median 0.01 s, p90 0.05 s, p99 0.33 s** (4,065 matched words, no real
   outliers). Outros ("End of section 7. Recording by …") are marked by
   regex in the last 120 s, cut at word level, so a Wesley dateline
   ("Preached at Balham, February 19th, 1790") right before "End of section"
   stays searchable. Dropped outros need no marking, since they can't
   produce search hits.
3. **Sequential (non-batched) decoding was worse**: 3.9% WER vs 1.4% on sermon 1,
   because it silently dropped a whole sentence (a known
   condition-on-previous-text failure), and it ran at half the speed. Batched
   mode won on both counts.

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
allowed under AGENTS.md §3.

## 3. Results

RESULTS_PLACEHOLDER

## 4. Open issues / risks

- **The intro cut depends on readers announcing the work title** (all
  sampled files across the three series do). If a file lacks it, the regex +
  pause fallback applies, and if that finds nothing the whole file is the
  main pass (cut 0). Some readers' disclaimers are skipped even by the probe
  (e.g. s2-06): `boilerplate_intro` is then empty, but the cut still lands
  correctly on the title announcement. The title/scripture announcement
  ("Sermon 7. The Way to the Kingdom.") stays searchable. It's the reader
  voicing Wesley's heading, which is harmless and useful.
- **Paragraph-number WER**: readers don't voice the printed "1." / "II."
  numbers or inline references like "Luke 4:34". `wer_check.py` drops
  paragraph numbers, but the inline references still count as errors, so the
  reported WER is an upper bound on ASR error.
- **Spelling of archaic forms** follows Whisper ("favour"/"favor" varies,
  "vouchsafe" → "vouchsage" once). Search should normalise British/American
  spellings.
- **OOM ladder is sticky** for the rest of a run after a back-off
  (conservative; the run gets slower but doesn't thrash). Restarting the
  command returns to fp16/batch 8.
- **CCEL scripture**: six overrides are hand-checked. Other CCEL headings were
  parsed automatically and spot-checked, not proofread line by line.
- **Prefaces**: `wesley-s1-00` (Preface) is included with `kind: "preface"`
  and `wesley_sermon_number: null`. The search UI may want to label or filter it.
- **Reader names** are public LibriVox credits (the readers' chosen display
  names) and are kept, as the task requires attribution. There are no church
  members' names anywhere in this data.
- Two GPU tenants: the run peaks at ~3.3 GB. That leaves ~7 GB of the 12 GB
  for the embedding benchmark, with ~1 GB used by the desktop.

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
Its word-level timestamps come from token timestamps, which are less reliable
than faster-whisper's cross-attention DTW alignment. Its Python bindings are
third-party. faster-whisper is one `uv add` and has real word timestamps, a
batched pipeline and int8_float16 for OOM back-off. Measured on sermon 1
(28 min, RTX 3060):

| Setup | Speed (×realtime) | VRAM peak | WER vs CCEL* |
|---|---|---|---|
| **large-v3-turbo, batched b8 fp16, prompt** | **~78×** | **3.3 GB** | **1.40%** |
| large-v3, batched b8 fp16, prompt | 42× | 6.8 GB | 1.47% |
| large-v3-turbo, sequential, prompt | 39× | — | 3.87% (dropped a sentence) |

\* first 1,500 words of the sermon body, paragraph numbers removed.
large-v3 gives no measurable gain here, takes twice as long, and comes within
200 MB of the 7 GB VRAM budget. Turbo is the clear choice.
