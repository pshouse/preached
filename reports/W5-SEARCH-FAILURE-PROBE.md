# W5-SEARCH-FAILURE-PROBE: where search quality and the confidence banner break down

Branch `qa/w5-search-failure-probe`, from origin/main **`d8a096693f82e8b00933451cb1060a71efafd80a`** (it had not moved). Date: 2026-10-31. Agent: Claude (Sonnet 5.5). **Report only: no code, index, eval set, label, calibration or doc was changed.** The only file in this PR is this report.

## Bottom line

30 queries (6 per group) plus 11 follow-up control queries, run in-process on main's code: Granite English R2 on the ONNX fp32 query embedder (the demo default), the Wesley index, the shipped floor 0.8129 from `search/abstain.toml`, `k = 10`, through `abstain.search_with_confidence` (the call `GET /api/search` makes).

1. **The banner can only say "strong" when BM25 found something, and for short natural questions it often finds nothing.** `fts.to_fts_query` ANDs a query of 4 or fewer content terms, so "How do I stop worrying about the future?" matches no chunk. 11 of the 30 queries got **0 BM25 rows**, including 7 of the 12 plain-English and typo questions. Those can never be `strong` and are at best `weak`, even when dense returns an excellent passage (a1, a2, b1, b2, b4). Hybrid then silently equals dense. The banner's "weak" therefore mostly says "short query", not "poor answer". (W3-RETRIEVAL-DIAG saw this on 2 blind items and called the AND rule documented behaviour; this probe shows how common it is on everyday phrasing.)
2. **"Strong" is close to free on longer queries, so it is wrong when it matters.** Every one of the 6 long multi-concept queries was `strong` because an OR query always returns 100 BM25 rows and "agreement" (any shown passage in both top-100 lists) is then nearly automatic. Two strong banners sit on bad results (**c3** theater/entertainment, **e6** "road to hell is paved with good intentions"), two more on partly-right ones (a3, a6), and an extra control (x10, "Why does God allow pain?") is strong with a #1 about self-denial. 11 of 15 strong banners were good. Of the 6 out-of-domain queries, **none was strong and 4 abstained**, but **2 did not abstain** (d1 recipe, d2 Super Bowl) and only because junk BM25 OR-matches ("good", "year", "last") fabricated agreement while dense was below the floor.
3. **For quotes, hybrid is sometimes worse than BM25 alone.** On the exact sentence "Nothing comes by chance; that is a silly word..." BM25 ranks the one chunk that holds it #1 by a wide margin (31.7 vs 16.4); hybrid puts it #3 behind two unrelated passages, and the banner is `weak` on an exact quote. On the proverb in e6, BM25 has the passage (Almost Christian, "Hell is paved, saith one, with good intentions") at #1 and hybrid has it nowhere in the top 10, with a `strong` banner.

## Hit rates

Judgments are mine alone, one LLM reader, from reading each hybrid top 3 against the query. "Good" means the top 3 hold a passage that answers the question; "partly" means a right-neighbourhood or only one weak hit or the answer at #3 behind wrong #1 and #2; "bad" means no answering passage in the top 3. For (e) ground truth is mechanical: the chunk(s) whose text contains the quoted words.

| group | good | partly | bad | notes |
| --- | --- | --- | --- | --- |
| (a) plain modern English | 3 | 3 | 0 | strong 3, weak 3; banner never wrong-direction here, but a3 and a6 are strong with weak results |
| (b) typos and misspellings | 4 | 1 | 1 | 5 of 6 have 0 BM25 rows; dense carries them. b5 bad, b6 a **false abstain** (`none` on an answerable question) |
| (c) multi-concept | 5 | 0 | 1 | all 6 strong; c3 is bad |
| (d) out-of-domain (should abstain or be low) | 4 abstained (`none`) | 2 `weak` | 0 `strong` | d1 recipe and d2 Super Bowl did **not** abstain |
| (e) exact and near quotes | 4 | 1 | 1 | sentence-containing chunk is hybrid #1 on 2 of 5 verbatim quotes, in top 3 on 5 of 5; e6 (near-quote) 0 of 1 |

By banner on all 30 hybrid runs: strong 15 (11 good, 2 partly, 2 bad), weak 10 (5 good, 2 partly, 3 bad, of which d1 and d2 are the out-of-domain misses), none 5 (4 correct abstentions, 1 false abstain).

## Cases the most important to read

### Banner says strong, results are bad or partly bad
- **c3** "Should Christians go to the theater, and does entertainment lead us away from God?": strong (bm25_hits 100, dense_top 0.8384, agreement true). Wesley's "On Public Diversions" is the answer (hybrid rank 9; absent from BM25 and dense top 10). Top 3: a word-match on "entertain his presence", "a life of religion is misery", Almost Christian. **Bad.**
- **e6** "the road to hell is paved with good intentions": strong (0.8307, agreement true). The passage exists (`002-c0037`, BM25 #1) and is missing from the hybrid and dense top 10. **Bad.**
- **a6** "Why does God allow suffering?": strong. Top 2 are about the pleasure of doing good; the answering passage is #3. **Partly.** Dense #1 was right.
- **a3** "How can I pray when God feels far away?": strong (0.859); nothing speaks to the distance. **Partly.**
- **x10** control "Why does God allow pain?": strong; hybrid #1 is Self-denial, dense finds "Heaviness through Manifold Temptations" and "God's Love to Fallen Man". Not graded in the 30; listed for completeness.
- Earlier reports already show the same failure on labelled data: `u-pretrib-rapture`, `p-004` and `p-023` come out `strong` under the shipped floor (W3-CONFIRMATORY open items; EVAL-GRADE "Abstain floor recheck").

### Out-of-domain queries that did not abstain
- **d1** recipe for chocolate chip cookies: `weak`, not `none`. dense_top 0.7827 is below the floor 0.8129. Agreement came from 100 BM25 OR-matches on "good", "recipe", etc.
- **d2** Super Bowl: `weak`. dense_top 0.7548, below the floor; again BM25 OR-matches.
- d3 to d6 (bicycle tyre, capital of Australia, Bitcoin vs index funds, vaccine): `none`. The cosines were 0.743 to 0.762, between 0.05 and 0.07 below the floor. d5 shows why the banner matters: its top passages are about riches and "save all you can, give all you can", and read like financial advice if the low-confidence banner is hidden.
- In all of them the passages are still shown by default under the banner, per W3-POLISH.

### Where hybrid is worse than BM25 or dense alone
| query | hybrid | better single ranker |
| --- | --- | --- |
| a5 raise my children | `094-c0030` good, then `053-c0061` ("children of wrath", false friend) | dense: top 4 are all family/education |
| a6 why does God allow suffering | wrong, wrong, right | dense: right at #1 |
| e2 exact sentence | `095-c0030` at #3 | BM25: #1, score 31.7 vs 16.4 |
| e6 proverb | not in top 10 | BM25: #1 |
| x5 "temptation and how to resist it" (clean spelling) | #1 Christian Perfection; the sermon "On Temptation" (`082`) is **not in the top 3** | BM25 #1 is `082-c0029`, dense #1 is `082-c0022`; both rank the sermon first but on different chunks, so RRF drops it |
| x10 why does God allow pain | #1 Self-denial | dense: Heaviness through Manifold Temptations, God's Love to Fallen Man |
| e3 gain/save/give | #2 | dense: #1 (hybrid still in top 3) |

Hybrid is better than both alone in no case I could identify in this set, and equal in most (a1, a2, b1 to b6 are dense-only because BM25 is empty). This is 30 queries and one reader: it is a list of failure cases, not a rate. For the aggregate evidence on labelled questions, see W3-RETRIEVAL-DIAG (hybrid worse than dense on 8 of 28 blind questions, better on 0) and W3-CONFIRMATORY (no accuracy claim supported; the fresh blind set does not exist).

### Typos (group b)
The typo itself rarely changes the result, because BM25 had no rows for the clean spelling either (x1, x4, x6). The exceptions: **b5** "temtation" is read by dense as "tempers" (bad), where the clean spelling finds the sermon "On Temptation" in BM25 and dense (x5); and **b6** "hwo do i know im saved" is `none` (dense_top 0.7976) while the clean "how do i know i'm saved" is `weak` (0.8313; x6). So one typo flipped a `weak` into an abstain. Controls are in the table at the end.

## Per-query results

Every query's top 3 in hybrid mode, then BM25 and dense modes. Scores differ by mode and are not comparable: hybrid is an RRF score (about 0.0164 for a dense-only list, up to about 0.033 when both rankers agree), BM25 is FTS5's bm25 negated, dense is a cosine. Chunk ids drop the `wesley-` prefix. Confidence is the level `search_with_confidence` returns for that mode (BM25-only is `unrated` with results and `none` with zero hits).

### (a) Plain modern-English questions

**a1** `How do I stop worrying about the future?`  
- Hybrid top 3 (chunk, sermon, RRF score): `029-c0064` Upon our Lord's Sermon on the Mount, Discourse 9 (0.0164); `050-c0034` The Use of Money (0.0161); `054-c0036` On Eternity (0.0156)  
- Confidence: **weak** (bm25_hits 0, dense_top 0.8229, agreement false; floor 0.8129)  
- Judgment: **good**. #1 is the "take no thought for the morrow" passage; #2 (Use of Money, "never leave anything till tomorrow") is a false friend.  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level weak): `029-c0064` (0.8229); `050-c0034` (0.818); `054-c0036` (0.8118)  
- Hybrid vs single: BM25 0 hits, so hybrid = dense order.

**a2** `What does the Bible say about forgiving someone who hurt me?`  
- Hybrid top 3 (chunk, sermon, RRF score): `026-c0072` Upon our Lord's Sermon on the Mount, Discourse 6 (0.0164); `005-c0030` Justification By Faith (0.0161); `023-c0082` Upon our Lord's Sermon on the Mount, Discourse 3 (0.0156)  
- Confidence: **weak** (bm25_hits 0, dense_top 0.9015, agreement false; floor 0.8129)  
- Judgment: **good**. #1 and #3 are the forgive-as-we-are-forgiven passages.  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level weak): `026-c0072` (0.9015); `005-c0030` (0.8734); `023-c0082` (0.864)  
- Hybrid vs single: BM25 0 hits, so hybrid = dense order.

**a3** `How can I pray when God feels far away?`  
- Hybrid top 3 (chunk, sermon, RRF score): `016-c0080` The Means of Grace (0.0302); `041-c0047` Wandering Thoughts (0.0267); `077-c0055` Spiritual Worship (0.0231)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8590, agreement true; floor 0.8129)  
- Judgment: **partly**. #1 (Means of Grace, trouble and heaviness) is near; #2 is about praying for deliverance from wandering thoughts; #3 is a hymn-like close. Nothing speaks to "God feels far".  
- BM25 top 3 (BM25 score; level unrated): `008-c0026` (9.5258); `041-c0047` (9.4766); `028-c0058` (9.1307)  
- Dense top 3 (cosine; level strong): `026-c0027` (0.859); `016-c0080` (0.8519); `026-c0019` (0.8446)  
- Hybrid vs single: No clear difference; BM25 top 3 are off-topic too.

**a4** `Is it wrong to want to be rich?`  
- Hybrid top 3 (chunk, sermon, RRF score): `028-c0083` Upon our Lord's Sermon on the Mount, Discourse 8 (0.0273); `087-c0041` The Danger of Riches (0.0164); `087-c0036` The Danger of Riches (0.0161)  
- Confidence: **strong** (bm25_hits 1, dense_top 0.9089, agreement true; floor 0.8129)  
- Judgment: **good**. #1 and #2 are about riches and the heart, the right sermon family.  
- BM25 top 3 (BM25 score; level unrated): `028-c0083` (10.3076)  
- Dense top 3 (cosine; level weak): `087-c0041` (0.9089); `087-c0036` (0.8999); `028-c0044` (0.8777)  
- Hybrid vs single: BM25 had a single hit and it became #1; dense alone is also fine.

**a5** `How should I raise my children?`  
- Hybrid top 3 (chunk, sermon, RRF score): `094-c0030` On Family Religion (0.0164); `053-c0061` On the Death of the Rev. Mr. George Whitefield (0.0164); `095-c0057` On the Education of Children (0.0161)  
- Confidence: **weak** (bm25_hits 22, dense_top 0.8505, agreement false; floor 0.8129)  
- Judgment: **partly**. #1 (Family Religion) is right; #2 is "children of wrath" (false friend); #3 is the mother-in-law passage.  
- BM25 top 3 (BM25 score; level unrated): `053-c0061` (8.5727); `068-c0057` (8.2967); `067-c0018` (6.7631)  
- Dense top 3 (cosine; level weak): `094-c0030` (0.8505); `095-c0057` (0.8388); `095-c0034` (0.8373)  
- Hybrid vs single: **Hybrid worse than dense**: dense top 4 are all Family Religion / Education of Children passages; BM25 pulled in the "children of wrath" passage.

**a6** `Why does God allow suffering?`  
- Hybrid top 3 (chunk, sermon, RRF score): `084-c0039` The Important Question (0.032); `084-c0031` The Important Question (0.0243); `059-c0025` God's Love to Fallen Man (0.0164)  
- Confidence: **strong** (bm25_hits 7, dense_top 0.8914, agreement true; floor 0.8129)  
- Judgment: **partly**. #1 and #2 (The Important Question) are about the pleasure of doing good; only #3 (God's Love to Fallen Man, good out of pain) answers.  
- BM25 top 3 (BM25 score; level unrated): `084-c0039` (8.2658); `020-c0063` (7.6348); `084-c0031` (7.2382)  
- Dense top 3 (cosine; level strong): `059-c0025` (0.8914); `141-c0066` (0.8802); `084-c0039` (0.8786)  
- Hybrid vs single: **Hybrid worse than dense**: dense #1 is the right passage. BM25 top 1 and 3 are the same wrong ones.


### (b) Typos and misspellings

**b1** `how do i get rid of anger and bitternes`  
- Hybrid top 3 (chunk, sermon, RRF score): `095-c0022` On the Education of Children (0.0164); `139-c0029` On Love (0.0161); `040-c0097` Christian Perfection (0.0159)  
- Confidence: **weak** (bm25_hits 0, dense_top 0.8385, agreement false; floor 0.8129)  
- Judgment: **good**. anger passages (On the Education of Children on anger, On Love, Christian Perfection).  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level weak): `095-c0022` (0.8385); `139-c0029` (0.826); `040-c0097` (0.8119)  
- Hybrid vs single: Typo is harmless here: BM25 returns 0 for the clean spelling too (x1). Hybrid = dense.

**b2** `what is sanctifacation`  
- Hybrid top 3 (chunk, sermon, RRF score): `086-c0069` A Call to Backsliders (0.0164); `083-c0015` On Patience (0.0161); `083-c0038` On Patience (0.0159)  
- Confidence: **weak** (bm25_hits 0, dense_top 0.8723, agreement false; floor 0.8129)  
- Judgment: **good**. #2 and #3 (On Patience) discuss sanctification directly; #1 is about persons "sanctified throughout".  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level weak): `086-c0069` (0.8723); `083-c0015` (0.8722); `083-c0038` (0.8702)  
- Hybrid vs single: Typo costs BM25 nothing it would have had; with the clean spelling (x2) hybrid #1 is On God's Vineyard. Hybrid = dense here.

**b3** `forgivness of sins`  
- Hybrid top 3 (chunk, sermon, RRF score): `026-c0072` Upon our Lord's Sermon on the Mount, Discourse 6 (0.0313); `026-c0070` Upon our Lord's Sermon on the Mount, Discourse 6 (0.0302); `138-c0022` On Grieving the Holy Spirit (0.026)  
- Confidence: **strong** (bm25_hits 90, dense_top 0.8975, agreement true; floor 0.8129)  
- Judgment: **good**. #1 and #2 are the forgive-us-our-debts passages.  
- BM25 top 3 (BM25 score; level unrated): `026-c0072` (9.9113); `026-c0069` (8.8196); `040-c0079` (8.596)  
- Dense top 3 (cosine; level strong): `021-c0066` (0.8975); `006-c0060` (0.8973); `026-c0070` (0.8936)  
- Hybrid vs single: Fine in all three modes.

**b4** `is it ok to be rich and wealthey`  
- Hybrid top 3 (chunk, sermon, RRF score): `126-c0003` On the Danger of Increasing Riches (0.0164); `131-c0017` The Late Work of God in North America (0.0161); `108-c0028` On Riches (0.0156)  
- Confidence: **weak** (bm25_hits 0, dense_top 0.8467, agreement false; floor 0.8129)  
- Judgment: **good**. #1 is the introduction to the riches sermon (On the Danger of Increasing Riches); #3 is On Riches.  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level weak): `126-c0003` (0.8467); `131-c0017` (0.8381); `108-c0028` (0.8306)  
- Hybrid vs single: BM25 0 hits (typo and AND rule). Hybrid = dense.

**b5** `temtation and how to resist it`  
- Hybrid top 3 (chunk, sermon, RRF score): `139-c0029` On Love (0.0164); `069-c0030` The Imperfection of Human Knowledge (0.0161); `022-c0008` Upon our Lord's Sermon on the Mount, Discourse 2 (0.0159)  
- Confidence: **weak** (bm25_hits 0, dense_top 0.8253, agreement false; floor 0.8129)  
- Judgment: **bad**. "temtation" is read as "tempers": results are about tempers and dispositions, not temptation.  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level weak): `139-c0029` (0.8253); `069-c0030` (0.8234); `022-c0008` (0.8208)  
- Hybrid vs single: BM25 0 hits. Dense misreads the typo. With the clean spelling (x5) the sermon "On Temptation" exists and BM25 and dense both rank it #1, but hybrid does not (see x5).

**b6** `hwo do i know im saved`  
- Hybrid top 3 (chunk, sermon, RRF score): `043-c0004` The Scripture Way of Salvation (0.0164); `058-c0031` On Predestination (0.0161); `065-c0013` The Duty of Reproving our Neighbour (0.0159)  
- Confidence: **none** (bm25_hits 0, dense_top 0.7976, agreement false; floor 0.8129)  
- Judgment: **partly**. #1 (Scripture Way of Salvation) is the right neighbourhood but not the assurance passages; #2 and #3 are off.  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level none): `043-c0004` (0.7976); `058-c0031` (0.7955); `065-c0013` (0.7945)  
- Hybrid vs single: **False abstain**: level none on an answerable question. The clean wording "how do i know i'm saved" (x6) is weak, not none. BM25 0 hits.


### (c) Multi-concept questions

**c1** `How do I forgive my father and also stop feeling guilty about my own anger?`  
- Hybrid top 3 (chunk, sermon, RRF score): `026-c0072` Upon our Lord's Sermon on the Mount, Discourse 6 (0.0328); `026-c0003` Upon our Lord's Sermon on the Mount, Discourse 6 (0.0287); `040-c0097` Christian Perfection (0.0248)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8536, agreement true; floor 0.8129)  
- Judgment: **good**. #1 and #2 are forgiveness passages, #3 is on anger. Does not address "my father" or guilt, which the text does not need.  
- BM25 top 3 (BM25 score; level unrated): `026-c0072` (19.2359); `026-c0003` (12.941); `034-c0055` (11.9413)  
- Dense top 3 (cosine; level strong): `026-c0072` (0.8536); `014-c0067` (0.8279); `005-c0030` (0.8277)  
- Hybrid vs single: BM25 and hybrid share #1 and #2.

**c2** `Can a rich person be saved and how should he use his money to help the poor?`  
- Hybrid top 3 (chunk, sermon, RRF score): `126-c0005` On the Danger of Increasing Riches (0.0325); `108-c0002` On Riches (0.0292); `126-c0016` On the Danger of Increasing Riches (0.029)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8838, agreement true; floor 0.8129)  
- Judgment: **good**. On the Danger of Increasing Riches and On Riches: how a rich person stands and what to do with money.  
- BM25 top 3 (BM25 score; level unrated): `126-c0004` (16.3151); `126-c0016` (12.8835); `126-c0034` (12.8768)  
- Dense top 3 (cosine; level strong): `126-c0005` (0.8838); `126-c0043` (0.87); `068-c0035` (0.8662)  
- Hybrid vs single: Fine in all three modes.

**c3** `Should Christians go to the theater, and does entertainment lead us away from God?`  
- Hybrid top 3 (chunk, sermon, RRF score): `138-c0001` On Grieving the Holy Spirit (0.0323); `084-c0027` The Important Question (0.0265); `002-c0000` The Almost Christian (0.0265)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8384, agreement true; floor 0.8129)  
- Judgment: **bad**. Wesley's sermon "On Public Diversions" (140) is the answer and is not in the hybrid top 3 (it is #9). Top 3 are "entertain his presence" (a word-match on "entertain"), a passage about religion being misery, and Almost Christian.  
- BM25 top 3 (BM25 score; level unrated): `138-c0001` (10.7954); `052-c0022` (9.6564); `034-c0071` (9.3257)  
- Dense top 3 (cosine; level strong): `037-c0023` (0.8384); `037-c0066` (0.8373); `138-c0001` (0.8367)  
- Hybrid vs single: **All three modes miss it** (BM25 and dense top 10 hold no 140 chunk). Banner **strong**.

**c4** `What is the difference between faith and works, and can a believer fall away from grace?`  
- Hybrid top 3 (chunk, sermon, RRF score): `001-c0034` Salvation by Faith (0.0284); `006-c0023` The Righteousness of Faith (0.0273); `043-c0061` The Scripture Way of Salvation (0.0257)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.9100, agreement true; floor 0.8129)  
- Judgment: **good**. Salvation by Faith, Righteousness of Faith, Scripture Way of Salvation answer the faith/works half; nothing in the top 3 speaks to falling from grace.  
- BM25 top 3 (BM25 score; level unrated): `006-c0023` (14.5496); `020-c0009` (13.7211); `035-c0031` (13.2977)  
- Dense top 3 (cosine; level strong): `027-c0003` (0.91); `085-c0037` (0.8845); `033-c0045` (0.8841)  
- Hybrid vs single: Dense top 3 are different passages (`027-c0003`, `085-c0037`, `033-c0045`), not read closely.

**c5** `How do I keep from gossiping and what should I do when someone speaks evil of me?`  
- Hybrid top 3 (chunk, sermon, RRF score): `049-c0002` The Cure of Evil-speaking (0.0309); `049-c0048` The Cure of Evil-speaking (0.0303); `049-c0026` The Cure of Evil-speaking (0.0292)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8509, agreement true; floor 0.8129)  
- Judgment: **good**. All three are The Cure of Evil-speaking.  
- BM25 top 3 (BM25 score; level unrated): `049-c0048` (9.6382); `140-c0011` (8.6257); `078-c0002` (7.9778)  
- Dense top 3 (cosine; level strong): `049-c0002` (0.8509); `049-c0011` (0.8362); `049-c0008` (0.8324)  
- Hybrid vs single: Fine in all three modes.

**c6** `Does God predestine some people to hell, and how can I be sure I am one of the elect?`  
- Hybrid top 3 (chunk, sermon, RRF score): `128-c0005` Free Grace (0.0328); `128-c0039` Free Grace (0.0304); `128-c0056` Free Grace (0.0299)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8884, agreement true; floor 0.8129)  
- Judgment: **good**. All three are Free Grace, Wesley's sermon against predestination.  
- BM25 top 3 (BM25 score; level unrated): `128-c0005` (16.9135); `128-c0039` (14.7379); `128-c0014` (14.2885)  
- Dense top 3 (cosine; level strong): `128-c0005` (0.8884); `128-c0033` (0.8669); `032-c0004` (0.8503)  
- Hybrid vs single: Fine in all three modes.


### (d) Out-of-domain (should abstain or show low confidence)

**d1** `What is a good recipe for chocolate chip cookies?`  
- Hybrid top 3 (chunk, sermon, RRF score): `002-c0037` The Almost Christian (0.027); `005-c0036` Justification By Faith (0.0231); `089-c0035` The More Excellent Way (0.0224)  
- Confidence: **weak** (bm25_hits 100, dense_top 0.7827, agreement true; floor 0.8129)  
- Judgment: **bad**. Should have abstained. Passages are generic ("Almost Christian", "Justification") apart from #3, which mentions plain wholesome food.  
- BM25 top 3 (BM25 score; level unrated): `005-c0036` (2.4487); `092-c0015` (2.4345); `014-c0044` (2.4109)  
- Dense top 3 (cosine; level weak): `089-c0034` (0.7827); `095-c0053` (0.7522); `098-c0015` (0.741)  
- Hybrid vs single: Dense top 0.783 is below the floor 0.8129; agreement is satisfied only by BM25 OR-matches on "good", "recipe" etc. That alone turns none into weak.

**d2** `Who won the Super Bowl last year?`  
- Hybrid top 3 (chunk, sermon, RRF score): `139-c0037` On Love (0.0233); `063-c0029` The General Spread of the Gospel (0.02); `084-c0065` The Important Question (0.0169)  
- Confidence: **weak** (bm25_hits 100, dense_top 0.7548, agreement true; floor 0.8129)  
- Judgment: **bad**. Should have abstained. Results are about the last words of a dying saint, the spread of the revival, "threescore years".  
- BM25 top 3 (BM25 score; level unrated): `053-c0082` (9.8491); `112-c0012` (9.0798); `096-c0022` (8.9673)  
- Dense top 3 (cosine; level weak): `001-c0052` (0.7548); `102-c0048` (0.7357); `059-c0037` (0.7326)  
- Hybrid vs single: Dense top 0.755 is below the floor; spurious BM25 OR-match ("won", "year", "last") creates agreement, so weak, not none.

**d3** `How do I fix a flat tire on my bicycle?`  
- Hybrid top 3 (chunk, sermon, RRF score): `131-c0002` The Late Work of God in North America (0.0164); `057-c0032` On the Fall of Man (0.0161); `078-c0040` Spiritual Idolatry (0.0154)  
- Confidence: **none** (bm25_hits 0, dense_top 0.7483, agreement false; floor 0.8129)  
- Judgment: **good**. Abstains (none). Results are irrelevant, correctly banner-flagged.  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level none): `131-c0002` (0.7483); `057-c0032` (0.7407); `078-c0040` (0.7306)  
- Hybrid vs single: All three modes abstain.

**d4** `What is the capital of Australia?`  
- Hybrid top 3 (chunk, sermon, RRF score): `085-c0003` On Working out our own Salvation (0.0164); `004-c0059` Scriptural Christianity (0.0159); `103-c0006` What is Man? (0.0156)  
- Confidence: **none** (bm25_hits 0, dense_top 0.7433, agreement false; floor 0.8129)  
- Judgment: **good**. Abstains (none).  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level none): `085-c0003` (0.7433); `004-c0059` (0.7403); `103-c0006` (0.7368)  
- Hybrid vs single: All three modes abstain.

**d5** `Should I buy Bitcoin or index funds?`  
- Hybrid top 3 (chunk, sermon, RRF score): `087-c0055` The Danger of Riches (0.0164); `126-c0000` On the Danger of Increasing Riches (0.0161); `094-c0050` On Family Religion (0.0159)  
- Confidence: **none** (bm25_hits 0, dense_top 0.7544, agreement false; floor 0.8129)  
- Judgment: **good**. Abstains (none), though the top passages are about riches and "save all you can", which a reader might take as financial advice. The low-confidence banner is what protects here.  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level none): `087-c0055` (0.7544); `126-c0000` (0.7457); `094-c0050` (0.744)  
- Hybrid vs single: All three modes abstain.

**d6** `How does a vaccine work?`  
- Hybrid top 3 (chunk, sermon, RRF score): `057-c0030` On the Fall of Man (0.0164); `083-c0039` On Patience (0.0161); `069-c0034` The Imperfection of Human Knowledge (0.0159)  
- Confidence: **none** (bm25_hits 0, dense_top 0.7620, agreement false; floor 0.8129)  
- Judgment: **good**. Abstains (none).  
- BM25 top 3 (BM25 score; level none): *no hits*  
- Dense top 3 (cosine; level none): `057-c0030` (0.762); `083-c0039` (0.7616); `069-c0034` (0.7567)  
- Hybrid vs single: All three modes abstain.


### (e) Exact quotes and near-quotes

**e1** `Is thine heart right, as my heart is with thy heart?`  
- Hybrid top 3 (chunk, sermon, RRF score): `039-c0027` Catholic Spirit (0.032); `039-c0007` Catholic Spirit (0.032); `039-c0043` Catholic Spirit (0.0315)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.9144, agreement true; floor 0.8129)  
- Judgment: **good**. Top 2 and #4 contain the quoted sentence (Catholic Spirit); #1 is a neighbour that shares its words.  
- BM25 top 3 (BM25 score; level unrated): `039-c0007` (22.8619); `039-c0000` (19.949); `039-c0027` (18.4742)  
- Dense top 3 (cosine; level strong): `039-c0027` (0.9144); `039-c0043` (0.8883); `039-c0008` (0.8852)  
- Hybrid vs single: All good. BM25 ranks 1,2,3; dense 1,3,10.

**e2** `Nothing comes by chance; that is a silly word; there is no such thing as chance.`  
- Hybrid top 3 (chunk, sermon, RRF score): `081-c0053` In What Sense we are to Leave the World (0.0325); `069-c0035` The Imperfection of Human Knowledge (0.0292); `095-c0030` On the Education of Children (0.0283)  
- Confidence: **weak** (bm25_hits 100, dense_top 0.8044, agreement true; floor 0.8129)  
- Judgment: **partly**. The only chunk containing the sentence (095-c0030) is hybrid #3. #1 (a Journal-style passage about a plan and visitors) and #2 have nothing to do with chance.  
- BM25 top 3 (BM25 score; level unrated): `095-c0030` (31.6992); `081-c0053` (16.3727); `015-c0034` (15.9636)  
- Dense top 3 (cosine; level weak): `081-c0053` (0.8044); `079-c0001` (0.804); `037-c0049` (0.8032)  
- Hybrid vs single: **Hybrid worse than BM25**: BM25 has the true chunk at #1 with a score of 31.7 against 16.4 for #2. Dense never finds it. Banner **weak** on an exact quote.

**e3** `Gain all you can, save all you can, give all you can.`  
- Hybrid top 3 (chunk, sermon, RRF score): `087-c0045` The Danger of Riches (0.0318); `050-c0061` The Use of Money (0.0315); `087-c0049` The Danger of Riches (0.0313)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8675, agreement true; floor 0.8129)  
- Judgment: **good**. #2 holds the sentence; #1 and #3 are the Danger of Riches sermon repeating the same teaching.  
- BM25 top 3 (BM25 score; level unrated): `087-c0045` (11.2389); `087-c0049` (9.7809); `116-c0047` (9.6655)  
- Dense top 3 (cosine; level strong): `050-c0061` (0.8675); `126-c0039` (0.8619); `050-c0012` (0.8593)  
- Hybrid vs single: Dense has it at #1, BM25 at #5, hybrid at #2.

**e4** `if they are elected or not elected then your advice and reproof is as useless as our preaching`  
- Hybrid top 3 (chunk, sermon, RRF score): `128-c0033` Free Grace (0.0328); `128-c0015` Free Grace (0.0318); `128-c0011` Free Grace (0.0308)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8819, agreement true; floor 0.8129)  
- Judgment: **good**. #1 is the sentence "as needless and useless as our preaching" (Free Grace). The second containing chunk is #7.  
- BM25 top 3 (BM25 score; level unrated): `128-c0033` (34.6052); `128-c0015` (19.82); `128-c0011` (15.942)  
- Dense top 3 (cosine; level strong): `128-c0033` (0.8819); `128-c0016` (0.8234); `128-c0018` (0.8123)  
- Hybrid vs single: Fine in all three modes.

**e5** `God makes the sun shine and the wind blow and the trees bear fruit, so nothing happens by chance`  
- Hybrid top 3 (chunk, sermon, RRF score): `094-c0033` On Family Religion (0.0325); `095-c0030` On the Education of Children (0.0325); `040-c0089` Christian Perfection (0.0306)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8607, agreement true; floor 0.8129)  
- Judgment: **good**. #2 is the chunk that says "there is no such thing as chance" and "God made you... the sun". #1 is a neighbouring passage in the same vein.  
- BM25 top 3 (BM25 score; level unrated): `095-c0030` (42.4531); `094-c0033` (19.2251); `114-c0016` (15.74)  
- Dense top 3 (cosine; level strong): `094-c0033` (0.8607); `095-c0030` (0.8556); `114-c0017` (0.8479)  
- Hybrid vs single: BM25 ranks it #1.

**e6** `the road to hell is paved with good intentions`  
- Hybrid top 3 (chunk, sermon, RRF score): `089-c0014` The More Excellent Way (0.0315); `136-c0026` On Corrupting the Word Of God (0.0283); `031-c0028` Upon our Lord'S Sermon on the Mount, Discourse 11 (0.0256)  
- Confidence: **strong** (bm25_hits 100, dense_top 0.8307, agreement true; floor 0.8129)  
- Judgment: **bad**. The proverb appears in The Almost Christian as `"Hell is paved," saith one, "with good intentions."` (002-c0037). It is not in the hybrid top 10. Top 3 are unrelated passages that share "good" and "hell".  
- BM25 top 3 (BM25 score; level unrated): `002-c0037` (17.3663); `136-c0026` (12.5911); `118-c0038` (9.736)  
- Dense top 3 (cosine; level strong): `032-c0004` (0.8307); `031-c0005` (0.8286); `089-c0014` (0.8209)  
- Hybrid vs single: **Hybrid worse than BM25**: BM25 ranks 002-c0037 #1 (17.4 against 12.6). Dense also misses it. Banner **strong**.


## Controls (follow-up queries, same run)

Clean spellings and rewordings of b1 to b6 and c3, plus three extras. Same columns: hybrid level, BM25 rows (of 100), dense top, then hybrid top 3, BM25 top 2 and dense top 2.

| id | query | hybrid level | bm25_hits | dense_top | hybrid top 3 | BM25 top 2 | dense top 2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| x1 | `how do i get rid of anger and bitterness` | weak | 0 | 0.8442 | `139-c0029` ; `033-c0051` ; `095-c0022` | *none* | `139-c0029` ; `033-c0051` |
| x2 | `what is sanctification` | strong | 86 | 0.8891 | `107-c0014` ; `107-c0017` ; `083-c0038` | `107-c0017` ; `107-c0011` | `083-c0015` ; `083-c0038` |
| x3 | `forgiveness of sins` | strong | 90 | 0.8996 | `026-c0072` ; `026-c0070` ; `005-c0029` | `026-c0072` ; `026-c0069` | `021-c0066` ; `026-c0070` |
| x4 | `is it ok to be rich and wealthy` | weak | 0 | 0.8743 | `131-c0017` ; `087-c0041` ; `126-c0005` | *none* | `131-c0017` ; `087-c0041` |
| x5 | `temptation and how to resist it` | strong | 9 | 0.8781 | `040-c0021` ; `068-c0048` ; `072-c0055` | `082-c0029` ; `040-c0021` | `082-c0022` ; `087-c0026` |
| x6 | `how do i know i'm saved` | weak | 0 | 0.8313 | `085-c0016` ; `010-c0016` ; `043-c0004` | *none* | `085-c0016` ; `010-c0016` |
| x7 | `Should Christians go to the theater?` | weak | 0 | 0.8464 | `037-c0023` ; `025-c0074` ; `063-c0044` | *none* | `037-c0023` ; `025-c0074` |
| x8 | `theatre plays and public diversions` | weak | 0 | 0.8556 | `089-c0042` ; `089-c0048` ; `140-c0032` | *none* | `089-c0042` ; `089-c0048` |
| x9 | `How do I know I am saved?` | strong | 4 | 0.8351 | `016-c0026` ; `085-c0016` ; `003-c0036` | `003-c0036` ; `016-c0077` | `085-c0016` ; `010-c0016` |
| x10 | `Why does God allow pain?` | strong | 7 | 0.8980 | `048-c0042` ; `084-c0039` ; `061-c0080` | `084-c0039` ; `061-c0080` | `047-c0020` ; `059-c0024` |
| x11 | `How can I pray when God feels far away` | strong | 100 | 0.8619 | `016-c0080` ; `041-c0047` ; `077-c0055` | `008-c0026` ; `041-c0047` | `026-c0027` ; `016-c0080` |

Reading: x1, x4, x6, x7 and x8 have 0 BM25 rows, so even the correctly-spelt versions of ordinary questions get `weak` and a dense-only list; x2, x3, x5, x9, x10, x11 have BM25 rows and are `strong`. The `theater` rewording (x7, 4 terms with stopwords removed) misses "On Public Diversions" in the top 3; naming the sermon's own words (x8, "public diversions") puts it at #3, with `weak`.

## Recommendations (ranked, at most 6; none implemented; #2 is blocked)

All are untested proposals. Anything touching `search/abstain.toml` or the scoring path needs the confirmatory protocol that W3-CONFIRMATORY says is still unmet (no fresh blind set exists), so none of these should be called an accuracy gain on the strength of this probe.

1. **Make the BM25 side return something for short natural questions. Must not ship without #4.** `src/preached/fts.py` `to_fts_query` (line 143): when the AND form is built, also try OR (or a relaxed AND of the rarest terms) if the AND query returns no rows; the retry would go in `Searcher._lexical` / `search.bm25_search`. Evidence: 11 of 30 queries (7 of 12 in groups a and b) had 0 BM25 rows, which caps the banner at `weak` and makes hybrid equal to dense. OR form brings the false friends that W3-RETRIEVAL-DIAG measured and is what fakes "agreement" in d1, d2, c3 and e6, so this must not ship without #4 (and #4's pre-registered dev set).
2. **BLOCKED (not a ranked fix): down-weight BM25 in OR form.** `src/preached/search.py` `Searcher.hybrid`, passing `weights` to `rank.reciprocal_rank_fusion`. This is blocked by the w=1.0 HOLD: the fusion weight stays at 1.0 until a future pre-registered study says otherwise, and that study is the only route. The only citable evidence is one sentence of W3-CONFIRMATORY, quoted exactly: "In a pre-registered evaluation (58 questions; relevance labels drafted with AI help, a subset confirmed blind by a human), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086)." My a5, a6 and x10 show the same false-friend pattern, but 3 anecdotes do not lift the block. It would also make e2 and e6 (quotes) worse (see #3).
3. **Let BM25 win when the query is a quote.** Same function, `Searcher.hybrid`, with a quote signal computed in `fts.to_fts_query`: e.g. a quoted-phrase FTS query returns rows, or BM25's top score is far above its second (e2: 31.7 vs 16.4). Only 2 of 6 quote queries are affected here (e2, e6), and e6's wording does not match the text exactly, so a phrase match alone would not catch it; treat this as a hypothesis to test.
4. **Make "agreement" harder to satisfy on OR-form queries.** `src/preached/abstain.py` `compute_signals`: today a shared row anywhere in two 100-deep lists counts, which is almost automatic for an OR query and is what turned d1 and d2 from `none` into `weak` and made c3 and e6 `strong`. Options to evaluate: depth 20 instead of 100 for the check, or ignore OR matches made only of high-document-frequency words. This changes the calibration. Any refit or threshold must use a pre-registered dev set that is disjoint from the frozen eval AND from these 41 probe queries (the 30 plus the 11 controls); tuning on the probe queries would overfit them. #1 must not ship without this.
5. **Stop reading "no BM25 rows" as "no agreement".** `src/preached/abstain.py` `decide`: with `bm25_hits == 0` and `dense_top` well above the floor, the level is `weak` and the WEAK note says the passages "may not answer your question" (a1, a2, b1, b2, b4 were good). Consider a separate wording or level for "your words did not appear; these match by meaning". Wording is a UI/API matter (`app/server.py` is owned by PR #88), so the proposal is the level in `decide`. Note that a new level changes the API's level set (clients, the UI banner and the tests that enumerate `strong`/`weak`/`none`) and the abstain metric (the eval scores abstention against the current levels), so it needs the same pre-registered dev set as #4 and is a breaking API change to plan, not a wording tweak.
6. **Do not drop a sermon both rankers like.** `Searcher.hybrid`: RRF scores chunks, so when BM25 and dense both put the same sermon first on different chunks, as for x5 ("On Temptation"), neither chunk gets a fused boost and unrelated chunks that appear in both lists win. Adding a small sermon-level term, or fusing at sermon level before `search.dedupe_adjacent`, would address it. One example only; the weakest recommendation.

## Cross-check with earlier reports

- **W3-RETRIEVAL-DIAG**: its LEX finding (BM25 OR false friends in the fusion) reproduces on a5, a6, x10 and, for out-of-domain queries, d1 and d2. Its note that `p-016` and `p-017` hit the AND rule is the 2-item version of recommendation 1; this probe finds it on 7 of 12 everyday questions. Its VOCAB finding (modern word, 18th-century wording) is not tested here.
- **W3-CONFIRMATORY**: the `u-pretrib-rapture` strong answer and the unmet fresh-blind-set condition are cited, not repeated; my d-group adds two non-abstentions (d1, d2) that come from spurious agreement, which that report does not examine. Not re-run: the frozen fusion test, `w = 0.5`.
- **EVAL-GRADE / EVAL-DELEAK / EVAL-PLAINQ**: the shipped floor sits at the top cosine of one unanswerable question (`u-book-of-mormon`), "short, vague, real-user questions sit below it" (EVAL-GRADE abstain recheck). b6 here is a new instance (a typo'd 6-word question at 0.7976). No labels or eval sets were touched.
- `src/preached/abstain.py` already says the floor "wrongly flags some answerable questions" and "passes a bare `\"`". That "weak" can mostly mean "short query" is not in it.

## Method, limits and disclosure

- **What ran.** `app/server.py` `load_search` with the ONNX fp32 query embedder (`encode.backend = onnx`, `variant = fp32`), `abstain.floor_for(model, backend, variant)` = 0.8129, and `abstain.search_with_confidence(searcher, query, vector, mode, 10, floor)` for each of `hybrid`, `bm25`, `dense`. That is the same call the server makes. One process, one pass, the query vector computed once per query. BM25 mode is run with no floor, as the server does. Timing was not measured.
- **Judgments** are one LLM reader's (Claude), made on the top 3 with the passage text visible; no second reader and no human review. The queries were written by the same agent after reading the repository's existing retrieval reports, and e1 to e6 were chosen after grepping the corpus for famous phrases. The 30 are not blind, not random, and not a sample of real users. Group sizes of 6 make every percentage coarse.
- **Privacy.** Only the public Wesley library was searched (Wesley sermons, public domain, ids `wesley-NNN-cNNNN`). No church library, congregant text or private data was opened.
- **Cache safety.** `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR` and `TORCH_HOME` pointed at fresh temp paths under `/tmp` (`mktemp -d -t probe.XXXXXX`, so they match the `/tmp/probe.` assert in `probe.py`) or at a read-only temp copy (`chmod -R a-w`) of `wesley.sqlite` and of `models/granite-english-r2-onnx`. The index was copied with the repo's `scripts/bundle_manifest.copy_index` (SQLite backup API, read-only source, DELETE-mode output), see R2 MF3. `find /cache -maxdepth 3 -printf '%p %s %T@\n' | sort` before and after the runs: **depth-3 listing identical (1642 lines, no difference)**. This is a depth-3 listing only, not a full recursive one. **One later difference (R2):** after I ran `copy_index` a second time (to test the corrected how-to-run line), `/cache/index/wesley.sqlite-shm` changed mtime (21:20 to 21:57 on 2026-10-31; size 32768 unchanged). That file is SQLite's shared-memory index, which any reader of a WAL database touches, even `mode=ro`. `wesley.sqlite` (189042688 bytes, mtime Oct 30 15:39) and `wesley.sqlite-wal` (0 bytes) are unchanged, and no other line in the listing differs. The first R2 run's before/after listings were identical; `wesley.sqlite-shm` mtime changed 21:20→21:57 (size unchanged; `wesley.sqlite` and `-wal` unchanged). Cause unverified: likely either my verification `copy_index` (a mode=ro WAL open still writes the -shm index) or the demo refresh that opened the index at 21:57:08–12. Benign: no database content changed. The copy was not deleted by any script of mine.
- **No new dependencies; no Chinese-developed models** (Granite English R2 is IBM).

## How to run it

The probe script is not committed (scope is this report only). Save the script below as `probe.py` outside the repo, save the `queries.json` block below (the exact 41 queries; `x` is the controls), then:

```
S=$(mktemp -d -t probe.XXXXXX)   # must match the /tmp/probe. assert in probe.py
mkdir -p $S/cache/index $S/cache/models
# never cp the live file (a plain cp of a WAL database can drop -wal frames); use the repo's backup-API copy
uv run --frozen --offline python -I -c "import sys;sys.path[:0]=['src','.'];from pathlib import Path;from scripts.bundle_manifest import copy_index;copy_index(Path('/cache/index/wesley.sqlite'),Path('$S/cache/index/wesley.sqlite'))"
cp -r /cache/models/granite-english-r2-onnx $S/cache/models/
chmod -R a-w $S/cache
for v in HF_HOME DENO_DIR XDG_CACHE_HOME UV_CACHE_DIR TORCH_HOME; do mkdir -p $S/$v; done
export PREACHED_CACHE=$S/cache PREACHED_ONNX_DIR=$S/cache/models/granite-english-r2-onnx \
  HF_HOME=$S/HF_HOME DENO_DIR=$S/DENO_DIR XDG_CACHE_HOME=$S/XDG_CACHE_HOME \
  UV_CACHE_DIR=$S/UV_CACHE_DIR TORCH_HOME=$S/TORCH_HOME HF_HUB_OFFLINE=1
cd /work/preached && uv run --frozen --offline python -I probe.py queries.json out.json
```

The `uv run` lines must run from `/work/preached` after the `PREACHED_*` exports (with the `-I` flag the `sys.path` insert in the copy line is what makes `scripts` importable). (`-I` drops the current directory from the import path, so `probe.py` adds `src` and `app` itself.) `probe.py`:

```python
import json,sys,os,sqlite3,time
sys.path.insert(0,'/work/preached/src'); sys.path.insert(0,'/work/preached/app')
from pathlib import Path
from preached.paths import INDEX_PATH
assert str(INDEX_PATH).startswith('/tmp/probe.'), INDEX_PATH
from preached.store import open_readonly
from preached.search import Searcher
import server
from preached.abstain import floor_for, search_with_confidence
conn=open_readonly(INDEX_PATH)
searcher,encode,note=server.load_search(conn,'granite-english-r2')
assert encode is not None, note
floor=floor_for('granite-english-r2',backend=encode.backend,variant=getattr(encode,'variant',None))
print('backend',encode.backend,getattr(encode,'variant',None),'floor',floor,file=sys.stderr)
Q=json.load(open(sys.argv[1]))
K=10
out=[]
for g,qs in Q.items():
    for i,q in enumerate(qs,1):
        rec={'id':f'{g}{i}','q':q}
        v=encode(q)
        for mode in ('hybrid','bm25','dense'):
            kept,conf=search_with_confidence(searcher,q,None if mode=='bm25' else v,mode,K,None if mode=='bm25' else floor)
            rec[mode]={'conf':conf.as_dict()['level'],'sig':conf.as_dict()['signals'],'floor':conf.floor,
              'hits':[{'id':h.chunk_id,'title':h.sermon_title,'score':round(float(h.score),4),'text':h.text} for h in kept]}
        out.append(rec)
json.dump(out,open(sys.argv[2],'w'),indent=1)
```

### queries.json (the exact 41 queries)

```json
{
 "a": [
  "How do I stop worrying about the future?",
  "What does the Bible say about forgiving someone who hurt me?",
  "How can I pray when God feels far away?",
  "Is it wrong to want to be rich?",
  "How should I raise my children?",
  "Why does God allow suffering?"
 ],
 "b": [
  "how do i get rid of anger and bitternes",
  "what is sanctifacation",
  "forgivness of sins",
  "is it ok to be rich and wealthey",
  "temtation and how to resist it",
  "hwo do i know im saved"
 ],
 "c": [
  "How do I forgive my father and also stop feeling guilty about my own anger?",
  "Can a rich person be saved and how should he use his money to help the poor?",
  "Should Christians go to the theater, and does entertainment lead us away from God?",
  "What is the difference between faith and works, and can a believer fall away from grace?",
  "How do I keep from gossiping and what should I do when someone speaks evil of me?",
  "Does God predestine some people to hell, and how can I be sure I am one of the elect?"
 ],
 "d": [
  "What is a good recipe for chocolate chip cookies?",
  "Who won the Super Bowl last year?",
  "How do I fix a flat tire on my bicycle?",
  "What is the capital of Australia?",
  "Should I buy Bitcoin or index funds?",
  "How does a vaccine work?"
 ],
 "e": [
  "Is thine heart right, as my heart is with thy heart?",
  "Nothing comes by chance; that is a silly word; there is no such thing as chance.",
  "Gain all you can, save all you can, give all you can.",
  "if they are elected or not elected then your advice and reproof is as useless as our preaching",
  "God makes the sun shine and the wind blow and the trees bear fruit, so nothing happens by chance",
  "the road to hell is paved with good intentions"
 ],
 "x": [
  "how do i get rid of anger and bitterness",
  "what is sanctification",
  "forgiveness of sins",
  "is it ok to be rich and wealthy",
  "temptation and how to resist it",
  "how do i know i'm saved",
  "Should Christians go to the theater?",
  "theatre plays and public diversions",
  "How do I know I am saved?",
  "Why does God allow pain?",
  "How can I pray when God feels far away"
 ]
}
```

## R2 (response to CTO CHANGES on e8f7d2c)

R2 merged `origin/main` (e434539) into the branch with a normal merge (no conflicts; no `--ours`/`--theirs`).

- **MF1 met.** Rec #2 no longer paraphrases W3-CONFIRMATORY. It quotes the one citable sentence exactly and drops the V10 and `w = 0.5` numbers that I had restated.
- **MF2 met.** Rec #2 is marked BLOCKED by the w=1.0 HOLD (a future pre-registered study only, not a ranked fix). Rec #4 now says any refit or threshold uses a pre-registered dev set disjoint from the frozen eval AND from these 41 probe queries.
- **MF3 met.** (a) The run dir is now `mktemp -d -t probe.XXXXXX`, which matches the `/tmp/probe.` assert in `probe.py` (the earlier `mktemp -d` did not); the how-to-run steps are corrected. (b) Re-derived the whole run from an index copied with `scripts/bundle_manifest.copy_index` (backup API) into a `/tmp/probe.*` dir, on the merged tree. Before copying I recorded the live `wesley.sqlite-wal` at **0 bytes** (`wesley.sqlite` 189042688 bytes), so the earlier claim that dropping the WAL cost nothing is now verified, not assumed. **No number changed**: all 30 queries (level, bm25_hits, dense_top to 4 places, hybrid top 3 ids) and all 11 controls match this report exactly; floor 0.8129, backend onnx fp32. (c) The exact 41-query `queries.json` is recorded above. (d) Every cache claim now says "depth-3 listing": the snapshot was `find /cache -maxdepth 3`, 1642 lines, identical before and after the R2 probe run; it is not a full recursive listing. A later extra `copy_index` test changed only the mtime of `wesley.sqlite-shm` (see Method); reported, not hidden.
- **S1 met.** Rec #1 states it must not ship without rec #4.
- **S2 met.** Rec #5 notes that a new level changes the API's level set and the abstain metric.

## R3 (response to CTO CONDITIONAL on 93e76ad)

- **MF-r2-1 met.** The `-shm` mtime change was stated as caused by my extra `copy_index`. That is now worded as an unverified cause (my `copy_index` or the demo refresh that opened the index at 21:57:08–12), in both Method/Cache safety and the PR BODY. Nothing else changed.

## PR BODY

PR title: W5 search failure probe (report only)

Summary: 30 queries in five groups plus 11 controls, run in-process on main `d8a0966` through the same `search_with_confidence` call the server uses (Granite ONNX fp32, floor 0.8129). Top 3 findings: (1) 11 of 30 queries, including 7 of 12 everyday and typo questions, get 0 BM25 rows because `to_fts_query` ANDs 4 or fewer terms, so the banner can only say `weak` for them and hybrid equals dense; (2) `strong` is nearly automatic on long queries and sits on bad results for c3 (theater) and e6 (a proverb Wesley quotes), and 2 of 6 out-of-domain queries (recipe, Super Bowl) do not abstain because junk BM25 matches fake agreement; (3) on quotes, hybrid is worse than BM25 alone (e2, e6). Six ranked recommendations, none implemented. No code, eval, label, calibration or doc change. Depth-3 `/cache` listing identical before and after the probe runs (shortened: `wesley.sqlite-shm` mtime changed 21:20→21:57 (size unchanged; `wesley.sqlite` and `-wal` unchanged). Cause unverified: likely either my verification `copy_index` (a mode=ro WAL open still writes the -shm index) or the demo refresh that opened the index at 21:57:08–12. Benign: no database content changed. Disclosed in Method.).

`git diff --stat origin/main...HEAD` (origin/main e434539):

```
 reports/W5-SEARCH-FAILURE-PROBE.md | 495 +++++++++++++++++++++++++++++++++++++
 1 file changed, 495 insertions(+)
```
