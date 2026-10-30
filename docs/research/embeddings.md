# Embedding model research for Preached

Last run: 2026-10-30 (America/New_York), task EVAL-DELEAK, on the 60-question grouped eval set. Results file: [`eval/results/2026-10-30-deleak.json`](../../eval/results/2026-10-30-deleak.json) ([table](../../eval/results/2026-10-30-deleak.md)); abstain check [`2026-10-30-deleak-abstain`](../../eval/results/2026-10-30-deleak-abstain.md). The previous headline run (40 questions) is [`eval/results/2026-10-30.json`](../../eval/results/2026-10-30.json). This document covers task W1-B (first benchmark, by the Grok CLI agent), the audit of that benchmark, the rerun, and the [title-leakage fix](#title-leakage). It is meant to be rerun as models improve. See [How to rerun or add a model](#how-to-rerun-or-add-a-model).

## Summary

**Read [Title leakage](#title-leakage) first.** The numbers in the bullets below were measured on the 35 original answerable questions, most of which name their sermon's title. They still reproduce exactly, but on questions written in everyday words (group `plain`) every model finds the graded passage almost never (nDCG@10 ≤ 0.11) and the right sermon in the top 5 only 20–52% of the time.

- **Ship `ibm-granite/granite-embedding-english-r2` with hybrid search (BM25 + dense, reciprocal rank fusion, k=60).** That was the W1-B recommendation, and it still holds after the audit, but the margin is much smaller than first reported.
- **The first run handicapped EmbeddingGemma 2.** Each chunk was encoded as `title: <sermon title> (<scripture>) | text: ...`. The other models saw the bare chunk. With the model card's `title: none | text: ...` prefix, EmbeddingGemma 2 dense Recall@5 rose from 0.357 to 0.586, and hybrid RRF rose from 0.500 (first run) to 0.643. Precision was not the cause (bf16 and fp32 vectors agree to cosine ≥ 0.9995).
- **Corrected, Granite and EmbeddingGemma 2 are tied within noise in hybrid mode.** The paired bootstrap difference in nDCG@10 (Gemma minus Granite) is −0.039, 95% CI [−0.12, +0.04]. Recall@5 is +0.014 [−0.11, +0.14]. Granite is ahead on ranking (MRR, nDCG), smaller (149M vs 270M text parameters), and faster per CPU query (p50 115 ms vs 130 ms). It is also the only clean-lineage candidate whose hybrid nDCG point estimate is the highest.
- **Hybrid reliably beats BM25 alone.** Granite hybrid RRF minus BM25: nDCG@10 +0.157 [+0.06, +0.26], MRR@10 +0.173 [+0.07, +0.28].
- **The eval set is small and its labels are an LLM agent's.** There were 35 answerable questions; EVAL-DELEAK adds 20 rewrites (55 answerable, 25 of them `plain`). Human review by Patrick is pending. Read every number with that in mind.

## Question and constraints

The question is which text embedding model to use, alongside BM25, to find the passage in Wesley's sermons (and later a church's transcribed sermons) that answers a church member's question. The constraints are:

- **Offline.** Weights run locally. No embedding API.
- **Non-PRC provenance.** AGENTS.md §3: no models from organizations based in the PRC, and no fine-tunes or distillations of them. If lineage is unclear, exclude or flag it.
- **One Sprite.** Queries are embedded on CPU at request time. The corpus can be embedded once on a GPU.
- **Permissive license**, compatible with a public hackathon entry.
- **No LLM in the product.** The model only embeds. It never writes or paraphrases.
- **Minimal dependencies**: numpy, sentence-transformers, and torch. One SQLite file, with brute-force cosine search.

## Candidates

| model | developer | license | params | status | lineage, with sources |
| --- | --- | --- | --- | --- | --- |
| `google/embeddinggemma-2` | Google DeepMind | Apache-2.0. The card also points to the Gemma 4 license and the prohibited-use policy | 270M text-only (740M with vision and audio) | **benchmarked, clean** | Gemma 4 backbone, Google DeepMind. No PRC base model or teacher is named in public sources. [card](https://huggingface.co/google/embeddinggemma-2), [arXiv:2610.37364](https://arxiv.org/abs/2610.37364) |
| `google/embeddinggemma-300m` | Google DeepMind | Gemma license, gated | 308M | not run: gated, no `HF_TOKEN` | Predecessor (Gemma 3). [card](https://huggingface.co/google/embeddinggemma-300m) |
| `ibm-granite/granite-embedding-english-r2` | IBM | Apache-2.0 | 149M | **benchmarked, clean, recommended** | IBM trained its own encoder from scratch with the ModernBERT architecture recipe, using no ModernBERT weights ("We train both our base and small models from scratch", [arXiv:2508.21085](https://arxiv.org/abs/2508.21085) §2). Synthetic data and query rewrites use Mistral-7B-Instruct (Mistral AI, France). Hard negatives are mined with IBM's own granite-embedding-125m. No MS-MARCO ([card](https://huggingface.co/ibm-granite/granite-embedding-english-r2)). |
| `ibm-granite/granite-embedding-small-english-r2` | IBM | Apache-2.0 | 47M | not run (same release, smaller) | Same paper. A candidate for a later "smaller and faster" row. |
| `Snowflake/snowflake-arctic-embed-l` (v1) | Snowflake | Apache-2.0 | 334M | **benchmarked, lineage unclear, pending Patrick** | Initialized from `intfloat/e5-large-unsupervised` (Microsoft Research Asia). The paper does not name the models used for hard-negative mining or LLM query generation ([arXiv:2405.05374](https://arxiv.org/abs/2405.05374), "Model Initialization", "Tunable Hard Negative Mining"). |
| `nomic-ai/nomic-embed-text-v2-moe` | Nomic AI | Apache-2.0 | 475M (305M active) | **excluded after benchmarking** | Its paper uses BAAI BGE-M3 to filter hard negatives for both English and multilingual data ([arXiv:2502.07972](https://arxiv.org/abs/2502.07972) §4.4). That alone is the basis for the exclusion. Two weaker lineage notes, worded to match the sources: its English pretraining pairs inherit Nomic v1's consistency filtering with Alibaba gte-base ([arXiv:2402.01613](https://arxiv.org/abs/2402.01613); v2 reuses that pre-filtered data, 2502.07972 §4.2), and the §7.3 ablation found Stella 1.5B v5 (built on Qwen2) the best negative-mining teacher, but the paper does not state which teacher the final model used. (The first CTO review of PR #2 said gte-base mined v2's hard negatives and Stella was the production teacher; CTO corrected that in the re-review.) It was also the only `trust_remote_code` load. |
| `Snowflake/snowflake-arctic-embed-l-v2.0` | Snowflake | Apache-2.0 | 568M | excluded | Initialized from BAAI `bge-m3-retromae` ([arXiv:2412.04506](https://arxiv.org/abs/2412.04506) §2.1). |
| `Snowflake/snowflake-arctic-embed-m-v2.0` | Snowflake | Apache-2.0 | 305M | excluded | Initialized from Alibaba `gte-multilingual-mlm-base` (same paper, §2.1). |
| `nomic-ai/nomic-embed-text-v1.5`, `nomic-ai/modernbert-embed-base` | Nomic AI | Apache-2.0 | 137M / 149M | not run | Older than v2-MoE. The same Nomic training-data lineage question applies. |
| Qwen3-Embedding, BGE (BAAI), GTE (Alibaba), Stella/Jasper, Jina | — | — | — | excluded by rule | AGENTS.md §3 (PRC developer, PRC base, or unclear provenance). |

The machine-readable version is `search/models.toml`: `[models.*]` for runnable models and `[[excluded]]` for the rest. A model with `provenance = "unclear: ..."` is benchmarked and flagged. The loader refuses to make it the default.

## Setup (2026-10-30 run)

| item | value |
| --- | --- |
| code | `feat/w1-retrieval` at commit `73f39d9` (harness and models.toml in `8583581`, EmbeddingGemma 2 prefix fix in `73f39d9`) |
| EVAL-DELEAK rerun | `feat/eval-deleak` at commit `bbb7fb2` (per-group reporting). Same models, revisions, prompts, dtype, fusion settings, and seed. Chunks: `/cache/corpus/wesley/chunks_aligned.jsonl` (8,383 chunks, the index since W1-CLI); the 35 original questions give identical numbers on it. Granite and Gemma 2 corpus vectors were cached (fingerprints match); Arctic was re-embedded (146 s on the 3060). |
| libraries | Python 3.12, torch 2.15.0+cu132, transformers 5.22.1, sentence-transformers 6.2.0, numpy 2.5.4 (pinned in `uv.lock`) |
| hardware | Corpus: NVIDIA RTX 3060 12 GB (driver 615.78.08), shared with a Whisper job. Queries: Intel i9-12900K CPU, torch default threads |
| dtype | **fp32 for every model, on GPU and CPU**, so precision is not a variable. The EmbeddingGemma cards forbid fp16 (NaN or silently degraded vectors). bf16 is allowed, and we measured it equivalent (below). |
| output | Each model's native size (768, or 1024 for Arctic). L2-normalized. No Matryoshka truncation. |
| pooling | From each repo's `1_Pooling`: EmbeddingGemma 2 mean, Granite CLS, Arctic CLS, Nomic mean |
| max length | No chunk is truncated. Chunks are at most 180 words (about 211 Gemma tokens). Context windows are 512 tokens (Nomic) to 8,192. |
| batch | 8 on GPU, 1 for queries |

Pinned revisions (Hugging Face commit hashes):

| key | repo | revision |
| --- | --- | --- |
| embeddinggemma-2 | google/embeddinggemma-2 | `f9972ac22e696a105c482202646979e33e4b5a1e` |
| granite-english-r2 | ibm-granite/granite-embedding-english-r2 | `47ea694b257b703fee9253d75c2b1f2985180498` |
| arctic-embed-l | Snowflake/snowflake-arctic-embed-l | `d8fb21ca8d905d2832ee8b96c894d3298964346b` |
| nomic-embed-text-v2-moe (excluded) | nomic-ai/nomic-embed-text-v2-moe | `1066b6599d099fbb93dfcb64f9c37a7c9e503e85` (remote code from nomic-ai/nomic-bert-2048 `7710840340a098cfb869c4f65e87cf2b1b70caca`) |
| embeddinggemma-300m (not run) | google/embeddinggemma-300m | `57c266a740f537b4dc058e1b0cda161fd15afa75` |

Prompts, as the model sees them. Questions are any query that ends in `?` or starts with a question word. Everything else counts as a keyword query.

| key | question | keyword | document |
| --- | --- | --- | --- |
| embeddinggemma-2 | `task: question answering \| query: {q}` | `task: search result \| query: {q}` | `title: none \| text: {chunk}` |
| granite-english-r2 | `{q}` (card: no prefix) | `{q}` | `{chunk}` |
| arctic-embed-l | `Represent this sentence for searching relevant passages: {q}` | same | `{chunk}` |
| nomic-embed-text-v2-moe | `search_query: {q}` | same | `search_document: {chunk}` |

Corpus and chunking: CCEL *Sermons on Several Occasions* (sha256 `883dd705…944784`, verified on fetch against `corpus/catalog.json`). 141 sermons, 652,145 words, 8,383 chunks. `corpus/chunk_config.json`: target 112 words (about 45 s of speech at 150 wpm), minimum 75, maximum 150, 25% overlap. Median chunk is 122 words, maximum 180.

Search: SQLite FTS5 BM25 (porter, unicode61) over chunk text, sermon title, and scripture. Dense search is a brute-force numpy dot product over float32 vectors. Hybrid RRF fuses the top 100 of each list with k=60. Hybrid weighted min-max-normalizes both lists and mixes them at 0.5. That weight was never tuned.

## Eval set and how it was labeled

`eval/questions.jsonl` has 60 items (40 before EVAL-DELEAK): 45 conceptual questions, 10 keyword queries (scripture references and named doctrines), and 5 with no answer in Wesley (`relevant: []`). Each item has a `group`: `plain` (25), `names-topic` (20), `title-keyword` (3), `scripture-keyword` (7), `unanswerable` (5). The 20 added items are `-plain` rewrites of the `names-topic` questions with identical labels. See [Title leakage](#title-leakage) and `eval/README.md`.

**The labels are an LLM agent's work.** The Grok CLI coding agent wrote all 40 questions and chose every relevant passage and its grade (2 = directly answers, 1 = related). It found candidates with ordinary text search and then read the surrounding paragraph. Every quote is a verbatim CCEL span, machine-checked to be inside at least one chunk (`eval/validate.py`). No embedding model under test was used to pick labels, and no model judges relevance at search time. The relevance calls are still a model's, not a person's. **Human review is pending: Patrick is to review all 40 items before submission** (the field is in `eval/README.md`). Until then, do not call this set human-labeled or human-verified.

Known biases:

1. **Keyword-search bias.** Candidates were found by text search, so passages that share words with the question are over-represented. This favors BM25 and hybrid modes, and it may understate dense models on paraphrased questions.
2. **Title-word reuse.** 23 of the 35 answerable questions share a content word with the answering sermon's title (for example "Christian perfection", "means of grace", "witness of the Spirit", "riches", "temptation"). FTS5 indexes titles. Absolute scores are therefore optimistic for anything with a lexical component. EVAL-DELEAK keeps these questions as groups `names-topic` and `title-keyword` and adds title-free rewrites; report the `plain` group separately (see [Title leakage](#title-leakage)).
3. **Small n.** With 35 answerable questions, one question moves a mean by about 0.03. Confidence intervals are wide (below).
4. **Quote-level strictness.** A hit means the exact graded quote is inside a returned chunk. "Right sermon, next paragraph" scores 0. `sermon@5` is reported as a looser check.

## Metrics

All metrics are computed on the answerable questions (35 before EVAL-DELEAK, 55 after), overall and per `group`. Unanswerable questions are reported only as top-1 scores here; the abstain rule (`--abstain`) uses them.

- **Per group**: `bench.py` reports every metric, and the paired Δ against the reference, separately for each `group` in `eval/questions.jsonl`. The bootstrap uses the same seed on each group's questions.

- **Recall@5**: the fraction of a question's graded quotes (grade ≥ 1) found in the top 5 chunks, averaged over questions.
- **MRR@10**: 1/rank of the first chunk that contains any graded quote, or 0 if it is not in the top 10.
- **nDCG@10**: gain 2^grade − 1 for each chunk, crediting each quote once even if overlap repeats it, with a log2 discount. The ideal ranking is one chunk per quote, best grade first.
- **sermon@5**: 1 if any top-5 chunk comes from a sermon that holds a top-grade quote.
- **95% CI**: percentile bootstrap over questions, 10,000 resamples, seed 20261030.
- **Paired Δ**: the bootstrap of the per-question difference against the reference row (Granite hybrid RRF), using the same resampled questions for both systems. The tables give wins/ties/losses per question. `p_le_zero` in the JSON is the share of resamples where the row is not better than the reference.
- **CPU latency**: one query embed plus the search, model on CPU in fp32, over all eval queries (60 since EVAL-DELEAK), warmup excluded, p50 and p95.

## Audit of the first run (2026-10-30)

The first run reported EmbeddingGemma 2 as the weakest model: dense Recall@5 0.357, below BM25's 0.486. Before trusting that, each setting was checked against the [model card](https://huggingface.co/google/embeddinggemma-2) and measured directly.

| check | card says | first run | finding |
| --- | --- | --- | --- |
| Query prompts | `task: search result \| query: ` for search, `task: question answering \| query: ` for QA | QA prompt for questions, search prompt for keywords, via ST prompt names (verified against the repo's `config_sentence_transformers.json`) | Correct. Using the search prompt for everything is within noise (see the sensitivity table). |
| **Document prompt** | `title: {title} \| text: {content}`, or `title: none` if there is no title. `prompt_name="Document"` gives `title: none` | `title: <sermon title> (<scripture>) \| text: <chunk>` for every chunk | **This was the problem.** Every chunk of a sermon (about 60 per sermon) carried the same title, which pulled a sermon's chunks together and drowned the passage. Titles like "Upon our Lord's Sermon on the Mount, Discourse 9" also say little. No other model got a title, so the comparison was not like for like. Fixed to `title: none`. |
| dtype | bf16 or fp32, never fp16 | bf16 on GPU, fp32 on CPU | Fine. fp32 vs bf16 corpus vectors: cosine min 0.9995, mean 0.99994. Same metrics (0.357 both ways). Now fp32 for every model. |
| Normalization | L2 (repo has a Normalize module) | L2 in ST and again in our code | Fine. |
| Max length and truncation | 8,192 tokens | ST reports no limit. Chunks are 173 tokens median, 211 max | Fine. Nothing is truncated. |
| Matryoshka dimension | 768 native; 512, 256, 128 optional, re-normalize after truncating | 768 | Fine. |
| Pooling | mean, prompt tokens included | from the repo (mean, `include_prompt: true`) | Fine. |
| Attention | bidirectional encoder | the first token's hidden state changes when later text changes | Fine (not a causal mask). |
| Padding and batching | — | batch 4, right padding | Fine. Batched and one-at-a-time vectors agree (cosine ≥ 0.99999). |
| Text-only load | `config_kwargs={"vision_config": None, "audio_config": None}` | same | Fine. The card example ranks the right document first (0.87 vs 0.55). |
| Library versions | sentence-transformers ≥ 6.1.0 | 6.2.0 with transformers 5.22.1 | Fine. |

The same check for Granite English R2: the card uses no prefix and CLS pooling (from the repo, so the W1-B report's "mean pooling" was a doc error only). fp16 GPU vs fp32 CPU vectors agree (cosine min 0.9997), and the first-run vectors match fp32 (cosine ≥ 0.999996). The Granite numbers reproduce exactly. The CTO's independent rerun also reproduced Granite hybrid RRF (R@5 0.629, MRR@10 0.506).

EmbeddingGemma 2 sensitivity to the prompt setup, fp32. This is a diagnostic only. It was not used to tune the shipped config, because that would fit the test set. The config follows the card.

| documents | queries | dense R@5 | dense MRR@10 | dense nDCG@10 | hybrid RRF R@5 | hybrid RRF nDCG@10 |
| --- | --- | --- | --- | --- | --- | --- |
| `title: <sermon> (<ref>) \| text:` (first run) | QA / search | 0.357 | 0.278 | 0.321 | 0.471 | 0.427 |
| same | search prompt for all | 0.386 | 0.280 | 0.329 | 0.500 | 0.433 |
| **`title: none \| text:` (card default, now used)** | **QA / search** | **0.586** | **0.339** | **0.420** | **0.643** | **0.518** |
| `title: none \| text:` | search prompt for all | 0.529 | 0.361 | 0.443 | 0.643 | 0.532 |
| no prefix | no prefix | 0.500 | 0.323 | 0.393 | 0.643 | 0.524 |

## Results (2026-10-30 rerun, all fp32, pinned revisions, 35 original questions)

These are the pre-EVAL-DELEAK headline numbers, on the 35 original answerable questions. The EVAL-DELEAK rerun reproduces every row exactly on that subset (`scripts/leak_subsets.py`). The new per-group numbers are under [Title leakage](#title-leakage).

Cells are the mean with a 95% bootstrap CI. Δ is the paired nDCG@10 difference against Granite hybrid RRF (wins/ties/losses per question).

Clean-lineage candidates:

| model | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs Granite RRF | CPU p50 / p95 ms | corpus chunks/s (3060, fp32) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.486 [0.31, 0.66] | 0.333 [0.22, 0.46] | 0.401 [0.28, 0.53] | 0.886 | −0.157 [−0.26, −0.06] (4/15/16) | — | — |
| granite-english-r2 | dense | 0.543 [0.39, 0.70] | 0.424 [0.29, 0.56] | 0.473 [0.34, 0.61] | 0.800 | −0.084 [−0.19, +0.03] (5/19/11) | 114 / 311 | 98.3 |
| **granite-english-r2** | **hybrid RRF** | **0.629 [0.47, 0.77]** | **0.506 [0.36, 0.65]** | **0.558 [0.42, 0.69]** | **0.971** | reference | **115 / 134** | 98.3 |
| granite-english-r2 | hybrid weighted | 0.571 [0.40, 0.73] | 0.477 [0.34, 0.61] | 0.541 [0.41, 0.67] | 0.943 | −0.017 [−0.05, +0.02] (3/27/5) | 117 / 161 | 98.3 |
| embeddinggemma-2 | dense | 0.586 [0.43, 0.74] | 0.339 [0.23, 0.46] | 0.420 [0.31, 0.54] | 0.857 | −0.138 [−0.24, −0.04] (8/12/15) | 132 / 209 | 63.9 |
| embeddinggemma-2 | hybrid RRF | 0.643 [0.49, 0.80] | 0.458 [0.33, 0.59] | 0.518 [0.39, 0.65] | 0.943 | −0.039 [−0.12, +0.04] (7/19/9) | 130 / 190 | 63.9 |
| embeddinggemma-2 | hybrid weighted | 0.586 [0.43, 0.74] | 0.451 [0.32, 0.59] | 0.511 [0.38, 0.64] | 0.943 | −0.046 [−0.13, +0.04] (8/19/8) | 133 / 165 | 63.9 |

Lineage unclear (pending Patrick's decision), kept as measurements:

| model | mode | R@5 | MRR@10 | nDCG@10 | Δ nDCG@10 vs Granite RRF | CPU p50 ms |
| --- | --- | --- | --- | --- | --- | --- |
| arctic-embed-l ⚠ | dense | 0.486 | 0.304 | 0.366 | −0.191 [−0.32, −0.07] | 143 |
| arctic-embed-l ⚠ | hybrid RRF | 0.600 | 0.426 | 0.492 | −0.065 [−0.14, +0.01] | 150 |
| arctic-embed-l ⚠ | hybrid weighted | 0.643 | 0.470 | 0.530 | −0.028 [−0.09, +0.03] | 150 |

Excluded on lineage after measurement (not a candidate):

| model | mode | R@5 | MRR@10 | nDCG@10 | Δ nDCG@10 vs Granite RRF |
| --- | --- | --- | --- | --- | --- |
| nomic-embed-text-v2-moe ✗ | dense | 0.429 | 0.277 | 0.338 | −0.220 [−0.33, −0.11] |
| nomic-embed-text-v2-moe ✗ | hybrid RRF | 0.529 | 0.411 | 0.465 | −0.092 [−0.17, −0.01] |
| nomic-embed-text-v2-moe ✗ | hybrid weighted | 0.557 | 0.425 | 0.482 | −0.075 [−0.15, −0.00] |

Paired comparisons that matter:

| comparison | metric | Δ (first − second) | 95% CI | reading |
| --- | --- | --- | --- | --- |
| Granite hybrid RRF vs BM25 | nDCG@10 | +0.157 | [+0.06, +0.26] | hybrid reliably better |
| Granite hybrid RRF vs BM25 | MRR@10 | +0.173 | [+0.07, +0.28] | hybrid reliably better |
| Gemma 2 hybrid RRF vs Granite hybrid RRF | nDCG@10 | −0.039 | [−0.12, +0.04] | tie |
| Gemma 2 hybrid RRF vs Granite hybrid RRF | MRR@10 | −0.048 | [−0.14, +0.04] | tie, leaning Granite (86% of resamples favor Granite) |
| Gemma 2 hybrid RRF vs Granite hybrid RRF | Recall@5 | +0.014 | [−0.11, +0.14] | tie |
| Gemma 2 dense vs Granite dense | Recall@5 | +0.043 | [−0.11, +0.20] | tie |
| Gemma 2 dense vs Granite dense | MRR@10 | −0.085 | [−0.22, +0.04] | tie; Gemma tends to rank the hit lower |
| Arctic weighted vs Granite RRF | nDCG@10 | −0.028 | [−0.09, +0.03] | tie |

These agree with the CTO's independent paired bootstrap on the first-run vectors: hybrid RRF reliably beats BM25, Granite vs Arctic is within noise, and Granite vs Gemma 2 on MRR is borderline. After the Gemma prefix fix, it is less than borderline.

Resources: at fp32 the extra GPU memory over the Whisper baseline (nvidia-smi, includes the CUDA context) was 1.3 GB (Granite), 1.4 GB (Arctic), 2.2 GB (Gemma 2), and 2.6 GB (Nomic). Each set of 768-d float32 vectors is 25.8 MB for 8,383 chunks.

Superseded first run (commit 7347eb7, unpinned revisions, fp16/bf16 GPU, GPU query vectors, titled Gemma documents). It is kept in `eval/results/2026-10-30-w1b-original.json`:

| model | dense R@5 | dense MRR@10 | hybrid RRF R@5 | hybrid RRF MRR@10 | hybrid RRF nDCG@10 |
| --- | --- | --- | --- | --- | --- |
| BM25 | 0.486 (bm25) | 0.333 | | | |
| embeddinggemma-2 (titled docs) | 0.357 | 0.273 | 0.500 | 0.362 | 0.428 |
| granite-english-r2 | 0.543 | 0.424 | 0.629 | 0.506 | 0.558 |
| arctic-embed-l | 0.486 | 0.309 | 0.600 | 0.426 | 0.492 |
| nomic-embed-text-v2-moe | 0.429 | 0.277 | 0.529 | 0.414 | 0.474 |

## Title leakage

### The issue

Patrick (2026-10-30): many eval questions name the expected sermon's title, so they test title lookup, not understanding. "What did Wesley say about the wilderness state?" finds *The Wilderness State* because FTS5 indexes the title column and every embedding model sees the same rare words in the chunk. A searcher in trouble would say "I used to feel close to God and now everything feels dark" instead. The old headline (Granite hybrid RRF nDCG@10 0.558) was measured mostly on questions like the first one.

### The fix (task EVAL-DELEAK)

1. **Originals kept, unchanged, and grouped.** Every question has a `group`: `names-topic` (conceptual questions that name the topic), `title-keyword` (keyword queries equal to a title: `k-christian-perfection`, `k-means-of-grace`, `k-witness-of-the-spirit`), `scripture-keyword` (the other 7 keyword queries; `k-gain-all-you-can` is a phrase from sermon 50, not scripture, but is not a title), `unanswerable` (5), and `plain`.
2. **Plain rewrites.** Each `names-topic` question has a `-plain` twin (`rewrite_of` points back) with the same `relevant` list, byte for byte. It is written the way a hurting or curious layperson would ask, and it avoids every content word of the sermon's title and the sermon's signature term or scripture phrase ("born again", "means of grace", "wilderness", "deny yourself", "way to escape", and so on). The 5 conceptual questions that were already title-free are also `plain` (25 in total).
3. **Five more than the brief listed.** Patrick listed 15 leaky conceptual questions. The lint (next item) found five of the remaining ten also share a title word: `q-money` ("money" / *The Use of Money*), `q-heaviness` ("heaviness", "heavy" / *Heaviness through Manifold Temptations*), `q-communion` ("communion" / *The Duty of Constant Communion*), `q-justification` ("justified" / *Justification by Faith*), `q-backsliders` ("backsliders" / *A Call to Backsliders*). They were treated the same way: original tagged `names-topic`, `-plain` rewrite added. So `names-topic` has 20 items, not 15.
4. **Lint.** `scripts/check_title_leak.py` fails if any `plain` question shares a content word (longer than 3 letters, not a stopword, light suffix stemming, prefix match for stems of 5+ letters) with the title of any sermon in its `relevant` list, or contains a signature phrase listed for that sermon. `tests/test_eval_leak.py` runs it, checks that every item has a known group, that every `names-topic` item has a `-plain` twin with identical labels, and that the lint catches each original.
5. **No other change.** Labels, chunks, models, revisions, prompts, dtype, RRF k=60, weighted mix 0.5, and bootstrap seed 20261030 are the same as the audit rerun. `bench.py` now also reports every metric per group. The rewrites were written and committed before any model was run on them and were not edited after.

Who wrote the rewrites: the EVAL-DELEAK coding agent (an LLM, Claude), not reviewed by a person. They inherit the "pending human review" status of the whole set.

### Results by group (2026-10-30, EVAL-DELEAK rerun)

Each cell is nDCG@10 / R@5 / MRR@10. `n` is the number of answerable questions. Full CIs and paired Δ per group are in [`2026-10-30-deleak.md`](../../eval/results/2026-10-30-deleak.md).

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

⚠ Arctic v1: lineage unclear, eval-only. Unanswerable (abstain) is below.

The `plain` group in detail, with 95% bootstrap CIs and the paired Δ against Granite hybrid RRF (wins/ties/losses). `sermon@5` (any top-5 chunk from the sermon holding a grade-2 quote) is the looser check and the more informative one here:

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

### Old vs new headline

| system | old headline: 35 original questions | new overall: 55 answerable | plain (25) | the 20 rewrites only | their 20 originals |
| --- | --- | --- | --- | --- | --- |
| Granite hybrid RRF nDCG@10 / R@5 / MRR@10 / sermon@5 | 0.558 / 0.629 / 0.506 / 0.971 | 0.361 / 0.400 / 0.324 / 0.745 | 0.028 / 0.040 / 0.013 / 0.440 | 0.016 / 0.000 / 0.006 / 0.350 | 0.543 / 0.600 / 0.475 / 1.000 |
| EmbeddingGemma 2 hybrid RRF | 0.518 / 0.643 / 0.458 / 0.943 | 0.330 / 0.409 / 0.292 / 0.727 | 0.013 / 0.000 / 0.005 / 0.400 | 0.000 / 0.000 / 0.000 / 0.350 | 0.478 / 0.675 / 0.395 / 1.000 |
| BM25 | 0.401 / 0.486 / 0.333 / 0.886 | 0.257 / 0.309 / 0.215 / 0.618 | 0.004 / 0.000 / 0.007 / 0.200 | 0.005 / 0.000 / 0.008 / 0.150 | 0.313 / 0.400 / 0.216 / 0.950 |

The 35-question column reproduces the audit rerun exactly for every model and mode. Asked in plain words, the same 20 needs drop from finding the right sermon every time (sermon@5 1.000) to about a third of the time (0.350), and the graded passage almost never reaches the top 10. The 5 questions that were title-free from the start also score near zero at quote level (Granite RRF nDCG@10 0.077), so the old headline was carried by questions that name their topic and by keyword queries. `scripts/leak_subsets.py` prints this table for every model.

### Abstain floor (0.8129) on the new set

`bench.py --abstain --models granite-english-r2 embeddinggemma-2` refits the floor on all 60 questions. **It still holds**: the refit is 0.8129 for Granite and 0.7413 for EmbeddingGemma 2, the same as `search/abstain.toml` (not rewritten). No answerable question in any group is abstained (false abstain 0, in-sample and leave-one-out). Unanswerable: Granite abstains on 4 of 5 in-sample and 3 of 5 leave-one-out, and flags 4 of 5 weak or none, exactly as before. The margin is thinner than it looks: the lowest Granite top cosine on a `plain` question is 0.8224, 0.0095 above the floor, and 3 of 25 `plain` questions sit below EmbeddingGemma 2's floor (they are rated `weak`, not `none`, only because BM25 and dense agree on a shown passage). Every `plain` question has agreement, which is what keeps them out of `none`.

### Is Granite still the best choice on `plain`?

**Granite is still the best clean-lineage model on `plain`, but hybrid RRF (the default mode) is not the best mode there, and no row is reliably good.**

- In the default mode (hybrid RRF), Granite (nDCG@10 0.028) is ahead of EmbeddingGemma 2 (0.013; Δ −0.015 [−0.04, +0.00]) and level with Arctic (0.030; +0.002 [−0.04, +0.04]).
- The best clean row on `plain` is **Granite dense alone**: nDCG@10 0.078, Δ **+0.050 [+0.01, +0.10]** over the default (4 wins, 20 ties, 1 loss). It is the only `plain` difference whose CI excludes zero. It rests on 4 wins (mourning, communion, wandering thoughts, evil-speaking) against 1 loss (forgiveness), and on sermon@5 Granite dense is not better (0.400 vs 0.440, Δ −0.04 [−0.28, +0.20]). On every other group, dense alone is worse than the default (names-topic −0.129 [−0.26, −0.01]).
- The best row overall on `plain` is **Arctic v1 dense** (lineage unclear, eval-only): nDCG@10 0.105, +0.077 [−0.02, +0.20] over the default, sermon@5 0.520 vs 0.440 (+0.08 [−0.20, +0.36]). Within noise, and Arctic dense is far worse on scripture keywords (−0.581 [−0.74, −0.45]).
- Hybrid fusion adds little on `plain` because BM25 is near zero there (nDCG@10 0.004, sermon@5 0.200): it mostly pulls the title-word chunks up.

**The default is not changed** (`default = "granite-english-r2"`, hybrid RRF). Whether to weight dense more for natural-language questions, or to switch modes by query type, is Patrick's call; this set is too small to tune it on.

### Wider grading and blind questions (EVAL-GRADE, labels proposed)

Most of the `plain` zero was narrow labels. EVAL-GRADE added 558 proposed grade-1 labels from a pool: the top 20 of every ranker, read and proposed by an LLM agent (Claude, `found_by` `llm-proposed:claude`). They are unconfirmed by a human. It also added 30 questions written blind to the corpus by an LLM agent (Grok, `provenance` `llm-written:grok`, group `plain-blind`). Those questions are unconfirmed by a human. Nothing below is confirmed by a person yet, and nothing was tuned on it.

Granite hybrid RRF (default), strict → lenient, with sermon-level hits:

| group | nDCG@10 strict | nDCG@10 lenient | hit@10 strict | hit@10 lenient | sermon@10 | sermon@50 |
| --- | --- | --- | --- | --- | --- | --- |
| plain (25) | 0.028 | 0.132 | 0.08 | 0.72 | 0.56 | 0.84 |
| plain-blind (28) | 0.032 | 0.027 | 0.07 | 0.11 | 0.36 | 0.82 |

On `plain-blind`, Granite dense alone beats the default on lenient hit@10 by +0.29 [+0.14, +0.46] (8 wins, 0 losses). The abstain floor no longer holds on that group. Full tables: `reports/EVAL-GRADE.md` and `eval/results/2026-10-30-grade.md`.

## Decision

**Keep Granite English R2 + BM25 hybrid RRF (k=60) as the default** (`default` in `search/models.toml`). The reasons:

1. Its quality is the best or tied-best on every metric. It has the highest MRR@10 and nDCG@10 point estimates, and no clean model beats it outside noise.
2. It is the cheapest on one Sprite: 149M parameters, p50 115 ms and p95 134 ms per CPU query, and 1.5× Gemma's GPU encode speed.
3. Its lineage is clean and documented (IBM from scratch, Mistral teacher, no MS-MARCO), and it is Apache-2.0.
4. The product path needs only numpy, sentence-transformers, and torch. No Pillow or torchvision.

**EmbeddingGemma 2 is a close, legitimate alternative, not the weakest model.** Patrick's original default was "Gemma Embeddings 2 unless there's a better offline option". On this eval, Granite is better on cost and equal on quality, so that bar is met, but only narrowly. Switching is a one-line change (`default = "embeddinggemma-2"`) plus `--group bench` dependencies, and it would cost about 15 ms per query. Gemma 2's multilingual and audio-embedding abilities are not used today. Revisit the choice if a non-English congregation or direct audio search becomes a requirement, or after the eval set is human-reviewed and grown.

Arctic v1 stays benchmark-only until Patrick rules on its lineage. Nomic v2-MoE is excluded.

**After EVAL-DELEAK (unchanged default, open question for Patrick).** On the 55-question set Granite hybrid RRF is still the best or tied-best clean row overall (nDCG@10 0.361; Gemma 2 RRF −0.031 [−0.08, +0.02]). On the `plain` group, Granite is still the best clean model, but Granite *dense alone* beats the default mode by +0.050 nDCG@10 [+0.01, +0.10] (4 wins, 1 loss) while losing on `names-topic`. Arctic v1 dense (eval-only) has the highest `plain` point estimate (+0.077 [−0.02, +0.20]). Every row is near zero at quote level on `plain`. The default was not changed. See [Is Granite still the best choice on `plain`?](#is-granite-still-the-best-choice-on-plain).

## Caveats and open issues

- **Labels are pending human review** (see above). If Patrick changes labels, rerun. Results files record `questions_sha256`.
- **Small n.** With 55 answerable questions (25 `plain`), most model-vs-model differences are inside the CIs. Growing the set to at least 100 questions, with a share written without keyword search, would tighten them and reduce the lexical bias.
- **Lexical optimism.** 23 of the 35 original questions reuse words from the answering sermon's title (`names-topic` and `title-keyword`). Read the `plain` group for natural-language quality.
- **Plain rewrites are an LLM agent's and the labels were chosen with keyword search.** The graded passages were picked for the titled wording (for example the sentence that says "heaviness of soul"). For a plain question a different paragraph of the right sermon may answer as well, and scores 0. That is why `sermon@5` is the better `plain` signal. Labels were not changed (Patrick's instruction); adding grade-1 passages for the plain rewrites is a human-review item.
- **The abstain margin on `plain` is thin.** Granite's lowest `plain` top cosine is 0.8224 against a 0.8129 floor; 3 `plain` questions are below EmbeddingGemma 2's floor and are saved from `none` only by agreement.
- **No tuning on this set.** RRF k, the weighted mix, and prompt variants were not tuned on it. The sensitivity table is diagnostic only.
- **Result diversity.** The top 5 averaged only 2.3 distinct sermons (CTO review). Sermon-level dedupe is open.
- **Transcripts.** These are text-derived chunks. The Wesley index will use canonical text aligned to the audio (W1-C), so numbers should carry over. Church sermons with ASR-only text may differ, so rerun when ASR chunks exist.
- **Not yet done:** EmbeddingGemma 300M (gated), Granite small R2, Matryoshka 256/512 rows, ONNX or int8 CPU runtimes, a CPU-only torch build in `uv.lock`, CI, and a LICENSE file.

## How to rerun or add a model

Rerun everything (each enabled model in `search/models.toml`, plus BM25):

```bash
cd /work/preached/.worktrees/feat/w1-retrieval      # or any checkout, inside the sandbox
uv run --group bench search/bench.py --note "why this run"
```

- The run writes `eval/results/YYYY-MM-DD.json` (everything: environment, versions, revisions, prompts, per-question metrics, CIs, paired deltas) and `eval/results/YYYY-MM-DD.md` (the table). A second run on the same day writes `YYYY-MM-DD-2.*`. Nothing is overwritten. Commit both files.
- Corpus vectors are cached in `/cache/index/wesley.sqlite` under a fingerprint of the revision, GPU dtype, dim, and document prefix. A rerun re-embeds only models whose fingerprint changed. `--reembed` forces it. Query-time search checks it too: `Searcher` (used by `search/query.py` and the app) raises `EmbeddingMismatch` when the stored fingerprint differs from `search/models.toml` (for example a revision bump without a rerun) instead of mixing old document vectors with new query vectors. BM25 mode needs no vectors. On a 3060, a full re-embed takes about 1.5 to 3 minutes per model at fp32.
- Query vectors are always computed on CPU, as on one Sprite.
- `--models granite-english-r2 embeddinggemma-2` runs a subset. The reference model (Granite) is always included, so paired deltas are comparable.
- Every run reports each metric and paired Δ per `group` (plain, names-topic, title-keyword, scripture-keyword) in both the JSON (`by_group`, `vs_reference_by_group`) and the Markdown.

The EVAL-DELEAK run, exactly:

```bash
uv run python scripts/check_title_leak.py                       # lint: exit 1 if a plain question leaks
uv run python eval/validate.py                                  # every graded quote is in a chunk
uv run --group bench search/bench.py --note "..."               # all enabled models + BM25
uv run --group bench search/bench.py --abstain --models granite-english-r2 embeddinggemma-2 --note "..."
uv run python scripts/leak_subsets.py eval/results/<run>.json   # old 35 vs rewrites vs originals
```

`--abstain` without `--write-calibration` only reports the refit floor; the shipped `search/abstain.toml` is untouched. The EVAL-DELEAK result files were renamed after the run to `2026-10-30-deleak*.{json,md}`, as earlier tasks did.

When adding eval questions: give each a `group`. A natural-language question goes in `plain` only if `scripts/check_title_leak.py` passes; otherwise put it in `names-topic`.
- Without a GPU, the corpus embeds on CPU (slow: about 8 chunks/s for Gemma 2).

To add a model, add one table to `search/models.toml`:

```toml
[models.my-new-model]
hf_id = "org/model-name"
revision = "<40-char commit hash from the HF 'Files and versions' tab>"
license = "Apache-2.0"
developer = "Org (country)"
lineage = "Base model -> ... -> this checkpoint. Teachers / negative miners: ..."
lineage_sources = ["https://huggingface.co/org/model-name", "https://arxiv.org/abs/..."]
provenance = "clear"             # or "unclear: <what is unknown>"
params = "150M"
dtype_gpu = "fp32"               # read the card: some models break in fp16
dtype_cpu = "fp32"
dim = 768                        # native size, or a Matryoshka size the card supports
question_prefix = "..."          # exactly as the card shows, including trailing space
keyword_prefix = "..."           # optional
document_prefix = "..."          # or document_template = "title: {title} | text: {text}"
```

Checklist before trusting a new row:

1. **Provenance first.** Check the base model, the distillation teacher, the hard-negative miner, and the data filters against AGENTS.md §3. If any is PRC-developed, or you cannot tell, mark it `unclear:` or put it in `[[excluded]]` with a source.
2. **Prompts** come from the card, not from defaults. Compare them with the repo's `config_sentence_transformers.json`. Give documents the same information as the other models. Do not add titles to one model only.
3. **dtype.** Run fp32 unless the card documents bf16 or fp16 as safe.
4. **Max length.** Confirm the longest chunk fits (`max_seq_length`).
5. **No `trust_remote_code`** unless there is no alternative. Note it if used.
6. Run it, then read the paired Δ and its CI before reading the point estimate. Update this document's Results and Decision sections only when a CI excludes zero or the cost/lineage picture changes.

Tests: `uv run python -m unittest discover -s tests` checks the config (pinned revisions, no fp16 for EmbeddingGemma, card prompts, excluded models not runnable, unclear lineage cannot be the default) and the statistics helpers.
