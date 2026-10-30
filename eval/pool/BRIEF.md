# Wider grading brief (EVAL-GRADE, 2026-10-30)

You are grading retrieval-eval labels for **Preached**, a search tool over John Wesley's 141 *Sermons on Several Occasions*. Search returns ~120-word chunks (excerpts) with sermon + timestamp. It never writes answers. The eval asks: for a church member's question, does search put a chunk in the top 10 that actually helps?

The existing labels are too narrow: usually one "grade-2" quote per question. Many other passages answer the question too, and a search that returns them is currently scored as a miss. Your job is to find those passages by **reading**, and propose them as grade-1 ("also acceptable"). Patrick (the owner) will confirm each one in a review sheet, so every reason you write is read by a human.

## Inputs

- Pool files: `/cache/eval-pool/2026-10-30/<family>.md`. Each holds the question(s), existing labels, every chunk that any ranker (BM25; three embedding models × dense / hybrid RRF / hybrid weighted) returned in its top 20 (union), and then every other chunk of the grade-2 sermon (the "own reading" pass). A family is one question, or an original plus its `-plain` rewrite (they share labels, so judge for the shared meaning of both).
- For plain-blind questions (`p-0xx`) there is no gold sermon. Read the pool, then **search further yourself**: `grep -i` over `/cache/corpus/wesley/chunks.jsonl` (one JSON chunk per line, fields `chunk_id`, `sermon_title`, `text`), or `cd /work/preached/.worktrees/feat/eval-deleak && uv run --offline python search/query.py "your words" --mode bm25 -k 20`. Try a few phrasings in Wesley's 18th-century vocabulary (e.g. "heaviness", "sorrow", "anger", "drunkenness", "envy", "evil-speaking", "dissipation", "the morrow", "providence", "praying for others"). Do not read or edit anything in the repo besides running those commands. Do not edit `eval/questions.jsonl` or any repo file.

## What counts (the bar)

A passage is acceptable when, shown alone as one search result, it gives the asker a real piece of **Wesley's answer to their question** — it speaks to what they are actually asking or suffering, not merely their topic.

- YES: Wesley addresses that question/need directly: counsel, a doctrinal answer, an explanation of the cause, a promise/scripture he applies to that situation, a direct exhortation to people in that situation.
- NO: shares a topic word but answers a different question; passing mention; a list item with no substance; the scripture text alone with no application, *unless* the query is itself a scripture reference/keyword query (then passages that quote and expound that verse are acceptable); narrative or argument against a third party that would confuse the asker.
- Pick from any sermon, not just the gold one. Over-including weak passages makes the eval meaningless; missing clear ones keeps it too narrow. When in doubt, leave it out. There is no quota: some questions will have 1-2, some 10+.
- Overlapping chunks: adjacent chunks overlap ~25%. One passage = one label. Don't label two chunks of the same paragraph run, and don't label a passage already covered by an existing label (same chunk).

## Grade 2 (plain-blind only)

For each `p-0xx`, also choose the single best passage as `grade2` (the one you'd most want the asker to see first). Then grade-1 the other acceptable ones.

`answerable`: true if at least one passage meets the bar, even if the modern object (phone, app, AI, livestream, scan, medicine) is not named, as long as Wesley speaks to the asker's actual need. false if nothing meets the bar; give `unanswerable_reason` (one line, e.g. "Wesley never discusses X; closest is Y which is about Z"). If only a loose analogy exists, it's false. `excluded`: only if the question is unusable as an eval item at all (not just vague — real users type vague things; a vague question with a reasonable reading should be graded on that reading and noted in a reason). Never change the question wording.

## Quotes

- `quote` must be an **exact contiguous substring** of that chunk's text as printed (copy-paste; whitespace and curly quotes are normalized, nothing else). 10-40 words, the sentence(s) that carry the substance. Must be 6-60 words or it fails the check.
- `reason`: one line, ≤ 25 words, plain English, says *why it answers the question* ("Says worry about tomorrow is needless because God provides daily; direct counsel to the anxious.").

## Output

One file per family: `/cache/eval-pool/2026-10-30/grades/<family>.json`:

```json
{"family": "q-worry",
 "grade1": [{"chunk_id": "wesley-029-c0031", "quote": "...", "reason": "..."}]}
```

plain-blind:

```json
{"family": "p-011", "answerable": true,
 "grade2": {"chunk_id": "...", "quote": "...", "reason": "..."},
 "grade1": [ ... ],
 "unanswerable_reason": null, "excluded": null}
```

Validate every file before finishing and fix anything reported:

```
cd /work/preached/.worktrees/feat/eval-deleak && uv run --offline python eval/apply_grades.py --check /cache/eval-pool/2026-10-30/grades/<family>.json
```

It must print no `PROBLEM` lines. Finish with a short summary: per family, number of labels, and anything you were unsure about (questions you found ambiguous, borderline calls).
