# W3-POLISH: honest "nothing found", dedupe recovery, page states

> **Read section 6 (CTO fix-up) first.** It changes three things described below: low-confidence results are now shown by default under a banner (the old "Nothing strong found" page state is gone; the floor is a heuristic), a bridging neighbour is merged only if every join succeeds, and a malformed `search/abstain.toml` disables abstain instead of crashing the server. Sections 1-5 are the original report, lightly corrected where they would otherwise be wrong.

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
- `none` ("low confidence"): both fail. The passages are in the response (`abstain: true`). *Fix-up:* the page now shows them by default under a low-confidence banner that calls the check a heuristic, with a "Hide low-confidence results" toggle (originally: "Nothing strong found" and a reveal button).
- `unrated`: BM25-only search with results (no dense signal).

**Fitting the floor (1 parameter).** The floor is the highest top cosine among unanswerable questions that have no agreement, rounded up to 4 decimals. Reading: "nothing found" is said only when the evidence is no better than for a question known to have no answer. That is the lowest floor that still catches those questions, which biases the rule toward showing results. A guard checks labelled answerable questions without agreement: if the floor would hide one, the floor drops just below it. The guard never fired on this set.

Every other choice was considered and left out to keep one fitted number: RRF score, BM25 top score, top-1/top-k margin, dense/BM25 top-10 overlap. The signal dump showed the RRF top score is a function of agreement (0.0164 = one list only), the BM25 score scale depends on query length, and the margin and overlap separate nothing that agreement does not.

**Uncalibrated model** (no entry in `search/abstain.toml`, or the stored fingerprints no longer match `models.toml`): it never says "nothing found" on dense evidence. A list with no agreement is `weak`. **BM25-only** (no model, or a fallback): "nothing found" only when BM25 returns nothing; otherwise `unrated`, with no note.

**Calibration file**: `search/abstain.toml`, one table per model, holding `dense_floor`, the document-vector `fingerprint`, and a `query_fingerprint` (query prefixes and CPU dtype, which change query cosines but are not in the document fingerprint). It is written by `bench.py --abstain --write-calibration`.

**Wiring.**
- `search_with_confidence` (in `abstain.py`) is `api_search` plus the level. `GET /api/search`, `search/query.py` and `bench.py --abstain` all call it.
- The response gains `abstain` (bool) and `confidence` (`{level, calibrated, note, signals: {bm25_hits, dense_top, agreement}}`).
- `/healthz` gains `abstain_calibrated`.
- `query.py` prints the passages and ends low-confidence and weak lists with the note; `--hide-low-confidence` hides low-confidence passages (*fix-up*; originally hidden unless `--show-anyway`). Its ranking itself is unchanged.

### 1.2 Dedupe: merge instead of drop

`dedupe_adjacent` (`src/preached/search.py`) used to drop any chunk that overlapped a higher-scoring chunk from the same sermon. In `q-sin-believers` and `q-perfection`, the dropped neighbour held the quote.

New rule: **a neighbour that ranks inside the requested top k is merged into the kept passage it overlaps; neighbours below k are dropped as before.** Justification, independent of those two questions: de-dup exists so no word is shown twice, and it should hide as few words of the plain top k as it can. What is guaranteed (*fix-up*, corrected): no word is shown twice, merges never pass 300 words, and de-dup is idempotent. When a join fails (no exact boundary, other audio, or the cap), the neighbour is dropped, so its words outside the kept passage are not shown; "every word of the plain top k" holds only when every join succeeds.

- The merged hit keeps the kept chunk's score, rank and `chunk_id`. Its text, word span, `start_s` and `end_s` cover both chunks, so **playback starts at the merged passage's first word**. The 0.75 s pre-roll stays in the player, unchanged.
- Results gain `chunk_ids`: every chunk in the span, in reading order.
- A neighbour that bridges two kept passages folds them into one, only if every join succeeds (*fix-up*; before, a failed second join left two overlapping cards).
- A merge is made only when both chunks have word offsets and the same sermon, audio file and text source, and their texts share a boundary run (the chunker's sentence overlap). All 7,769 overlapping neighbour pairs in the index stitch exactly that way.
- Anything else is dropped as before: time-only or text-only spans, or a merge past **300 words**. 300 is twice the chunker's `max_words` of 150, about two minutes read aloud. Uncapped, one chained merge reached 601 words.

### 1.3 Page states (`app/static/`)

| state | what the page shows |
| --- | --- |
| loading | "Searching the sermons." in the status line, a small CSS spinner (off with `prefers-reduced-motion`), and `aria-busy="true"` on the results section |
| results | "10 passages." and the cards |
| weak | a dashed note above the cards: "These passages may not answer your question. They are the closest matches, not strong ones." |
| low confidence (abstain), *fix-up* | "10 passages." and the cards, under a dashed banner: "Low confidence: these passages may not answer your question. This is a rough automatic check (a heuristic), so read them and judge for yourself." A "Hide low-confidence results" toggle (`aria-pressed`) hides them ("Low-confidence results hidden."); the choice holds for later searches. |
| empty (zero hits) | "Nothing found in these sermons. Try other words, or a Bible verse such as Romans 8:16." |
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
# (the committed runs were renamed to 2026-10-30-w3polish-*; see section 6)
uv run --group bench search/bench.py --abstain --models granite-english-r2 embeddinggemma-2
#   add --write-calibration to refresh search/abstain.toml from that run
# API-path retrieval (dedupe), writes eval/results/YYYY-MM-DD-dedupe[-N].{json,md}
uv run --group bench search/bench.py --dedupe --models embeddinggemma-2 granite-english-r2
# Tests
uv run python -m unittest discover -s tests
# CLI and server
uv run search/query.py "What did Wesley say about vaccines?"      # passages + low-confidence note
uv run search/query.py "What did Wesley say about vaccines?" --hide-low-confidence
uv run app/server.py                                             # http://127.0.0.1:8000
```

`--abstain` needs stored vectors for each model. **EmbeddingGemma 2 vectors were not in the shared index** (the W1-CLI rebuild had dropped them). The first `--dedupe` run of this task embedded them into `/cache/index/wesley.sqlite` (104 s on the RTX 3060, fingerprint `affcd14fa7a7bfee`). Granite's vectors were untouched.

## 3. Results

### 3.1 Abstain, per model (API path: hybrid RRF, dedupe, k=10)

Run: `eval/results/2026-10-30-w3polish-abstain.{json,md}` (fix-up rerun; identical floors and levels to the original `abstain-2` run). **Cross-validation: leave-one-out over all 40 questions** (chosen before running). Each question is judged with a floor refitted on the other 39. LOO is the headline; in-sample is alongside. An abstained answerable question counts as a miss.

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

Before: `eval/results/2026-10-30-w3polish-dedupe-before` (origin/main code). After: `eval/results/2026-10-30-w3polish-dedupe` (merge with the 300-word cap and the fix-up's all-or-nothing join). Both were rerun in the fix-up; every per-question metric equals the original runs (`dedupe-2` and `dedupe-4`, now removed). The uncapped run is no longer committed; its Granite rows matched the capped run. For reference, the raw-ranker top 10 with no de-dup (`eval/results/2026-10-30.md`) is Granite hybrid 0.629 / 0.506 / 0.558 and EG2 hybrid 0.643 / 0.458 / 0.518.

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
- **Cost: longer cards**, and some of the gain is simply more text on the page. That is the honest reading of these numbers. On Granite hybrid, 74 of 400 results (18%) are merges (18 of them 3+ chunks). Words per result: median 121 → 126, mean 120 → 137, max 300 (was 601 uncapped). Other rows (40 eval questions; merged results; 3+ chunk merges; words/result median and mean, before → after; max after): Granite dense 64/400, 12, 123 → 127, 122 → 136, 297; Granite BM25 69/360, 12, 118 → 122, 116 → 133, 298; EG2 hybrid 72/400, 14, 121 → 124, 120 → 136, 300; EG2 dense 62/400, 10, 123 → 127, 122 → 135, 295; EG2 BM25 69/360, 12, 118 → 122, 116 → 133, 298. These were measured before the fix-up; section 6 has the post-fix numbers on a wider query set.

### 3.3 Tests

**149 tests, all passing** (`uv run python -m unittest discover -s tests`, 3.2 s), up from 120 on `origin/main`. New:
- `tests/test_abstain.py` (17): levels, the uncalibrated and BM25-only behaviour, floor fitting and its guard, the calibration file's fingerprint checks, and API fields on a fixture server (nothing found still returns passages, weak/strong, uncalibrated, BM25 fallback, and a merged neighbour returned as one result with `chunk_ids`).
- `tests/test_dedupe.py` (+9): merge before and after, below-limit drop, bridge fold, the no-word-lost and nothing-twice invariant, the 300-word cap, no merge without a boundary, across audio files, or without word offsets.
- `tests/test_app_js.py` (+3): `describeResponse` and `failureMessage` in Deno; the real `showResults`, `revealClosest` and `showFailure` driven through a small fake DOM that throws if `innerHTML` is set; a static check of the state elements, no inline handlers or styles, no `innerHTML`/`eval`/`new Function`/`.style.`.
- `tests/test_server.py`: schema updated for `chunk_ids`, `abstain`, `confidence`.

## 4. Open issues, risks, exclusions

- **The thresholds rest on 5 LLM-chosen negatives**, all short questions. Refit after Patrick's review with `--abstain --write-calibration`. Adding 10–20 longer, natural-language unanswerable questions (and answerable ones without title words) would test the dense floor where agreement no longer helps.
- **`u-pretrib-rapture`-style false friends** are not caught. A BM25 term match on a different sense of the word gives agreement.
- **Vocabulary mismatch** (the "gin" probe, "worry") can produce a false low-confidence rating. Since the fix-up the passages are shown by default under the banner.
- **The floor is tight.** It sits 0.015 below the lowest answerable top cosine on both models. Re-embedding, a new revision, or a prefix change invalidates the stored floor automatically (fingerprint check), and that model then runs uncalibrated (no abstain) until `--abstain --write-calibration` is rerun.
- **`compute_signals` repeats the BM25 and dense searches** instead of reusing the ranker's lists. That keeps the ranking code untouched, at a p95 cost of about 50 ms on long OR queries. Returning the two candidate lists from `Searcher.hybrid` would remove it.
- **Merged cards are longer** (mean +17 words, max 300). If the demo wants short cards, lower `MERGE_MAX_WORDS`. That trades back some of the recovered recall; re-measure with `--dedupe`.
- `search/query.py` still prints the raw ranker list (no de-dup or merge), as before. Only the confidence line is new.
- No new models. Arctic-embed-l (lineage unclear) was not calibrated and has no stored vectors in the shared index. It was used only to force the stale-vector fallback in the live check.
- `eval/timestamps.py` was not rerun; it scores the raw hybrid list, which this branch does not change.

## 5. Dependencies added

None. Standard library, numpy, and the existing Deno test path (skipped when `deno` is missing).

## 6. CTO review fix-up (PR #11, head 30444cd)

`origin/main` (with #4 YouTube import and #9 W1-HARDEN) was merged in, not rebased (`d221f82`). The only conflict was `app/server.py`: `App` and `build_app` now take both `floor` and `library`. `search/query.py` and `src/preached/search.py` merged cleanly: query.py keeps main's URL guard and control-character cleaning plus this branch's abstain output; search.py keeps main's `math.isfinite` pre-roll check. `search/bench.py` had no main-side changes. PR #10 (W3-CPU) was **not** merged when this started, so the floor is now keyed on backend+variant as well (below).

### 6.1 Item → commit → test

| item | what changed | commit | test |
| --- | --- | --- | --- |
| Must 1: malformed `search/abstain.toml` crashed startup | `load_calibrations` treats unreadable, non-UTF-8, invalid TOML and a non-table `models` as no calibration; `floor_for` rejects a non-table entry and any `dense_floor` that is not a finite number in [-1, 1] (nan, ±inf, 5.0, strings, bools). Each logs a warning and returns no floor. `build_app` also wraps the call. | `462d510` | `tests/test_abstain.py` `BadCalibrationFileTests`: for truncated TOML, `models = 5`, a non-table entry, non-UTF-8 bytes, `nan`, `5.0`, `-inf` and a string floor it asserts the warning, then starts the real server through `build_app` and checks `/healthz` (`ok`, `dense`, `abstain_calibrated: false`) and that a search returns results with `abstain: false`. A control with a valid file asserts `abstain_calibrated: true`. On the old code 8 subtests and 1 other test fail. |
| Must 2: `dedupe_adjacent` could show words twice | All or nothing: if any join of a bridging neighbour fails (usually the 300-word cap), the neighbour is dropped and the kept cards are left as they were. | `0ee14c3` | `tests/test_dedupe.py`: `test_failed_second_join_drops_the_bridge` (the CTO shape); `DedupePropertyTests`: 20,000 seeded random lists (stdlib `random`, seed 20261030; 1-3 sermons, 60-150-word windows with 25% overlap, ties, some other-audio neighbours, k 1-10). It checks that same-sermon cards never overlap in word range, `repeats_kept` holds for no pair, no word is shown twice, no merge passes 300 words, text length equals the word span, and de-dup is idempotent. The old code fails 855 of the 20,000 lists. |
| Must 2: real queries | `scripts/check_dedupe.py` (read-only): 56 queries (40 eval, 12 bench probes, `catholic spirit`, `worry`, "How do I stop worrying?", `"`) × (BM25 + Granite/EG2 dense and hybrid) = 280 lists | `527e028` | Before the fix (`d221f82`): **14 overlapping same-sermon pairs in 13 lists, 13 non-idempotent** (Granite hybrid 7 pairs in 6 lists, EG2 hybrid 3, BM25 3, EG2 dense 1, including `catholic spirit`). After: **0 pairs, 0 non-idempotent**. |
| Must 2: R@5 | Reran `bench.py --dedupe` on both models | `86ec71a` | **Granite hybrid R@5 stays 0.657** (MRR@10 0.540, nDCG@10 0.590). Every per-question metric in every row equals the pre-fix capped run (`dedupe-4`). The before run reproduces `dedupe-2` per question. |
| Must 3: default UI hid results | An abstain response is shown by default under a dashed banner: "Low confidence: these passages may not answer your question. This is a rough automatic check (a heuristic), so read them and judge for yourself." The reveal button became an inverted toggle, **"Hide low-confidence results"** (`aria-pressed`, keeps focus, and the choice holds for later searches). Zero hits say "Nothing found in these sermons." The API keeps `abstain` and `confidence`; its `none` note now uses the same low-confidence wording. `query.py`: `--hide-low-confidence` replaces `--show-anyway`. The heuristic wording was added to the docs (`abstain.py` docstring, `search/abstain.toml` header, `eval/README.md`, this report). | `39bc8e2` | `tests/test_app_js.py` (Deno): `describeResponse` low/hidden/strong/empty states; fake DOM: low results shown with the banner, toggle hides and shows again, `aria-pressed`, focus, and the choice holding across searches. `tests/test_server.py`: page has the toggle, script says "heuristic" and no longer says "Nothing strong found". Headless Chromium at 360 px against the real server (`/cache/w3-polish/browser-fixup/`): vaccines and "How do I stop worrying?" give 10 cards, the banner and the toggle; the worry chip gives weak (10 cards, weak note, no toggle); child-of-God gives strong (10 cards). The server was stopped in the same command. |
| Should: int8 vs fingerprint | PR #10 not merged, so each `search/abstain.toml` entry now carries `backend` and `variant` (torch; for torch the variant is the CPU dtype, `fp32`). `floor_for(model, backend=, variant=)` returns no floor on a mismatch or a missing key. `build_app` passes `encode.backend`/`encode.variant` when the encoder has them (PR #10's does) and defaults to torch. `bench.py --write-calibration` writes both. | `462d510` | `test_floor_is_keyed_on_backend_and_variant` (onnx/int8 and onnx/fp32 get no floor; an unkeyed entry gets none); `test_committed_file_is_per_model` checks the keys. |
| Should: docstrings | `search.py` module header and `dedupe_adjacent` docstring now say exactly what is guaranteed (no word twice, the cap, idempotence) and what is not (every word of the plain top k). Section 1.2 was corrected to match. | `0ee14c3` | the property tests above |
| Should: eval result files | Final runs committed as `eval/results/2026-10-30-w3polish-{dedupe-before,dedupe,abstain}.{json,md}`. Removed `2026-10-30-dedupe-{2,3,4}.*` and the superseded `2026-10-30-abstain{,-2}.*`. `search/abstain.toml` points at the new abstain run. `bench.py` naming is unchanged: the files were renamed after the run, the same way PR #10 renamed its runs, so `bench.py` merges cleanly with #10's `--tag`. | `86ec71a` | `test_committed_file_is_per_model` |
| Should: `/cache/w3-polish/lengths-capped.txt` | Numbers inlined in section 3.2; post-fix numbers below | this commit | n/a |
| Optional: drop `dense_top` | **Not done.** It is the one number that explains a low-confidence rating while the floor is a heuristic, and dropping it is a one-line change in `Confidence.as_dict` if wanted. | n/a | n/a |
| Should: 10-20 natural-language questions | `eval/nl-questions-w3polish.jsonl`: 18 questions **written by this agent (Claude), not human-reviewed**, mostly without title words, including "How do I stop worrying?" and "worry". Each lists the sermon(s) the agent expects. `scripts/check_nl_questions.py` prints the levels. **Not refitted** (below). | `29e2536` | n/a (probe, not a test) |

### 6.2 Natural-language probes (hybrid, k=10, current floors)

| | Granite (floor 0.8129) | EG2 (floor 0.7413) |
| --- | --- | --- |
| strong / weak / low (`none`) | 9 / 6 / 3 | 8 / 8 / 2 |
| low confidence (`none`) | stop-worrying (0.8080), worry (0.7927), anxious-about-the-future (0.8004) | stop-worrying (0.7360), worry (0.7321) |
| expected sermon in the top 10 | 15 of 18 | 14 of 18 |
| `none` although an expected sermon is in the top 10 | 1 (anxious-about-the-future) | 2 (stop-worrying, worry) |

- All three "worry" questions have no BM25 hit ("worry" is not in Wesley's text), so there is no agreement and the dense top cosine falls under the floor. This confirms the CTO's finding: the floor flags exactly the vocabulary-mismatch questions a church member is likely to ask.
- On Granite, "How do I stop worrying?" and "worry" do **not** retrieve Sermon 29 in the top 10 at all. That is a ranking miss, not only an abstain miss. EG2 has it in the top 5 for both.
- **Refit: not done.** Adding these 18 as answerable questions to the fit (the `fit_floor` guard) would lower the floors to Granite 0.7926 and EG2 0.7319. Of the 5 labelled unanswerable questions, 2 would still be caught in-sample instead of 4. That trades half the abstain recall for three probes that are now shown under the banner anyway. That is not an obvious improvement, so the floors are unchanged (`search/abstain.toml`).

### 6.3 Post-fix card lengths (`scripts/check_dedupe.py`, 56 queries)

Words per result, drop-only (origin/main) → merge (this branch): Granite hybrid median 121 → 125, mean 119 → 133, max 300, merged 95/560 (16 of them 3+ chunks). EG2 hybrid 120 → 124, 119 → 133, max 300, 100/560 (16). Granite dense 122 → 126, 121 → 133, max 297. EG2 dense 121 → 125, 120 → 132, max 295. BM25 118 → 123, 116 → 133, max 298.

### 6.4 Numbers

- Tests: `uv run python -m unittest discover -s tests`: **207 tests, OK** (12.6 s; it was 202 right after the merge). The Deno tests ran (`deno` is installed).
- `uv lock --check`: OK (75 packages). No dependency added.
- Eval: Granite hybrid (page default) R@5 0.657, MRR@10 0.540, nDCG@10 0.590; EG2 hybrid 0.671 / 0.509 / 0.561 (`2026-10-30-w3polish-dedupe.md`). Abstain floors unchanged: Granite 0.8129, EG2 0.7413. LOO: abstain precision 1.00, recall 0.60, false abstain 0/35 on both models (`2026-10-30-w3polish-abstain.md`).

### 6.5 Still open

- **After PR #10 merges, the default ONNX fp32 embedder gets no floor**, because the floors were fitted on torch fp32. Abstain then only reaches `weak` (the uncalibrated path) until an ONNX entry is calibrated. `bench.py --abstain` embeds with torch, so an ONNX calibration needs #10's backend option in the abstain path. Whether ONNX fp32 may simply reuse the torch floor is #10's parity question. This branch does not assume it.
- The floor still rests on one question in practice (`u-book-of-mormon` sets Granite's floor) and five LLM-written negatives. The CTO also reports that a bare `"` is rated strong; that was not changed. The UI now treats the rating as advice, not a gate.
- The CLI's raw-ranker listing is unchanged (no de-dup), as before.
