# EVAL-DELEAK: remove title leakage from the retrieval eval and rerun the embedding comparison

Branch `feat/eval-deleak` from `origin/main` (`4129646`). Agent: Claude (Opus 5.5). Date: 2026-10-30.

## Bottom line

- **On plain-language questions, retrieval at the passage level is close to zero for every model.** Granite hybrid RRF (the default) has nDCG@10 0.028, R@5 0.040, and sermon@5 0.440 on the 25 `plain` questions. On the 20 originals that name the topic it has 0.543 / 0.600 / 1.000. The old headline (nDCG@10 0.558 on 35 questions) mostly measured title lookup.
- **Granite is still the best clean-lineage model on `plain`, but not in the default mode.** Granite *dense alone* beats the default by +0.050 nDCG@10 [+0.01, +0.10] (4 wins, 20 ties, 1 loss), the only `plain` difference whose CI excludes zero. Arctic v1 dense (lineage unclear, eval-only) has the highest `plain` point estimate, +0.077 [−0.02, +0.20]. **The default was not changed.** Patrick decides.
- **The abstain floor still holds.** The refit on the 60-question set is Granite 0.8129 and EmbeddingGemma 2 0.7413, unchanged. There are no false abstains in any group. The margin on `plain` is thin (see Results).
- **I rewrote 20 questions, not the 15 in the brief.** The lint found 5 of the "clean" ten also share a title word with their sermon (`q-money`, `q-heaviness`, `q-communion`, `q-justification`, `q-backsliders`). The other 15 match the brief.

## 1. What was done

1. **Groups.** Every item in `eval/questions.jsonl` now has a `group`. The original 40 are otherwise byte-identical (checked field by field):
   - `names-topic` (20): the 15 listed plus the 5 above.
   - `title-keyword` (3): `k-christian-perfection`, `k-means-of-grace`, `k-witness-of-the-spirit`.
   - `scripture-keyword` (7): the other keyword items. `k-gain-all-you-can` is a phrase from sermon 50, not scripture, and not a title. It went here because the brief has no other keyword group.
   - `unanswerable` (5).
   - `plain` (25).
2. **20 `-plain` rewrites.** Each has the same `relevant` list as its original, byte for byte, and `rewrite_of` points to the original. None contains a title content word, the sermon's signature term, or its key scripture phrase. The 5 already-clean conceptual questions are also `plain`. I wrote and committed the rewrites (`990a583`) before running any model on them and did not edit them afterwards. Labels were not changed. `eval/validate.py` still passes: every graded quote is in a chunk.
3. **Lint.** `scripts/check_title_leak.py [questions.jsonl]` exits 1 when a `plain` question:
   - shares a content word with the title of any of its relevant sermons (over 3 letters, not a stopword, light suffix stemming, with a prefix match for stems of 5 or more letters), or
   - contains a per-sermon signature phrase (`SIGNATURE`, for example "born again", "means of grace", "deny", "way to escape").

   `tests/test_eval_leak.py` (5 tests) runs it on the real file, checks that every group is known, that every `names-topic` item has a `-plain` twin with identical labels, that the lint flags every original, and that the stemmer catches inflections.
4. **Bench.** `search/bench.py` now reports every metric and the paired Δ against the reference per group, in both JSON (`by_group`, `vs_reference_by_group`) and Markdown. `--abstain` reports false abstain and abstain recall per group. Scoring and ranking code are unchanged.
5. **Rerun.** I reran the full comparison with the same models (EmbeddingGemma 2, Granite English R2, Arctic v1 eval-only, plus BM25), revisions, prompts, fp32, RRF k=60, weighted 0.5, and bootstrap seed 20261030. I also refit the abstain floor without writing `search/abstain.toml`.
6. **Docs.** `docs/research/embeddings.md` got a new "Title leakage" section and updates to its summary, setup, eval set, metrics, decision, caveats, and how-to-rerun sections. `eval/README.md` now describes the groups and the lint. `scripts/leak_subsets.py` prints the old-35 vs rewrites comparison from a results JSON.

## 2. How to run it

```bash
cd /work/preached/.worktrees/feat/eval-deleak
uv run python scripts/check_title_leak.py                     # lint
uv run python eval/validate.py                                # quotes vs chunks
uv run --group bench search/bench.py --note "..."             # comparison (writes eval/results/<date>[-N].*)
uv run --group bench search/bench.py --abstain --models granite-english-r2 embeddinggemma-2 --note "..."
uv run python scripts/leak_subsets.py eval/results/2026-10-30-deleak.json
uv run python -m unittest discover -s tests
uv lock --check
```

Results committed: `eval/results/2026-10-30-deleak.{json,md}` and `eval/results/2026-10-30-deleak-abstain.{json,md}`. These were written as `2026-10-30-3.*` and `2026-10-30-abstain.*` and then renamed, as earlier tasks did. The abstain `.md` was regenerated from its JSON after the LOO wording fix ("the other 39" became "all the others").

## 3. Results

### Rewritten questions, side by side

Grade in parentheses. Labels are identical to the original's.

| original (`names-topic`) | rewrite (`plain`) | expected sermon(s) |
| --- | --- | --- |
| `q-money`: Is it wrong for a Christian to try to earn more money? What did Wesley say about making a living? | `q-money-plain`: Is it okay to work hard for a bigger paycheck, or should a follower of Jesus not care about getting ahead? | The Use of Money (2) |
| `q-riches`: Can a Christian be wealthy without it hurting their soul? What did Wesley say about the danger of riches? | `q-riches-plain`: I've done well in business and now have a lot more than I need. Could having all this be bad for me spiritually? | The Danger of Riches (2); On Riches (1) |
| `q-perfection`: What does Wesley mean by Christian perfection? Can a believer be made perfect in this life? | `q-perfection-plain`: Is it possible to stop sinning altogether and love God with my whole heart before I die, or will I always fall short? | Christian Perfection (2); On Perfection (1) |
| `q-heaviness`: I have been sad for a long time and my faith feels heavy. What did Wesley say about heaviness and sorrow in a believer? | `q-heaviness-plain`: I've felt low and weighed down for months, even though I still trust God. Is something wrong with me spiritually? | Heaviness through Manifold Temptations (2) |
| `q-mourning`: My child died and I do not know how to grieve. What did Wesley say about mourning the dead? | `q-mourning-plain`: My little boy passed away last month and I can't stop crying. How do I go on after losing a child? | On Mourning for the Dead (2) |
| `q-satan`: I feel like the devil is attacking my faith. What did Wesley say about Satan's devices? | `q-satan-plain`: Something keeps trying to pull me away from God and make me lose heart. How do I keep from being tricked? | Satan's Devices (2) |
| `q-temptation`: The temptation I am facing feels too strong to bear. What did Wesley say about God making a way to escape? | `q-temptation-plain`: I keep getting pulled toward something I know is wrong and I feel too weak to say no. Will God help me get through it? | On Temptation (2) |
| `q-communion`: How often should a Christian receive the Lord's Supper? What did Wesley teach about communion? | `q-communion-plain`: How often should I take the bread and the cup at church? Is a few times a year enough? | The Duty of Constant Communion J.W. (2) |
| `q-means`: What are the means of grace, and do they actually help a person grow? | `q-means-plain`: Do things like praying, reading the Bible and going to church actually help me get closer to God, or are they just habits? | The Means of Grace (2) |
| `q-salvation`: If I cannot earn heaven, how is a person saved? What did Wesley say about salvation by faith? | `q-salvation-plain`: I'll never be good enough for heaven no matter how hard I try. So how does anybody get right with God? | Salvation by Faith (2) |
| `q-justification`: What does it mean to be justified? Does Wesley say God justifies good people or ungodly people? | `q-justification-plain`: Does God only accept good people, or will he forgive someone who has done terrible things? | Justification By Faith (2); The Scripture Way of Salvation (1) |
| `q-new-birth`: What does it mean to be born again? What did Wesley preach about the new birth? | `q-new-birth-plain`: People at church say I need God to give me a whole fresh start on the inside. What actually changes in a person when that happens? | The New Birth (2); The Marks of the New Birth (1) |
| `q-sin-believers`: I am a Christian and I still struggle with pride and unbelief. Did Wesley say that sin remains in believers? | `q-sin-believers-plain`: I gave my life to Jesus years ago but I still catch myself being proud and doubting. Does that mean I was never really saved? | On Sin in Believers (2) |
| `q-original-sin`: Are people basically good? What did Wesley teach about original sin and the human heart? | `q-original-sin-plain`: Are people good deep down and just pick up bad habits, or is something wrong with us from the very start? | Original Sin (2) |
| `q-catholic-spirit`: How should I treat Christians who disagree with me on doctrine? What did Wesley mean by a catholic spirit? | `q-catholic-spirit-plain`: My friend goes to a church that teaches very differently from mine. Can we still be close and work together without pretending our differences don't matter? | Catholic Spirit (2) |
| `q-backsliders`: I used to believe and then I fell away. What did Wesley say to backsliders who think God will not take them back? | `q-backsliders-plain`: I walked away from God years ago. I want to come back, but I'm scared he won't have me. Is it too late? | A Call to Backsliders (2) |
| `q-self-denial`: What does it mean to deny yourself and take up your cross? What did Wesley say about self-denial? | `q-self-denial-plain`: Do I really have to give up things I want in order to follow Jesus? How much is God asking me to let go of? | Self-denial (2) |
| `q-wandering-thoughts`: My mind wanders when I try to pray. Are wandering thoughts a sin? What did Wesley say? | `q-wandering-thoughts-plain`: When I pray, my mind keeps drifting off to my shopping list and my job. Is God upset with me for that? | Wandering Thoughts (2) |
| `q-wilderness`: I used to feel close to God, and now everything feels dark. What did Wesley say about the wilderness state? | `q-wilderness-plain`: A few years ago I felt so close to God and full of joy. Now I feel empty and far away from him. What happened, and can I get that back? | The Wilderness State (2) |
| `q-evil-speaking`: Is it gossip if what I say about someone is true? What did Wesley teach about evil-speaking? | `q-evil-speaking-plain`: Is it wrong to talk about a coworker behind their back if everything I say is true? | The Cure of Evil-speaking (2) |

### Lint output

On the committed file:

```
$ uv run python scripts/check_title_leak.py
questions.jsonl: 60 questions; groups {"names-topic": 20, "plain": 25, "scripture-keyword": 7, "title-keyword": 3, "unanswerable": 5}
plain questions checked: 25; leaking: 0
$ echo $?
0
```

As a negative control, I copied the file with every `names-topic` original moved to `plain`. The lint flags all 20 originals (73 leak lines) and exits 1:

```
$ uv run python scripts/check_title_leak.py /tmp/deleak/originals-as-plain.jsonl
originals-as-plain.jsonl: 60 questions; groups {"plain": 45, "scripture-keyword": 7, "title-keyword": 3, "unanswerable": 5}
LEAK q-money: title word "money" (The Use of Money) ~ "money"
LEAK q-riches: title word "danger" (The Danger of Riches) ~ "danger"
LEAK q-riches: title word "riches" (The Danger of Riches) ~ "riches"
LEAK q-riches: signature "riches" (wesley-087)
LEAK q-riches: title word "riches" (On Riches) ~ "riches"
...
plain questions checked: 45; leaking: 20
$ echo $?
1
```

Before any rewrite, the same check on the "clean ten" flagged `q-money`, `q-heaviness`, `q-communion`, `q-justification`, and `q-backsliders`. That is why there are 20 rewrites.

### Per-group results, each model

Each cell is nDCG@10 / R@5 / MRR@10. 55 answerable questions, 5 unanswerable. Commit `bbb7fb2`, 8,383 aligned chunks, torch 2.15.0, transformers 5.22.1, sentence-transformers 6.2.0, RTX 3060 for corpus vectors, i9-12900K CPU for queries.

| model | mode | plain (25) | names-topic (20) | scripture-keyword (7) | title-keyword (3) | overall (55) |
| --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.004 / 0.000 / 0.007 | 0.313 / 0.400 / 0.216 | 0.876 / 1.000 / 0.833 | 0.544 / 0.667 / 0.500 | 0.257 / 0.309 / 0.215 |
| embeddinggemma-2 | dense | 0.028 / 0.000 / 0.012 | 0.342 / 0.575 / 0.236 | 0.842 / 1.000 / 0.786 | 0.544 / 0.667 / 0.500 | 0.274 / 0.373 / 0.219 |
| embeddinggemma-2 | hybrid RRF | 0.013 / 0.000 / 0.005 | 0.478 / 0.675 / 0.395 | 0.947 / 1.000 / 0.929 | 0.544 / 0.667 / 0.500 | 0.330 / 0.409 / 0.292 |
| embeddinggemma-2 | hybrid weighted | 0.000 / 0.000 / 0.000 | 0.463 / 0.575 / 0.364 | 0.947 / 1.000 / 0.929 | 0.667 / 0.667 / 0.667 | 0.325 / 0.373 / 0.287 |
| granite-english-r2 | dense | 0.078 / 0.040 / 0.043 | 0.414 / 0.500 / 0.354 | 0.704 / 0.857 / 0.655 | 1.000 / 1.000 / 1.000 | 0.330 / 0.364 / 0.286 |
| **granite-english-r2** | **hybrid RRF (default)** | **0.028 / 0.040 / 0.013** | **0.543 / 0.600 / 0.475** | **0.895 / 1.000 / 0.857** | **0.667 / 0.667 / 0.667** | **0.361 / 0.400 / 0.324** |
| granite-english-r2 | hybrid weighted | 0.025 / 0.000 / 0.010 | 0.504 / 0.550 / 0.424 | 0.895 / 1.000 / 0.857 | 0.767 / 0.667 / 0.704 | 0.350 / 0.364 / 0.306 |
| arctic-embed-l ⚠ | dense | 0.105 / 0.120 / 0.100 | 0.434 / 0.550 / 0.371 | 0.313 / 0.571 / 0.226 | 0.649 / 0.667 / 0.542 | 0.281 / 0.364 / 0.239 |
| arctic-embed-l ⚠ | hybrid RRF | 0.030 / 0.040 / 0.015 | 0.484 / 0.600 / 0.392 | 0.847 / 1.000 / 0.798 | 0.544 / 0.667 / 0.500 | 0.327 / 0.400 / 0.278 |
| arctic-embed-l ⚠ | hybrid weighted | 0.062 / 0.120 / 0.043 | 0.521 / 0.675 / 0.431 | 0.876 / 1.000 / 0.833 | 0.667 / 0.667 / 0.667 | 0.366 / 0.464 / 0.319 |

`sermon@5` (any top-5 chunk from the sermon holding a grade-2 quote) by group:

| model | mode | plain | names-topic | scripture-keyword | title-keyword | overall |
| --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.200 | 0.950 | 1.000 | 1.000 | 0.618 |
| embeddinggemma-2 | dense | 0.480 | 0.850 | 1.000 | 1.000 | 0.709 |
| embeddinggemma-2 | hybrid_rrf | 0.400 | 1.000 | 1.000 | 1.000 | 0.727 |
| embeddinggemma-2 | hybrid_weighted | 0.360 | 1.000 | 1.000 | 1.000 | 0.709 |
| granite-english-r2 | dense | 0.400 | 0.900 | 0.714 | 1.000 | 0.655 |
| granite-english-r2 | hybrid_rrf | 0.440 | 1.000 | 1.000 | 1.000 | 0.745 |
| granite-english-r2 | hybrid_weighted | 0.440 | 1.000 | 1.000 | 1.000 | 0.745 |
| arctic-embed-l ⚠ | dense | 0.520 | 0.900 | 0.571 | 1.000 | 0.691 |
| arctic-embed-l ⚠ | hybrid_rrf | 0.520 | 1.000 | 1.000 | 1.000 | 0.782 |
| arctic-embed-l ⚠ | hybrid_weighted | 0.440 | 0.950 | 1.000 | 1.000 | 0.727 |

The `plain` group with 95% bootstrap CIs and the paired Δ against Granite hybrid RRF (wins/ties/losses):

| model | mode | nDCG@10 | R@5 | MRR@10 | sermon@5 | Δ nDCG@10 vs Granite RRF | Δ sermon@5 vs Granite RRF |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.004 [0.00, 0.01] | 0.000 [0.00, 0.00] | 0.007 [0.00, 0.02] | 0.200 [0.04, 0.36] | -0.024 [-0.07, +0.01] (1/22/2) | -0.240 [-0.40, -0.08] (0/19/6) |
| embeddinggemma-2 | dense | 0.028 [0.00, 0.07] | 0.000 [0.00, 0.00] | 0.012 [0.00, 0.03] | 0.480 [0.28, 0.68] | -0.001 [-0.06, +0.06] (2/21/2) | +0.040 [-0.16, +0.24] (4/18/3) |
| embeddinggemma-2 | hybrid_rrf | 0.013 [0.00, 0.04] | 0.000 [0.00, 0.00] | 0.005 [0.00, 0.01] | 0.400 [0.20, 0.60] | -0.015 [-0.04, +0.00] (0/23/2) | -0.040 [-0.16, +0.08] (1/22/2) |
| embeddinggemma-2 | hybrid_weighted | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.000 [0.00, 0.00] | 0.360 [0.16, 0.56] | -0.028 [-0.07, +0.00] (0/23/2) | -0.080 [-0.24, +0.08] (1/21/3) |
| granite-english-r2 | dense | 0.078 [0.02, 0.15] | 0.040 [0.00, 0.12] | 0.043 [0.01, 0.09] | 0.400 [0.20, 0.60] | +0.050 [+0.01, +0.10] (4/20/1) | -0.040 [-0.28, +0.20] (4/16/5) |
| granite-english-r2 | hybrid_rrf | 0.028 [0.00, 0.07] | 0.040 [0.00, 0.12] | 0.013 [0.00, 0.03] | 0.440 [0.24, 0.64] | +0.000 [+0.00, +0.00] (0/25/0) | +0.000 [+0.00, +0.00] (0/25/0) |
| granite-english-r2 | hybrid_weighted | 0.025 [0.00, 0.06] | 0.000 [0.00, 0.00] | 0.010 [0.00, 0.03] | 0.440 [0.24, 0.64] | -0.003 [-0.01, +0.00] (1/23/1) | +0.000 [-0.16, +0.16] (2/21/2) |
| arctic-embed-l ⚠ | dense | 0.105 [0.00, 0.24] | 0.120 [0.00, 0.28] | 0.100 [0.00, 0.22] | 0.520 [0.32, 0.72] | +0.077 [-0.02, +0.20] (3/21/1) | +0.080 [-0.20, +0.36] (7/13/5) |
| arctic-embed-l ⚠ | hybrid_rrf | 0.030 [0.00, 0.07] | 0.040 [0.00, 0.12] | 0.015 [0.00, 0.04] | 0.520 [0.32, 0.72] | +0.002 [-0.04, +0.04] (2/22/1) | +0.080 [-0.12, +0.28] (4/19/2) |
| arctic-embed-l ⚠ | hybrid_weighted | 0.062 [0.00, 0.14] | 0.120 [0.00, 0.28] | 0.043 [0.00, 0.10] | 0.440 [0.24, 0.64] | +0.034 [-0.03, +0.10] (3/21/1) | +0.000 [-0.24, +0.20] (4/17/4) |

Overall, with CIs (55 answerable): Granite hybrid RRF has nDCG@10 0.361 [0.25, 0.47]. The other rows' Δ nDCG@10 against it:

| row | Δ nDCG@10 vs Granite hybrid RRF |
| --- | --- |
| EmbeddingGemma 2 RRF | −0.031 [−0.08, +0.02] |
| Granite dense | −0.030 [−0.10, +0.05] |
| Arctic weighted | +0.005 [−0.04, +0.05] |
| BM25 | −0.104 [−0.18, −0.04] |

Full table: `eval/results/2026-10-30-deleak.md`.

### Old vs new headline (by subset; nDCG@10 / R@5 / MRR@10 / sermon@5)

| model | mode | original 35 (n=35) | plain rewrites (n=20) | plain clean originals (n=5) | their 20 originals | sermon@5 by group: plain / names-topic |
| --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.401 / 0.486 / 0.333 / 0.886 | 0.005 / 0.000 / 0.008 / 0.150 | 0.000 / 0.000 / 0.000 / 0.400 | 0.313 / 0.400 / 0.216 / 0.950 | 0.200 / 0.950 |
| embeddinggemma-2 | dense | 0.420 / 0.586 / 0.339 / 0.857 | 0.018 / 0.000 / 0.008 / 0.450 | 0.067 / 0.000 / 0.029 / 0.600 | 0.342 / 0.575 / 0.236 / 0.850 | 0.480 / 0.850 |
| embeddinggemma-2 | hybrid_rrf | 0.518 / 0.643 / 0.458 / 0.943 | 0.000 / 0.000 / 0.000 / 0.350 | 0.063 / 0.000 / 0.025 / 0.600 | 0.478 / 0.675 / 0.395 / 1.000 | 0.400 / 1.000 |
| embeddinggemma-2 | hybrid_weighted | 0.511 / 0.586 / 0.451 / 0.943 | 0.000 / 0.000 / 0.000 / 0.300 | 0.000 / 0.000 / 0.000 / 0.600 | 0.463 / 0.575 / 0.364 / 1.000 | 0.360 / 1.000 |
| granite-english-r2 | dense | 0.473 / 0.543 / 0.424 / 0.800 | 0.080 / 0.050 / 0.045 / 0.400 | 0.071 / 0.000 / 0.033 / 0.400 | 0.414 / 0.500 / 0.354 / 0.900 | 0.400 / 0.900 |
| granite-english-r2 | hybrid_rrf | 0.558 / 0.629 / 0.506 / 0.971 | 0.016 / 0.000 / 0.006 / 0.350 | 0.077 / 0.200 / 0.040 / 0.800 | 0.543 / 0.600 / 0.475 / 1.000 | 0.440 / 1.000 |
| granite-english-r2 | hybrid_weighted | 0.541 / 0.571 / 0.477 / 0.943 | 0.017 / 0.000 / 0.007 / 0.400 | 0.058 / 0.000 / 0.020 / 0.600 | 0.504 / 0.550 / 0.424 / 1.000 | 0.440 / 1.000 |
| arctic-embed-l | dense | 0.366 / 0.486 / 0.304 / 0.771 | 0.132 / 0.150 / 0.125 / 0.550 | 0.000 / 0.000 / 0.000 / 0.400 | 0.434 / 0.550 / 0.371 / 0.900 | 0.520 / 0.900 |
| arctic-embed-l | hybrid_rrf | 0.492 / 0.600 / 0.426 / 0.943 | 0.037 / 0.050 / 0.018 / 0.500 | 0.000 / 0.000 / 0.000 / 0.600 | 0.484 / 0.600 / 0.392 / 1.000 | 0.520 / 1.000 |
| arctic-embed-l | hybrid_weighted | 0.530 / 0.643 / 0.470 / 0.914 | 0.078 / 0.150 / 0.054 / 0.400 | 0.000 / 0.000 / 0.000 / 0.600 | 0.521 / 0.675 / 0.431 / 0.950 | 0.440 / 0.950 |

The "original 35" column reproduces the 2026-10-30 audit rerun exactly for every row: Granite RRF 0.558 / 0.629 / 0.506 / 0.971, Gemma 2 RRF 0.518 / 0.643 / 0.458 / 0.943, and BM25 0.401 / 0.486 / 0.333 / 0.886. Nothing but the questions changed.

Headline: Granite hybrid RRF nDCG@10 was **0.558** on 35 questions. It is **0.361** overall on 55 and **0.028** on `plain`.

### Unanswerable (abstain) and the floor check

`bench.py --abstain`, API path (hybrid, dedupe, k=10). Leave-one-out, with in-sample in parentheses:

| model | refit floor | shipped floor | holds? | unanswerable abstained | unanswerable weak or none | false abstain (all groups) | `plain` weak |
| --- | --- | --- | --- | --- | --- | --- | --- |
| granite-english-r2 | 0.8129 | 0.8129 | **yes** | 3/5 (4/5) | 4/5 | 0 | 0/25 |
| embeddinggemma-2 | 0.7413 | 0.7413 | yes | 3/5 (4/5) | 4/5 | 0 | 3/25 |

The unanswerable numbers are identical to the W3-POLISH run. The floor holds, but the margin on `plain` is thin:

- Granite's lowest top cosine on a `plain` question is 0.8224, 0.0095 above the floor.
- 3 `plain` questions fall below Gemma 2's floor. Every `plain` question has BM25 and dense agreement, which is what keeps them at `weak` and out of `none`.

### CPU latency (unchanged)

p50 per query, hybrid RRF:

| model | p50 |
| --- | --- |
| Granite | 115 ms |
| Gemma 2 | 134 ms |
| Arctic | 156 ms |

## 4. Default recommendation

**Keep Granite English R2 + BM25 hybrid RRF as the default for now. It is unchanged.**

- **Overall (55 questions).** It is still the best or tied-best clean row. No clean row beats it outside noise.
- **On `plain`, the plain answer is that the default mode is not the best.**
  - Granite dense alone wins by +0.050 nDCG@10 [+0.01, +0.10], on 4 questions out of 25 (mourning, communion, wandering thoughts, evil-speaking; it loses on forgiveness).
  - Dense alone loses on `names-topic` (−0.129 [−0.26, −0.01]) and on scripture keywords.
  - On sermon@5 it is not better (0.400 vs 0.440).
- **Among models in the default mode**, Granite (0.028) is ahead of Gemma 2 (0.013) and level with Arctic (0.030).
- **The best `plain` row of all is Arctic v1 dense** (0.105 nDCG@10, +0.077 [−0.02, +0.20]; sermon@5 0.520 vs 0.440). It is within noise and lineage-unclear, so it stays eval-only.

Decision for Patrick:

- Whether to lean the fusion toward dense for natural-language questions, or switch modes by query type, given a 25-question group where most rows are 0.
- I would not tune either on this set. Adding more plain questions, and grade-1 passages for them, would come first.

## 5. Open issues, risks, exclusions

- **The rewrites are an LLM's (mine) and not human-reviewed**, like the rest of the set. Patrick should review the 20 pairs above. The review CSV at `~/agents/preached/eval-review/` was not regenerated, per the brief. `questions.jsonl` carries `group` and `rewrite_of` for it.
- **The labels favor the titled wording.** The graded passages were found by keyword search for the original phrasing. A plain question answered by another paragraph of the right sermon scores 0, so `sermon@5` is the fairer `plain` signal. Labels were not changed, per the brief. Adding grade-1 passages for the rewrites is the natural next step.
- **20 rewrites instead of 15.** See section 1. If Patrick prefers exactly the listed 15, revert the 5 extra rewrites and accept that the lint fails on those 5 originals, or keep them as `names-topic` without twins.
- **`k-gain-all-you-can` is in `scripture-keyword`** although it is a sermon phrase, not scripture.
- **Small n.** There are 25 `plain` questions. One question moves a `plain` mean by 0.04, and most `plain` CIs include zero.
- **The lint is heuristic.** Light stemming plus a hand-made signature list. It flags whole words (for example a `plain` question for *The Means of Grace* must avoid "mean"). It does not catch synonyms of title words; a human review of the pairs does.
- **The Arctic corpus vectors were (re)embedded on the aligned chunks for this run** (146 s on the 3060). Granite and Gemma 2 vectors were cached with matching fingerprints.

## 6. Dependencies added

None. `uv lock --check`: `Resolved 75 packages`, exit 0.

## Tests

`uv run python -m unittest discover -s tests`: **251 tests, OK** (246 before, plus 5 in `tests/test_eval_leak.py`).
