# AGENTS.md: rules for every agent working on Preached

Read `BRIEF.md` first. This file holds the rules. If it conflicts with BRIEF.md, BRIEF.md wins for product decisions and this file wins for process.

## 1. Product design rules (from BRIEF.md, non-negotiable)

1. Never generate an answer in the preacher's voice. Return excerpts + timestamps.
2. Every result must cite sermon + timestamp and be playable from there.
3. Humans approve anything that gets published or sent.
4. Keep the stack simple enough to run on one Sprite.
5. Commit often; history is part of the evidence that work happened in-window (Oct 30 – Nov 27, 2026).

## 2. First principles, minimal dependencies

- Question every requirement. Delete it unless it has to come back.
- Prefer the Python standard library plus **one SQLite file** (FTS5 for keyword search, vectors stored as BLOBs, brute-force similarity).
- **No vector database.** **No LLM/chat model in the product.** The AI only **transcribes, embeds, and ranks**. It never writes answers, summaries, or paraphrases.
- Every new dependency must be justified in the PR description: what it does, why stdlib/existing deps can't, and its size/footprint. Pin versions (`uv` with a lockfile).
- Do not drift into a clipping tool (that's Sermon Shots' product). We search across the whole archive.

## 3. Model provenance

- **No models developed by organizations based in the People's Republic of China.** Examples excluded: Qwen (Alibaba), DeepSeek, BGE (BAAI), GTE (Alibaba), Yi, InternLM, MiniCPM, Baichuan, GLM/Zhipu, Moonshot/Kimi, Stella/Jasper (derived from Qwen/GTE).
- This includes fine-tunes or distillations of those models.
- **When unsure of a model's developer or base model, exclude it and note it in your report.** (Jina AI embeddings are excluded under this rule: the company has had PRC operations, and provenance is unclear.)
- Allowed examples: Whisper (OpenAI), EmbeddingGemma (Google), Granite Embedding (IBM), Nomic Embed (Nomic), all checked for base-model lineage.

## 4. Data, weights, and the repo

- All large data (audio, full transcripts, indexes) and all model weights live in **`/cache`** (e.g. `/cache/huggingface`, `/cache/audio`, `/cache/transcripts`). **Never commit them.**
- Commit only code, manifests, small samples (< 1 MB per file), eval sets, and reports.
- Public-domain sources only for the built-in library. Curate sources by hand; **never bulk-import by archive.org tag**.

## 5. Privacy

- **No personal information of church members anywhere** (code, data, samples, reports, commits). Sermons are public teaching, but congregant names in stories get flagged and stripped. Stripping is assisted, not guaranteed: publish only after `privacy.review()` and a human skim. Use sample data for anything member-related.
- Gaston Community Church sermons are not to be used or published until the pastor's permission is confirmed.

## 6. Git workflow

- Each agent works in **its own git worktree** at `/work/preached/.worktrees/<branch>` on **its own branch** (e.g. `feat/w1-ingest`), created from `origin/main`:
  `git worktree add -b <branch> /work/preached/.worktrees/<branch> origin/main`
- **Never push to `main`** (it is protected; merges happen through PRs reviewed by a human or the director).
- Commit small and often with clear messages (imperative mood, what + why). Push your branch regularly: `git push -u origin <branch>`.
- Don't rewrite pushed history.
- Never modify files outside your worktree, except shared data in `/cache`.

### Standing process rules

- **DEPLOY.md cites.** If you edit `app/server.py` or any other file cited in `docs/DEPLOY.md`, re-pin in the same PR: the affected DEPLOY.md cites, the `CITED` pins in `tests/test_deploy_alerts.py`, and any DEPLOY.md sentence that names the tree or sha those line numbers hold on (prefer tree-relative wording). Verify each by reading the file, never by arithmetic alone. The full suite must show zero `test_every_cited_file_line_holds_its_string` failures attributable to your change.
- **Cache safety.** Test and mutant runs must never point `PREACHED_CACHE`, `PREACHED_ONNX_DIR` or `HF_HOME` at a real cache for any output (temp dirs only; the real cache may only be read). Before any destructive call (rmtree, unlink, overwrite), resolve the path and assert it is under `tempfile.gettempdir()`. Snapshot the real cache listing (paths, sizes, mtimes) before and after your runs and report any difference.
- **Merge conflicts.** Resolve every conflict by editing to the correct merged content. `git checkout --ours`, `--theirs` or any whole-file pick of one side is banned because it silently drops the other side's changes. The only exception is a file where the other side's hunks are provably already present; then say so in the commit message and show that `git diff OTHER-SIDE..HEAD -- FILE` is empty for those hunks.

## 7. Finishing a task

Every task ends with **`reports/<task-id>.md`** on your branch, pushed, containing:

1. What was done
2. How to run it (exact commands). For the full suite use `PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`: the flag makes a missing `deno` fail the deno-backed tests that honor it (`tests/test_app_js.py`, `test_mobile_ux.py`, `test_privacy_wire_fix.py`, `test_privacy_merge.py`) instead of skipping them in a passing run.
3. Results and numbers (benchmarks, throughput, counts)
4. Open issues, risks, and anything excluded (with reason)
5. Dependencies added and why
