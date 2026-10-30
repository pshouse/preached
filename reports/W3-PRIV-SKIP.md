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

### Synthetic evaluation (small, hand-written by me, Claude; not real services)
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
