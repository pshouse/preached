# PR #17: De-leak the eval, widen grading, and add blind plain questions

Covers EVAL-DELEAK (`reports/EVAL-DELEAK.md`) and EVAL-GRADE (`reports/EVAL-GRADE.md`). This PR merges `origin/main` (#10, #14) and `feat/eval-plainq` (Grok's 30 blind questions).

**This PR does not change search, fusion weights, the default model, or `search/abstain.toml`.** Every label added in EVAL-GRADE has status `"proposed"`. Patrick confirms each one in `eval/review/review-2026-10-30.csv`, and nothing was tuned on proposed labels.

## Headline (Granite + BM25 hybrid RRF, the default)

| group | n | nDCG@10 strict | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| plain | 25 | 0.028 | 0.132 | 0.08 | 0.72 | 0.56 | 0.84 |
| plain-blind | 28 | 0.032 | 0.027 | 0.07 | 0.11 | 0.36 | 0.82 |
| names-topic | 23 | 0.480 | 0.402 | 0.70 | 0.96 | 0.96 | 0.96 |

- **`plain`:** the 0.028 is mostly narrow labels. With acceptable passages counted, 18 of 25 questions get one in the top 10.
- **`plain-blind`:** retrieval really is weak. Granite dense alone beats the default on lenient hit@10 by +0.29 [+0.14, +0.46] (8 wins, 0 losses), so BM25 fusion hurts here. Nothing was changed.
- **Abstain floor:** 0.8129 still refits unchanged without `plain-blind`. With the blind questions the refit drops to 0.7753 and abstains on nothing. With the shipped floor, 2 blind answerable questions would be hidden. The floor was not written.

## What changed

- **Merges.**
  - `origin/main`: one conflict in `search/bench.py`, both sides kept.
  - `feat/eval-plainq`: clean.
- **`search/query.py`:** an `ArtifactError` now prints as a one-line error and exits 1 (CTO should-fix from #10).
- **Leak lint (CTO c, d):**
  - It now catches quote and key-scripture phrase overlap (`eval/key_scripture.json`), 3-letter title words, `-ial`/`-ied` inflections, and a short synonym list per title.
  - `q-worry`, `q-assurance`, and `q-faith-works` leaked, so each got a `-plain` twin and the original moved to `names-topic`.
  - The 20 accepted rewrites are untouched.
- **Wider grading:**
  - `eval/pool.py` pools the top 20 of BM25 and of 3 models × 3 modes per question family, plus the rest of the gold sermon.
  - Claude subagents read the pool against `eval/pool/BRIEF.md`, and `eval/apply_grades.py` checks the judgments and applies them.
  - Result: 456 proposed grade-1 labels on existing questions. On the 30 `plain-blind` questions: 28 proposed grade-2 and 102 grade-1 labels, 2 unanswerable, 0 excluded.
- **`search/bench.py`:**
  - Scores three label sets: pre-grading (reproduces EVAL-DELEAK exactly), `_strict`, and `_lenient`.
  - Adds `hit@10`, `sermon@10`, and `sermon@50`.
  - Skips `excluded` items, and adds `--questions` and `--exclude-group`.
- **Review sheet:** `scripts/review_sheet.py` writes `eval/review/review-2026-10-30.csv`. `.gitignore` excepts only `/eval/review/`.

## Dependencies

None. `uv lock --check` is OK.

## Tests

369 OK.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
