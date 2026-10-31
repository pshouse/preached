# W3-DIAG-FIX: CTO #42 r1 must-fixes and should-fixes (retrieval diagnosis honesty)

Branch `docs/w3-retrieval-diag` (PR #42). Agent: Claude (Opus 5.5). Date: 2026-10-31.
Code head (scripts + report): `7412829d8433256bf957f568d43915f8fce6903d`. The branch head is the commit that adds this report. Before it: `8e893b1` (S4 scripts), `c6e29eb` (merge of origin/main `6a94caf`, merge commit, no rebase).

Precondition: PR #42 was OPEN with head `0baa33c9aa7de1de085c01bb78e6948725a3d423` (checked through the public GitHub API, since `gh` is not installed).

This is an eval-honesty fix. **Every number is as computed.** Only labelling, disclosure and caveats changed. The only number-bearing edit is S6, which moves two category labels; the counts are unchanged. Nothing in `src/`, the index, `eval/questions.jsonl` or the grades was changed. No model was downloaded. No dependencies were added.

## 1. Item-by-item

Line numbers are in `reports/W3-RETRIEVAL-DIAG.md` at this head.

| item | what changed | where |
| --- | --- | --- |
| MF1 held-out | Every `plain-blind` number in the Bottom line is marked "post-hoc, not held out" | Bottom line, L11–L15 |
| MF1 | §5: "no blind number is fully held out" becomes "no `plain-blind` number in §6 is held out, for any variant (V3, V4, V10, V11 as much as V7, V12)". Adds that the OR-shape rule is close to a long-question detector (26 of 28 answerable blind questions are OR-form), and that `plain-blind` is an in-sample check from now on | §5, L251 |
| MF1 | `*` is redefined as "uses a question-derived lexicon" (V7, V12), separate from post-hoc. Every `plain-blind` cell is marked post-hoc (column header and prose). The prefix-probe blind column and the V3/V4 reading are marked too | §6, L260, L281, L299, L307 |
| MF1 | §7 #1 Honest test is rewritten. (a) points to the PR #43 pre-registration (`reports/W3-FUSION-PREREG.md`: grid and rule frozen in their own commit, labels re-frozen before any run). (c) `plain-blind` is reported only as an in-sample check, not held out. (d) A fresh blind set, frozen and committed before any ranker runs on it, is the confirmatory test. It is required before any accuracy claim, not only before shipping, and is disclosed as LLM-written if an LLM writes it. The Expected effect row is marked post-hoc. The Overfitting risk row gains the long-question caveat. §7 #2 now evaluates on the fresh set, not on blind | §7, L329, L331, L333, L343 |
| MF1 | §4 what-if table header and §9 open issue | L214, L470 |
| MF2 LLM-written | Disclosure line added to §1 Sources: Grok wrote the blind questions (`llm-written:grok`), Claude proposed every blind label, and no person has confirmed any of them | §1, L53 |
| MF2 | Same disclosure at the Bottom line's first use of "blind" | L11 |
| MF2 | §3 reworded: "The blind questions imitate how people type: an LLM (Grok) wrote them…, not questions typed by people" | §3, L156 |
| MF2 | The GRADE flags come from Claude, the same model family that proposed all the blind labels. Noted in §1, §4 and the Bottom line | L49, L186, L13 |
| S1 | The whole-file index hash is replaced by content identifiers: Granite fingerprint `13e0ed78bb32d86b`, `meta.chunks_sha256` `19833913…e363b2` (= sha256 of `chunks_aligned.jsonl`), 8,383 chunk rows and 8,383 Granite embedding rows, plus a read-only query to check them | §8, L425 |
| S2 | Reranker exclusion list extended: BGE, Jina, GTE (incl. `gte-reranker-modernbert-base`), Qwen3-Reranker, mxbai-rerank-v2 (Qwen2.5 base), DeepSeek-derived models. Lineage is checked by base and teacher, not only by name. MS MARCO is described as "non-commercial research purposes only", which rules out `cross-encoder/ms-marco-*` unless Patrick decides otherwise. `granite-embedding-reranker-english-r2` is listed as a **candidate needing Patrick's approval**. The 149M / Apache-2.0 / Granite R2 base / no MS MARCO facts are attributed to the CTO's check, not re-verified here. The revision pin is unconfirmed. Nothing was downloaded | §7 #3, L350 |
| S3 | Multiplicity stated: 12 variants against V0 across 6 groups, best picked, no interval adjustment. On blind questions V10 equals V3 by construction (verified per question: 26/28 are OR-form, `p-016` has no BM25 rows, `p-017` has identical top-10 scores) | Bottom line L15, §6 L261 and L300, §7 L329 |
| S4 | `diag.py`, `experiments.py`, `prefixes.py`: `store.connect` (WAL pragma, DDL, ALTER via `migrate`) → `store.open_readonly` (URI `mode=ro` + `PRAGMA query_only`). `stats.py` and `table.py` now write to `$TMPDIR/w3-retrieval-diag/` by default, not cwd. The §8 bench step now runs on a copy of the index (`--index $W/wesley.sqlite`), because `bench.py` migrates and calls `ensure_chunks` on its index | scripts (commit `8e893b1`); §8 L374, L379 |
| S5 | Original script hashes restored: the full sha256 of the five `/cache/w3-retrieval-diag/scripts/*.py`, which match the 12-hex prefixes `a2bcbec` published for four of the five. **Correction (W3-DIAG-FIX2): not for `diag.py`.** `a2bcbec` published `9dfaeb558806`; the file's hash begins `9dfaeb5588c7`. See `reports/W3-DIAG-FIX2.md` §1. The report says that `832a198` dropped them. The committed-file table now shows the current hash next to the `832a198` hash | §8, L401, L411 |
| S6 | p-015 GRADE → LEX: its flagged `028-c0009` is dense 3 but not in the hybrid top 10. p-030 LEX → GRADE: its flagged `024-c0012` is hybrid 6. Both are checked with a read-only top-10 run. `categories.json` notes updated. §2 rows regenerated by `table.py` and pasted (the report's §2 equals the generated `table.md`). §4 rank cells: p-030 "dense 1, hybrid 6", p-027 "dense 1, hybrid 7". Counts unchanged: blind GRADE 6, LEX 6 (superseded by FIX2: LEX 5). The Bottom line's "6 of 25" and the what-if 3→9 still hold (the 6 GRADE questions are exactly those with a flag in the hybrid top 10) | §2 L108, L123; §4 L198–L199; `categories.json` |
| S7 | Confirmed: the #43 sheet `reports/W3-LABEL-SHEET.csv` at `8ee909f` (sha256 `6141beae…69b12`) has blank verdict and notes columns. It contains none of the §4 leaning phrases ("weaker", "already grade", "already a HIT", "artefact", "plausib", "Suspected", "flag", "grade", "dense", "hybrid"). The only hits for "already" (4) and "acceptable" (1) are inside Wesley's chunk text. Noted in §4. No change to #43 | §4, L188 |

**One item for #43 (outside this branch).** `reports/W3-FUSION-PREREG.md` at `8ee909f` still says "`plain-blind` is reported once, after `w` is chosen, as the held-out number". Its fresh-blind-set step is headed "before any ship". Both conflict with MF1 as now written in §7 #1. #43 should align: `plain-blind` as an in-sample check only, and the fresh set required before any accuracy claim. I did not edit #43.

## 2. How to run

```sh
cd /work/preached/.worktrees/docs/w3-retrieval-diag
# §8 commands, as in reports/W3-RETRIEVAL-DIAG.md (scripts now open /cache/index/wesley.sqlite read-only)
W=/tmp/w3fix/after; mkdir -p $W
uv run --group bench python reports/w3-retrieval-diag/diag.py $W/diag.json
uv run --group bench python reports/w3-retrieval-diag/experiments.py $W/experiments.json > $W/experiments.txt
uv run --group bench python reports/w3-retrieval-diag/prefixes.py > $W/prefixes.txt
python3 reports/w3-retrieval-diag/stats.py $W/diag.json /cache/corpus/wesley/chunks.jsonl $W/stats.json
cp reports/w3-retrieval-diag/categories.json reports/w3-retrieval-diag/flags.json $W/ && python3 reports/w3-retrieval-diag/table.py $W
# bench on a copy
cp /cache/index/wesley.sqlite /tmp/w3fix/bench/wesley.sqlite
uv run --group bench search/bench.py --models granite-english-r2 --index /tmp/w3fix/bench/wesley.sqlite --out /tmp/w3fix/bench/bench-raw.json --note "W3-RETRIEVAL-DIAG baseline, raw ranker"
uv run python -m unittest discover -s tests && uv lock --check
```

For the before/after comparison, the `0baa33c` scripts (`git archive 0baa33c reports/w3-retrieval-diag`) were run against a copy of the index, in a scratch `PREACHED_CACHE=/tmp/w3fix/cacheA` holding a copy of `index/wesley.sqlite` and symlinks to `corpus/wesley` and `huggingface`. This kept the old `connect()` away from `/cache`. `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` were set throughout.

## 3. Results: rerun diff and index check

**Before** = `0baa33c` scripts on an index copy. **After** = S4 scripts on `/cache/index/wesley.sqlite`, with the old `categories.json`.

| output | before vs after |
| --- | --- |
| `diag.json`, `experiments.json`, `experiments.txt`, `prefixes.txt`, `stats.json` | byte-identical |
| `stats.py` printout, `table.md`, `legend.md`, `table.py` category counts | byte-identical |

Full sha256 (identical in both runs):

```
a875192f4a903631d1bcd95ee6400fe0aebef26049f6efb38597e63e2a2c3e1f  diag.json
433130b11eaa1a266711a2e6f69ae423a1f9a79fbd5765dcb3bce651f5572257  experiments.json
8004b427184e83ac26904a713170c91571597da499ebd9682f9bd41a639a8c50  experiments.txt
1c79359a234a8eec7af8d9ae5a42e47daa25e78b4828b53dcd4cee30f721a379  prefixes.txt
5e03dc4e878bda9c5919b47ec103e30f33f45f210bb0efcaaeb16306a9388155  stats.json
559cb4e99c4bd534ab77f58cfb5ba5b96c60ce2a91538c4953c967b0671a535d  stats.py stdout
2cdab2eb73e6bfe52f837c532ea66c946a53f1418ecbe241ecc60614418014f7  table.md
636abf3934c80fee17a88af5e3d503d2cbab5c61174254c6293fe74598ceb1e3  legend.md
c14706960acadfb3150271156d649ba0a51f9efbd5a7f3349ce8adc3b7e8b644  table.py stdout (category counts)
```

The committed `results/stats.json`, `results/experiments.txt` and `results/prefixes.txt` are byte-identical to the after-run.

**Intended path changes only.** With no output argument, `stats.py` and `table.py` now write to `/tmp/w3-retrieval-diag/`. Those default-path outputs are byte-identical to the explicit-path ones, and `git status` showed nothing new in the worktree.

**Index unchanged** (before and after the read-only run, and again around the bench-on-copy run):

```
909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b  /cache/index/wesley.sqlite   (before)
189042688 2026-10-30 15:39:09.550258600 -0400
909afd60b3fcd91993686f9e2c08eab49cea35949fe841c45b1c818ae7fe972b  /cache/index/wesley.sqlite   (after)
189042688 2026-10-30 15:39:09.550258600 -0400
```

**Bench on a copy:** every score, CI and win/tie/loss is identical to the committed `results/bench-raw.md`. Only the timestamp and the latency columns differ.

**S6, after the S4 comparison:** `table.md` differs from before in exactly two rows. The category counts printout is unchanged: `plain-blind` GRADE 6, LEX 6, HIT 3, VOCAB 4, AMBIG 5, THEME 2, PASSAGE 2, UNANS 2.

```
42c42  p-015 … | 93/–/– | GRADE | dense 3 is 028-c0009 (…) … but not here
       →  p-015 … | 93/–/– | LEX   | … but not here; it is not in the hybrid top 10
57c57  p-030 … | –/10/23 | LEX   | dense labelled at 10 plus 024 social-religion chunks at 1-2 (unlabelled); BM25 "bed", "months" noise
       →  p-030 … | –/10/23 | GRADE | hybrid 6 is 024-c0012 (social religion, unlabelled); 024 social-religion chunks at dense 1-2 (unlabelled); dense labelled at 10; BM25 "bed", "months" noise
```

Read-only top-10 check behind S6 (L = labelled, F = flagged):

```
p-015 hybrid 1:045-c0033 2:016-c0079 3:014-c0015 4:045-c0032 5:077-c0055 6:016-c0080 7:014-c0014 8:141-c0011 9:120-c0029 10:026-c0027   (028-c0009 absent; dense 3)
p-030 hybrid 1:115-c0030 2:093-c0022 3:025-c0073 4:046-c0040 5:014-c0029 6:024-c0012F 7:122-c0031 8:024-c0013 9:013-c0069 10:084-c0048
```

A number check on the diff: every numeric token removed from the report reappears in the added lines, except the removed whole-file index hash (S1).

## 4. Tests

```
uv run python -m unittest discover -s tests
Ran 933 tests in 182.112s
OK
uv lock --check
Resolved 79 packages in 0.64ms
```

gitleaks is not installed on this machine, so it was not run.

## 5. Open issues, exclusions, process

- The PR #43 pre-registration still uses "held-out" for `plain-blind` (§1 above). It needs a change on that branch.
- The `granite-embedding-reranker-english-r2` facts are the CTO's, not re-verified here. The revision pin and any download need Patrick's approval.
- `open_readonly` (`mode=ro`) can still update the `-shm` sidecar of a WAL-mode database. That is SQLite's shared-memory index, not the index file, whose hash and mtime are unchanged.
- `sandbox.sh` and `gh` are not on this machine. I used plain git in the existing worktree: one merge commit from origin/main, no rebase, no force-push.
- Dependencies added: none.
