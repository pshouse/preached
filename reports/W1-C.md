# W1-C: canonical Wesley text aligned to the LibriVox audio

Branch `feat/w1-align`, created from `origin/main` at `6da9756` (W1-B and W2-A
were already merged). Code is in `align/`. Report written 2026-10-30.

## 1. What was done

W1-A's transcription was already complete (143/143 files, `reports/W1-A.md`), so
nothing had to be resumed. Whisper output is now used **only for timing**. The
searchable text is Wesley's published words from W1-B's CCEL corpus
(`/cache/corpus/wesley/sermons.jsonl`, sha256-pinned in `corpus/catalog.json`).

- **Mapping file → sermon** (`align/wesley.py map`). Writes
  `align/manifest/wesley.jsonl`: every W1-A manifest row, unchanged, plus
  `canonical_sermon_id` (`wesley-001`..`wesley-141`, Jackson numbering),
  `canonical_title`, `canonical_source_url` (CCEL page), `canonical_part` /
  `canonical_parts`, and a `mapping_check`. The mapping comes from W1-A's
  `wesley_sermon_number`. It is then checked against the words actually read:
  for each file, it measures the share of its Whisper word trigrams found in
  each of the 141 CCEL sermons. **All 142 sermon files match their manifest
  sermon.** The lowest best-match score is 0.77 (s2-11), and the best runner-up
  is 0.07. The two-part *Christian Perfection* reading (s1-40, s1-41) maps to
  `wesley-040` as part 1/2. The preface (s1-00) maps to null with a note, since
  W1-B doesn't index it either.
  - Why a separate file instead of editing `ingest/manifest/wesley.jsonl`:
    that file lives on `feat/w1-ingest`, which isn't merged. Adding a modified
    copy here would cause an add/add merge conflict. The new file is a strict
    superset, so it can replace the W1-A manifest once both branches are in.
- **Normalization** (`align/textnorm.py`). The same rules run on both sides,
  so a rule that over-merges only causes a harmless collision:
  - lowercase, strip punctuation, drop apostrophes
  - numbers to words: cardinals, ordinals ("19th" → "nineteenth"), years read
    as speech ("1790" → "seventeen ninety")
  - Roman numerals ("XII", and "viii" inside references)
  - Scripture abbreviations ("Rom." → "romans"), only when a period follows,
    so the word "Job" in prose stays as it is
  - archaic and British spellings: an explicit table (shew, connexion,
    publick, stedfast…) plus `-our`/`-or`, `-ise`/`-ize`, `-lled`/`-led` and
    `-tre`/`-ter`
  - "&c." ↔ "etc." / "et cetera"
  - hyphens split, and 1872 two-word compounds are split on both sides
    ("to-day" = "to day" = "today", "any thing" = "anything", "for ever")
  
  Canonical token indices are exactly W1-B's `preached.corpus.word_tokens`
  indices, so they line up with `word_start`/`word_end` in the chunk records.
- **Alignment** (`align/seqalign.py`, generic, stdlib `difflib`):
  1. `SequenceMatcher(autojunk=False)` runs on the normalized token streams of
     the canonical sermon and the Whisper words inside W1-A's
     `searchable_start..searchable_end` window, which excludes the LibriVox
     intro and outro. Boilerplate segments are skipped too.
  2. Matched runs shorter than 4 tokens are dropped when they have more than
     15 unmatched tokens on both sides. These are coincidences such as a lone
     "of the" inside a skipped passage.
  3. In gaps of up to 4 tokens with equal length on both sides, words spelled
     alike (ratio ≥ 0.7) are paired as **fuzzy** anchors
     ("Hutcheson"/"Hutchinson").
  4. Canonical words without an anchor are **interpolated** between their
     anchored neighbours, in proportion to character length. Words before the
     first anchor or after the last one collapse onto it. A gap that crosses
     the two *Christian Perfection* files stays in the first file, up to its
     last word.
  5. Times are kept monotone. An anchor that would go backwards is
     un-anchored and interpolated instead.
  
  A sermon aligns in 0.1–0.8 s. All 141 take 22 s on CPU.
- **Per-sermon JSON** in `/cache/aligned/wesley/wesley-NNN.json` (141 files,
  21 MB). Each file has:
  - `sermon_id`, number, title, scripture, `text_source: "canonical"`
  - `source_url` (CCEL page) and `text_url` (CCEL dump), plus a `text_note`
    saying the words are Wesley's and only the timing comes from Whisper
  - `audio[]`, one entry per file: `file_id`, `audio_url`, `reader`,
    `ia_url`, `librivox_url`, license, the searchable window and per-file
    coverage
  - `voice_note` ("Read by a volunteer LibriVox reader, NOT Wesley's voice")
  - `alignment` statistics
  - `paragraphs[]`, each with `start_s`/`end_s`/`part`/`anchored` and its
    `sentences[]` (text, canonical word span, `start_s`, `end_s`, `part`,
    `anchored` share)
  - `words[]`: `[part, start_s, end_s, anchor]` for every canonical token
    (1 exact, 2 fuzzy, 0 interpolated), so any later chunking can be timed
    without re-aligning
  
  Sentences use W1-B's `split_sentences`. Committed sample:
  `align/samples/wesley-001.json` (128 KB).
- **Timed chunks** (`align/wesley.py chunks`) →
  `/cache/corpus/wesley/chunks_aligned.jsonl`, 8,383 records. These are W1-B's
  chunks, built in-process by the same code (`preached.corpus.chunk_sermon`)
  with the same `corpus/chunk_config.json` (target 112, min 75, max 150,
  overlap 0.25). Verified against the existing `chunks.jsonl`:
  **`chunk_id`, text, word spans, title, scripture and source URL are
  identical in all 8,383 rows.** So eval quotes and `eval/validate.py` are
  unaffected. Filled or added per record:
  - `start_s` and `end_s`, from the first and last canonical word
  - `audio_url` and `reader`
  - `text_source: "canonical"`
  - `audio_file_id`, for the two-part sermon
  - `alignment_anchored`, the share of the chunk's words with a real anchor
  
  A chunk that crosses from s1-40 into s1-41 plays from the file that holds
  most of its words. Sample: `align/samples/chunks_aligned-wesley-001.jsonl`.
- **Generic ASR path** (`align/asr_chunks.py`). Builds the same record with
  `text_source: "asr"` from any W1-A-style Whisper transcript, using the
  same chunker and params. That is the path for church sermons, which have no
  published text. A pause of 1.5 s or more starts a paragraph, so
  unpunctuated stretches still break near a natural boundary (W1-A notes that
  some segments come out without punctuation). Records keep the same keys, so
  the index and the page handle both sources the same way. W2-A's page
  already shows "Wording follows the recording" for `asr`. Sample:
  `align/samples/chunks_asr-wesley-s1-01.jsonl`.
- **QA** (`align/wesley.py qa`) → `/cache/aligned/wesley/qa.json` (copy in
  `align/samples/qa.json`): coverage per file, a timing check on every
  sentence, and 10 random sentences (seed 20261030) set against the Whisper
  words in their window.
- **Tests**: `tests/test_align.py`, 12 stdlib `unittest` cases (normalization,
  skip/insert anchoring, stranded-run drop, fuzzy pairing, interpolation
  including across parts, majority-part spans, sentence coverage, ASR chunk
  records).

### How the index should consume `chunks_aligned.jsonl`

Per the task, I did not change W1-B's or W2-A's code. The exact change is in
**`align/index_consumption.patch`**, 6 files, +35/−22. It was tested on a
scratch copy of this branch: it applies cleanly, and all 46 existing tests
pass with it. The patch:

1. `src/preached/paths.py`: adds `ALIGNED_CHUNKS_JSONL` and
   `INDEX_CHUNKS_JSONL`. `INDEX_CHUNKS_JSONL` is `$PREACHED_CHUNKS` if set,
   else `chunks_aligned.jsonl` if it exists, else `chunks.jsonl`.
   `CHUNKS_JSONL` stays the file that `corpus/chunk_sermons.py` **writes**.
   Repointing `CHUNKS_JSONL` directly would let a re-chunk overwrite the
   aligned file with null timestamps.
2. `src/preached/store.py`: adds `audio_url`, `reader` and `text_source`
   (TEXT) to the `chunks` schema and to `CHUNK_COLUMNS`. `connect()` runs
   `ALTER TABLE … ADD COLUMN` for an index that predates them.
   `replace_chunks` fills missing keys with NULL, so a text-only chunk file
   still loads.
3. `search/build_index.py`, `search/query.py`, `search/bench.py`: read
   `INDEX_CHUNKS_JSONL`.
4. `tests/test_server.py`: the fixture no longer adds the three columns
   itself, because `connect()` now creates them.

App code (`app/server.py`, `preached/search.py`) needs **no change**. It
already reads the three columns and treats a missing column as NULL.

Then rebuild:

```bash
git apply align/index_consumption.patch
uv run search/build_index.py                       # loads chunks_aligned.jsonl; prints 8383
uv run search/bench.py --models granite-english-r2 # re-embed (~75 s GPU)
```

The re-embed is needed because W1-B's `sync_chunks` drops every embedding
when the chunk file's hash changes, since rowids are reassigned. The texts
are identical, so the vectors will be too. Verified on a scratch index in
`/tmp`:
- a fresh build gives 8,383 rows, all `canonical`, no NULL `start_s` or
  `audio_url`
- an index first built by the unpatched code from `chunks.jsonl` migrates
  (columns added) and then reloads with timestamps
- `search/query.py "Christian perfection" --mode bm25` prints
  `wesley-040-c0004 start_s=156.0 end_s=208.8`

## 2. How to run

```bash
cd /work/preached/.worktrees/feat/w1-align
python3 align/wesley.py all          # map + align + chunks + qa, ~70 s, stdlib only
# or step by step:
python3 align/wesley.py map --source-manifest ../w1-ingest/ingest/manifest/wesley.jsonl
python3 align/wesley.py align [--ids wesley-001 wesley-040]
python3 align/wesley.py chunks
python3 align/wesley.py qa [--seed 20261030]
python3 align/asr_chunks.py /cache/transcripts/wesley/wesley-s1-01.json --out /tmp/asr.jsonl
python3 -m unittest tests.test_align
```

Inputs: `/cache/transcripts/wesley/*.json` (W1-A), `/cache/corpus/wesley/sermons.jsonl`
(W1-B), and the W1-A manifest, which `map` needs only once. `map` defaults to
the `feat/w1-ingest` worktree path; the result is committed. Any Python 3.12+
works. Nothing to install. `PREACHED_CACHE` relocates `/cache`, the same as
W1-B.

## 3. Results

| Metric | Value |
|---|---|
| Files mapped | 143 (142 sermon files → 141 sermons; 1 preface → null). 0 disagreements between manifest numbering and text overlap |
| Canonical words aligned | 652,145 across 141 sermons |
| **Coverage (canonical words anchored, exact + fuzzy)** | **mean 98.5%, median 98.6%, min 93.1%**, word-weighted 98.5% |
| Files under 90% | **none** (under 95%: 2, under 97%: 4, under 98%: 20, under 99%: 113) |
| Timed chunks | 8,383, all with `start_s` < `end_s`, monotone within each file; median duration 45.7 s, max 88.9 s; median anchored share 0.991; 0 chunks under 50% anchored |
| Sentence timing check (all 22,863 sentences of 6+ words) | share of the sentence's normalized words that Whisper heard inside `[start_s − 0.3, end_s + 0.3]`: **median 1.00, p10 0.956**; 24 sentences under 0.5, all reviewed (below) |
| Runtime | ~70 s for everything (alignment 22 s, mapping 18 s, QA ~25 s), CPU, stdlib |

Lowest coverage files, all above the 90% flag:

| file | sermon | coverage | why |
|---|---|---|---|
| s1-40 | 40 Christian Perfection (part 1) | 93.1% | dense inline references ("[Acts 20:26, 27]", "[see Mark 13:5; Eph. 5:6; 2 Thess. 2:3]") the reader doesn't voice |
| s1-41 | 40 Christian Perfection (part 2) | 94.5% | same |
| s2-22 | 75 On Schism | 96.0% | references |
| s2-39 | 92 On Zeal | 96.2% | references |
| s2-08 | 61 The Mystery of Iniquity | 97.0% | a 58-word CCEL editor's footnote ("Mr. Wesley doubtless quoted from memory…") and a translator note, unread |

<details><summary>Coverage for all 142 sermon files</summary>

| file | sermon | title | reader | coverage |
|---|---|---|---|---|
| wesley-s1-01 | wesley-001 | Salvation by Faith | Robert G. Smith | 97.8% |
| wesley-s1-02 | wesley-002 | The Almost Christian | Christopher Smith | 98.7% |
| wesley-s1-03 | wesley-003 | Awake, Thou That Sleepest | Greg Giordano | 97.8% |
| wesley-s1-04 | wesley-004 | Scriptural Christianity | Tim Cote | 98.5% |
| wesley-s1-05 | wesley-005 | Justification By Faith | Bill Mosley | 99.2% |
| wesley-s1-06 | wesley-006 | The Righteousness of Faith | Brian Wilson | 98.7% |
| wesley-s1-07 | wesley-007 | The Way to the Kingdom | Tim Cote | 98.8% |
| wesley-s1-08 | wesley-008 | THE FIRST FRUITS OF THE SPIRIT | Tim Cote | 98.8% |
| wesley-s1-09 | wesley-009 | The Spirit of Bondage and of Adoption. | Robert G. Smith | 97.9% |
| wesley-s1-10 | wesley-010 | THE WITNESS OF THE SPIRIT, Discourse I | Tim Cote | 98.8% |
| wesley-s1-11 | wesley-011 | The Witness of the Spirit, Discourse II | Tim Cote | 98.3% |
| wesley-s1-12 | wesley-012 | The Witness of our own Spirit | Tim Cote | 99.1% |
| wesley-s1-13 | wesley-013 | On Sin in Believers | Jackson Bates | 98.6% |
| wesley-s1-14 | wesley-014 | The Repentance of Believers | RLC | 99.0% |
| wesley-s1-15 | wesley-015 | The Great Assize | Robert Hoffman | 98.4% |
| wesley-s1-16 | wesley-016 | The Means of Grace | fshort | 98.8% |
| wesley-s1-17 | wesley-017 | The Circumcision of the Heart | Kim Moses | 98.1% |
| wesley-s1-18 | wesley-018 | The Marks of the New Birth | RLC | 98.4% |
| wesley-s1-19 | wesley-019 | The Great Privilege of those that are Born of God | Fr. Richard Zeile of Detroit | 98.8% |
| wesley-s1-20 | wesley-020 | The Lord our Righteousness | Matthew James Gray | 98.6% |
| wesley-s1-21 | wesley-021 | Upon our Lord's Sermon on the Mount, Discourse 1 | Tim Cote | 98.6% |
| wesley-s1-22 | wesley-022 | Upon our Lord's Sermon on the Mount, Discourse 2 | fshort | 98.8% |
| wesley-s1-23 | wesley-023 | Upon our Lord's Sermon on the Mount, Discourse 3 | Kris Gannon, Braden River, Florida | 98.7% |
| wesley-s1-24 | wesley-024 | Upon our Lord's Sermon on the Mount, Discourse 4 | Joseph Abell | 98.9% |
| wesley-s1-25 | wesley-025 | Upon our Lord's Sermon on the Mount, Discourse 5 | TriciaG | 99.0% |
| wesley-s1-26 | wesley-026 | Upon our Lord's Sermon on the Mount, Discourse 6 | Matthew James Gray | 98.3% |
| wesley-s1-27 | wesley-027 | Upon our Lord's Sermon on the Mount, Discourse 7 | Matthew James Gray | 98.5% |
| wesley-s1-28 | wesley-028 | Upon our Lord's Sermon on the Mount, Discourse 8 | Joseph Abell | 98.5% |
| wesley-s1-29 | wesley-029 | Upon our Lord's Sermon on the Mount, Discourse 9 | Joseph Abell | 99.4% |
| wesley-s1-30 | wesley-030 | Upon our Lord's Sermon on the Mount, Discourse 10 | Joseph Abell | 98.4% |
| wesley-s1-31 | wesley-031 | Upon our Lord'S Sermon on the Mount, Discourse 11 | Melora | 98.9% |
| wesley-s1-32 | wesley-032 | Upon our Lord's Sermon on the Mount, Discourse 12 | Fr. Richard Zeile of Detroit | 98.6% |
| wesley-s1-33 | wesley-033 | UPON OUR LORD'S SERMON ON THE MOUNT, Discourse 13 | Alistair Bench | 99.1% |
| wesley-s1-34 | wesley-034 | The Original, Nature, Property, and Use of the Law | Greg Giordano | 98.4% |
| wesley-s1-35 | wesley-035 | The Law Established through Faith, Discourse I | Aaron Weber | 97.3% |
| wesley-s1-36 | wesley-036 | The Law Established through Faith, Discourse 2 | Aaron Weber | 98.1% |
| wesley-s1-37 | wesley-037 | The Nature of Enthusiasm | Robert G. Smith | 98.5% |
| wesley-s1-38 | wesley-038 | A Caution against Bigotry | Robert G. Smith | 98.3% |
| wesley-s1-39 | wesley-039 | Catholic Spirit | Robert G. Smith | 97.9% |
| wesley-s1-40 | wesley-040 | Christian Perfection | Robert G. Smith | 93.1% |
| wesley-s1-41 | wesley-040 | Christian Perfection | Robert G. Smith | 94.5% |
| wesley-s1-42 | wesley-041 | Wandering Thoughts | Greg Giordano | 97.8% |
| wesley-s1-43 | wesley-042 | Satan's Devices | Greg Giordano | 98.2% |
| wesley-s1-44 | wesley-043 | The Scripture Way of Salvation | RLC | 98.6% |
| wesley-s1-45 | wesley-044 | Original Sin | Kevin W. Davidson | 98.1% |
| wesley-s1-46 | wesley-045 | The New Birth | RLC | 99.1% |
| wesley-s1-47 | wesley-046 | The Wilderness State | Arnie Horton | 99.6% |
| wesley-s1-48 | wesley-047 | Heaviness through Manifold Temptations | RLC | 98.6% |
| wesley-s1-49 | wesley-048 | Self-denial | RLC | 98.9% |
| wesley-s1-50 | wesley-049 | The Cure of Evil-speaking | Bill Mosley | 99.6% |
| wesley-s1-51 | wesley-050 | The Use of Money | Tim Cote | 98.8% |
| wesley-s1-52 | wesley-051 | The Good Steward | John Lieder | 99.2% |
| wesley-s1-53 | wesley-052 | The Reformation of Manners | amaskill | 98.7% |
| wesley-s1-54 | wesley-053 | On the Death of the Rev. Mr. George Whitefield | Chessie Joy | 98.4% |
| wesley-s2-01 | wesley-054 | On Eternity | MaryAnn | 98.3% |
| wesley-s2-02 | wesley-055 | On the Trinity | MaryAnn | 98.7% |
| wesley-s2-03 | wesley-056 | God's Approbation of His Works | MaryAnn | 98.2% |
| wesley-s2-04 | wesley-057 | On the Fall of Man | Ladypolanna | 99.2% |
| wesley-s2-05 | wesley-058 | On Predestination | TriciaG | 99.0% |
| wesley-s2-06 | wesley-059 | God's Love to Fallen Man | Jacob Paul Starr | 98.8% |
| wesley-s2-07 | wesley-060 | The General Deliverance | Lynne T | 99.2% |
| wesley-s2-08 | wesley-061 | The Mystery of Iniquity | Robert G. Smith | 97.0% |
| wesley-s2-09 | wesley-062 | The End of Christ's Coming | Robert G. Smith | 98.3% |
| wesley-s2-10 | wesley-063 | The General Spread of the Gospel | TriciaG | 99.0% |
| wesley-s2-11 | wesley-064 | The New Creation | Greg Giordano | 98.7% |
| wesley-s2-12 | wesley-065 | The Duty of Reproving our Neighbour | KHand | 98.5% |
| wesley-s2-13 | wesley-066 | The Signs of the Times | KHand | 99.0% |
| wesley-s2-14 | wesley-067 | On Divine Providence | KHand | 97.8% |
| wesley-s2-15 | wesley-068 | The Wisdom of God's Counsels | TriciaG | 99.2% |
| wesley-s2-16 | wesley-069 | The Imperfection of Human Knowledge | TimoleonWash | 98.6% |
| wesley-s2-17 | wesley-070 | The Case of Reason Impartially Considered | TimoleonWash | 98.2% |
| wesley-s2-18 | wesley-071 | Of Good Angels | TriciaG | 99.0% |
| wesley-s2-19 | wesley-072 | Of Evil Angels | TriciaG | 99.1% |
| wesley-s2-20 | wesley-073 | Of Hell | Bill Mosley | 98.9% |
| wesley-s2-21 | wesley-074 | Of the Church | Bill Mosley | 98.7% |
| wesley-s2-22 | wesley-075 | On Schism | Simon Brouwer | 96.0% |
| wesley-s2-23 | wesley-076 | On Perfection | Larry Wilson | 98.2% |
| wesley-s2-24 | wesley-077 | Spiritual Worship | TriciaG | 98.6% |
| wesley-s2-25 | wesley-078 | Spiritual Idolatry | Greg Giordano | 97.7% |
| wesley-s2-26 | wesley-079 | On Dissipation | Larry Wilson | 98.1% |
| wesley-s2-27 | wesley-080 | On Friendship with the World | MaryAnn | 98.4% |
| wesley-s2-28 | wesley-081 | In What Sense we are to Leave the World | MaryAnn | 98.5% |
| wesley-s2-29 | wesley-082 | On Temptation | MaryAnn | 98.0% |
| wesley-s2-30 | wesley-083 | On Patience | Beth Thomas (1974-2020) | 99.2% |
| wesley-s2-31 | wesley-084 | The Important Question | MaryAnne | 98.5% |
| wesley-s2-32 | wesley-085 | On Working out our own Salvation | Beth Thomas (1974-2020) | 98.7% |
| wesley-s2-33 | wesley-086 | A Call to Backsliders | Robert G. Smith | 98.6% |
| wesley-s2-34 | wesley-087 | The Danger of Riches | Larry Wilson | 98.5% |
| wesley-s2-35 | wesley-088 | On Dress | TriciaG | 99.0% |
| wesley-s2-36 | wesley-089 | The More Excellent Way | MaryAnne | 98.7% |
| wesley-s2-37 | wesley-090 | An Israelite Indeed | Christopher Smith | 98.9% |
| wesley-s2-38 | wesley-091 | On Charity | Denise Nordell | 98.8% |
| wesley-s2-39 | wesley-092 | On Zeal | Simon Brouwer | 96.2% |
| wesley-s2-40 | wesley-093 | On Redeeming the Time | Bruce Kachuk | 98.9% |
| wesley-s2-41 | wesley-094 | On Family Religion | Bruce Kachuk | 98.6% |
| wesley-s2-42 | wesley-095 | On the Education of Children | Bruce Kachuk | 99.0% |
| wesley-s2-43 | wesley-096 | On Obedience to Parents | Bruce Kachuk | 99.4% |
| wesley-s2-44 | wesley-097 | On Obedience to Pastors | Bruce Kachuk | 99.1% |
| wesley-s2-45 | wesley-098 | On Visiting the Sick | Bruce Kachuk | 98.9% |
| wesley-s2-46 | wesley-099 | The Reward of the Righteous | TriciaG | 98.9% |
| wesley-s2-47 | wesley-100 | On Pleasing all Men | Larry Wilson | 99.2% |
| wesley-s2-48 | wesley-101 | The Duty of Constant Communion J.W. | Larry Wilson | 98.7% |
| wesley-s2-49 | wesley-102 | Of Former Times | Robert G. Smith | 97.8% |
| wesley-s2-50 | wesley-103 | What is Man? | Timothy Watson | 98.0% |
| wesley-s2-51 | wesley-104 | On Attending the Church Service | Bill Mosley | 98.8% |
| wesley-s2-52 | wesley-105 | On Conscience | TimoleonWash | 97.9% |
| wesley-s2-53 | wesley-106 | On Faith | TimoleonWash | 98.6% |
| wesley-s2-54 | wesley-107 | On God's Vineyard | Bruce Kachuk | 99.1% |
| wesley-s2-55 | wesley-108 | On Riches | Bruce Kachuk | 99.0% |
| wesley-s3to5-01 | wesley-109 | What is Man? | MaryAnn | 98.8% |
| wesley-s3to5-02 | wesley-110 | On the Discoveries of Faith | MaryAnn | 98.7% |
| wesley-s3to5-03 | wesley-111 | On the Omnipresence of God | Andrea Rovny | 98.3% |
| wesley-s3to5-04 | wesley-112 | The Rich Man and Lazarus | Andrea Rovny | 98.3% |
| wesley-s3to5-05 | wesley-113 | The Difference Between Walking by Sight, and Walking by Faith | Bob Scott | 99.2% |
| wesley-s3to5-06 | wesley-114 | The Unity of the Divine Being | Avielh Tolentino | 98.0% |
| wesley-s3to5-07 | wesley-115 | The Ministerial Office | Avielh Tolentino | 97.8% |
| wesley-s3to5-08 | wesley-116 | Causes of the Inefficacy of Christianity | TimoleonWash | 98.9% |
| wesley-s3to5-09 | wesley-117 | On Knowing Christ after the Flesh | Avielh Tolentino | 98.6% |
| wesley-s3to5-10 | wesley-118 | On a Single Eye | laurencetrask | 98.7% |
| wesley-s3to5-11 | wesley-119 | On Worldly Folly | laurencetrask | 99.0% |
| wesley-s3to5-12 | wesley-120 | On the Wedding Garment | laurencetrask | 98.6% |
| wesley-s3to5-13 | wesley-121 | Human Life a Dream | laurencetrask | 98.8% |
| wesley-s3to5-14 | wesley-122 | On Faith | TimoleonWash | 98.3% |
| wesley-s3to5-15 | wesley-123 | The Deceitfulness of the Human Heart | Avielh Tolentino | 97.9% |
| wesley-s3to5-16 | wesley-124 | The Heavenly Treasure in Earthen Vessels | Avielh Tolentino | 97.8% |
| wesley-s3to5-17 | wesley-125 | On Living Without God | AlvinJPrice | 98.5% |
| wesley-s3to5-18 | wesley-126 | On the Danger of Increasing Riches | Avielh Tolentino | 98.2% |
| wesley-s3to5-19 | wesley-127 | The Trouble and Rest of Good Men | Avielh Tolentino | 98.5% |
| wesley-s3to5-20 | wesley-128 | Free Grace | Matthew | 98.1% |
| wesley-s3to5-21 | wesley-129 | The Cause and Cure of Earthquakes | Kathleen Moore | 99.2% |
| wesley-s3to5-22 | wesley-130 | National Sins and Miseries | Kathleen Moore | 98.3% |
| wesley-s3to5-23 | wesley-131 | The Late Work of God in North America | Michele Fry | 98.6% |
| wesley-s3to5-24 | wesley-132 | On Laying the Foundation of the New Chapel, Near the City-Road, London | Larry Wilson | 98.7% |
| wesley-s3to5-25 | wesley-133 | Preached on Occasion of the Death of the Rev. Mr. John Fletcher, Vicar of | Larry Wilson | 98.9% |
| wesley-s3to5-26 | wesley-134 | True Christianity Defended | Avielh Tolentino | 97.6% |
| wesley-s3to5-27 | wesley-135 | On Mourning for the Dead | TriciaG | 99.4% |
| wesley-s3to5-28 | wesley-136 | On Corrupting the Word Of God | Bob Scott | 98.5% |
| wesley-s3to5-29 | wesley-137 | On the Resurrection of the Dead | Tony Addison | 98.9% |
| wesley-s3to5-30 | wesley-138 | On Grieving the Holy Spirit | Larry Wilson | 99.3% |
| wesley-s3to5-31 | wesley-139 | On Love | David Lodes | 98.8% |
| wesley-s3to5-32 | wesley-140 | On Public Diversions | AlvinJPrice | 99.4% |
| wesley-s3to5-33 | wesley-141 | On the Holy Spirit | Larry Wilson | 99.2% |

</details>

What stays unanchored is almost entirely apparatus the readers skip: paragraph
numbers ("1.", "II."), bracketed Scripture references, CCEL editorial notes
("Section numbers … follow the Bicentennial Edition"), and Latin/Greek that
Whisper spells phonetically. Across the corpus there are only 10 unanchored
runs of 10+ words (192 words in total) and 3 runs of 20+ words.

All 24 sentences under 0.5 window recall were reviewed. 20 are Latin or Greek
quotations, where the timing is right but Whisper's spelling isn't (e.g. CCEL
"Infectum eluitur scelus, aut exuritur igni." vs Whisper "Infectum eluritur
cellis, ot exuritur igne."). 3 are bracketed editorial lines nobody reads
("[The following is Gifford's translation…"). 1 is a hymn line the reader
shortened.

**Spot check: 10 random sentences** (seed 20261030; full text in
`align/samples/qa.json`). "Whisper span" is the first and last Whisper word
in the window.

| sermon / file | canonical sentence (start) | start–end s | Whisper span s | anchored | word recall |
|---|---|---|---|---|---|
| 105 / s2-52 | "Professor Hutcheson, late of Glasgow, places conscience…" | 455.28–459.86 | 455.28–459.86 | 100% | 91% (Whisper: "Hutchinson") |
| 41 / s1-42 | "Add to this, that they can inject a thousand thoughts…" | 644.87–653.87 | 644.87–653.87 | 97% | 97% ("it being" → "of being") |
| 108 / s2-55 | "How strongly and continually are they solicited…" | 837.52–854.92 | 837.52–854.92 | 100% | 100% |
| 63 / s2-10 | "From them the leaven will soon spread…" | 1249.58–1255.68 | 1249.58–1255.68 | 100% | 100% |
| 79 / s2-26 | "The whole visible world, all we see, hear, or touch…" | 329.72–349.25 | 329.72–349.25 | 100% | 100% (an unpunctuated Whisper segment; canonical text restores punctuation) |
| 9 / s1-09 | "And as he knows, 'all things are naked and open…'" | 863.25–884.05 | 863.25–884.05 | 100% | 98% |
| 99 / s2-46 | "Does not the very expression imply the excellency…" | 614.12–618.62 | 614.12–619.44 | 100% | 100% (window pad catches the next word "Is") |
| 116 / s3to5-08 | "What know they of the very first principles of it?…" | 415.21–442.92 | 415.21–442.92 | 100% | 100% |
| 49 / s1-50 | "Indeed, you still owe to him… earnest, tender goodwill." | 1663.42–1670.95 | 1663.42–1670.95 | 100% | 100% |
| 127 / s3to5-19 | "Sin hath no more dominion over thee." | 832.00–834.22 | 832.00–834.96 | 100% | 100% (pad catches "For") |

All 10 start and end on the matching Whisper words. Note that this check
measures how faithfully timing is carried from Whisper words onto canonical
words. The accuracy of Whisper's own word times was measured independently in
W1-A: median 0.01 s, p90 0.05 s against a sequential decode.

## 4. Open issues, risks, exclusions

- **The index does not use the timestamps until the patch is applied** and
  the index is rebuilt and re-embedded (§1). This was a deliberate scope
  boundary set by the task.
- **The manifest with mapping is `align/manifest/wesley.jsonl`**, not
  `ingest/manifest/wesley.jsonl` (reason in §1). After both branches merge,
  the director may want to replace the W1-A file with it and drop the
  duplicate.
- **Unread canonical text is still searchable, with an approximate time.**
  Editorial notes, references and paragraph numbers that the reader skipped
  get interpolated times. These are usually a fraction of a second at the
  right spot, so Play starts within a sentence of the passage. The CCEL
  editorial notes ("Section numbers in brackets follow the Bicentennial
  Edition", a 58-word footnote in sermon 61) are in W1-B's corpus text. They
  are not Wesley's words, and W1-B may want to strip them from the corpus.
  That is a corpus change, so I left it out of scope here.
- **Paragraph numbers become one-word "sentences"** ("1.") in W1-B's splitter.
  In the per-sermon JSON they get interpolated times. This is harmless, but a
  UI that lists sentences should skip them.
- **Two-part sermon 40**: a chunk that spans the file boundary plays from the
  file holding most of its words, so the first or last few words may be in
  the other file. One chunk is affected (`wesley-040-c0055`).
- **Spelling normalization is a hand list plus a few suffix rules.** Misses
  fall through to fuzzy pairing or interpolation, which is why coverage
  includes a small fuzzy share (0.1–1.5% per sermon).
- **Coverage counts reader skips as misses by design.** The task metric is
  "% canonical words anchored". A file well under 90% would mean a
  wrong-file mapping or a broken transcript, and none occurred.
- **Window recall uses Whisper words on both sides**, so it is a consistency
  check, not ground truth (see the note under the spot check).
- **ASR path heuristics** (1.5 s paragraph pause) are tuned on LibriVox
  narration. Church audio with music or crowd noise should be re-checked in
  W2/W3, after W2's boilerplate detection.
- No church audio, member data or personal information was touched. Reader
  names are public LibriVox credits, carried for attribution.

## 5. Dependencies added

**None.** Everything uses the Python standard library: `difflib`, `json`,
`re`, `statistics`, `random`, `argparse`. It imports only W1-B's stdlib-only
`preached.corpus` (tokenizer, sentence splitter and chunker), so the chunk
params and tokens can't drift. No model is used in this step.
