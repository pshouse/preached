# W3-PRIV-WIRE: privacy wired into both ingest paths

**Base.** PR #8 (`feat/w3-priv`) and PR #4 (`feat/w2-youtube`) were NOT merged into `origin/main` when I started. The branch is `origin/feat/w3-priv` + `origin/main` + `origin/feat/w2-youtube`, all merged (no rebase). The PR is therefore stacked on #4 and #8. One conflict, in `store.replace_chunks` (kept both main's transaction docstring and the review-item guard), and one in `.gitignore` (kept both sets of lines).

## Pending decision
**The exact audio policy for flagged chunks is pending Patrick's decision.** Config key: `flagged_audio` in the privacy TOML, or `PREACHED_FLAGGED_AUDIO`, or `--flagged-audio` (import CLI, server, `search/query.py`). Precedence: flag, env, TOML key, default. Values are exactly `play`, `shifted`, `none`; anything else is an error. Default `none`.

## What changed
1. **W2-YT:** `youtube/privacy.py` re-exports `preached.privacy.redact`. The pipeline calls it with `config=` and `source=<video id>` (drop windows work). `test_privacy_hook_is_identity` still passes unchanged (no names, no drop windows: `redact` returns the same list). Two existing tests changed for the new behaviour: `_chunks_for` now returns `(records, review_items)`, and two tests that serve an imported library now run `--ack-review` first.
2. **W1-C:** `asr_chunks(..., privacy=Config|None)`. CLI `--library` (default `wesley`) and `--privacy`; `$PREACHED_PRIVACY` applies to any library except `wesley`, and `--privacy` with `wesley` is an error. Redacted chunks get `flag_end_s`.
3. **Review files:** after redaction `review()` runs on the same sermon words (drop windows removed). Written through `write_review_file` (0600 file, 0700 dir) to `<index dir>/<library>/review/<video_id>.review.jsonl` (JSON lines, so `.review.jsonl`, already git-ignored). `write_private_review` refuses any path inside the repo. Console shows counts only. Every sermon gets a file, even with zero items, because a human skim is the point.
4. **Config:** `--privacy <toml>` on the import command, else `$PREACHED_PRIVACY`. Bad TOML, a missing file or an invalid `flagged_audio` exit 2 before any download.
5. **Unpublished until approved.** Every imported video lands with `videos.review_sha256` set and `approved_sha256` empty. `store.hidden_rowids` hides its chunks from `Searcher` (BM25, dense, hybrid), `/api/search`, `/api/sermon/<id>` and the `/healthz` chunk count. Approve with `--ack-review VIDEO_ID` (repeatable, no channel URL): it re-hashes the review file, refuses if it differs from the hash stored at import, then stores the approval. A re-import clears the approval. A library file lacking the gate columns hides everything (fails closed). Wesley's index has no `video_id` column and is never gated.
6. **Flagged-audio policy** (`src/preached/audio_policy.py`): a chunk is flagged when it holds a `[name]` word or overlaps a `review()` item; `flag_end_s` = end of the last such word. `play`: normal link. `shifted`: start `flag_end_s + 0.5 s` (margin for ASR timing error), `none` when no audio is left in the chunk. `none`: no play link. Applied in `watch_url` (import time), `hit_dict` (API JSON; the server recomputes from `video_id`, so the policy can change without a re-import), `app.js` (`play_from_s` = exact seek without pre-roll, `audio_withheld` shows "Text only") and `search/query.py`. Unflagged chunks and Wesley JSON are unchanged (the new keys appear only on flagged chunks).
7. **Titles** go through `redact_metadata` after the listing and again after the metadata fetch, so the stored title, the embedded document title, dry-run output and the TIMING log line are redacted. Descriptions are never stored.

Files: `src/preached/audio_policy.py` (new), `privacy.py` (+`flagged_audio`, `apply_drops`), `store.py`, `search.py`, `youtube/{privacy,pipeline,library,listing,cli}.py`, `align/asr_chunks.py`, `app/server.py`, `app/static/app.js`, `search/query.py`, `privacy.example.toml`, `tests/test_privacy_wire.py` (new, 18 tests), `tests/test_youtube.py` (3 small edits).

## How to run
```
uv run --extra youtube import/youtube.py <channel-url> --library church --privacy /cache/index/church-privacy.toml
# read /cache/index/church/review/<id>.review.jsonl and skim the transcript, then:
uv run --extra youtube import/youtube.py --library church --ack-review <id>
# restart the server: it reads approvals at start
uv run app/server.py --library church [--flagged-audio shifted]
uv run python -m unittest discover -s tests
```

## Results
- Full suite: **221 tests, all pass** (203 before this task's tests, 18 new).
- **Wesley byte-identical check:** `align/asr_chunks.py` from `origin/main` vs this branch over all 143 transcripts in `/cache/transcripts/wesley` (8,265 chunks), `PREACHED_PRIVACY` unset: `cmp` identical, sha256 `5f624dd5…aee720` both. Same hash with `PREACHED_PRIVACY` set (ignored for `wesley`). I did not rebuild or hash a Wesley SQLite index; nothing on that path writes to it.
- End-to-end test (2 invented videos): names gone from the whole SQLite file, stdout and stderr; chunk `start_s`/`end_s`/`word_start`/`word_end` equal the unredacted chunking; review files 0600 in a 0700 dir; unacknowledged sermons invisible to search, `/api/sermon` and `/healthz`; approving one publishes only that one; re-import revokes; an edited review file cannot be approved.

## Open issues
- **The `[name]` timestamp still marks where a name is spoken.** The policy only removes or shifts the play link; the displayed `start_s`/`end_s` range and the YouTube video itself remain. `play` plays the names.
- **The church ASR path (`asr_chunks.py`) has no review file and no gate**: its chunks have no `video_id`, so whatever builds an index from them must apply the gate. Only the YouTube channel import is gated.
- **Approvals are read at server start** (a restart is needed). The server does not re-hash the review file; the file hash is checked at import and approval only.
- Approval is a CLI act of the operator; nothing proves the file was read.
- `shifted` relies on ASR word times (up to ~0.76 s late per W1-C); the 0.5 s margin is a guess, not measured. YouTube `t=` is whole seconds, rounded up.
- A kept-but-unflagged name (the silent-miss class in `reports/W3-PRIV.md`) is neither redacted nor audio-restricted.
- The sermon-level `audio_url` in `/api/sermon/<id>` skips flagged chunks unless the policy is `play`.
- Titles are redacted by the same rules (recall 0.926 on blind3), so titles can still leak names.

Dependencies added: none.
