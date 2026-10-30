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
# read /cache/index/church/review/<id>.review.jsonl and skim the transcript, then
# approve under the SAME privacy config as the import:
uv run --extra youtube import/youtube.py --library church --ack-review <id> --privacy /cache/index/church-privacy.toml
# a running server serves it from its next request (no restart since the fix-up)
uv run app/server.py --library church [--flagged-audio shifted]
uv run python -m unittest discover -s tests
```

## Results
- Full suite: **221 tests, all pass** (203 before this task's tests, 18 new).
- **Wesley byte-identical check:** `align/asr_chunks.py` from `origin/main` vs this branch over all 143 transcripts in `/cache/transcripts/wesley` (8,265 chunks), `PREACHED_PRIVACY` unset: `cmp` identical, sha256 `5f624dd5…aee720` both. Same hash with `PREACHED_PRIVACY` set (ignored for `wesley`). I did not rebuild or hash a Wesley SQLite index; nothing on that path writes to it.
- End-to-end test (2 invented videos): names gone from the whole SQLite file, stdout and stderr; chunk `start_s`/`end_s`/`word_start`/`word_end` equal the unredacted chunking; review files 0600 in a 0700 dir; unacknowledged sermons invisible to search, `/api/sermon` and `/healthz`; approving one publishes only that one; re-import revokes; an edited review file cannot be approved.

## Open issues
- **The `[name]` timestamp still marks where a name is spoken.** The policy only removes or shifts the play link; the displayed `start_s`/`end_s` range and the YouTube video itself remain. `play` plays the names.
- ~~The church ASR path has no review file and no gate~~ and ~~approvals are read at server start~~: fixed, see the fix-up section below.
- The server does not re-hash the review file; the file hash is checked at import and approval only.
- Approval is a CLI act of the operator; nothing proves the file was read.
- `shifted` relies on ASR word times (up to ~0.76 s late per W1-C); the 0.5 s margin is a guess, not measured. YouTube `t=` is whole seconds, rounded up.
- A kept-but-unflagged name (the silent-miss class in `reports/W3-PRIV.md`) is neither redacted nor audio-restricted.
- The sermon-level `audio_url` in `/api/sermon/<id>` skips flagged chunks unless the policy is `play`.
- Titles are redacted by the same rules (recall 0.926 on blind3), so titles can still leak names.

Dependencies added: none.

## Fix-up after CTO review of PR #12 (head 8ffd87f)

`origin/main` (PR #8 merged as 9c3e303, containing 0d04334) was merged in with a merge commit (no rebase or force-push). There was one conflict, in `store.replace_chunks`, and I kept main's `_refuse_review_items()` call. After the merge: 221 tests passed and the #9 crash probe (`test_crash_after_replace_leaves_index_fully_old`) passed.

| Item | Commit | Change | Test (`tests/test_privacy_wire_fix.py` unless noted) |
|---|---|---|---|
| **M1** gate computed once at startup | fd43391 | `store.visible_sql` is a SQL condition evaluated on every request against the file as it is now. BM25 joins it inside the FTS query. Dense/hybrid walk the full ranking and keep only rows visible now (`visible_rowids`). `Searcher._pack` re-reads rows per call, so a `--redo` never serves cached text. `/api/sermon` and `/healthz` query with the same condition. Vectors reload when `PRAGMA data_version` shows another process committed, so a re-imported or approved sermon is findable by dense without a restart. The app forces the gate for any library but `wesley`. | `LiveGateTests.test_import_redo_and_approval_while_the_server_runs`: real HTTP server in a thread, BM25/dense/hybrid/`/api/sermon`/`/healthz`. It approves A, starts the server, `--redo`s A and B while it runs (nothing served, count 0, no names in `/healthz`), imports a never-approved C (nothing served), then approves A while it runs (served on the next request, new words found by BM25 and dense). Against the pre-fix code this test fails: dense and hybrid still return A after the `--redo`. |
| **M2** W1-C fails open | fa07791 (+ fd43391 for the store refusal) | `--library` is required. Any library other than `wesley` exits 2 without `--privacy`/`$PREACHED_PRIVACY` and writes nothing. With a config it always redacts words and the title. It writes a private review file per sermon (title line + `review()` items, 0600, never in the repo). Chunks carry `video_id` (gate key) + `flag_end_s` (now also from review items). `--index <lib>.sqlite` loads them **unpublished** via `index_video`; approve with `import/youtube.py --library <lib> --ack-review <sermon id>`. `store.replace_chunks`/`update_chunk_metadata` refuse any chunk with a `video_id`, so church chunks cannot enter the ungated Wesley index. | `AsrGateTests`: `test_library_is_required`, `test_church_without_a_config_is_refused`, `test_church_is_always_redacted_and_keyed_to_the_gate` (flag and env; "Fenwick"/"Gerald"/"Timothy" absent from JSONL, SQLite, stdout/stderr; unpublished until ack), `test_gate_keyed_chunks_never_enter_an_ungated_index`, `test_without_index_review_goes_to_the_index_dir`, `test_wesley_output_is_unchanged` |
| **M3** titles/descriptions not reviewed; casing leaks | 6658495 | The review file now starts with `{"field":"title","stored":<exactly what is stored>,"review":[...]}` and `{"field":"description","stored":null,"redacted":...,"review":[...]}`, so the approved sha256 covers them. Descriptions are still never stored, embedded or shown. `redact_metadata` recases before the rules run: ALL-CAPS words become Capitalized, then capitalized words that are only English words (not given/Bible/public/place names) become lowercase. "PRAYER FOR GRACE TOWNSEND" → "PRAYER FOR [name] [name]"; "Baby Dedication: Liam and Olivia Kowalczyk" → "Baby Dedication: [name] and [name] [name]". `redact()` on transcripts is unchanged. | `TitleTests.test_cto_examples_are_fully_redacted` (also checks that "THE GRACE OF GOD", "Mark 4: The Sower" and "Faith Over Fear" stay unchanged), `test_title_and_description_are_in_the_review_file` (editing the title line blocks approval) |
| **M4** merge main | 16c3253 | See above. | Full suite + `test_store.CrashWindowTests` |
| **M5** exact times bracket the name | fd43391 | `audio_policy.public_times`: under `none` (or `shifted` with no audio left) `start_s` and `end_s` are `null` and `audio_withheld` is true. Under `shifted`, `start_s` is the play position, `end_s` is `null`, and `play_from_s` equals `start_s`. So no field holds the chunk start. Applied to the API (`hit_dict`), the page (`app.js` shows "Text only" first), `search/query.py` (prints that `start_s`) and `watch_url` (`t=` is the play position or no link). | `TimesTests` (incl. a Deno `renderCard` check), updated `test_privacy_wire.FlaggedAudioTests.test_api_json_for_all_three_values_and_unflagged_chunks` |
| S: review file follows symlinks | 6658495 | It writes a `.tmp` file opened `O_CREAT|O_EXCL|O_NOFOLLOW` 0600 in the same directory, fsyncs it, then calls `os.replace`, so a planted symlink is replaced and its target is never touched. An existing directory is tightened to 0700. A symlinked directory, or one owned by another uid, is refused. | `ReviewFileTests` (3 tests) |
| S: privacy config hash | 6658495 | `privacy.config_sha256` (allow/block/drop/token, order- and case-insensitive) is stored in the new `videos.privacy_sha256` column at import. `--ack-review` takes `--privacy`/env and refuses on mismatch, including imports made before the hash existed. | `ConfigHashTests` (2 tests); `test_privacy_wire.test_changed_review_revokes_approval` now acks with `--privacy` |
| S: NULL `video_id` rows | fd43391 | Hidden by `visible_sql`. | `LiveGateTests.test_rows_without_a_video_id_are_hidden` |
| S: pending count in `/healthz` | fd43391 | `pending_review` is a count only. Church libraries only; Wesley's `/healthz` is unchanged. | live test; `test_wesley_health_has_no_pending_key` |
| S: review file not re-read | 6658495 | Documented in `approve_review`, the `--ack-review` help and `privacy.example.toml`. | n/a |
| S: flagged default + margin | 6658495 | Default stays `none`. `privacy.example.toml` and `audio_policy` note that the 0.5 s `shifted` margin is **not measured on real audio** and that the policy choice is **pending Patrick**. | n/a |

### Results
- Full suite: **242 tests, all pass** (`uv run python -m unittest discover -s tests`): 221 after the merge plus 21 new. The #9 crash probe passes.
- `uv lock --check`: `Resolved 75 packages`, lockfile unchanged. **No dependencies added.**
- **Wesley API byte-identical to `origin/main`:** both checkouts ran the same script over `/cache/index/wesley.sqlite` with Granite loaded on CPU (no fallback): 40 eval questions × bm25/dense/hybrid, `/healthz`, `/api/sermon/wesley-001..059` (180 JSON responses, `took_ms` removed). `cmp` reports identical; sha256 `b70f1be7…3d3a86` for both.
- Wesley ASR chunks: `align/asr_chunks.py` on `origin/main` vs this branch (`--library wesley`, with `PREACHED_PRIVACY` set) over 143 transcripts: 8,265 chunks, identical, sha256 `5f624dd5…` (same as before).
- blind3 (`python eval/privacy/evaluate.py eval/privacy/blind3.jsonl`): recall 224/242 = 0.9256, false redaction 55/354 = 0.1554, the same as the frozen result. The title recasing only runs in `redact_metadata`, which the eval does not call. I did not change the frozen rules.

### Open issues from the fix-up
- Title recasing is checked only on the CTO's examples and a handful of invented titles. A capitalized English word that is also a given name ("Grace", "Faith", "Mark") stays capitalized and is judged by the normal rules. "Faith Over Fear" and "The Grace Of God" are kept, but other titles may be redacted or kept wrongly. There is no title eval set.
- With the gate on, dense search scores all stored vectors, then checks visibility in batches of 4×k rows. That is fine for a church library; Wesley skips this path.
- When vectors are reloaded after an import, a failed fingerprint check keeps the old vectors and logs it. The gate does not depend on the vectors.
- Under `shifted`, the text and the play position still show that a name was spoken just before `start_s`, and the YouTube video itself is public.
