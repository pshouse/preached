# W1-B: Wesley eval set and retrieval benchmark

## Audit and rerun, 2026-10-30 (read this first)

The results below this section are the **first run, now superseded**. The full method, audit, and current numbers are in [`docs/research/embeddings.md`](../docs/research/embeddings.md). The current table is [`eval/results/2026-10-30.md`](../eval/results/2026-10-30.md).

- **EmbeddingGemma 2 was misconfigured.** Every chunk was encoded as `title: <sermon title> (<scripture>) | text: ...`, while the other models saw the bare chunk. With the card's `title: none | text: ...`, dense Recall@5 went from 0.357 to 0.586 and hybrid RRF from 0.500 to 0.643 (nDCG@10 0.428 to 0.518). dtype, prompts, pooling, normalization, length, and dimension were all correct. bf16 and fp32 vectors agree to cosine ≥ 0.9995.
- **Rerun:** every model in fp32 at pinned revisions, with query vectors on CPU. Granite reproduces exactly (hybrid RRF R@5 0.629, MRR@10 0.506, nDCG@10 0.558).
- **The recommendation stands, with a smaller margin.** Granite English R2 + BM25 hybrid RRF stays the default. Gemma 2 hybrid RRF vs Granite: nDCG@10 −0.039, 95% CI [−0.12, +0.04], which is a tie. Granite wins on cost: 149M parameters and 115 ms vs 130 ms CPU p50. Hybrid beats BM25 reliably (nDCG@10 +0.157 [+0.06, +0.26]).
- **Lineage (CTO review):** Nomic v2-MoE is now **excluded** (hard negatives filtered with BAAI BGE-M3, per arXiv:2502.07972 §4.4; gte-base and Stella/Qwen2 mining per the CTO review). Arctic-embed-L v1 is **flagged lineage unclear, pending Patrick**. Granite R2: IBM trained its own encoder from scratch with the ModernBERT recipe (no ModernBERT weights), with an IBM-tuned Mistral teacher and no MS-MARCO.
- **Label provenance is corrected.** The Grok CLI agent (an LLM) wrote the questions and chose every passage and grade. Quotes are verbatim and machine-checked. Human review by Patrick is pending (`eval/README.md`). The sentence below that called the labels "human readings" was wrong.
- **Rerun command:** `uv run --group bench search/bench.py`. Models live in `search/models.toml`, and results go to `eval/results/YYYY-MM-DD[-N].{json,md}` without overwriting. `reports/bench_results.json` moved to `eval/results/2026-10-30-w1b-original.json` and is marked superseded.
- **Dependencies:** Pillow and torchvision moved to the `bench` group (only Gemma 2 needs them). einops was dropped (only Nomic needed it).

---


## What was done

Built a public-domain text stand-in for the LibriVox sermons, a 40-question graded eval, and a single-SQLite retrieval CLI. Transcripts from `feat/w1-ingest` are not in this branch. Text chunks use the same record a transcript chunk will use, with `start_s` and `end_s` null.

Corpus: CCEL *Sermons on Several Occasions*, UTF-8 dump `https://www.ccel.org/ccel/w/wesley/sermons/cache/sermons.txt` (sha256 `883dd705fa14ee7bb70b14b03c85b021f3c1ed04212d93f0492708d852944784`). wesley.nnu.edu URLs 404, so they are not used. The number index is `https://www.ccel.org/ccel/wesley/sermons/sermons.iii.html`. Per-sermon pages are `https://ccel.org/ccel/wesley/sermons/{page}`.

Sermon ids are Jackson 1872 numbers, `wesley-001` through `wesley-141`, which match the LibriVox grouping:

| sermons | series | LibriVox id |
| --- | --- | --- |
| 1–53 | 1 | `sermonsfirstseries_1307_librivox` (track 00 is the preface, not a sermon) |
| 54–108 | 2 | `sermonssecondseries_1503_librivox` |
| 109–126 | 3 | `sermons3to5series_1511_librivox` |
| 127–133 | 4 | same third-to-fifth collection |
| 134–141 | 5 | same collection |

The preface is not indexed. There is no `wesley-000`.

141 sermons, 652,145 words, 8,383 chunks. Chunk params are frozen in `corpus/chunk_config.json`: target 112 words (~45 s at 150 wpm), minimum 75, maximum 150, overlap 0.25. Median 122 words, max 180. Ten chunks are 151–180 because a short heading was merged onto the next sentence with 30 words of slack. 190 chunks are under 75 words. 473 of 8,242 adjacent pairs do not overlap, because a sentence longer than 150 words is hard-split with no overlap. Do not retune unless a graded quote stops fitting in one chunk.

Eval: `eval/questions.jsonl`, 25 conceptual, 10 keyword, 5 unanswerable (`relevant: []`). ~~Labels are human readings of the CCEL text. No model judged relevance or wrote quotes.~~ Correction: the Grok CLI agent (an LLM) wrote the questions and chose every passage and grade. Quotes are verbatim CCEL text and are machine-checked. Human review is pending. Method is in `eval/README.md`. `uv run python eval/validate.py --write` confirmed every graded quote is contained in at least one chunk.

Retrieval: one SQLite file, `/cache/index/wesley.sqlite`. Table `chunks`, FTS5 `chunks_fts` (porter, unicode61) on text, sermon title, and scripture, and `embeddings` as float32 L2-normalized BLOBs. Cosine is a numpy dot product. BM25 uses SQLite `bm25()` negated so higher is better. This SQLite (3.53.1) rejects infix `NEAR/N`, so scripture queries use `NEAR("rom" "8" "16", 8)`. Hybrid is reciprocal rank fusion with k=60 over the top 100 of each list. Weighted fusion min-max normalizes each list and mixes them at `dense_weight=0.5`. That weight was not swept.

The CLI prints sermon title, chunk text, score, chunk id, sermon id, timestamps, and source URL. It prints `Nothing strong found in the indexed sermons.` only when there are zero hits. There is no score threshold. Measured top-1 scores of answerable and unanswerable queries overlap, so a threshold would be invented.

## How to run

From `/work/preached/.worktrees/feat/w1-retrieval`:

```bash
uv run corpus/fetch_wesley.py
uv run corpus/chunk_sermons.py
uv run python eval/validate.py
uv run search/bench.py
uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
```

`search/query.py` defaults to `--mode hybrid`, `--fusion rrf`, `--model granite-english-r2`, and `--device cpu`. Other modes: `--mode bm25`, `--mode dense`, `--fusion weighted`. Weights and the corpus dump stay under `/cache` (`HF_HOME=/cache/huggingface`). The index is `/cache/index/wesley.sqlite`.

The worry command above was run on CPU against the finished Granite index. It prints five excerpts with scores, sermon ids, null timestamps, and CCEL URLs. For that wording, sermon 29 is not in the top 5, which matches the quote-level miss on `q-worry`.

Rebuild one model without wiping the others:

```bash
uv run search/bench.py --models granite-english-r2
```

`--reembed` forces a new GPU encode. A partial run merges into `reports/bench_results.json` instead of replacing it.

## Results

Metrics use 35 answerable questions. A hit is quote containment, not "right sermon, nearby paragraph." Unanswerable questions are omitted from Recall, MRR, and nDCG. Recall@5 is the fraction of grade ≥ 1 quotes found in the top 5. MRR@10 and nDCG@10 use the same quotes. One BM25 row is shared. CPU latency is the query embed plus the search, model in float32 on CPU, 40 eval queries, warmup excluded.

| model | mode | R@5 | MRR@10 | nDCG@10 | chunks/s | VRAM delta MiB | CPU p50 / p95 ms | dim | vector bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 | bm25 | 0.486 | 0.333 | 0.401 |  |  |  |  |  |
| embeddinggemma-2 | dense | 0.357 | 0.273 | 0.316 | 58.4 | 875 | 143 / 258 | 768 | 25,752,576 |
| embeddinggemma-2 | hybrid RRF | 0.500 | 0.362 | 0.428 |  |  | 147 / 313 |  |  |
| embeddinggemma-2 | hybrid weighted | 0.529 | 0.408 | 0.475 |  |  | 148 / 427 |  |  |
| granite-english-r2 | dense | 0.543 | 0.424 | 0.473 | 115.3 | 475 | 116 / 152 | 768 | 25,752,576 |
| granite-english-r2 | hybrid RRF | 0.629 | 0.506 | 0.558 |  |  | 115 / 135 |  |  |
| granite-english-r2 | hybrid weighted | 0.571 | 0.477 | 0.541 |  |  | 117 / 254 |  |  |
| arctic-embed-l | dense | 0.486 | 0.309 | 0.370 | 79.1 | 1740 | 148 / 211 | 1024 | 34,336,768 |
| arctic-embed-l | hybrid RRF | 0.600 | 0.426 | 0.492 |  |  | 150 / 227 |  |  |
| arctic-embed-l | hybrid weighted | 0.643 | 0.470 | 0.530 |  |  | 150 / 279 |  |  |
| nomic-embed-text-v2-moe | dense | 0.429 | 0.277 | 0.338 | 34.5 | 1090 | 143 / 178 | 768 | 25,752,576 |
| nomic-embed-text-v2-moe | hybrid RRF | 0.529 | 0.414 | 0.474 |  |  | 144 / 236 |  |  |
| nomic-embed-text-v2-moe | hybrid weighted | 0.557 | 0.425 | 0.482 |  |  | 146 / 307 |  |  |

Encode batch size was 4. VRAM delta is measured from before the weights load, so it includes the model. The baseline already held the Whisper job (about 3.4–4.6 GiB). Every delta is under the 4 GiB share. GPU peaks were 5,162 MiB (Gemma), 4,782 MiB (Granite), 5,134 MiB (Arctic), and 5,695 MiB (Nomic, baseline 4,605, delta 1,090). With all four vector sets stored, the SQLite file is 154,312,704 bytes. Full JSON: `reports/bench_results.json`.

Quote-complete at Recall@5 = 1, hybrid RRF: Granite 21/35, Arctic 20/35, Nomic 18/35, Gemma 17/35. A separate check, not the official metric: Granite hybrid RRF puts a grade-2 sermon in the top 5 for 34 of 35 questions. The miss is `q-faith-works` (wanted `wesley-043`, got 91, 1, 33, 83). Quote-level misses for Granite RRF are `q-worry`, `q-assurance`, `q-money`, `q-riches`, `q-prayer`, `q-perfection` (recall 0.5), `q-heaviness`, `q-temptation`, `q-communion`, `q-salvation`, `q-justification`, `q-faith-works`, `q-new-birth` (recall 0.5), and `k-witness-of-the-spirit`. `q-salvation` is a fusion miss: BM25 recall is 1.0 and RRF drops the hit out of the top 10. `k-witness-of-the-spirit` is found by Granite dense (recall 1.0) and missed by RRF, because a chunk that appears in only one list loses to chunks that appear in both.

### Recommendation

Ship `ibm-granite/granite-embedding-english-r2` with hybrid RRF, k=60. `search/query.py` defaults to that.

It has the best MRR@10 (0.506) and nDCG@10 (0.558), and the best Recall@5 among RRF runs (0.629). Arctic weighted reaches 0.643 Recall@5, with worse MRR and nDCG, a larger vector (1024-d), a slower CPU query (~150 ms vs ~115 ms), and a 1,740 MiB GPU delta. The weighted mix was not tuned on a held-out set, so the higher Arctic recall is not a reason to switch. Granite is also the smallest extra VRAM (475 MiB), the fastest GPU embed (115 chunks/s), and the fastest CPU query (p50 115 ms, p95 135 ms), which is what one Sprite has to do per question.

License is Apache-2.0. ~~The base is ModernBERT (Answer.AI, US, and LightOn, France), trained by IBM.~~ Correction: IBM trained its own encoder from scratch with the ModernBERT architecture recipe and no ModernBERT weights (arXiv:2508.21085). The teacher is an IBM-tuned Mistral, and there is no MS-MARCO. It is not derived from a PRC model. The card uses no query or document prefix. English R2 (149M, Aug 2025, arXiv:2508.21085) is still the newest English Granite embedder. `granite-embedding-small-english-r2` is the same release, smaller, not newer. The May 2026 multilingual R2 line was not selected for this English corpus.

Nomic finished and does not change the pick. Its best mode is weighted hybrid (Recall@5 0.557, MRR@10 0.425, nDCG@10 0.482), behind Granite RRF on every metric. Nomic RRF is 0.529 / 0.414 / 0.474. Dense Nomic is below BM25 on MRR and nDCG. CPU hybrid RRF is 144 ms p50 and 236 ms p95, slower than Granite, and the GPU embed is 34.5 chunks/s against Granite's 115. The pure-PyTorch expert loop (megablocks not installed) is the likely cause. Quote-complete RRF is 18/35.

### Models, prefixes, and provenance

| key | Hugging Face id | license | what we ran |
| --- | --- | --- | --- |
| embeddinggemma-2 | `google/embeddinggemma-2` | Apache-2.0, and the card points at the [Gemma 4 license](https://ai.google.dev/gemma/docs/gemma_4_license) plus the Gemma prohibited-use policy | Text-only (`vision_config` and `audio_config` null). bf16 on GPU, fp32 on CPU. Questions use `QuestionAnswering` (`task: question answering \| query: `). Keyword queries use `SearchQuery` (`task: search result \| query: `). Documents are formatted by hand as `title: {title} ({scripture}) \| text: {text}` because `prompt_name="Document"` forces `title: none`. |
| embeddinggemma-300m | `google/embeddinggemma-300m` | Gemma license, gated weights | Skipped. Download returned 401 `GatedRepoError` with no `HF_TOKEN`. Request `Root=1-6ae49f80-3e9d80405b812b203f452157;6bd876cd-0938-4a4b-ae9b-6ebfca58c119`. |
| granite-english-r2 | `ibm-granite/granite-embedding-english-r2` | Apache-2.0 | No prefix. fp16 on GPU. CLS pooling (from the repo; "mean" was a doc error), 768-d, 8192 context. |
| arctic-embed-l | `Snowflake/snowflake-arctic-embed-l` | Apache-2.0 | v1 large, from Microsoft `intfloat/e5-large-unsupervised`. Query prefix only, via the repo prompt `query`: `Represent this sentence for searching relevant passages: `. Documents have no prefix. fp16. |
| nomic-embed-text-v2-moe | `nomic-ai/nomic-embed-text-v2-moe` | Apache-2.0 | Latest Nomic text embedder (Feb 2025, arXiv:2502.07972). Tree: `FacebookAI/xlm-roberta-base` → `nomic-ai/nomic-xlm-2048` → `nomic-embed-text-v2-moe-unsupervised` → this checkpoint. Allowed. Queries use prompt `query` = `search_query: `. Documents use prompt `passage` = `search_document: `. The repo also has a `document` prompt whose value is an empty string; that key is not used. fp16. `trust_remote_code`. 512-token ST window. Mean pooling. |

Excluded:

- `Snowflake/snowflake-arctic-embed-l-v2.0` starts from BAAI `bge-m3-retromae`. AGENTS.md excludes BGE and its fine-tunes. Arctic-Embed 2.0 paper, arXiv:2412.04506, section 2.1.
- `Snowflake/snowflake-arctic-embed-m-v2.0` starts from Alibaba `gte-multilingual-mlm-base`. Same paper, same section. GTE is excluded.
- The v1 model card says the v2 models outperform v1 and should replace it (card note dated 12/04/2024). We did not follow that, because both v2 checkpoints are built on excluded bases. v1 is the newest Arctic embedder whose base is allowed.

`nomic-ai/modernbert-embed-base` (Dec 2024) and `nomic-embed-text-v1.5` are older than v2-moe and were not substituted.

### Abstain scores

Top-1 on the 35 answerable questions vs the 5 unanswerable ones, Granite, embeddings already stored:

| mode | answerable min / p50 / max | unanswerable |
| --- | --- | --- |
| bm25 | 6.82 / 14.44 / 27.51 (all 35 hit) | 4 of 5 empty. `u-pretrib-rapture` scores 10.69, inside the answerable range |
| dense | 0.828 / 0.875 / 0.938 | 0.781–0.828. The rapture query touches the answerable minimum |
| hybrid RRF | 0.0164 / 0.0320 / 0.0328 | 0.0164 on four queries, 0.0225 on rapture |
| hybrid weighted | 0.50 / 0.88 / 1.00 | all five are 0.50 |

BM25's empty list is the only clean "nothing found" signal, and it fails on rapture: sermon 23 says some people run "mad after raptures and inward feelings," and sermon 133 says Fletcher "broke out in a rapture." Those are false friends, documented in `eval/README.md`. Weighted fusion scores every unanswerable query at 0.50 because min-max turns the best dense-only hit into 1.0, times `dense_weight` 0.5. That is not evidence of relevance. No threshold was added.

## Open issues

- Nomic's remote Bert calls `get_extended_attention_mask`, which transformers 5.22 removed. `src/preached/embed.py` installs that helper again as a (batch, 1, 1, seq) additive mask before load. The encode then succeeded. Nomic's megablocks fork was not installed. The pure-PyTorch expert loop warns and runs, which is the likely reason embed throughput is 34.5 chunks/s and CPU queries are slower than Granite. Quality still trails Granite, so the fallback did not change the recommendation.
- EmbeddingGemma 2 still constructs image and video processors when `vision_config` and `audio_config` are null. That pulls in Pillow and torchvision. fp16 is forbidden by the card (NaN). The run used bf16.
- EmbeddingGemma 300M stays skipped until someone has a Hugging Face token and has accepted the gate. Do not retry unauthenticated.
- Text chunks have null timestamps. The ingest branch can fill `start_s` and `end_s` without a schema change.
- Ten chunks exceed 150 words (none over 180). 5.7% of adjacent pairs have a gap instead of overlap.
- Quote metrics are stricter than "the right sermon." 34/35 sermon hits and 21/35 quote-complete is the Granite RRF picture. Shared scripture sentences count a hit in any sermon that prints them (`k-romans-8-16`, `k-luke-22-19`).
- `q-faith-works`, `q-salvation`, and `k-witness-of-the-spirit` are the fusion cases worth a later look. Do not retune RRF k or the weighted mix on this same set.
- VRAM baselines include Whisper. Deltas are this job's extra memory, not the whole card.
- The director opens the PR. This branch is `feat/w1-retrieval`. It is not merged to `main`.

## Dependencies and why

Direct dependencies in `pyproject.toml`, locked in `uv.lock`:

| package | locked | why |
| --- | --- | --- |
| numpy 2.5.4 | `numpy>=2.1` | Brute-force cosine. No vector database. |
| sentence-transformers 6.2.0 | `>=6.1.0` | Loads each checkpoint, applies the card's prompt names, mean-pools. EmbeddingGemma 2 needs 6.1 or newer. Pulls transformers 5.22.1. |
| torch 2.15.0+cu132 | `torch>=2.5` | GPU encode and CPU query latency for the benchmark. |
| pillow 13.0.0 | `pillow>=10` | EmbeddingGemma 2's processor imports `Gemma4ImageProcessorPil` even for a text-only load. |
| torchvision 0.29.2 | `torchvision>=0.29.2` | The same load imports `EmbeddingGemma2VideoProcessor`, which requires torchvision. The wheel did not replace the existing torch build. |
| einops 0.8.2 | `einops>=0.8.2` | Nomic's remote `modeling_hf_nomic_bert.py` imports it. |

Not added: flash-attn, megablocks, a vector database, an LLM client. BM25-only calls do not need the heavy imports until a dense or hybrid query starts.

The benchmark stack needs torch. A later Sprite build can drop it by exporting the chosen model to ONNX and running with onnxruntime. Arctic v1 and Nomic publish ONNX weights. The Granite English R2 snapshot we used does not include an ONNX file, so this branch keeps torch. Pillow, torchvision, and einops are only there so the models we measured can load. A Granite-only product does not need those three.
