# W3-PRIV-SKIP: announcements, prayer requests and testimonies are never indexed

**Decision (Patrick, 2026-10-30 2:59 PM ET):** for church libraries, stretches that are announcements, prayer requests or prayer lists, or testimonies are excluded. They are never indexed, embedded, searchable or playable.

**Base.** `feat/w3-priv-skip` branches from `origin/feat/w3-priv-wire` at `3eaf0ad` (PR #12, with 11-W3-PRIV-WIRE-ALLOWLIST pushed). PR #12 was **not merged** when I started, so this PR stacks on #12. No merges were needed and nothing was rebased.

## What was done

1. **Detector `src/preached/skip.py` (new, stdlib only, no model).** `propose(words) -> [Stretch]`. Each stretch has `start`/`end` word indexes (end exclusive), a category, the matched cues as `(cue phrase, word index)`, and the reasons (`cue`, `before the sermon proper`, `after the benediction`). The method is described below.
2. **Import never indexes a proposed stretch.** On the YouTube path (`youtube/pipeline._plan`) and the church ASR path (`align/asr_chunks.church_plan` → `preached/asr.church_records`), the sermon words are redacted as before. The stretches are then proposed, and each run of kept words is chunked **on its own**. A chunk that would span a boundary is therefore cut at it. `word_start`/`word_end` still index the sermon's words (YouTube) or tokens (ASR), so neighbouring chunks stay comparable for dedupe and `touches_flagged`. Name review items that lie wholly inside an excluded stretch are dropped from the review file, because those words are not indexed. The console prints counts only.
3. **The review file lists the stretches** and is covered by the sha256 stored at import. After the title and description lines it holds:
   - one `{"field": "exclusions", "words": N, "words_file_sha256": …, "how": …}` line;
   - one `{"field": "exclude", "start_word", "end_word", "start_s", "end_s", "category", "cues", "reasons", "opening", "closing"}` line per stretch. `opening`/`closing` are the first and last 12 words, so the reviewer can find the stretch in the recording.

   Next to the review file, a second owner-only file `<id>.words.review.jsonl` holds the **kept** words (already redacted) with their times. It contains none of the excluded words, and its sha256 is on the `exclusions` line. It is written with the same no-symlink, 0600 writer as the review file.
4. **Approval excludes exactly what the reviewed file lists** (`preached/exclusions.approve`, called by `--ack-review`).
   - **Unchanged file:** approved as before, with no re-embedding.
   - **Edited `exclude` lines:** the reviewer may confirm a line, widen it (lower `start_word` or raise `end_word`, or change `start_s`/`end_s`), or add a line by time or by word range. A line's word range and time range are unioned. Every other line must be byte-identical; that is checked against a new `videos.review_base_sha256` column (the file's sha256 without its `exclude` lines). The kept-words file must match its sha256.
   - **Rebuild:** if the edit excludes more words, the sermon's chunks are rebuilt from the kept words minus the new stretches, re-embedded, and written over the old rows. SQLite `secure_delete` is on for this write, the FTS index is merged (`optimize`) and the WAL is checkpointed. The approval is then stored against the edited file's sha256, and the kept-words file is deleted.
   - **Refused:** narrowing or removing a proposed stretch (its words were never stored), malformed ranges, edits outside `exclude` lines, a tampered kept-words file, and **any edit after approval** ("changed after approval; re-import with --redo"). The existing sha gate handles that last case: `approved_sha256` is fixed and any other digest is refused.
5. **Unaffected.** Wesley (`asr_chunks --library wesley`, no privacy config) never runs the detector. Spurgeon and Edwards are built by `search/build_library.py`, which does not import the detector. No serving or search code changed (`app/`, `search/`, `store.py`, `search.py` are untouched), so what is served from an index is unchanged; only what goes into a church index changed.

### Method and cues
The words are split into units: sentences, or 30-word pieces when the ASR has no punctuation. Cues are matched on lowercased words with punctuation removed. `TIME` matches a clock time ("6:30", "7pm", "p.m.", "o'clock"), `[name]` matches a redacted name, and `*` matches 1–3 words. The full lists are `CUES`, `SERMON_START`, `BENEDICTION`, `TESTIMONY_END` and `PRAYER_OPENERS` in `skip.py`. Examples:

| | strong cues (one seeds a stretch) | weak cues (two different ones in a unit seed a stretch; any one extends it) |
|---|---|---|
| announcements | announcements, potluck, sign up, covered dish, fellowship hall, bulletin, connection card, first time guest, nursery, VBS, youth group, bake sale, info table, give online, church app, small groups | this week, next week, tonight, weekday names, TIME, don't forget, reminder, join us, bring a, deadline, register, lobby, foyer, after the service, welcome, kids, breakfast, supper |
| prayer | prayer requests, prayer list, prayer chain, please be praying, please pray for, be praying for, pray for [name], keep … in your prayers, let's pray, bow your heads, unspoken, praise report, passed away, home to be with the Lord, traveling mercies | pray for, praying, prayers, hospital, surgery, diagnosed, cancer, chemo, recovering, funeral, grieving, lift up, deployed, rehab, ICU, "her mother", "their son" |
| testimony | testimony, testify, I want to share, share what God did, what God has done in my life, going to share with us, come up and share, share my story | my life, I was, I had, got saved, baptized, God showed up, praise God, my husband, my kids, lost my, years ago, I felt |

"testimony of", "testimony to the" and "testify of" do not count ("the testimony of Scripture").

Rules:
- **Grow.** A seeded stretch grows over units while a cue of any category occurs within `GAP` = 2 cue-less units. It then takes `PAD` = 1 unit on each side. It never crosses a "sermon starts" marker.
- **Testimony.** It runs to an end marker ("thank you for sharing", "give him a hand"), or at least 12 units. Testimony stories carry few cue words after the first sentence.
- **Opened prayer.** A prayer opened by "let's pray" or "bow your heads" runs to its "amen".
- **Position.**
  - Before the first sermon marker in the first half ("open your Bibles", "turn with me", "our text", "stand for the reading of God's word"): if that part holds any cue, everything from the start to the marker is excluded.
  - After the last benediction in the last quarter ("the Lord bless you and keep you", "go in peace", "now unto him who is able", "you're dismissed"): everything after it is excluded.
- **Merge.** Stretches that overlap or are at most one unit apart merge.

`redact` runs before detection, so cues see `[name]`. I first counted a bare `[name]` as a weak prayer cue, but then the pastor's own name stories in the existing fixtures were excluded (for example "I told [name] about the hospital"). It is now only part of the strong cue `pray for [name]`.

## How to run
```
uv run --extra youtube import/youtube.py <channel-url> --library church --privacy /cache/index/church-privacy.toml
# read /cache/index/church/review/<id>.review.jsonl with the recording: confirm, widen or add "exclude" lines
uv run --extra youtube import/youtube.py --library church --ack-review <id> --privacy /cache/index/church-privacy.toml
# church ASR path: same review and approval
PREACHED_PRIVACY=/cache/index/church-privacy.toml uv run align/asr_chunks.py <transcripts> --library church --out /tmp/c.jsonl --index /cache/index/church.sqlite
uv run python eval/skip/evaluate.py eval/skip/dev.jsonl eval/skip/test.jsonl [--show]
uv run python -m unittest discover -s tests && uv lock --check
```

## Results

### Synthetic evaluation (small, LLM-written by me, Claude; not real services)
`eval/skip/dev.jsonl` (8 docs) and `eval/skip/test.jsonl` (12 docs) are **synthetic transcripts that I wrote for this task**. All names are invented. Gold stretches are marked inline. The sets include hard negatives: a sermon about prayer, "this week" homework, a pastor's own hospital and funeral stories, a joke that quotes a bulletin, and "the testimony of the apostles". I wrote both splits before running the detector on either. The test split was **scored once and the rules were not changed afterwards**. The dev split was also scored once and needed no change; the rules were written against the unit-test fixtures only. That I wrote both the rules and the sets is weak protection against overfitting. Results: `eval/skip/results-2026-10-30.json`.

| | dev (8 docs, 2,048 words) | **test (12 docs, 2,386 words)** |
|---|---|---|
| gold stretches | 8 | 14 |
| stretch recall, every word excluded | 8/8 = 1.000 | **11/14 = 0.786** |
| stretch recall, at least one word | 8/8 | 13/14 |
| by category (full) | ann. 4/4, prayer 2/2, testimony 2/2 | ann. 7/8, prayer 3/3, testimony 1/3 |
| word recall | 636/636 = 1.000 | **635/730 = 0.870** |
| over-exclusion (non-gold words excluded) | 119/1,412 = 0.084 | **444/1,656 = 0.268** |
| proposed stretches / false (<10% gold) | 8 / 0 | 10 / 1 |

Misses on test:
- **test-10, 0% covered.** A welcome that introduces a new staff member and announces a birthday ("this is Clementine…, she's our new children's director", "it's Mr. … ninetieth birthday"). It has none of the cue words, and the sermon marker ("Let's go to Psalm 90") is not in `SERMON_START`, so the position rule did not fire.
- **test-08, 73%.** The intro to a testimony video ("a short video … about what God did in his family"): "what God did in his family" is not a listed phrase.
- **test-12, 85%.** The opening question "Is there anybody who has a praise this morning?" ("a praise" is not a cue).

Over-exclusion comes from the padding and the minimum lengths:
- test-03: the 12-unit testimony minimum ran 96 words into the sermon.
- test-12: a prayer request was padded and grew 130 words into the sermon.
- test-11: a closing prayer for illumination after "let's pray" was excluded; I labelled it not gold.
- test-09: one false stretch, a sermon joke about a bulletin "potluck" typo.

On recall, **3 of 14 test stretches would have been left partly or wholly in the index** without a human. The two partial misses are the opening sentences before the strong cue. **The human review step is the real safeguard:** the reviewer reads the recording against the proposed stretches and adds what the rules missed (tested: `test_reviewer_added_stretch_is_excluded`).

### Over-exclusion on real public-domain ASR (no gold; a different genre)
I ran `propose` (not wired to this path) over the 143 Wesley LibriVox transcripts, 653,506 words:
- 4.0% of the words fall in a proposed stretch, in 73 of the 143 sermons.
- By category: 69 testimony, 46 prayer, 10 announcements. 18th-century first-person preaching ("I was…", "I had…", "testify") reads like a testimony.
- Speed: about 10,000 words/s on one CPU core, under 1 s for a 45-minute sermon.

This is real ASR, but not church services, so it only bounds how much the rules cut from plain sermon text.

### Tests
- **Full suite:** `uv run python -m unittest discover -s tests` runs **466 tests, all pass** (450 before, 16 new in `tests/test_priv_skip.py`). Deno page tests are included.
- **Each category excluded (YouTube import).** Lowercase marker words inside an announcement, a prayer request, a testimony and a post-benediction notice are absent from the SQLite file and its WAL, from stdout/stderr, from BM25 and from the kept-words file. The vector count equals the chunk count. Words outside the stretches are present and searchable after approval.
- **Boundary cutting.** No chunk overlaps an excluded stretch by word range or time. Some chunk ends exactly at the prayer stretch's first word and another starts at its end, and chunk text equals its words.
- **Reviewer-added stretch** (by time, YouTube; by word range, ASR path). After `--ack-review` the marker is gone from the SQLite file and WAL and from BM25, chunks are cut at the new boundary, the sermon is served, and the kept-words file is deleted. Turning off FTS `optimize` makes these two tests fail: the removed word stays in the old FTS segments. Turning off `secure_delete` alone does not make them fail here; I kept it as defence in depth.
- **Widened stretch** excluded. **Narrowed or removed** stretch refused; the unchanged file then approves without re-embedding.
- **Edit after approval refused** ("changed after approval"). An edited title line or a tampered kept-words file is refused, and so are malformed `exclude` lines.
- **Detector unit tests:** each category, the position rules, hard negatives kept, deterministic output, and imports limited to `re`/`dataclasses`/`typing`.
- **Wesley.** `asr_chunks` without a privacy config keeps every word. The classics builders do not import the detector.

### Wesley byte-identical
`align/asr_chunks.py --library wesley` on this branch, compared with `origin/main` (`git archive` to `/tmp`; main has no `--library` flag), over all 143 transcripts in `/cache/transcripts/wesley`: 8,265 chunks each. `cmp` reports them identical, sha256 `5f624dd5…aee720` for both (the same hash as in W3-PRIV-WIRE). I did not re-run the Wesley API byte check. This branch changes no file under `app/`, `search/`, or `store.py`/`search.py`, and the Wesley index is not rebuilt by anything here.

## Open issues, risks, exclusions
- **Recall is not enough on its own.** On the synthetic test split, 3 of 14 stretches were not fully covered and one was missed entirely. A welcome without cue words (staff introductions, birthdays, thank-yous to families) is the weak spot. Publish only after a person reads the review file **with the recording**. Real services are unmeasured. The eval is small (14 test stretches), and I wrote it, so it shares my blind spots.
- **Over-exclusion is high** (26.8% of non-gold words on test) because of padding and the testimony minimum. That costs search coverage, not privacy. A reviewer cannot narrow a stretch, so a false exclusion is permanent unless the sermon is re-imported. I chose this deliberately (fail closed); it is the trade-off for never storing excluded words.
- **Excluded words outside the index.** The excluded words are not in chunks, FTS, vectors, logs or the repo. They do exist in two places:
  - the private review file's `opening`/`closing` previews (owner-only, outside the repo; the same file already holds real names);
  - the YouTube video itself, which stays public. A clear card's timed link can still be scrubbed into an excluded stretch; this is the residual risk Patrick accepted in W3-PRIV-WIRE.
- **The kept-words file is a second copy of the redacted sermon text** in `<index dir>/<library>/review/` until approval. It is deleted after a successful approval. A sermon that is never approved keeps it, as it keeps its review file.
- **Approval can re-embed.** When the reviewer adds exclusions, `--ack-review` loads Granite ONNX on CPU. It is skipped when the file is unchanged.
- **Old imports.** A sermon imported before this change has no `review_base_sha256`. Its review file can only be approved unchanged; to get exclusions, re-import it with `--redo`.
- **`drop` windows still apply first.** Word indexes in the review file count the words left after `drop` windows.
- **Rules not changed after the test split.** The misses above suggest cues ("introduce", "birthday", "a praise", "what God did in his family") and the marker "let's go to". Adding them now would be fitting to the test set; they need new data to be measured.

## Dependencies added
None. `uv lock --check`: 79 packages, lockfile unchanged. No model calls of any kind.

## Merge of #12 and main (14-W3-PRIV-SKIP-MERGE12)

- **Merged:** `origin/feat/w3-priv-wire` at its post-FIX5 head `96efa8a6ca571345ee73d18261f222ad6bb41ba4` (FIX4 `touches_flagged` boundary rule, SEEK_SLACK_S 1.5 s, `/healthz` 503 on a refused index), as merge commit `0744eda`. Then `origin/main` at `c95d8721fcd97da7161dbde9f3777e4ff313c698` (#14): "Already up to date", because #12 had already been re-merged onto main after #14. Merge commits only, no rebase or force-push.
- **Conflicts:** none. Git merged every file automatically. #12 touched `app/`, `search/`, `search.py`, `store.py`, `privacy.py`, `audio_policy.py` and `libraries.py`; this branch touched `exclusions.py`, `skip.py`, `asr.py`, `pipeline.py`, `library.py`, `align/asr_chunks.py` and `cli.py`, so no hunk overlapped. I checked the result by hand. `search.touches_flagged` and `SEEK_SLACK_S = 1.5` are #12's, unchanged. #14's `libraries.classic_index_problem` is still the only owner/mode gate: this branch adds no gate, and `align/asr_chunks.py` still refuses the classics slugs through `PUBLIC_DOMAIN`.
- **Tests after the merge:** 494, all pass (before the fix-up below).

## Fix-up: CTO review of #19 at dd33e2f (Oct 30, 4:49 PM ET) and the 5:00 PM update

Commits on top of the merge: `d9b67a1`, `76040b1`, `c7e4916`, `556bdf4` (then this report).

| Item | Fix | Commit | Tests |
|---|---|---|---|
| **Must-fix 1**: play links seek into excluded stretches | New `exclusions.boundary_flags`: the first and last chunk of every kept run next to a stretch get `flag_end_s` (the start of the first kept word after the stretch, or the run's own end when the stretch runs to the end). This happens in `youtube_records`, `asr.church_records`, and the rebuild at approval. Under `none` those chunks get no link. `search.sermon_flagged` then drops the untimed sermon links (the 0:00 `source_url` on `/api/sermon`). #12's shared `search.touches_flagged` (SEEK_SLACK_S 1.5 s, unchanged; #19 has no margin of its own) withholds the link of any other chunk whose seek could reach back into the stretch. A redacted name next to a stretch composes the same way. | `d9b67a1` | `tests/test_priv_skip_links.py` (5). Real HTTP `/api/search`, `/api/sermon` and `query.print_hits` are checked on a YouTube import and on an ASR (archive.org) import, plain and with a redacted name in the chunk before the prayer stretch. No seek falls in `[stretch start, stretch end + 1.5 s)`, the neighbour cards are `audio_withheld`, and `/api/sermon` has a null `source_url` and only timed links. Plus a `boundary_flags` unit test. With `boundary_flags` disabled, all 5 fail, and the surface check reproduces the CTO's `seek 122.0 inside excluded 95.5-123.4`. |
| **Must-fix 2**: `--redo` deletes without secure_delete | `youtube.library.open_library` (church libraries only; Wesley and the classics never use it) turns on `PRAGMA secure_delete` and refuses to write if SQLite will not. `index_video` runs `scrub` after it replaces earlier rows (`--redo`, a rebuild): FTS `optimize`, commit, then the checked checkpoint below. | `76040b1` | `SecureDeleteTests`: a canary is replaced on an open connection and is gone from the raw db + `-wal` bytes (`-wal` is 0 bytes). A control with secure_delete off and no scrub keeps the canary. `test_redo_canary_removed_from_db_and_wal` covers the end-to-end `--redo`. Note: this end-to-end test also passes with secure_delete off, because page reuse happens to overwrite the canary there. The open-connection test is the one that discriminates. |
| **Must-fix 3**: checkpoint result ignored | `youtube.library.checkpoint` reads `wal_checkpoint(TRUNCATE)`'s `(busy, frames, done)` and treats it as done only when busy is 0 and frames equals done. Otherwise it retries with backoff (0.05 to 4 s, 200 ms busy timeout per try, about 8 s in all) and raises `CheckpointBusy`. `approve()` scrubs before recording **every** approval, so a refused checkpoint approves nothing. `--ack-review` prints "not approved: … checkpoint …" and exits 1, and a later retry finishes the job. A refused checkpoint during `--redo` fails that video (exit 1). | `76040b1` | `CheckpointTests` (backoff sequence, then refused; succeeds once the reader lets go). `test_ack_with_a_concurrent_reader_exits_nonzero_then_retries`: a reader holds a read transaction, `--ack-review` exits 1 and nothing is approved, then after release it exits 0 and the canary is gone. `test_unchanged_ack_with_a_reader_is_refused_too`, `test_redo_with_a_busy_reader_fails_loudly`. With the result check removed, all 4 fail. |
| **Must-fix 4**: eval set labelled "hand-marked" | `eval/skip/evaluate.py` now says the data is synthetic and LLM-written (Claude wrote the transcripts and the gold stretches; no person checked them). Every line of `dev.jsonl`/`test.jsonl` has a `provenance` field, and `evaluate.py` refuses a line without it. Also changed: `eval/README.md` (new section), the `skip.py` docstring, and the heading of this report's eval section. Scores unchanged (test word recall 635/730 = 0.870). | `c7e4916` | `evaluate.py` re-run: same numbers. |
| Should-fix: `--redo` keeps reviewer-added stretches | `exclusions.previous_excludes` reads the old review file (O_NOFOLLOW; a symlink at the name is ignored and replaced as before). `carried_stretches` maps every old `exclude` line onto the new words: the time range always counts, and the word range only when the word count is unchanged. A word-only line on a changed transcript stops the re-import. Carried words are excluded at import and appear as `proposed_by: "previous review"` lines. The same applies to a re-run of `align/asr_chunks.py`. | `76040b1` | `test_redo_secure_deletes_and_keeps_reviewer_stretches` (same transcript, then a longer one), `test_redo_word_only_line_on_a_changed_transcript_is_refused`, `AsrOutTests.test_rerun_keeps_reviewer_stretches` |
| Should-fix: ASR `--out` keeps excluded words after approval | `asr_chunks.py` records the absolute `--out` path in the kept-words meta. A rebuild at approval replaces that sermon's rows in the file, in place and in order (`exclusions.replace_out_rows`: atomic replace, old bytes zeroed, no symlink followed). Other sermons' rows are unchanged. | `76040b1` | `test_out_file_drops_newly_excluded_words_and_keeps_other_sermons` |
| Should-fix: purge the 12-word previews on approve | After approval, `_purge_previews` rewrites the review file without `opening`/`closing` (`privacy.replace_private_bytes`: temp file, rename, then the old inode is zeroed). The stored `review_sha256` and `approved_sha256` move to the purged file in one statement, so the sermon stays published and later edits are still refused. The kept-words file is zeroed, then deleted. | `76040b1` | `test_previews_are_purged_and_the_sermon_stays_published` |
| Should-fix: approve opens its files with O_NOFOLLOW | New `privacy.read_private_file` opens each directory from `/` with `O_DIRECTORY \| O_NOFOLLOW` (#12's `_open_private_dir`, now with `create=False`), then the file with `O_NOFOLLOW`. Approval reads the review and kept-words files only this way. `library.approve_review` was folded into `exclusions.approve` and removed. | `76040b1` | `test_symlinked_review_or_words_file_is_refused` (each file swapped for a symlink to an identical copy: refused, not approved) |
| CTO ruling: the human check is the real control | The review file's `exclusions` header line has a `reviewer_must` field: listen through the whole recording before approving. It cites word recall 0.870. README (church import), `privacy.example.toml`, the `exclusions`/`skip` docstrings and `eval/README.md` say the same. `docs/DEPLOY.md` exists only on `feat/w3-deploy-prep` (not merged to main), so it is not changed here. It needs the same sentence when that PR lands. | `76040b1`, `556bdf4` | `test_review_header_says_listen_to_the_whole_recording` |
| 5:00 PM update: same margin | #19 has no seek margin of its own. The boundary chunks are flagged, and #12's `touches_flagged` with `SEEK_SLACK_S = 1.5` decides every other link. The link tests assert against that constant. | `d9b67a1` | as must-fix 1 |

Every new test was also run against the code with its fix disabled; the listed tests fail there.

### Numbers
- **Full suite** (`uv run python -m unittest discover -s tests`): **513 tests, all pass**, none skipped. That is 494 after the merge, plus 5 in `tests/test_priv_skip_links.py` and 14 in `tests/test_priv_skip_fixup.py`.
- **`uv lock --check`**: 79 packages, lockfile unchanged. No dependencies added. No model calls of any kind.
- **Wesley API byte-identical to `origin/main` (`c95d872`).** `git archive origin/main` was extracted to `/tmp`, and the same script ran in both trees on `/cache/index/wesley.sqlite`. It used `build_app` with the default loader (Granite, asserted no fallback) and covered 40 eval questions × bm25/dense/hybrid at k=10, `/healthz` and `/api/sermon` for all 141 sermon ids: 262 responses with `took_ms` removed. `cmp` reports them identical; sha256 `43233c40…66dad4ae` for both.
- **Wesley ASR chunks byte-identical:** `align/asr_chunks.py` on `origin/main` vs this branch (`--library wesley`) over 143 transcripts gives 8,265 chunks. sha256 is `5f624dd5…aee720` for both, the same as in earlier rounds.

### How to run
```bash
uv run python -m unittest discover -s tests && uv lock --check
uv run python -m unittest tests.test_priv_skip_links tests.test_priv_skip_fixup
uv run python eval/skip/evaluate.py eval/skip/dev.jsonl eval/skip/test.jsonl
```

### Open issues and risks (fix-up)
- **Approval needs a quiet moment.** A checkpoint is refused while a reader holds a read transaction for the whole ~8 s of retries. The server's queries are short, so this should be rare, but a busy server can make `--ack-review` exit 1. Retrying is safe.
- **Boundary flags cost links.** Two chunks per stretch lose their play link. Whole sermons that touch a stretch also lose `source_url`, which in practice is every church sermon with a stretch. The flag value is the first kept word's start, not the excluded word's end (the rebuild does not keep excluded word times). The 1.5 s slack in `touches_flagged` covers late ASR word ends.
- **Zeroing files is best effort.** Journaling or copy-on-write filesystems and SSD wear-levelling can keep old blocks of the review, kept-words and `--out` files. secure_delete covers SQLite pages only.
- **`--out` must sit under a symlink-free path** for the rewrite at approval. Otherwise approval is refused with a message, which fails closed.
- **Preview purge after a crash.** If the process dies between the file rewrite and the sha256 update, the sermon stays published under the old sha256, and a re-ack reports "changed after approval". Re-import with `--redo` to recover.
- **Reviewer-only safeguard.** As ruled, the human listening through the whole recording is the control. The rules' 0.870 word recall comes from LLM-written synthetic data, and real services are unmeasured.

## Re-merge of #12 FIX6

- **Merged:** `origin/feat/w3-priv-wire` at `93928fa` (FIX6; #19 had merged `96efa8a`), then `origin/main` at `c95d872` (already up to date, nothing to merge). Merge commits only.
- **Conflicts:** one, in `src/preached/privacy.py::_open_private_dir`. #19 added the `create` flag (`create=False` raises on a missing directory, for `read_private_file`); #12 added the retry when `mkdir` loses a race (`FileExistsError`). Kept both: raise if `not create`, else `mkdir`, tolerate `FileExistsError`, then open again (it still fails closed on anything that is not a plain directory). Everything else merged cleanly.
- **`shifted` removed:** #12's deletion wins (`SHIFT_MARGIN_S`, `scripts/measure_shift_margin.py`, the policy value, its tests and its `play_from_s` plumbing). #19 had no code, tests, config or docs of its own that used `shifted` or `SHIFT_MARGIN_S`, so nothing more to remove. What remains is wording that says `shifted` is refused (`privacy.example.toml`, the comments in `app/server.py` and `search/query.py`, history in `reports/W3-PRIV-WIRE.md`). `FLAGGED_AUDIO` is `("play", "none")` as in #12; church libraries accept only `none`.
- **Kept:** the stretch-neighbour `flag_end_s` rule, `secure_delete`, the checked checkpoint, eval provenance labels and the "listen through the whole recording" text. #19 still uses #12's shared `touches_flagged` with `SEEK_SLACK_S = 1.5` and has no margin of its own (`tests/test_priv_skip_links.py` and `tests/test_priv_seek.py` assert against that constant).
- **Checks:** full suite **512 tests, all pass**. `uv lock --check`: 79 packages, unchanged. Wesley API byte-identical to `origin/main`: 261 responses (40 questions × bm25/dense/hybrid at k=10, plus `sermon()` for 141 ids; `took_ms` removed), same sha256 prefix `a71689a08fee816f` in both trees. Wesley ASR chunks identical: 8,265 chunks, sha256 `5f624dd5…` for both.
- **New head:** see the commit that adds this section (`git log -1`).

## Fix-up round 3: CTO final gate on #19 at e08a9da

Merged `origin/main` (98e2e9a, merge commit, no rebase). Product code unchanged apart from two messages and one path resolve.

| Item | Change | Test |
|---|---|---|
| **Must-fix**: redo canary test passed without secure_delete | `test_redo_canary_removed_from_db_and_wal` now imports a long transcript (`SERVICE + FILLER*40`), then `--redo`s a much shorter one, so pages are freed. It asserts the canary is absent from the raw db and `-wal`, that every free page is all zero (`free_pages`: leaves whole; a trunk page's first 64 bytes, which are old b-tree header and cell offsets that SQLite does not wipe, are skipped), and that `PRAGMA secure_delete` is 1 on every connection `open_library` returns during the `--redo`. | same test |
| Mutation | With the `secure_delete = ON` line removed from `open_library`, the test fails on the pragma assertion (`[0]`). With that assertion also disabled, it still fails on "free page 16 holds stale bytes". Restored afterwards. | |
| `create=False` guard (`privacy.py` `_open_private_dir`) | New test: a missing directory raises `FileNotFoundError` and nothing is created, for `_open_private_dir` and `read_private_file`. With the guard removed, it fails. | `test_create_false_never_makes_a_missing_directory` |
| Checkpoint error names db and `-wal` | `library.checkpoint` message now includes both paths. | asserted in `test_redo_with_a_busy_reader_fails_loudly` |
| `asr_chunks --out` resolved | `Path(out).resolve()` instead of `abspath`. | existing ASR out tests |
| Refused `--redo` takes the sermon offline | The CLI prints `sermon <id> is now offline until re-reviewed (--redo failed, so it is marked error)`. | asserted in the busy-reader test |

- **Tests:** full suite 528 pass (includes the merged main tests).
- **Wesley ASR chunks vs `origin/main`:** 8,265 chunks over 143 transcripts, `cmp` identical, sha256 `5f624dd5…` for both. No change under `app/`, `search/`, `store.py`, `search.py`.
- **`uv lock --check`:** passes, 79 packages, no new dependencies.
