# ASR repro fixtures (CTO round 1 on PR #20)

Real-world input for `tests/test_coverage.py::CorruptedAsrFixtureTests`.

- `cNN.db.npy`: int16 frame level of the clip in 0.1 dB steps (`preached.youtube.coverage.frame_db`, 30 ms frames, 8000 frames). Enough to rebuild the sound spans exactly as from the WAV; the 7.7 MB WAVs stay in `/cache/asr-repro/`.
- `cNN.amx-corrupt.json`: `[start, end, word]` from the CTO's run on a Xeon with AMX, where CTranslate2's int8 path ran through MKL's AMX kernels and returned corrupted, non-deterministic encoder output. Holes over 5 s: c01 24.52-30.64, 140.42-156.18; c03 25.58-54.16, 96.68-115.38, 116.66-146.66, and the junk word `eject` stretched over 56.92-85.38.
- `cNN.clean.json`: the same model and settings on an i9-12900K (no AMX), 2026-10-30. No holes.

Provenance: LibriVox Wesley, archive.org `sermonsfirstseries_1307_librivox` (public domain). Clips: `ffmpeg -ss 60 -t 240 -i sXX.mp3 -ar 16000 -ac 1 cXX.wav`. c01.wav sha256 `7338e033c5b721bc5c8b59694d773c162b3c960c6a385b0971d4cdfa47b76a4d`, c03.wav sha256 `ff4e3ed68c84f93f059ff7dff1ec419ea55719a72c47e517aad884ab351415ac`. Model `mobiuslabsgmbh/faster-whisper-large-v3-turbo` @ `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, faster-whisper 1.2.1, ctranslate2 4.8.4, CPU int8, language en, word timestamps, VAD on, beam 5, `condition_on_previous_text=False`, prompt "English speech, with punctuation.".
