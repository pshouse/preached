# Wesley retrieval eval

Ninety-three questions a church member might ask of John Wesley's *Sermons on Several Occasions* (Jackson numbering, CCEL text): the original 40, 23 plain-language rewrites (EVAL-DELEAK and EVAL-GRADE), and 30 questions written blind to the corpus (EVAL-PLAINQ, group `plain-blind`). The file is `questions.jsonl`.

Each line has `id`, `query`, `type`, `group`, and `relevant`; rewrites also have `rewrite_of`. A relevant passage has `passage_id`, `sermon_id`, `sermon_title`, `grade`, `quote`, `source_url`, and `chunk_ids`. Grade 2 means the passage directly answers the question. Grade 1 means it is also acceptable: Wesley substantially addresses the question there too. Unanswerable items have `relevant: []`.

**Proposed labels (EVAL-GRADE).** A label with `"status": "proposed"` was added by wider grading and has not been confirmed by a person. It also has a one-line `reason` and `found_by` (the pool file). All grade-1 labels added by pooling, and every label on a `plain-blind` question, are proposed. Labels without `status` are the earlier ones. `search/bench.py` scores three label sets: the plain metric names use the labels as they stood before wider grading (every label except proposed grade-1), `_strict` uses grade 2 only, and `_lenient` adds the proposed grade-1 labels. Nothing is fitted or tuned on proposed labels. Patrick confirms or rejects them in `eval/review/review-YYYY-MM-DD.csv`.

## Wider grading (EVAL-GRADE): how to rerun the pool

1. `uv run --group bench eval/pool.py` takes, for every answerable question and every `plain_candidates.jsonl` question, the top 20 chunks from BM25 and from each enabled model in each bench mode (dense, hybrid RRF, hybrid weighted). These are the same calls as the bench, and the top 10 matched the bench's lists on all 550 question × ranker pairs. A rewrite and its original are one family with one pool. It writes `eval/pool/pool-YYYY-MM-DD.jsonl` (ids and ranks) and `/cache/eval-pool/YYYY-MM-DD/<family>.md` (texts, then the rest of the grade-2 sermon for a reading pass).
2. A reader judges every pooled chunk against the bar in `eval/pool/BRIEF.md`. For `plain-blind` questions the reader also searches the corpus beyond the pool. The output is one JSON per family.
3. `uv run python eval/apply_grades.py --check DIR` validates the judgments: each quote is in its chunk, 6–60 words, a one-line reason, and no two labels share a chunk. `uv run python eval/apply_grades.py DIR` then writes them into `questions.jsonl` as proposed. It is idempotent and removes earlier proposals first.
4. `uv run python scripts/review_sheet.py` writes the review CSV.

## Groups (title leakage)

Many of the original questions named the expected sermon's title ("What did Wesley say about the wilderness state?"), so they tested title lookup, not understanding. Each item now has a `group`, and `search/bench.py` reports every metric per group:

| group | n | what it is |
| --- | --- | --- |
| `plain` | 25 | Everyday-language questions that share no content word (or listed synonym) with the expected sermon's title, avoid its signature term, and share no two-word phrase with the grade-2 quote or the sermon's key scripture. 23 are `-plain` rewrites of `names-topic` items (same `relevant` list as the original, `rewrite_of` points back). `q-prayer` and `q-forgiveness` were clean from the start. |
| `plain-blind` | 30 | Written by another agent before it read the corpus (`plain_candidates.jsonl`, EVAL-PLAINQ). Wording is frozen. All labels are proposed (EVAL-GRADE). Items judged unanswerable have `type: "unanswerable"` and an `unanswerable_reason`. |
| `names-topic` | 23 | Original conceptual questions that name the topic or title, or (`q-worry`, `q-assurance`, `q-faith-works`, moved in EVAL-GRADE) borrow a phrase from the gold quote or key scripture. Unchanged apart from `group`. |
| `title-keyword` | 3 | Keyword queries equal to a title: `k-christian-perfection`, `k-means-of-grace`, `k-witness-of-the-spirit`. |
| `scripture-keyword` | 7 | The other keyword queries: six scripture references and `k-gain-all-you-can` (a phrase from sermon 50, not a title). |
| `unanswerable` | 5 | No answer in Wesley. |

`names-topic` is the 15 questions Patrick listed plus five the lint found (`q-money`, `q-heaviness`, `q-communion`, `q-justification`, `q-backsliders`), which share a title word too.

**Lint:** `uv run python scripts/check_title_leak.py` exits 1 if a `plain` question shares a content word (3+ letters, not a stopword, light suffix stemming) or a listed synonym with any of its sermons' titles, contains a signature phrase listed for that sermon, or shares two consecutive content words with its grade-2 quote or the key scripture of its grade-2 sermon (`key_scripture.json`, rebuilt with `--write-scripture`). `plain-blind` overlaps are printed as notes and do not fail. `tests/test_eval_leak.py` runs it. The `-plain` rewrites were written by the EVAL-DELEAK coding agent (an LLM, Claude), committed before any model was run on them, and not reviewed by a person. Results and the old vs new headline: `docs/research/embeddings.md`, "Title leakage", and `reports/EVAL-DELEAK.md`.

## How the labels were made

**Who made these labels.** The Grok CLI coding agent (an LLM) wrote the original 40 questions and chose every relevant passage and grade while working task W1-B. The quotes are verbatim CCEL text and are machine-checked against the chunks (`eval/validate.py`), but the relevance calls are the agent's judgment, not a person's. No model is used at search time to judge relevance, and no embedding model under test was used to pick labels.

**Human review.**

- Status: pending: Patrick to review all 93 items (the 23 `-plain` rewrites, the 30 `plain-blind` questions, and every proposed label) in `eval/review/review-2026-10-30.csv` before submission.
- Reviewer:
- Date:
- Changes made in review:

Until that review is filled in, do not describe this set as human-labeled or human-verified.

The agent's steps were:

1. Read the sermon that the standard numbering assigns to the topic (assurance is sermons 10 and 11, the use of money is sermon 50, and so on). Candidates were located with ordinary text search, then the surrounding paragraph was read by the agent.
2. Copy a short span that is an exact substring of `/cache/corpus/wesley/sermons.jsonl`. Quotes are Wesley's words or the scripture he is expounding, not a paraphrase.
3. `uv run python eval/validate.py --write` checks that the normalized quote is contained in at least one chunk. It writes `chunk_ids` back. The quote is the judgment. Chunk ids are a cache and go stale if the chunker changes.

A chunk matches a quote when `normalize(quote)` is contained in `normalize(chunk)`. Overlap can put one quote in two chunks. Metrics count that quote once, at the first ranked chunk that contains it. See `src/preached/metrics.py`.

Recall@5, MRR@10, and nDCG@10 are computed only on questions with a relevant passage. Unanswerable questions are reported separately as the top-1 score, so a later threshold for "nothing strong found" can be chosen from the numbers rather than invented here. That threshold now exists as a heuristic, not a verdict: `search/bench.py --abstain` fits a per-model dense floor (`search/abstain.toml`) from the unanswerable items (in practice one of them sets it) and reports leave-one-out numbers. The page shows low-confidence results by default under a banner. See `reports/W3-POLISH.md`. It inherits every caveat on this page.

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
- 23 of the 35 original answerable questions share a content word with the title of the sermon that answers them (for example "Christian perfection", "the means of grace", "the witness of the Spirit", "riches", "temptation"), and FTS5 indexes the title column. They are now the `names-topic` and `title-keyword` groups; read `plain` for natural-language quality.
- The graded passages were picked with keyword search for the titled wording. A plain rewrite keeps those labels, so another paragraph of the right sermon that answers it scores 0. `sermon@5` is the fairer check on `plain`.
- 55 answerable questions (25 `plain`) is small: one question moves the overall mean by about 0.02 and a `plain` mean by 0.04. `search/bench.py` reports bootstrap 95% intervals; read differences inside them as ties.

## Natural-language probes (W3-POLISH, not human-reviewed)

`nl-questions-w3polish.jsonl` holds 18 short questions **written by the W3-POLISH coding agent (an LLM, Claude), not reviewed by a person**. They avoid sermon-title words where possible and include the CTO's "worry" and "How do I stop worrying?". Each lists the sermon(s) the agent expects to answer it (`expected_sermons`), checked only against sermon titles and a text grep, so treat them as probes, not labels. They are not part of `questions.jsonl`, are not used by `bench.py`, and the abstain floor is **not** fitted on them. `uv run --group bench scripts/check_nl_questions.py` prints the abstain level for each and what a refit would do. Results: `reports/W3-POLISH.md`, fix-up section.
