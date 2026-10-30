# W3-ASR-COVERAGE: ASR coverage gate

Branch `feat/w3-asr-coverage`, rebased on `origin/main` (`3c5526d`). The WIP commit from the stopped run was reviewed, fixed and folded in.

## What was done

1. **Coverage check** (`src/preached/youtube/coverage.py`). Decodes the audio with ffmpeg to 16 kHz mono and finds non-silent stretches by frame energy (30 ms frames, within 30 dB of the file's 98th-percentile level, floor -58 dBFS, breaths under 0.6 s merged, sound under 0.25 s dropped). Transcript words, padded 0.3 s, are subtracted. What is left, merged across short silences and longer than `MAX_UNCOVERED_S = 5.0`, is an uncovered span. Energy was used on purpose: the stack's Silero VAD is the transcriber's own filter, and a check that shares it shares its blind spot. If ffmpeg cannot decode the file, the video's duration counts as speech (fallback to audio length); with neither, the import fails.
2. **Gate.** Both import paths store the spans in `videos.coverage_gaps` (JSON; new column). `approve_review` refuses when the column is NULL (check never ran) or non-empty, and names the spans. Spans also go into the private review file as `field: "coverage"` lines. The YouTube path checks the whole file; a `--windows` entry for the video limits the check to that window (a human has said where the sermon is). `align/asr_chunks.py` (transcript JSON import) takes `--audio-dir` (`<sermon id>.<ext>`) and checks inside `searchable_start..searchable_end`; without audio it stores NULL, so approval is refused.
3. **Cause.** Not reproduced (below). No setting was changed. The WIP's only change to `transcribe.py` was moving the prompt into `INITIAL_PROMPT`; that is kept (same text).
4. `scripts/asr_holes.py`: probe that runs named Whisper settings on one file and prints the uncovered spans.

## Measured holes

Audio: `/cache/w3-asr/clip240.wav` (240 s) and the full `/cache/youtube/cc-speech/BGoD6CIpLWQ.webm` (321.6 s). Model large-v3-turbo (Mobius conversion) unless noted. Language en, word timestamps, VAD on, beam 5, `condition_on_previous_text=False`, the product prompt.

| Device | Settings | Audio | Holes | Uncovered |
|---|---|---|---|---|
| CPU int8 | product | 240 s | 1 (28.2-33.7 s) | 5.5 s |
| CPU int8 | `vad_filter=False` | 240 s | 1 | 5.5 s |
| CPU int8 | looser VAD (thr 0.3, silence 1000 ms, pad 400 ms) | 240 s | 1 | 5.5 s |
| CPU int8 | no_speech 0.9, logprob -2.0, compression 2.8 | 240 s | 1 | 5.5 s |
| CPU int8 | `temperature=0` | 240 s | 1 | 5.5 s |
| CPU int8 | looser VAD and thresholds | 240 s | 1 | 5.5 s |
| CPU float32, 4 threads | product | 240 s | 1 | 5.5 s |
| CPU int8 | product | 321.6 s | 1 | 5.5 s |
| CPU `tiny.en` int8 (the product's CPU fallback) | product / no VAD / loose thresholds | 240 s | 1 each | 5.2 s |
| GPU (3060) int8_float16 | product | 240 s and 321.6 s | 1 | 5.5 s |
| GPU | loose thresholds | 240 s | 1 | 5.5 s |

**The CTO's 22-75 s holes (15-30 s each) did not reproduce** on this audio, on CPU or GPU, with any setting above. "Before" and "after" are therefore the same. The one span, 28-34 s, is not speech: transcribing 20-40 s alone with VAD off and no prior text returns text for 20.6-27.8 s and 34.2-38.8 s and nothing between (no_speech_prob 0). It is music or a sting in the intro. The gate flags it, and a listen clears it (re-import with a `--windows` entry that starts after it). So the gate costs one false positive on this file, and I did not find the cause of the CTO's holes: the CTO's file, thread count or batched pipeline may differ from what I ran. Open item for them: send the file, or the exact command.

GPU shows the same single span and 5 s wall time vs 43-57 s on CPU for turbo (85 s float32).

## Gate behaviour

- Import never fails because of a gap. The sermon lands unpublished with the spans stored and printed (`coverage <id>: no transcript for sound at 28.2-33.7s`).
- `--ack-review` refuses: `ID: 1 stretch(es) of sound have no transcript (28-34s). Listen, then re-import with --redo ...`.
- Music, applause and singing that no word covers also block. There is no "clear this span" command; the clearing step is a re-import with a window. Say if you want a per-span ack instead.
- A hole in the first or last seconds of a sermon is caught on the YouTube path only because the check runs over the whole file when there is no window.

## How to run

```bash
uv run python -m unittest discover -s tests
uv run --extra transcribe python scripts/asr_holes.py AUDIO --device cpu --variant product --variant novad
uv run python align/asr_chunks.py T.json --out o.jsonl --library church --index church.sqlite --audio-dir AUDIO_DIR
```

## Results

- Tests: 503 pass (492 before; 11 new in `tests/test_coverage.py`: synthetic audio with a missed speech stretch is found and blocks approval end to end; a clean file passes and is approved; gap under 5 s, room-tone silence, hole at the end, two holes, undecodable audio, window clipping, unchecked import refused). Existing import tests inject `coverage=lambda *_a, **_k: []` because their audio files are fake.
- `uv lock --check`: passes (`Resolved 79 packages`).
- Head SHA: see the PR head (`git rev-parse HEAD` on the branch).

## Dependencies

None added (numpy and ffmpeg are already needed).

## Risks

- Energy marks any loud non-speech as sound; expect false positives on music and applause.
- Quiet speech more than 30 dB below the file's loud end counts as silence and is never checked.
- The gate is only as good as the `--windows` discipline for clearing.
