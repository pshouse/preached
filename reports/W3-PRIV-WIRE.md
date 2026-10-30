# W3-PRIV-WIRE: privacy wired into both ingest paths

**Base.** PR #8 (`feat/w3-priv`) and PR #4 (`feat/w2-youtube`) were NOT merged into `origin/main` when I started. The branch is `origin/feat/w3-priv` + `origin/main` + `origin/feat/w2-youtube`, all merged (no rebase). The PR is therefore stacked on #4 and #8. One conflict, in `store.replace_chunks` (kept both main's transaction docstring and the review-item guard), and one in `.gitignore` (kept both sets of lines).

## Audio policy decision
**Decided (2026-10-30, see the last section): Patrick chose: no play link on name passages; announcements, prayer requests and testimonies are excluded (see W3-PRIV-SKIP).** `none` is now fixed for church libraries. The `--flagged-audio` flags are gone, and `play`/`shifted` in the TOML or env are refused. The original text below is kept as history.

~~The exact audio policy for flagged chunks is pending Patrick's decision.~~ Config key: `flagged_audio` in the privacy TOML, or `PREACHED_FLAGGED_AUDIO`, or `--flagged-audio` (import CLI, server, `search/query.py`). Precedence: flag, env, TOML key, default. Values are exactly `play`, `shifted`, `none`; anything else is an error. Default `none`.

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
- `shifted` relies on ASR word times (up to ~0.76 s late per W1-C); the 0.5 s `shifted` margin is a guess, not measured. The *seek* margin (`SEEK_SLACK_S`) is now 1.5 s, from measurement (round 5): large-v3-turbo word ends vs forced alignment were p95 0.12 s, p99 0.48 s, max 3.58 s late on clean studio audio, so 1.5 = p99 + 0.5 s with headroom; church audio will be worse. YouTube `t=` is whole seconds, rounded up.
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

## Merge with main after PR #11 (W3-POLISH) and PR #13 (W2-YT-PLAY)

`origin/main` at `e2ddbc7` (#11 merged as `6a16b1f`, #13 as `e2ddbc7`) was merged into this branch with a merge commit, **`225eb16`** (parents `9b2a3fb`, `e2ddbc7`). There was no rebase and no force-push. The fix is a separate commit, **`052e3c2`**.

### Conflicts and how they were resolved (both behaviours kept)
| File | #12 side | main side | Resolution |
|---|---|---|---|
| `src/preached/search.py` | `Hit.video_id`, `Hit.flag_end_s` | `Hit.merged_ids`, `chunk_ids` (#11 dedupe merge) | All four kept. |
| `app/server.py` | `App`/`build_app(flagged_audio=)`, `hit_dict(hit, policy)` | `floor=` (abstain), `chunk_ids`, `abstain`, `confidence` | Both signatures merged. The API returns #11's fields and #12's policy fields. |
| `search/query.py` | `--flagged-audio`, `public_times`, `hit_play` | abstain rule, `--hide-low-confidence`, #13's validated YouTube play line | Both kept. `print_hits` gets the policy on both the normal path and the hidden-results path. |
| `app/static/app.js` | "Text only" for `audio_withheld`; `play_from_s` exact seek | "Watch on YouTube at m:ss" link | `audio_withheld` is checked first, so it renders no link. The YouTube label and the audio button both use the shifted start when there is one. |
| `tests/test_youtube.py` | `_chunks_for` returns `(records, review_items)` | 11-character sample id `samplevid01` | Both changes kept. #12's `--ack-review samplevid001` line now uses `samplevid01`. |

Director must-fixes for the merge, all in `225eb16`:
- **Policy `none` gives no link.** The server nulls `audio_url` and, when it is a YouTube URL, `source_url` too, so no YouTube link renders.
- **`shifted` jumps past the name.** The server and the CLI never pass the stored link through: its `t=` was set at import time under that time's policy and may sit on the name. `listing.chunk_video_id` takes the 11-character id from the stored `audio_url` or `source_url`, and only when it is a valid watch URL. The two must agree with each other and with the chunk's `video_id`. `listing.watch_url` then builds `https://www.youtube.com/watch?v=<id>&t=<int>s`, where `t` = ceil(shifted start), from the validated id and an `int`. If a YouTube link cannot be rebuilt, audio is withheld (fails closed). `watch_url` now returns None for an id that is not 11 characters.
- **The label uses the shifted start**: "Watch on YouTube at m:ss".

After the merge: **282 tests, all pass**.

### CTO must-fix: dedupe merged a flagged neighbour into an unflagged card (`052e3c2`)
- **`merge_overlapping` never merges when either chunk has `flag_end_s`, and requires the same `video_id`.** The flagged neighbour is dropped (as in #11's drop rule), not folded in.
- **Defence in depth: `search.touches_flagged(connection, hit)`.** A card counts as touching when its word span overlaps any flagged chunk of the same sermon. If word offsets are missing it uses the time span; if there is no span at all, any flagged chunk in the sermon counts. Under `none`, the API (`App.search` → `hit_dict(near_flag=)`) and the CLI (`print_hits(connection=)`) give such a card no link and no times. I read the CTO's "word span touches a flagged chunk" literally. An unflagged chunk next to a flagged one holds none of the flagged words, but a link to it keeps playing into the name. **This is a behaviour change: under `none`, more cards near a name are now text only.** `shifted` and `play` are unchanged for unflagged cards.
- Under `none` and `shifted`, a flagged YouTube card also drops its `source_url`, because that watch link starts at 0:00.

**Finding: YouTube chunks never merge, on main or here.** #11 merges only chunks with the same `audio_url`, and each YouTube chunk stores its own `&t=` link. So the CTO's bug was reachable only on the church ASR path (W1-C), where every chunk of a sermon shares one audio file. The end-to-end tests therefore cover both paths.

Tests: `tests/test_privacy_merge.py`, 13 new.
- (a) `MergeGuardTests`: a candidate pair with a flagged neighbour stays separate, and the flagged chunk gets no link under `none`. A flagged kept card absorbs nothing. Different `video_id`s never merge. A seeded property test (5,000 lists, about 25% of chunks flagged) checks that no merged card contains a flagged chunk, that each card's flag equals "holds a flagged chunk", and #11's invariants: no repeats, no word twice, the 300-word cap, idempotence.
- (b) `ServedTests` (YouTube import, imported under `play` so the stored links point at the names) and `ChurchAsrServedTests` (W1-C index, where merges happen): 14 queries × k ∈ {1, 3, 5, 10, 20} through `App.search` under the default policy. Every card whose word span touches a flagged chunk has `audio_url` null, `audio_withheld` true, no times, no `play_from_s` and no YouTube URL anywhere in its JSON. Clear cards keep their link. No merged card contains a flagged chunk, under `none` or `play`.
- Policy `none` gives no link on the page (Deno `renderCard` over the served cards: "Text only", no "Watch on YouTube"/"Play from", no href) and in the CLI (`print_hits`: "audio withheld", no `youtube`).
- `shifted`: the API link is `…&t=<int>s` with `t > flag_end_s`, `t = ceil(play_from_s)`, and differs from the stored link. The page label is "Watch on YouTube at <shifted m:ss>" with exactly that href. The CLI prints the same rebuilt link. A YouTube link that is malformed or carries a mismatched id is withheld.
- **The tests catch the bug:** with only the merge guard removed, 5 tests fail, plus many runs of the property test.

### Results
- Full suite (`uv run python -m unittest discover -s tests`): **295 tests, all pass** (282 after the merge plus 13 new; the Deno tests ran).
- #11's dedupe property test (`test_dedupe.DedupePropertyTests`, 20k lists) passes.
- `scripts/check_dedupe.py` (56 queries × 5 mode/model lists = 280 lists, `/cache/index/wesley.sqlite`): **0 overlapping pairs, 0 non-idempotent**. Merged counts and card lengths are the same as #11's report §6.3 (for example, Granite hybrid merged 95/560, median 125, mean 133, max 300).
- `search/bench.py --dedupe --models granite-english-r2` (results written to `/tmp`, not committed): **Granite hybrid RRF R@5 0.657**, MRR@10 0.540, nDCG@10 0.590, the same as #11. Every per-question entry, including the top-10 lists, is identical to the committed `eval/results/2026-10-30-w3polish-dedupe.json` for dense, hybrid_rrf, hybrid_weighted and BM25. Wesley has no flagged chunks, so the guard never fires there.
- `uv lock --check`: `Resolved 75 packages`, lockfile unchanged. **No dependencies added.** No LLM.

### Open issues
- **The whole video and the sermon-level link stay public.** A clear card's YouTube link (and the `/api/sermon/<id>` `audio_url`) plays from its `t=` onward. A clear card's YouTube `source_url` plays from 0:00, so it can play an opening name. Only cards that touch a flagged chunk lose their links. Closing this fully means withholding YouTube links per sermon whenever any of its chunks is flagged. That is a product call for Patrick, together with the pending `flagged_audio` decision.
- `touches_flagged` runs one SQL query per card under `none` (on Wesley too, where it finds nothing). That is fine at k ≤ 50 and was not timed separately. I did not repeat the byte-identical Wesley API check from the fix-up section; the bench per-question identity covers the ranking, not the JSON.
- The page still labels a YouTube `source_url` "Read this sermon on CCEL". That predates this merge (#13).

## Fix-up: merge with main (#15) and #14, shared public-domain allow-list, Patrick's decisions

**Base.** I checked PR #14 on the GitHub API first: it is **open, not merged**. `gh` is not installed here, so I used the public REST endpoint. I merged two things into this branch, merge commits only, no rebase and no force-push:
- `origin/main` at `4129646` (#15 merged), as **`cca8cbf`**;
- the PR #14 branch `origin/feat/w3-lib` at `18825ef`, as **`812d618`**, so that `src/preached/libraries.py` is present.

**Once #14 merges, this PR's diff against main shrinks by #14's files.** PR #10 (`feat/w3-cpu`) is **not on main**, so the "re-apply hidden rows in #10's per-request reload" requirement does not apply yet. The gate here is already a per-request SQL condition (fix-up M1). The reload is #10's code and is not in this branch.

### Conflicts (6 files, both behaviours kept)
| File | Merge | Resolution |
|---|---|---|
| `src/preached/youtube/listing.py` | main | One builder. `watch_url` keeps #15's `_watch_link`, its 24 h / duration cap and its non-finite handling, and gains #12's `end_s`/`flag_end_s`/`policy`. **The shifted seek is built by `watch_url` → `_watch_link`** from a validated 11-character id and an `int` `t` (ceil of the shifted start). A shifted seek that is non-finite, or that the cap would pull back onto the name, returns no link. `watch_video_id` reads the id from `youtube_watch_url`'s canonical output, and `policy_watch_url` calls `watch_url`. There is no separate builder. |
| `src/preached/youtube/pipeline.py` | main | `watch_url(..., duration_s=video.duration_s, end_s=, flag_end_s=, policy=)`. |
| `app/server.py` | main | Imports from both sides (`public_audio_url` plus the policy helpers). |
| `app/static/app.js` | main | #15's `watchHref` (source-link dedupe) is set on the YouTube link, and its label uses the shifted start (`playLabel`). |
| `search/query.py` | #14 | #14's `INDEX_DIR`/`open_readonly` plus #12's `touches_flagged`/`chunk_video_id`/`policy_watch_url`. |
| `src/preached/youtube/library.py` | #14 | `index_video` takes both #12's `review_sha256`/`privacy_sha256` and #14's `reader`/`sermon_number`/`librivox_id`. |

`tests/test_youtube.py` merged cleanly, but #15's new assertion used `_chunks_for`'s old return value. I unpacked `(records, items)` there.

### CTO decision: one shared allow-list, everything else fails closed (`fb944fe`)
- **The gate exemption is keyed on the slug.** `store.public_domain_file(connection, library)` returns true only when `preached.libraries.is_public_domain(library)` holds (spurgeon or edwards, with committed provenance) **and** the file is that library's own build: meta `library` equals the slug (written by `build_library.py`), no `videos.review_sha256` is set and no chunk has `flag_end_s`. `visible_sql(..., library=)` re-checks this on every call, so church rows written into a classics file re-gate it on the next request. A missing column never exempts a file. Without this, the merged branch hid the classics entirely: their files have `videos`/`video_id` and no approvals. The server (`App`), `/healthz` (no `pending_review` key for the classics), `/api/sermon`, `search/query.py --library` and `scripts/classics_smoke.py` all pass the slug. A server started with an allow-listed slug on a file that is not its own build logs a warning and stays gated.
- **Fails closed:**
  - **YouTube import:** `--privacy` or `$PREACHED_PRIVACY` is now required for import, `--dry-run` and `--ack-review` (new `privacy.required_config`). Before, an empty config was used silently. Without one the import exits 2 before listing or downloading anything. `wesley`, `spurgeon` and `edwards` are refused as import slugs, because those files are served ungated.
  - **`align/asr_chunks.py`:** unchanged for church slugs (config required, redaction, review file, unpublished). It now also refuses `spurgeon`/`edwards`.
  - **`search/build_library.py` and `ingest/run.py --library`:** these are only for the allow-list. Any other slug exits non-zero with or without a privacy config. Church audio never goes through them.
- **Classics stay visible** (`ClassicsVisibleTests`): a Spurgeon file built by the real `build_library.py` (synthetic transcript, fake embedder) is served by `App(library="spurgeon")`, `/healthz`, `/api/sermon` and `query.py --library spurgeon`. The same file stays hidden in each of these cases: served as `edwards`, `church`, `talmage` or another slug; tainted with a review hash or a flag; or lacking the marker. A test also shows that without the slug the gate hides it.
- **Non-allow-listed slug, no privacy config, non-zero exit on each path** (`FailClosedTests`): YouTube import and `--dry-run` (exit 2, no callbacks run, nothing written), `--ack-review` (2), `asr_chunks.py` (2, no output), `build_library.py church` and `ingest/run.py --library church --all` (non-zero, also with a config). The public-domain slugs are refused by the YouTube import, `--ack-review` and `asr_chunks.py`.
- On the real `/cache` indexes: spurgeon 534/534 and edwards 2,514/2,514 chunks visible, and `cc-speech` 0/11 (gated). `scripts/classics_smoke.py`: 12/12 (a smoke test, not a quality metric).

### Patrick's decisions
- **Church audio policy is `none`, fixed.** `audio_policy.resolve_flagged_audio()` always returns `none`. `PREACHED_FLAGGED_AUDIO` and the TOML key `flagged_audio` may still say `none`, so old configs load, but `play`/`shifted` raise ("Patrick chose 'none'…") and the import, server and CLI exit 2. The `--flagged-audio` flags are removed from `import/youtube.py`, `app/server.py` and `search/query.py`. The `shifted` code is kept because it is tested (`flagged_play`, `public_times`, `watch_url(policy=)`, `hit_dict(policy)`). It is now reachable only from code: tests set `app.flagged_audio` directly. `ServedTests` and the new sermon tests write play-era links into the fixture DB to simulate an import made before the decision, because `play` can no longer be configured. New test: `test_church_audio_policy_cannot_be_chosen`.
- **Default embedding model:** unchanged (Granite English R2).
- **Whole-sermon withholding: NO.** Only cards that touch flagged passages lose their play/YouTube links, which is the current behaviour. **Residual risk, accepted by Patrick:** an unflagged card's link, and the `/api/sermon` link, can still be scrubbed to a flagged moment elsewhere in the same sermon (on YouTube, the whole video is public). Human review plus the W3-PRIV-SKIP exclusions are the mitigation. This is recorded in `BRIEF.md` (Privacy), `README.md`, `privacy.example.toml` and the `audio_policy` docstring.
- Docs wording: "policy pending Patrick" is replaced with "Patrick chose: no play link on name passages; announcements, prayer requests and testimonies are excluded (see W3-PRIV-SKIP)" in `privacy.example.toml`, `audio_policy.py`, BRIEF and the top of this report. BRIEF had no "pending" sentence, so the decision was added to its Privacy bullet. W3-PRIV-SKIP is not in this branch; the docs only point to it.

### CTO: `/api/sermon` returned the stored `audio_url` (`fb944fe`)
`App._sermon_links` applies the card rules. The stored link is never passed through:
- A non-YouTube URL goes through `public_audio_url`, so `javascript:`, `http:` and `data:` give no link.
- A YouTube link is rebuilt by `policy_watch_url` from the validated id.
- Flagged chunks are skipped (any policy but `play`). Under `none`, chunks that touch a flagged chunk (`touches_flagged`) are skipped too. The first chunk left gives the link; if none is left there is no link.
- A YouTube `source_url` (a watch link from 0:00) is dropped when the sermon has any flagged chunk.

Tests are `SermonLinkTests` (a YouTube sermon whose stored first link plays the names gets the first clear chunk's rebuilt link; an unflagged sermon keeps its links; an all-flagged sermon gets no link) and `ChurchAsrSermonTests` (archive URL kept; unsafe stored URLs give None). This changes one existing assertion: `LiveGateTests` now expects sermon A's YouTube `source_url` to be null.

### Results
- Full suite (`uv run python -m unittest discover -s tests`): **340 tests, all pass**, Deno page tests included. That is 326 after both merges, plus 1 policy test and 13 in `tests/test_priv_allowlist.py`.
- `uv lock --check`: `Resolved 75 packages`. `pyproject.toml` and `uv.lock` are identical to main. **No dependencies added.** No LLM.
- **Wesley API byte-identical to `origin/main`.** Method: `git archive origin/main` was extracted to `/tmp`, and the same script ran in both trees on `/cache/index/wesley.sqlite` with Granite on CPU (asserted no fallback). It covered 40 eval questions × bm25/dense/hybrid at k=10, `/healthz`, and `/api/sermon` for all 141 sermon ids: 262 responses with `took_ms` removed. `cmp` reports them identical; sha256 `a7183ca0…f405df` for both.

### How to run
```
uv run --extra youtube import/youtube.py <channel-url> --library church --privacy /cache/index/church-privacy.toml
uv run --extra youtube import/youtube.py --library church --ack-review <id> --privacy /cache/index/church-privacy.toml
uv run app/server.py --library church          # flagged passages: text only
uv run app/server.py --library spurgeon        # classics: no gate
uv run search/query.py --library edwards "sinners in the hands of an angry god" --mode bm25
uv run python -m unittest discover -s tests && uv lock --check
```

### Open issues
- **#14 is not merged.** If #14 changes `libraries.py` before it merges, this branch needs another merge. #10 is not on main, so its reload has not been checked against the gate.
- `public_domain_file` trusts the meta `library` marker, which `build_library.py` writes. Anyone with write access to `/cache/index` could forge it on a church file. The review-hash and flag checks catch files written by the church import paths, but not a hand-edited file.
- A junk stored YouTube `audio_url` with a valid `source_url` still gets a link rebuilt from that id (same as cards). It is never the stored string.
- `/api/sermon` runs one `touches_flagged` query per chunk until it finds a clear one, and only for sermons with flagged chunks. This was not timed.
- The open issues from the earlier sections still apply: `[name]` timestamps in text, the silent-miss class, title recall 0.926, and the public YouTube video.

## Fix-up: CTO review of PR #12 at 3dc06cd (12-W3-PRIV-REFIX)

**Base and merges (merge commits only, no rebase or force-push).** When I started, `origin/main` was `4129646`, already in this branch. PR #14 was **open** at `ad72124` (CTO round-3 head, including `classic_index_problem`), and I merged it as **`9aa19b3`**. While I worked, **PR #10 (W3-CPU) merged to main** (`2ad5550`), so I merged `origin/main` as **`16db5a0`**, and must-fix 4 applies (see below). The merge order stays #14, #10, #12, #16. Once #14 merges, this PR's diff shrinks by #14's files. **When #14 merges into main, it will hit the same `search/query.py` conflict:** #10 removed the Wesley chunk sync from `query.py`, but #14's `open_index` still called `ensure_chunks`. I resolved it here on #10's side (read-only, never syncs) and kept #14's checks; see `16db5a0`.

| Item | Commit | Change | Tests |
|---|---|---|---|
| **M1** classics exemption not bound to real files | `a7d27be` | `store.public_domain_file` now also requires `store.classic_file_problem`. That check takes the file the connection actually opened (`PRAGMA database_list`, not a path a caller claims) and runs it through **#14's `libraries.classic_index_problem`, reused and not duplicated**: allow-listed slug, canonical `INDEX_DIR/<slug>.sqlite`, no symlinks, realpath equality. It then runs `owner_only_problem` on INDEX_DIR as named, INDEX_DIR resolved, and the file: owned by this euid, not a symlink, not group- or other-writable (checked with `lstat`). The marker, review-hash and flag checks run after that. Anything else is church content: gated, so nothing is served without an approved review. `server.check_servable` adds the same owner/mode check for `--library spurgeon/edwards`. `search/query.py --library` calls `classic_file_problem` after opening. `scripts/classics_smoke.py` opens through `query.open_index` (read-only and canonical) instead of `connect()` (read-write). | `test_priv_allowlist.ForgedMarkerTests` (8): **the CTO repro**, a classics build copied to `tmp/forged.sqlite`, `<root>/spurgeon.sqlite`, `index/sub/spurgeon.sqlite` and `index/edwards.sqlite`, gives 0/14 passages, no `/api/sermon`, `/healthz` 0 with `pending_review`; `server.main --library spurgeon --index <forged>` exits; a symlink at the canonical path, a symlinked INDEX_DIR, group/world-writable dir or file, another owner, or an in-memory DB are all not exempt; the canonical build is still served. `ClassicsVisibleTests` now patch `preached.paths.INDEX_DIR`, and the taint test writes into the canonical path. |
| **M2** untimed YouTube 0:00 link rode on unflagged hits | `04b3aa1` | **Patrick's rule:** flagged passages get no link. Unflagged passages in the same sermon keep their **own timed link**. The untimed sermon-level links (`source_url`, a watch link with no `t=`, an audio file with no seek) are dropped for **any sermon with a flagged passage**, on every surface. New `search.sermon_flagged`. `/api/search`: `hit_dict(..., sermon_flagged=)` sets `source_url` to null, and `audio_url` comes from `server.timed_link`: a rebuilt YouTube link that must carry `&t=`, or an audio file plus a seekable `start_s`. Otherwise `audio_withheld`. `/api/sermon`: `source_url` is null, and `audio_url` is the first clear chunk's own timed link (YouTube `t=`, or `#t=<seek>` on an audio file, never the bare file); with none, no link. `search/query.py`: the play line rebuilds a timed link or prints "withheld"; the text line is `n/a (withheld…)`. A sermon with no flagged passage is unchanged (Wesley byte-identical below). Cards that touch a flagged chunk (`touches_flagged`, an earlier CTO must-fix) still get no link. | `tests/test_priv_links.py` (10): YouTube `/api/search` over 9 queries × k ∈ {1, 5, 20} (flagged: no link at all; clear: exactly `watch_url(id, own start)` with `&t=`; no untimed YouTube URL anywhere in sermon A's JSON; sermon B keeps `source_url`); untimed clear passage gets no link; `/api/sermon` (timed first-clear link, null `source_url`, B unchanged, untimed → none); `query.print_hits` and `hit_play`/`hit_text_link`; the W1-C archive path (`source_url` = details page dropped, CLI links all `#t=`, `/api/sermon` `#t=`). **Against the old server/query code, 12 fail and 1 errors.** `test_privacy_wire.test_served_results_follow_the_policy` and `ChurchAsrSermonTests` were updated to the new rule. |
| **M3** `write_private_review` followed symlinks | `719b228` | The path is never resolved. It is made absolute, and every existing directory above it must not be a symlink. The directory is created 0700, opened `O_DIRECTORY\|O_NOFOLLOW`, checked through `fstat` (directory, owner) and tightened with **`fchmod` on that descriptor** (no `chmod` on a path). The file is a temp opened `O_CREAT\|O_EXCL\|O_NOFOLLOW` 0600 with `dir_fd`, fsynced, and `os.replace`d within the same directory descriptor, then the directory is fsynced. The returned sha256 is of the bytes written, not a re-read (`privacy.write_review_file_sha256`). The repo refusal checks both the absolute path and the realpath of the parent. `align/asr_chunks.py` writes through the same helper. | `tests/test_priv_review_symlink.py` (10): symlink at the file (victim content, mode and **victim dir mode 0755 unchanged**, temp file gone, sha256 matches), dangling symlink, symlinked review dir, symlinked ancestor, relative path through a symlink, open dir tightened via fd, another owner, repo paths (direct and through a symlink), and asr_chunks with a symlinked file and dir. **Against the old code, 9 fail.** |
| **M4** #10 reload must keep the gate | `16db5a0`, `c48f32d` | **#10 is on main** (`2ad5550`). Every Searcher that #10's App builds (`_reload_cached_index`, `_serve_keyword_only` for the stale-vector and status-read-failure paths) goes through `App._searcher()`, which passes `gated` and `library`. Visibility is still the per-request `visible_sql`, and the Searcher still reloads vectors on `PRAGMA data_version`. `health()` runs #10's refresh, then counts visible rows only. | `tests/test_priv_reload.py` (2): with B unapproved, B stays out of bm25/dense/hybrid, `/api/sermon` and the `/healthz` count after a stamp reload (dense), after a status-read failure and its recovery, and after vectors are removed (BM25 fallback). An approval made after a reload is served on the next request with no further reload. With `_searcher()` dropping the gate, 3 subtests fail. |
| **S** Wesley writers and asr_chunks | `fb89ae7` | `store.replace_chunks` and `update_chunk_metadata` (through `_refuse_review_items`) refuse any chunk whose `sermon_id` is not `wesley-*` or that has `flag_end_s` or `video_id`, before writing. `asr_chunks --library wesley` exits 2 on a non-`wesley-*` id or a flagged/gate-keyed row and writes no output. | `tests/test_priv_wesley_writers.py` (2); `AsrGateTests.test_wesley_output_is_unchanged` (a church id is refused; a `wesley-001` id gives exactly the old chunks) |
| **S** read-only opens | `a7d27be`, `16db5a0` | `query.py`: every path is read-only (`mode=ro`, `query_only`) and **never syncs** (main #10 removed the sync; I took that over #14's `ensure_chunks`). `classics_smoke.py`: read-only through `query.open_index`. | #14's `QueryIndexTargetTests` now assert nothing is synced (`test_wesley_index_is_never_synced`); `WesleyNeverSyncedTests` (missing index refused and not created; existing index unchanged, writes fail). Run on `/cache`: smoke **12/12**, and the `.sqlite` mtimes did not change. |
| **S** measure the shift margin | `e63883c` | `scripts/measure_shift_margin.py` (numbers only); results below. | n/a |
| CTO r3: `test_priv_allowlist` fails under #14's sha256 check | `a7d27be` | The fixture writes synthetic audio to `<root>/audio/spurgeon/<file_name>`, and `build_library.provenance_files` is wrapped so that one entry's sha256 is that audio's hash. The committed provenance is untouched, so `is_public_domain` still checks the real file. | the 4 failing tests pass |
| CTO r3: relax `check_servable` for church libraries | `a7d27be` | `check_servable(..., church_gate=)` serves a church slug only when `main` has loaded a privacy config (`required_config()`, i.e. `$PREACHED_PRIVACY`, the config `App` reads) **and** the gate is on (`library != wesley`). After `build_app`, `main` also refuses if `app.gated` is false. A bad config exits. `query.py --library <church>` follows the same rule. | `ChurchServeTests` (4): refused without a config; `check_servable` refused without `church_gate`; served gated with a config (`chunks` 0, `pending_review` 2); a bad config is refused. `test_query_cli_library_flag`: church refused without a config, gated ("Nothing found") with one. |

### Shift margin (should-fix)
`uv run scripts/measure_shift_margin.py` runs the frozen redaction rules (`Config()`) over 188 public-domain ASR transcripts (Wesley 143, Spurgeon 5, Edwards 40) and chunks them as the church ASR path does. The margin is measured against **Whisper's recorded end of the last `[name]` word** in each chunk:

| | n | min | median | p90 | max |
|---|---|---|---|---|---|
| margin, audio-file seek (s) | 1,172 | 0.50 | 0.50 | 0.50 | 0.50 |
| margin, YouTube `t=` (ceil to whole s) (s) | 1,172 | 0.50 | 0.99 | 1.40 | 1.49 |
| gap from name end to the next word (s) | 1,172 | 0.00 | 0.10 | 0.46 | 26.12 |
| words skipped after the name, audio seek | 1,172 | 0 | 1 | 2 | 4 |
| words skipped after the name, YouTube `t=` | 1,172 | 0 | 2 | 4 | 7 |

Of the 1,216 flagged chunks, 44 had no audio left after the shift (withheld). The audio-file margin is the constant 0.5 s by construction. That is less than W1-C's max onset error of 0.76 s in **all** 1,172 cases, and the YouTube margin is in 314 of 1,172. So if Whisper's word end is as early as its worst measured onset, the tail of a name can still be heard. This is measured against Whisper times, not the acoustic end of the name; there is no church audio and no word-end ground truth. `shifted` is not selectable in the product: Patrick chose `none`.

### Results
- Full suite (`uv run python -m unittest discover -s tests`): **450 tests, all pass** (Deno page tests included). That is 372 after the #14 merge (4 failing before the fixture fix), plus 42 from the #10 merge, plus 36 new: ForgedMarker 8, ChurchServe 4, links 10, review symlinks 10, Wesley writers 2, reload 2.
- `uv lock --check`: `Resolved 79 packages`, lockfile unchanged from main (79 since #10). **No dependencies added. No LLM.**
- **Wesley API byte-identical to `origin/main` (`2ad5550`).** The same script ran against a detached `origin/main` worktree and this branch on `/cache/index/wesley.sqlite`, with `build_app` and the default loader (ONNX fp32, asserted no fallback). It covered 40 eval questions × bm25/dense/hybrid at k=10, `/healthz` and `/api/sermon` for `wesley-001..059`: 180 responses with `took_ms` removed. `cmp` reports them identical; sha256 `f27e2a1c…6996df` for both.
- **Wesley ASR chunks byte-identical:** `align/asr_chunks.py` on `origin/main` vs this branch (`--library wesley`) over 143 transcripts gives 8,265 chunks, sha256 `5f624dd5…aee720` for both (the same hash as the earlier rounds).
- **Forged-marker repro on the real `/cache`:** canonical `/cache/index/spurgeon.sqlite` is exempt and serves 14/14 passages (`/healthz` 534/534). A byte-for-byte copy at `/tmp/…/spurgeon.sqlite` is not exempt: 0/14, `/healthz` 0/534, and `server.main --library spurgeon --index <copy>` exits with "is not /cache/index/spurgeon.sqlite".

### How to run
```
PREACHED_PRIVACY=/cache/index/church-privacy.toml uv run app/server.py --library church   # church: needs the config; gated
uv run app/server.py --library spurgeon        # classics: only /cache/index/spurgeon.sqlite, owner-only
PREACHED_PRIVACY=/cache/index/church-privacy.toml uv run search/query.py --library church "grace" --mode bm25
uv run scripts/classics_smoke.py               # read-only
uv run scripts/measure_shift_margin.py
uv run python -m unittest discover -s tests && uv lock --check
```

### Open issues
- **I could not update the PR body.** `gh` is not installed and there is no GitHub token, so this section exists only in the report. It needs to be pasted into PR #12.
- "Owner-only" is enforced as: owned by this user, not a symlink, and not group- or other-writable, for both INDEX_DIR and the file. The real `/cache/index` is 0755 and its files 0644, which passes. I did not require 0700, because that would refuse the current deployment without adding protection against other local users (they cannot write a 0755 directory).
- `approve_review` still re-hashes the review file with `Path.read_bytes`, which follows a symlink. A planted symlink there can only change what gets hashed, not write anywhere, and the hash must still equal the one stored at import.
- Under Patrick's rule, a clear card's own timed link still plays the whole recording onward from its seek, so a listener can scrub to a name. Patrick accepted that risk (see the audio-policy section).
- `sermon_flagged` runs one indexed query per distinct sermon in the results, and `/api/sermon` one per chunk until it finds a clear one. Neither was timed.

## Fix-up round 4: CTO review of PR #12 at 3eaf0ad (12-W3-PRIV-WIRE-FIX4)

**Merge (merge commits only, no rebase or force-push).** PR #14 merged to main as `c95d872`, so I merged `origin/main` as **`ddb2d05`** and did not merge `feat/w3-lib` separately. There were conflicts in `app/server.py`, `search/query.py` and `tests/test_libraries.py`. I kept #14's re-check of `servable` on reload, the refusal state (`App.refused`, 503), the `WESLEY_SCHEMA` allow-list and the file-identity check. I also kept #12's publish gate (`visible_sql` and `visible_count` in `/healthz`, `/api/sermon` and the searcher), the church gate in `check_servable`, and the read-only `query.py`. In `health`/`sermon`, `_check_refused()` now runs before the gated queries. **`libraries.classic_index_problem` is now the only owner/mode gate** (next row).

| Item | Commit | Change | Tests |
|---|---|---|---|
| **Must-fix**: back-to-back chunks kept a link that seeks into the name | `51e06e5` | `search.touches_flagged`, the one shared function used by `/api/search` (`hit_dict` near flag), `/api/sermon` (`_sermon_links`) and `search/query.py`, adds the CTO's rule. A passage touches a flagged chunk when any flagged chunk of the same sermon has `flag_end_s > seek - 0.5 s` (`SEEK_SLACK_S`) and starts before the passage's end. If the passage has no end, or the flagged chunk has no start, it counts. The seek is `search.seek_time(start_s)`, the earliest seek any link uses: the minimum of the audio `#t=` (`play_start`, 0.01 s) and YouTube's whole second (`int(start_s - 0.75)`). For the CTO's numbers (next chunk at 379.9 s) that is 379.0, so a name ending after 378.5 s withholds the link. The old word-span (or time-span) overlap test is still OR'd in, so nothing that was withheld before is served now. | `tests/test_priv_seek.py` (7). **YouTube import** and **ASR archive.org import** through the real HTTP server (`LiveServer`, ephemeral socket). Each has a flagged chunk ending at 378.86–379.22 s whose `word_end` equals the next chunk's `word_start` (the test asserts the old word check passes it). The next chunk's card gets `audio_url` null, `audio_withheld`, no `&t=379s` / `#t=379.15`, and no such link in `/api/sermon`. `query.print_hits` prints "withheld". A control with the name ending exactly at seek − 0.5 keeps `&t=379s` / the audio file. Unit tests cover the boundary (`>` vs `=`), a flagged chunk after the passage, a passage with no end, and a flagged start that is NULL. **On the old rule, 4 of the 7 fail**, including both socket tests (served `…&t=379s` and the bare audio file). |
| **Should-fix**: duplicate owner/mode loop | `d1af557` | Removed `store.owner_only_problem` and the loop in `server.check_servable`. `store.classic_file_problem` now just runs `classic_index_problem` on the file the connection actually opened (`PRAGMA database_list`). | `ForgedMarkerTests.test_another_owner_is_not_exempt` now patches `preached.libraries.os.geteuid`; all of `test_priv_allowlist` and `test_libraries` pass. |
| **Should-fix**: `os.getuid` → `os.geteuid` | `d1af557` | `privacy.write_review` (review-directory owner check). No other `getuid` is left in `src/`, `app/`, `search/` or `tests/`. | `test_priv_review_symlink.test_directory_owned_by_another_user_is_refused` patches `geteuid`. |
| **Should-fix**: dead gate-off check | `d1af557` | Removed `if church and not app.gated: … publish gate off` from `server.main`. `App.gated` is true for every library but wesley, and no switch turns it off, so it could never fire. `church_gate` is now set only after a privacy config loads. | Existing `ChurchServeTests` (config required, gate on). |
| **S1** (#14 ruling): sidecars of a classic index | `14c2d79` | `classic_index_problem` gives any existing `-wal`, `-shm` or `-journal` next to the index (`SIDECAR_SUFFIXES`) the file checks: lstat (no symlink), regular file, one link, owner root or euid, no group/world write. **Reproduced locally:** a WAL written to a scratch copy and planted next to the real classic file is replayed by the read-only reader, which then shows the planted text. SQLite resets an *empty* sidecar to the db file's mode when it opens it; an empty one has nothing to replay. On `/cache/index`, spurgeon and edwards still pass (their sidecars are 0644). | `test_libraries.ClassicSidecarTests` (3): the CTO repro (served without the check, refused by `classic_index_problem`, `server.main --library edwards` and `query.py --library edwards`); every suffix × {group-writable, symlink, hardlink, directory, other owner} refused and root-owned accepted; a private (0644) WAL passes. |
| **S2** (#14 ruling, with correction): root as owner | `14c2d79` | `libraries._owner_mode_problem` accepts uid 0 or the server's euid for the parent, INDEX_DIR, the index and its sidecars. Group/world write is still refused for both. #14 refused root-owned dirs; this is the change. | `test_libraries.ClassicRootOwnerTests` (3): root-owned parent/dir/file pass `classic_index_problem` and `server.main`; root-owned but world-writable is refused; another uid is still refused. |

The old `test_world_or_group_writable_is_refused` tests (in `test_libraries` and `test_priv_allowlist`) needed a fixture fix after S1. While a test had the db file chmodded group-writable, SQLite created a `-wal` with that mode, and the new check correctly refused it afterwards. The tests now set the sidecars back to the file's mode when they restore it.

### Results
- Full suite (`uv run python -m unittest discover -s tests`): **475 tests, all pass**, none skipped (Deno page tests ran). That is 462 after the merge (the same after the should-fix commit), plus 6 for S1/S2 and 7 for the must-fix.
- `uv lock --check`: `Resolved 79 packages`. `pyproject.toml` and `uv.lock` are identical to `origin/main`. **No dependencies added.** No LLM.
- **Wesley API byte-identical to `origin/main` (`c95d872`).** `git archive origin/main` was extracted to `/tmp`, and the same script ran in both trees on `/cache/index/wesley.sqlite`. It used `build_app` with the default loader (Granite, asserted no fallback) and covered 40 eval questions × bm25/dense/hybrid at k=10, `/healthz` and `/api/sermon` for all 141 sermon ids: 262 responses with `took_ms` removed. `cmp` reports them identical; sha256 `c38d3a41…d4e29cd8` for both.
- I could not edit the PR body: `gh` is not installed in this environment. This section is the record for round 4.

### Open issues
- A swapped-in WAL is checked when the server starts and whenever the gate re-runs on reload (stamp change). A WAL replaced under an already-open reader is not replayed while the existing `-shm` index doesn't match it, so I did not add a reload test for that case. Only root or the server's euid can write INDEX_DIR, so planting needs one of those uids.
- The seek rule uses a fixed 1.5 s slack (`SEEK_SLACK_S`, was 0.5 s before round 5) before the earliest seek. A word end later than that (the clean-audio maximum was 3.58 s) or a player that lands more than 1.5 s before the requested `t=` could still reach a name. YouTube's whole-second `t=` is already covered by `seek_time`.
- The earlier open issues still apply (residual same-sermon scrub risk accepted by Patrick, `[name]` timestamps, title recall).

## Fix-up round 5: CTO review of PR #12 at d82a388 (13-W3-PRIV-WIRE-FIX5)

The CTO's report file was not visible to me; I worked from the task text. No merge was needed (`origin/main` is still `c95d872`).

| Item | Commit | Change | Test |
|---|---|---|---|
| **Must-fix**: privacy margin | `19226a9` | `SEEK_SLACK_S` 0.5 → **1.5 s**. Large-v3-turbo word ends vs forced alignment were p95 0.12 s, p99 0.48 s, max 3.58 s late on clean studio audio; church audio will be worse. 1.5 = p99 + 0.5 s. Not addressed by rounding: `seek_time` floors, which moves the seek toward the name, so it was left alone. | `test_priv_seek.py`: boundary and both control tests derive from `SEEK_SLACK_S` (no pinned 0.5). New `test_margin_is_wide_enough_for_late_asr_word_ends`: ends at seek−0.51, −1.0, −1.49 (between the old and new margin) now touch; exactly seek−1.5 and anything earlier do not. |
| **Should-fix**: `/healthz` on a refused index | `ad41d07` | `App.health` re-runs the serve gate itself each call (a swapped `-wal` can leave the index stamp unchanged, so the reload path never re-checked and `/healthz` reported ok with 0 chunks). A refusal now returns HTTP 503 and sets `_status_failed`, so recovery rebuilds the searcher. | `test_libraries.test_healthz_reports_a_refusal_the_stamp_did_not_notice`: gate fails with the stamp unchanged → `/healthz` and search 503; gate passes again → both serve. |
| **Round-4 leftover**: `audio_policy` rounding | `ac942c6` | `flagged_play` rounds the `shifted` seek **up** to 0.01 s (was `round`, which could pull it earlier than `flag_end_s + margin`). If rounding reaches the chunk end, no audio is left. The excluded span can only widen. | `test_privacy_wire`: 20.001 → 20.51; seek ≥ flag_end + margin; 54.491 → withheld. |
| **Round-4 leftover**: review-path ancestor race | `7c8ab3c` | `privacy._open_private_dir` walks the path from `/` one component at a time with `O_DIRECTORY \| O_NOFOLLOW` relative to the previous descriptor (`mkdir` with `dir_fd` for missing parts). No check-then-use window: a component swapped for a symlink fails the open, and the descriptor held stays on the directory that was checked. The islink loop is gone. | `test_priv_review_symlink`: a component swapped for a symlink immediately before it is opened is refused and the victim directory is untouched; the existing symlink tests pass. |
| **Round-4 leftover**: Wesley in-place rows (documentation) | this section | Wesley is not gated (`App.gated` false) and has no `flag_end_s`, so the privacy rules never apply to it. The searcher re-reads row text per call (M1), so a row edited in place is served as edited on the next request. Cached vectors and the abstain state reload only when the index stamp (chunk hash, row count, embedding records) changes, so an in-place edit that keeps the hash and counts is not re-embedded until restart. Nothing in this branch writes to the Wesley index. | n/a |

### Results
- Full suite: **478 tests, all pass** (475 before, plus 3 new).
- **Wesley byte-identical to `origin/main` (`c95d872`)**: same script in both trees on `/cache/index/wesley.sqlite` (40 eval questions × bm25/dense/hybrid at k=10, `/healthz`, `/api/sermon` for 141 ids; 262 responses, `took_ms` removed). sha256 `4d018f76…311f311` for both. `/healthz` now runs the Wesley gate check on each call; the payload is unchanged.
- `uv lock --check`: `Resolved 79 packages`; `pyproject.toml` and `uv.lock` identical to `origin/main`. No dependencies added, no LLM.
