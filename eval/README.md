# Wesley retrieval eval

Forty questions a church member might ask of John Wesley's *Sermons on Several Occasions* (Jackson numbering, CCEL text). The file is `questions.jsonl`.

Each line has `id`, `query`, `type`, and `relevant`. Types are `conceptual` (25), `keyword` (10), and `unanswerable` (5). A relevant passage has `passage_id`, `sermon_id`, `sermon_title`, `grade`, `quote`, `source_url`, and `chunk_ids`. Grade 2 means the passage directly answers the question. Grade 1 means it is on the same subject but is not the passage that answers it. Unanswerable items have `relevant: []`.

## How the labels were made

**Who made these labels.** The Grok CLI coding agent (an LLM) wrote all 40 questions and chose every relevant passage and grade while working task W1-B. The quotes are verbatim CCEL text and are machine-checked against the chunks (`eval/validate.py`), but the relevance calls are the agent's judgment, not a person's. No model is used at search time to judge relevance, and no embedding model under test was used to pick labels.

**Human review.**

- Status: pending: Patrick to review all 40 items before submission.
- Reviewer:
- Date:
- Changes made in review:

Until that review is filled in, do not describe this set as human-labeled or human-verified.

The agent's steps were:

1. Read the sermon that the standard numbering assigns to the topic (assurance is sermons 10 and 11, the use of money is sermon 50, and so on). Candidates were located with ordinary text search, then the surrounding paragraph was read by the agent.
2. Copy a short span that is an exact substring of `/cache/corpus/wesley/sermons.jsonl`. Quotes are Wesley's words or the scripture he is expounding, not a paraphrase.
3. `uv run python eval/validate.py --write` checks that the normalized quote is contained in at least one chunk. It writes `chunk_ids` back. The quote is the judgment. Chunk ids are a cache and go stale if the chunker changes.

A chunk matches a quote when `normalize(quote)` is contained in `normalize(chunk)`. Overlap can put one quote in two chunks. Metrics count that quote once, at the first ranked chunk that contains it. See `src/preached/metrics.py`.

Recall@5, MRR@10, and nDCG@10 are computed only on questions with a relevant passage. Unanswerable questions are reported separately as the top-1 score, so a later threshold for "nothing strong found" can be chosen from the numbers rather than invented here. That threshold now exists: `search/bench.py --abstain` fits a per-model dense floor (`search/abstain.toml`) from the unanswerable items and reports leave-one-out numbers. See `reports/W3-POLISH.md`. It inherits every caveat on this page.

## Shared sentences

Two quotes are scripture sentences Wesley prints in more than one sermon. A chunk from any of those sermons counts as a hit:

- "The Spirit itself beareth witness..." (`k-romans-8-16`) is the text of sermons 10 and 11 and is also discussed in sermon 18, *The Marks of the New Birth*.
- "Do this in remembrance of me." (`k-luke-22-19`) is the text of sermon 101 and is also quoted in sermon 120, *On the Wedding Garment*, which is about the Lord's Supper.

## Unanswerable items

These five were checked by searching the full 141-sermon text. The terms do not occur, except for the false friend noted below.

| id | query | corpus check |
| --- | --- | --- |
| u-book-of-mormon | Book of Mormon | `mormon` = 0 |
| u-nuclear-weapons | nuclear weapons | `nuclear` = 0, `bomb` = 0 |
| u-smartphones | smartphones and social media | both phrases = 0 |
| u-vaccines | vaccines | `vaccine`, `inoculat`, `smallpox` = 0 |
| u-pretrib-rapture | a secret pre-tribulation rapture | `pre-trib` / `pretrib` = 0 |

`rapture` occurs twice, and neither is the eschatological doctrine. Sermon 23 says some people run "mad after raptures and inward feelings." Sermon 133 says John Fletcher "broke out in a rapture, God is love!" A keyword hit on those chunks is a false friend, not a missed label.

## Chunks the quotes were checked against

`corpus/chunk_config.json` is frozen: target 112 words, minimum 75, maximum 150, overlap 0.25, 150 words per minute. That is about 30–60 seconds of speech, with a target near 45 seconds. Text-derived chunks have `start_s` and `end_s` null. The record is `{chunk_id, sermon_id, sermon_title, text, start_s, end_s}` plus sermon number, scripture, source URL, and word span, so a later transcript chunk can fill in the timestamps without a new schema.

The current file `/cache/corpus/wesley/chunks.jsonl` has 8,383 chunks (median 122 words, max 180). Ten chunks are 151–180 words because a heading shorter than 75 words was merged onto the next sentence, with 30 words of slack past the maximum. 190 chunks are under 75 words. 473 of 8,242 adjacent pairs do not overlap: a sentence longer than 150 words is hard-split on word boundaries with no overlap. Do not retune the chunker unless a graded quote stops fitting inside one chunk.

## Known biases

- Labels were found with keyword search, so passages that share words with the question are over-represented. That favors BM25 and hybrid modes.
- 23 of the 35 answerable questions share a content word with the title of the sermon that answers them (for example "Christian perfection", "the means of grace", "the witness of the Spirit", "riches", "temptation"), and FTS5 indexes the title column. Absolute scores are optimistic for any lexical component.
- 35 answerable questions is small: one question moves a mean by about 0.03. `search/bench.py` reports bootstrap 95% intervals; read differences inside them as ties.
