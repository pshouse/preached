# W3-POLISH: honest "nothing found", dedupe recovery, page states

Branch `feat/w3-polish`, started from `origin/main` at `000b89d` (PR #7 merged). **W1-HARDEN (`feat/w1-harden`) had not merged when this started, so it is not in this branch. Merge `origin/main` into this branch (merge commit, no rebase) once W1-HARDEN lands.** This branch does not touch `store.py`'s rebuild path, `play_start`, `search/query.py` `play_url`/`print_hits`, or `eval/timestamps.py`. Expect small textual conflicts only in import blocks: `search/query.py` (both add imports near the top), `src/preached/search.py` (W1-HARDEN adds `import math`, this branch changes the `dataclasses` import two lines below), and possibly `tests/test_app_js.py`.

No LLM, no reranker, no new model, no new dependency. Models used: Granite English R2 (IBM) and EmbeddingGemma 2 (Google), both already in `search/models.toml`. The default model is unchanged (`granite-english-r2`), and switching it still works the same way. The abstain threshold is stored per model, keyed to that model's fingerprints.

## Caveats first

1. **The eval labels were written by an LLM agent and are pending Patrick's human review** (`eval/README.md`, "Human review: pending"). That covers the 40 questions, the relevant passages and the grades. The five unanswerable questions were also chosen by that agent. Every threshold below is fitted to those labels. Do not describe these numbers as human-validated.
2. **Title-word overlap.** 23 of the 35 answerable questions share a content word with the title of the sermon that answers them (`eval/README.md`, "Known biases"). FTS5 indexes the title, so these questions get more BM25 hits, and so more agreement between BM25 and dense, than a typical visitor's question would. Their dense cosines are also pulled up by the shared topic word.
3. **How these could move the thresholds.**
   - Answerable questions without title words would have lower dense top cosines and less agreement. More of them would land in "weak", and some could fall to "nothing found". The fitted floors (Granite 0.8129, EG2 0.7413) sit only **0.015** below the lowest answerable top cosine in this set (Granite 0.8282, EG2 0.7564), so the measured 0% false-abstain rate is optimistic.
   - If review changes which questions count as unanswerable, the floor moves directly, because it is fitted only from the unanswerable questions that lack agreement.
   - With 5 negatives, each abstain-recall step is 0.2.
   - 0 false abstains in 35 answerable questions still allows a true rate up to about 8.6% (rule of three: 3/35).
4. **All five unanswerable questions are short.** Four have at most 4 content words, so BM25 ANDs them and returns nothing. That is what makes "no agreement" fire. A long unanswerable question becomes an OR query, gets BM25 hits and usually agreement, so it can only reach "weak" through the dense floor (see the probes below).

## 1. What was done

### 1.1 Abstain rule (hybrid, dense, BM25)

Code: `src/preached/abstain.py`. It uses two signals the ranker already has:

| signal | parameter | why |
| --- | --- | --- |
| **Agreement**: some result on the page is in both BM25's and dense's top 100 | none (100 is the depth RRF already fuses, not tuned) | If nothing shown is found by both rankers, the words of the question either do not occur, or they point somewhere other than its meaning. It is binary, the same for every model, and needs no calibration. |
| **Dense floor**: top dense cosine ≤ `floor` | one per model | Cosines are on different scales per model: unanswerable questions top out near 0.83 on Granite and 0.75 on EG2. So it must be calibrated per model. |

Levels:

- `strong`: agreement, and the top cosine is above the floor.
- `weak`: exactly one of the two signals fails. Results are shown with the note "These passages may not answer your question. They are the closest matches, not strong ones."
- `none`: both fail. The page says **"Nothing strong found in these sermons."** The closest passages are still in the response (`abstain: true`), behind a "Show the closest passages anyway" button. A wrong "nothing found" then costs the user one tap, not the answer.
- `unrated`: BM25-only search with results (no dense signal).

**Fitting the floor (1 parameter).** The floor is the highest top cosine among unanswerable questions that have no agreement, rounded up to 4 decimals. Reading: "nothing found" is said only when the evidence is no better than for a question known to have no answer. That is the lowest floor that still catches those questions, which biases the rule toward showing results. A guard checks labelled answerable questions without agreement: if the floor would hide one, the floor drops just below it. The guard never fired on this set.

Every other choice was considered and left out to keep one fitted number: RRF score, BM25 top score, top-1/top-k margin, dense/BM25 top-10 overlap. The signal dump showed the RRF top score is a function of agreement (0.0164 = one list only), the BM25 score scale depends on query length, and the margin and overlap separate nothing that agreement does not.

**Uncalibrated model** (no entry in `search/abstain.toml`, or the stored fingerprints no longer match `models.toml`): it never says "nothing found" on dense evidence. A list with no agreement is `weak`. **BM25-only** (no model, or a fallback): "nothing found" only when BM25 returns nothing; otherwise `unrated`, with no note.

**Calibration file**: `search/abstain.toml`, one table per model, holding `dense_floor`, the document-vector `fingerprint`, and a `query_fingerprint` (query prefixes and CPU dtype, which change query cosines but are not in the document fingerprint). It is written by `bench.py --abstain --write-calibration`.

**Wiring.**
- `search_with_confidence` (in `abstain.py`) is `api_search` plus the level. `GET /api/search`, `search/query.py` and `bench.py --abstain` all call it.
- The response gains `abstain` (bool) and `confidence` (`{level, calibrated, note, signals: {bm25_hits, dense_top, agreement}}`).
- `/healthz` gains `abstain_calibrated`.
- `query.py` prints "Nothing strong found…" and hides the passages unless `--show-anyway`; weak lists end with the note. Its ranking itself is unchanged.

### 1.2 Dedupe: merge instead of drop

`dedupe_adjacent` (`src/preached/search.py`) used to drop any chunk that overlapped a higher-scoring chunk from the same sermon. In `q-sin-believers` and `q-perfection`, the dropped neighbour held the quote.

New rule: **a neighbour that ranks inside the requested top k is merged into the kept passage it overlaps; neighbours below k are dropped as before.** Justification, independent of those two questions: de-dup exists so no word is shown twice. It should never hide words the plain top-k list would have shown. With the merge, every word of the plain top k is on the page, at the same rank or higher, and still none is shown twice (both properties are tested).

- The merged hit keeps the kept chunk's score, rank and `chunk_id`. Its text, word span, `start_s` and `end_s` cover both chunks, so **playback starts at the merged passage's first word**. The 0.75 s pre-roll stays in the player, unchanged.
- Results gain `chunk_ids`: every chunk in the span, in reading order.
- A neighbour that bridges two kept passages folds them into one.
- A merge is made only when both chunks have word offsets and the same sermon, audio file and text source, and their texts share a boundary run (the chunker's sentence overlap). All 7,769 overlapping neighbour pairs in the index stitch exactly that way.
- Anything else is dropped as before: time-only or text-only spans, or a merge past **300 words**. 300 is twice the chunker's `max_words` of 150, about two minutes read aloud. Uncapped, one chained merge reached 601 words.

### 1.3 Page states (`app/static/`)

| state | what the page shows |
| --- | --- |
| loading | "Searching the sermons." in the status line, a small CSS spinner (off with `prefers-reduced-motion`), and `aria-busy="true"` on the results section |
| results | "10 passages." and the cards |
| weak | a dashed note above the cards: "These passages may not answer your question. They are the closest matches, not strong ones." |
| nothing found (abstain) | "Nothing strong found in these sermons. The closest passages are weak matches. You can still look at them." and a "Show the closest passages anyway" button. Pressing it shows the cards with the weak note and moves focus to that note. |
| empty (zero hits) | "Nothing strong found in these sermons. Try other words, or a Bible verse such as Romans 8:16." |
| server error (5xx) | "The search had a problem on our side. Try again in a moment." and a "Try again" button. The server's text is not shown. |
| bad request (4xx) | "Search failed: <the server's fixed validation message>." |
| network failure | "Could not reach the search. Check your connection and try again." and "Try again" |
| unreadable body | "The search sent back something unexpected. Try again." |
| BM25 fallback | the server's `note`, as before, in its own box ("Embedding model failed to load; results are BM25 only." / "…do not match…" / "Embeddings are not loaded…") |

- All text goes in through `textContent`. There is no `innerHTML`, no inline script or style, no `eval`, and the CSP is unchanged.
- The single `role="status" aria-live="polite"` line carries every state. Buttons keep the 44 px minimum height.
- `describeResponse` and `failureMessage` are pure functions, tested in Deno.

## 2. How to run

From `/work/preached/.worktrees/feat/w3-polish`:

```bash
# Abstain eval, both models, writes eval/results/YYYY-MM-DD-abstain[-N].{json,md}
uv run --group bench search/bench.py --abstain --models granite-english-r2 embeddinggemma-2
#   add --write-calibration to refresh search/abstain.toml from that run
# API-path retrieval (dedupe), writes eval/results/YYYY-MM-DD-dedupe[-N].{json,md}
uv run --group bench search/bench.py --dedupe --models embeddinggemma-2 granite-english-r2
# Tests
uv run python -m unittest discover -s tests
# CLI and server
uv run search/query.py "What did Wesley say about vaccines?"      # nothing found
uv run search/query.py "What did Wesley say about vaccines?" --show-anyway
uv run app/server.py                                             # http://127.0.0.1:8000
```

`--abstain` needs stored vectors for each model. **EmbeddingGemma 2 vectors were not in the shared index** (the W1-CLI rebuild had dropped them). The first `--dedupe` run of this task embedded them into `/cache/index/wesley.sqlite` (104 s on the RTX 3060, fingerprint `affcd14fa7a7bfee`). Granite's vectors were untouched.

## 3. Results

### 3.1 Abstain, per model (API path: hybrid RRF, dedupe, k=10)

Run: `eval/results/2026-10-30-abstain-2.{json,md}`. **Cross-validation: leave-one-out over all 40 questions** (chosen before running). Each question is judged with a floor refitted on the other 39. LOO is the headline; in-sample is alongside. An abstained answerable question counts as a miss.

| model | eval | floor | abstain precision | abstain recall | flagged (weak or none) recall | false abstain (answerable) | weak (answerable) | R@5 → with abstain | MRR@10 → with abstain |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| granite-english-r2 | **LOO** | 0.7988–0.8129 per fold | **1.00** (3/3) | **0.60** (3/5) | 0.80 | **0/35** | 1/35 | 0.657 → **0.657** | 0.540 → **0.540** |
| granite-english-r2 | in-sample | **0.8129** | 1.00 (4/4) | 0.80 | 0.80 | 0/35 | 1/35 | 0.657 → 0.657 | 0.540 → 0.540 |
| granite-english-r2 | no floor | – | – | 0.00 | 0.80 | 0/35 | 1/35 | unchanged | unchanged |
| embeddinggemma-2 | **LOO** | 0.7367–0.7413 per fold | **1.00** (3/3) | **0.60** (3/5) | 0.80 | **0/35** | 0/35 | 0.671 → **0.671** | 0.509 → **0.509** |
| embeddinggemma-2 | in-sample | **0.7413** | 1.00 (4/4) | 0.80 | 0.80 | 0/35 | 0/35 | 0.671 → 0.671 | 0.509 → 0.509 |
| embeddinggemma-2 | no floor | – | – | 0.00 | 0.80 | 0/35 | 0/35 | unchanged | unchanged |

- **LOO recall is lower than in-sample by construction.** The floor sits at the highest unsupported negative, so when that question is held out it lands just above the refitted floor and is shown as "weak" instead (`u-book-of-mormon` on Granite, `u-vaccines` on EG2). That is the honest estimate for new unanswerable questions: the easy ones get "nothing found"; ones near the boundary get results with the weak note.
- **`u-pretrib-rapture` is never caught** (it is `strong` on both models). BM25 finds Wesley's "rapture" false friends (sermons 23 and 133), they agree with dense, and the dense top cosine is above the floor. Catching it would need a floor above the lowest answerable question (`q-worry` 0.8282 on Granite), which would hide real answers.
- **"Weak" on an answerable question:** Granite `k-matthew-6-34` (no shown passage is in both top 100s; R@5 is 1.0, and the weak note is shown above a correct result). EG2: none.
- No answerable question is hidden, so R@5 and MRR@10 are unchanged by the rule on both models.

Unlabelled probes (`PROBES` in `search/bench.py`, not used to fit, no ground truth; level with the in-sample floor):

| probe | Granite | EG2 | comment |
| --- | --- | --- | --- |
| What did Wesley say about worry? (page chip) | weak | weak | "worry" is not in the corpus, so BM25 is empty and the dense result (*On Riches*, fretfulness) is reasonable but not the Sermon on the Mount passage. The note is deserved. |
| child of God / money / Romans 8:16 (page chips) | strong | strong | |
| What did Wesley say about drinking gin? | **none** | **none** | Probably a **false "nothing found"**: Wesley condemns spirituous liquors in *The Use of Money*, but "gin" does not occur. This is the vocabulary-mismatch failure, and the reason the closest passages stay one tap away. |
| slavery / electricity | strong | strong | |
| Is it okay for Christians to play video games? | weak | weak | long query: BM25 OR finds words, the dense floor flags it |
| dinosaurs / the internet / climate change | none | none | |
| Did Wesley support the American Revolution? | none | weak | |

Live server, Granite (`app/server.py --port 8765`):

| query | level | `abstain` | top result |
| --- | --- | --- | --- |
| "How can I know that I am a child of God?" | strong (dense top 0.906, BM25 9 hits, agreement) | false | `wesley-011-c0025` merged with `c0026` |
| "What did Wesley say about vaccines?" | none | true | 10 closest passages still returned |
| "worry" chip | weak | false | |
| rapture | strong | false | (the miss above) |

Forced fallback:
- `--bm25-only`: note "Embeddings are not loaded…", vaccines → `none` with 0 results, child-of-God → `unrated` with 7 results.
- `--model arctic-embed-l` (no stored vectors): note "Stored passage vectors do not match…", `fallback: true` on `/healthz`, same levels.

Headless Chromium at 360 px against the live server showed the abstain state (status and reveal button, no cards), the weak state (dashed note and 10 cards) and the strong state (10 cards, no note). Every server was stopped after its check, and no process was left running.

Cost: `compute_signals` runs BM25 and dense again at depth 100. On Granite CPU that is p50 5.6 ms and p95 51 ms per search (n=120), on top of `api_search` p50 9.7 ms. Both exclude the ~110 ms query embedding. The p95 comes from the second BM25 run on long OR queries (see Open issues).

### 3.2 Dedupe, before → after (`bench.py --dedupe`, API path)

Before: `eval/results/2026-10-30-dedupe-2` (origin/main code). After: `eval/results/2026-10-30-dedupe-4` (merge with the 300-word cap). The `-3` run is the uncapped merge, kept for the record; its Granite rows are identical to `-4`. For reference, the raw-ranker top 10 with no de-dup (`eval/results/2026-10-30.md`) is Granite hybrid 0.629 / 0.506 / 0.558 and EG2 hybrid 0.643 / 0.458 / 0.518.

| model | mode | R@5 before → after | MRR@10 before → after | nDCG@10 before → after |
| --- | --- | --- | --- | --- |
| granite-english-r2 | **hybrid RRF (page default)** | 0.614 → **0.657** | 0.497 → **0.540** | 0.546 → **0.590** |
| granite-english-r2 | dense | 0.600 → 0.629 | 0.420 → 0.471 | 0.464 → 0.510 |
| granite-english-r2 | hybrid weighted | 0.543 → 0.600 | 0.461 → 0.515 | 0.528 → 0.576 |
| embeddinggemma-2 | hybrid RRF | 0.671 → 0.671 | 0.462 → 0.509 | 0.522 → 0.561 |
| embeddinggemma-2 | dense | 0.557 → 0.614 | 0.329 → 0.366 | 0.406 → 0.441 |
| embeddinggemma-2 | hybrid weighted | 0.586 → 0.614 | 0.453 → 0.468 | 0.506 → 0.524 |
| BM25 | bm25 | 0.429 → 0.514 | 0.314 → 0.385 | 0.372 → 0.447 |

Per question (R@5 and MRR@10, every model and mode):

- **Both lost hits are back.** Granite hybrid: `q-sin-believers` R@5 0 → 1 (MRR 1.0), `q-perfection` R@5 0 → 0.5 (MRR 0.5). Also recovered elsewhere: Granite dense/weighted and BM25 `q-sin-believers`; BM25 `q-catholic-spirit` and `q-backsliders`.
- **One loss, out of 7 model×mode rows:** EG2 **dense** `q-communion`, MRR@10 0.14 → 0 (R@5 was already 0). The quote chunk `wesley-101-c0007` was raw rank 11, outside the plain top 10. It reached rank 7 before only as a de-dup fill-in. Now its neighbour `c0008` (raw rank 5) is merged into the kept passage, so `c0007` repeats shown words and is dropped. The guarantee is relative to the plain top k, and that holds. No loss in any hybrid row or on Granite.
- **Cost: longer cards**, and some of the gain is simply more text on the page. That is the honest reading of these numbers. On Granite hybrid, 74 of 400 results (18%) are merges (18 of them 3+ chunks). Words per result: median 121 → 126, mean 120 → 137, max 300 (was 601 uncapped). Other modes and EG2 are similar (`/cache/w3-polish/lengths-capped.txt`).

### 3.3 Tests

**149 tests, all passing** (`uv run python -m unittest discover -s tests`, 3.2 s), up from 120 on `origin/main`. New:
- `tests/test_abstain.py` (17): levels, the uncalibrated and BM25-only behaviour, floor fitting and its guard, the calibration file's fingerprint checks, and API fields on a fixture server (nothing found still returns passages, weak/strong, uncalibrated, BM25 fallback, and a merged neighbour returned as one result with `chunk_ids`).
- `tests/test_dedupe.py` (+9): merge before and after, below-limit drop, bridge fold, the no-word-lost and nothing-twice invariant, the 300-word cap, no merge without a boundary, across audio files, or without word offsets.
- `tests/test_app_js.py` (+3): `describeResponse` and `failureMessage` in Deno; the real `showResults`, `revealClosest` and `showFailure` driven through a small fake DOM that throws if `innerHTML` is set; a static check of the state elements, no inline handlers or styles, no `innerHTML`/`eval`/`new Function`/`.style.`.
- `tests/test_server.py`: schema updated for `chunk_ids`, `abstain`, `confidence`.

## 4. Open issues, risks, exclusions

- **The thresholds rest on 5 LLM-chosen negatives**, all short questions. Refit after Patrick's review with `--abstain --write-calibration`. Adding 10–20 longer, natural-language unanswerable questions (and answerable ones without title words) would test the dense floor where agreement no longer helps.
- **`u-pretrib-rapture`-style false friends** are not caught. A BM25 term match on a different sense of the word gives agreement.
- **Vocabulary mismatch** (the "gin" probe) can produce a false "nothing found". It is mitigated by keeping the closest passages one tap away.
- **The floor is tight.** It sits 0.015 below the lowest answerable top cosine on both models. Re-embedding, a new revision, or a prefix change invalidates the stored floor automatically (fingerprint check), and that model then runs uncalibrated (no abstain) until `--abstain --write-calibration` is rerun.
- **`compute_signals` repeats the BM25 and dense searches** instead of reusing the ranker's lists. That keeps the ranking code untouched, at a p95 cost of about 50 ms on long OR queries. Returning the two candidate lists from `Searcher.hybrid` would remove it.
- **Merged cards are longer** (mean +17 words, max 300). If the demo wants short cards, lower `MERGE_MAX_WORDS`. That trades back some of the recovered recall; re-measure with `--dedupe`.
- `search/query.py` still prints the raw ranker list (no de-dup or merge), as before. Only the confidence line is new.
- No new models. Arctic-embed-l (lineage unclear) was not calibrated and has no stored vectors in the shared index. It was used only to force the stale-vector fallback in the live check.
- `eval/timestamps.py` was not rerun; it scores the raw hybrid list, which this branch does not change.

## 5. Dependencies added

None. Standard library, numpy, and the existing Deno test path (skipped when `deno` is missing).
