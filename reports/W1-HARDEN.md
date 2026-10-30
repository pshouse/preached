# W1-HARDEN: CTO should-fix and nits from PR #7 and PR #5

Branch `feat/w1-harden` from `origin/main` `000b89d`. No new dependencies. No transcription, no GPU, no network beyond git.

## 1. What was done

| # | Item | Change | Test |
|---|---|---|---|
| 1 | One-transaction rebuild | `src/preached/store.py` `replace_chunks` (~:159) no longer commits and now also runs `DELETE FROM meta WHERE key LIKE 'embeddings:%'`, so no caller can forget it. `sync_chunks` (~:208-220) commits once after DELETE, INSERT, hash write and meta clear. A no-op seam `_after_replace()` sits between the replace and the hash write so a test can crash there. Callers: `build_index.py`, `query.py`, `bench.py` go through `sync_chunks` (commits). The only direct caller was the test helper `build_legacy_index`, which now commits. | `tests/test_store.py` `CrashWindowTests`: a subprocess hard-exits (`os._exit(7)`) at the seam. The DB is then fully old (old text, old hash, 3 vectors, old `embeddings:*`, `Searcher` loads). The next `sync_chunks` + `Searcher` ends fully new (new text, new hash, 0 vectors, no meta, `EmbeddingMismatch` rather than "fingerprint ok, 0 vectors"). Also `test_replace_chunks_clears_embedding_meta_itself`. The in-place path tests (`InPlaceMetadataTests`) still pass. |
| 2 | `play_start` | `src/preached/search.py:40`: `math.isfinite` (NaN, inf, -inf give `None`, as JS `Number.isFinite`). | `tests/test_preroll_paths.py` `test_play_start`; JS parity in `tests/test_app_js.py` (NaN, Infinity, -Infinity; deno is installed, so it ran). |
| 3 | `play_url` / terminal output | `search/query.py`: `play_url` reuses `ingest/manifest.py` `check_audio_url` (https, archive.org, default port, no credentials); anything else prints `n/a (unsafe URL hidden)`. `clean()` turns C0/C1/DEL/ESC runs into one space in title, chunk id, reader, source URL, quote and play URL. | `test_play_url_hides_unsafe_urls` (`javascript:x`, `http://`, `file://`, off-host, credentials, ESC-prefixed), `test_print_hits_strips_control_characters`. |
| 4 | Strict file match | `eval/timestamps.py:80`: `same_file = chunk_file_id is not None and chunk_file_id == span["file_id"]`. | `tests/test_timestamps_eval.py`. **Re-ran the eval: nothing changed.** Summary, all per-question rows and the spot check are identical (overlap 14/35 hit@1, 23/35 hit@5; strict 5 and 7). Every chunk has a file id, so the old `None` case never fired. |
| 5 | Metric labels | `reports/W1-CLI.md` (box above the table, table row labels, "equal by construction"), `README.md` (one sentence), `eval/timestamps.py` `METRIC_NOTE`, and a `note` field added to `reports/W1-CLI-timestamps.json`. Numbers kept. Text says: derived from the alignment, equal to the text metric by construction, not an independent audio-accuracy result; the audio evidence is the W1-C spot-check (median 0.42 s, max 0.76 s, covered by the 0.75 s pre-roll). | docs only |
| 6 | CCEL sha fatal | New `catalog_text_sha()` in `src/preached/corpus.py` raises on a missing catalog or a missing/empty `sha256_text`. Used by `ingest/manifest.py` `ccel_text()` and `fetch_corpus`. `--accept-new-text` still skips the check. A first-ever `fetch_corpus` with no catalog still bootstraps, because it writes the catalog. | `tests/test_ingest.py` `CcelShaTests` (match, wrong, missing, empty, null, no catalog, corpus refusal and the escape hatch). |
| 7 | Whisper `model.bin` sha256 | Done (stdlib `hashlib`). `ingest/transcribe.py`: `MODEL_BIN_SHA256` (from `reports/W1-A.md`), `snapshot_model_bin()`, `verify_model_bin()` streams 8 MiB blocks, memoised per process by path+size+mtime, opt-out `PREACHED_SKIP_MODEL_SHA=1`. `Transcriber._load` verifies cached weights before `WhisperModel(...)` and again right after (covers a first download). Only for the pinned repo and revision. | `tests/test_ingest.py` `ModelBinShaTests` with a tiny fake file (match, once per process, mismatch, tampered, opt-out, pin equals the report). The real weights and `_load` were **not** exercised (no GPU or transcription here). |
| 8 | Suite | See below. | |

## 2. How to run

```bash
uv run python -m unittest discover -s tests          # 136 tests, OK (main: 120)
uv run python -m unittest tests.test_store tests.test_preroll_paths tests.test_app_js tests.test_timestamps_eval
uv run eval/timestamps.py --out /tmp/ts.json         # needs /cache data; CPU only
```

## 3. Results

- Tests: 136 run, OK (main had 120 plus 79 subtests). Added: 16 tests plus new subtests.
- Timestamp eval re-run: identical to the committed numbers (see item 4).

## 4. Open issues and notes

- Item 7 verifies in `_load`, which I could not run here. The path is `HF_HUB_CACHE/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots/<rev>/model.bin`; if the cache layout differs, the pre-check returns False (absent) and the post-load check still reports a mismatch if there is one. The first run on the GPU box hashes 1.6 GB once (a few seconds).
- `_after_replace` is a production no-op seam kept only for the crash test.
- `clean()` replaces newlines in the quote with spaces, so CLI quotes print on one line.

## 5. Dependencies added

None.

## Fix-up after CTO review of PR #9

- **Crash test imports the checkout** (`tests/test_store.py`, `CRASH_SCRIPT` + `test_crash_after_replace_leaves_index_fully_old`). The subprocess still runs `python -I` (no PYTHONPATH, no user site), but the script now puts this checkout's `src` (passed as argv[3]) first on `sys.path` and exits 3 unless `preached.store.__file__` resolves under it; exit 7 is the crash hook, 0 means the hook doesn't exist (old code). Checked with a throwaway venv whose site-packages "installs" a different `src` via a `.pth`:
  - old checkout (main's `store.py`) + fixed installed copy: original test **passed** (CTO's false pass), new test **fails** (`0 != 7`).
  - fixed checkout + stale installed copy (main's `src`): original test **failed** (CTO's false fail), new test **passes**.
  - a `src` without `preached` makes the guard exit 3 with "imported …, not this checkout's …".
- **Model assigned only after the hash check** (`ingest/transcribe.py` `Transcriber._load`): the loaded model is held in a local and stored on `self` only after the post-load check passes, so a caught failure leaves `_model`/`_pipe` None and the retry verifies again. `verify_model_bin(..., required=True)` makes an absent `model.bin` after loading an error ("missing … refusing to use them"); the pre-download check still allows absent, and `PREACHED_SKIP_MODEL_SHA=1` still opts out. Tests: `TranscriberLoadTests` (fake `faster_whisper`, tiny fake weights: good download, bad download + retry, missing after load, opt-out, unpinned repo) and `ModelBinShaTests.test_missing_file_is_an_error_when_required`. All but the opt-out/unpinned cases fail on the f1f5aac code.
- **`reports/W1-CLI.md`**: the "alignment lost nothing" sentence now says the stored times agree with the text, not the audio, and points to the W1-C spot-check (median 0.42 s, max 0.76 s, covered by the 0.75 s pre-roll).
- Tests: `uv run python -m unittest discover -s tests`: 142 OK (was 136).
