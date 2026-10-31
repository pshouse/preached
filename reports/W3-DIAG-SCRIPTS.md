# W3-DIAG-SCRIPTS: make PR #42's retrieval diagnosis reproducible

Branch `docs/w3-retrieval-diag` (PR #42). Agent: Claude (Sonnet 5.5). Date: 2026-10-31.
Code head (scripts + §8): `832a198694158420403c32c65ddd1e37b43d71d1`, on top of `a2bcbecc9f8ffa00d6e041636681c06815e44e67`. The head of the branch is the commit that adds this report.

Changes no `src/`, index, `eval/questions.jsonl` or grades. No new dependencies.

## 1. What was done
- Copied the five scratch scripts (`diag.py`, `experiments.py`, `prefixes.py`, `stats.py`, `table.py`) and the two hand-written inputs (`categories.json`, `flags.json`) into `reports/w3-retrieval-diag/`. Only usage docstrings and path handling changed (`PREACHED_CACHE`, optional CLI args for `stats.py` and a work dir for `table.py`).
- Committed small results in `reports/w3-retrieval-diag/results/` (`experiments.txt`, `prefixes.txt`, `stats.json`, `bench-raw.md`, `variants.md`). Not committed: `diag.json` (975 KB), `experiments.json` (818 KB), `bench-raw.json` (378 KB), anything from `/cache/index`.
- Rewrote §8 of `reports/W3-RETRIEVAL-DIAG.md`: commands point at the committed scripts, sha256 of each committed file, sha256 of the two `/cache` inputs (index `909afd60…7fe972b`, chunks `110dd519…de016f`), and the reproduction check. Fixed the two other places that said the scripts were uncommitted.
- The scripts are not imported by `src/`, `app/` or `tests/` and live outside `tests/`, so the suite does not collect them.

## 2. Reproduction check
Reran everything from the committed location into a scratch dir and compared with the original `/cache/w3-retrieval-diag/` outputs:
- `diag.json`, `experiments.json`: parsed JSON equal. `stats.json`, `table.md`, `legend.md`: byte-identical. `experiments.txt`, `prefixes.txt`: identical except a model-loading progress-bar line.
- Headline reproduces exactly: `plain-blind 28 ... bm25/dense/hybrid 3 11 3 fusion_loss 8 fusion_gain 0`; `plain 25 ... 8 17 18 fusion_loss 2 fusion_gain 3`. V10 and the other variants match `experiments.txt`.
- `search/bench.py` baseline: scores and CIs identical; only date, commit hash and latency columns differ.

## 3. Tests
`uv run python -m unittest discover -s tests`: 772 tests OK. `uv lock --check`: resolved, unchanged.

## 4. Open issues
- I could not check that PR #42 is still open (no `gh` here). The branch head was `a2bcbec` as expected, so I proceeded.
- `sandbox.sh` is not available here, so I used plain git in the existing worktree; merge-style history only, no rebase or force-push.
- The original scripts in `/cache/.../scripts/` were left untouched; the committed ones differ from them only as described.
