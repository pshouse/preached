# W5 demo query spot check (report only)

Base: `origin/main` = 9690f4ff67fac5ec36dcd3c527301b37fdce84d4 (exactly the expected sha).
Target: live demo at `http://127.0.0.1:8800`, queried over HTTP only. No server started, no suite run, `/cache` not read, no python/uv used (curl + jq only).
Date of run: 2026-10-31. 25 requests, spaced about 1.2 s apart. All returned HTTP 200 (no 503s).

Params copied from `app/static/app.js` (`runSearch`, default "classic" view): `GET /api/search?q=<query>&mode=hybrid&k=10&library=wesley`. I graded only the top 3 of the 10 returned. The corpus behind `library=wesley` is Wesley's sermons (LibriVox audio), so "does it have this?" is judged against that.

Grading: 2 = directly answers or is the named passage, 1 = related or tangential, 0 = off target. Grades are my own reading of the excerpt and sermon title/scripture, so they are a judgment, not ground truth.

Observation up front: no result in any response carries a `why` field. Every result has these keys: `audio_url, chunk_id, chunk_ids, end_s, reader, score, scripture, sermon_id, sermon_number, sermon_title, source_url, start_s, text, text_source`. So "why" is "absent" below. Confidence is `confidence.level` (strong/weak/none) plus `abstain`.

## Summary table

| # | Query | Kind | Level / abstain | Top-3 grades | Banner matched my judgment? |
|---|---|---|---|---|---|
| 1 | What is grace? | topical | strong / no | 1,1,2 | yes (acceptable) |
| 2 | How does God forgive sins? | topical | strong / no | 2,1,1 | yes |
| 3 | How can I have assurance of salvation? | topical | strong / no | 1,2,1 | yes |
| 4 | What does it mean to be justified by faith? | topical | strong / no | 2,2,2 | yes |
| 5 | Romans 8 | reference | strong / no | 0,2,2 | mostly (rank 1 is Romans 7) |
| 6 | the prodigal son | reference | strong / no | 0,0,0 | **no, overconfident** |
| 7 | Sermon on the Mount | reference | strong / no | 2,2,2 | yes (but all three are Discourse 1) |
| 8 | the good Samaritan | reference | weak / no | 1,0,0 | yes |
| 9 | How should I pray when I'm anxious? | practical | weak / no | 2,1,0 | **under-confident** |
| 10 | How do I deal with doubt in my faith? | practical | weak / no | 2,2,1 | **under-confident** |
| 11 | What is Christian perfection? | topical | strong / no | 2,2,2 | yes |
| 12 | Why does God allow suffering? | practical | strong / no | 0,0,1 | **no, overconfident** |
| 13 | How should I treat my enemies? | practical | none / **abstain** | 1,0,2 | **no, false abstain** |
| 14 | What does the Bible say about money and riches? | topical | weak / no | 2,1,2 | **under-confident** |
| 15 | How do I know if I am truly born again? | practical | strong / no | 2,2,2 | yes |
| 16 | What is the witness of the Spirit? | topical | strong / no | 2,1,2 | yes |
| 17 | How can I overcome temptation? | practical | strong / no | 2,0,1 | roughly (rank 1 good, rest weak) |
| 18 | What is the narrow way to heaven? | topical | strong / no | 2,1,2 | yes |
| 19 | How should Christians worship together? | practical | strong / no | 1,0,1 | borderline, leans overconfident |
| 20 | Is it okay to feel angry at God? | practical | weak / no | 0,1,1 | yes |
| 21 | What is repentance? | topical | strong / no | 2,2,2 | yes |
| 22 | Who won the Super Bowl last year? | off-topic | weak / **no abstain** | 0,0,0 | **no, should abstain** |
| 23 | best chocolate chip cookie recipe | off-topic | weak / **no abstain** | 0,0,0 | **no, should abstain** |
| 24 | What is the current price of bitcoin? | off-topic | none / abstain | 0,0,0 (riches sermons, loosely 1) | yes |
| 25 | How do I fix a flat bicycle tire? | off-topic | none / abstain | 0,0,0 | yes |

Note: 21 queries are real questions (topical, reference, practical) and 4 are off-topic (22 to 25); the task asked for at least 3 off-topic.

## Per-query detail

Format: `title | scripture | score | grade, reason`. Excerpts are the first ~100 chars of the returned chunk text. `why`: absent on every result. `signals` = `confidence.signals` (dense_top, bm25_hits).

### 1. What is grace? (strong; dense_top 0.894, bm25 100)
- The Means of Grace | Mal 3:7 | 0.0325 | 1. "They have probably tried most outward means, and found no ease in them..." Related (means of grace) but not a definition of grace.
- On Visiting the Sick | Matt 25:36 | 0.0316 | 1. "...the means of grace and the ordinances of God are equivalent terms." About ordinances, not grace itself.
- Salvation by Faith | Eph 2:8 | 0.031 | 2. "...'grace upon grace!' If God vouchsafe still to pour fresh blessings..." Good fit.
Banner: strong is acceptable, though the best hit is third. "Salvation by Faith" would be the better opener.

### 2. How does God forgive sins? (strong; dense_top 0.909, bm25 73)
- Sermon on the Mount, Discourse 6 | Matt 6:1-15 | 0.0328 | 2. "If ye forgive men their trespasses, your heavenly Father will also forgive you..." Good.
- Sermon on the Mount, Discourse 6 | Matt 6:1-15 | 0.031 | 1. Same sermon, passage about sins as diseases; the connection to forgiveness is indirect.
- Justification By Faith | Rom 4:5 | 0.029 | 1. "He justifieth the ungodly" is close to pardon but not the forgiveness mechanics.
Banner: matched.

### 3. How can I have assurance of salvation? (strong; dense_top 0.873, bm25 6)
- On Grieving the Holy Spirit | Eph 4:30 | 0.0277 | 1. Sealing of the Spirit and "they shall be mine" touch assurance indirectly.
- The Scripture Way of Salvation | Eph 2:8 | 0.0256 | 2. "...hath the witness in himself... the Spirit witnesseth with his spirit that he is a child of God."
- On Working out our own Salvation | Phil 2:12-13 | 0.016 | 1. About salvation stages, not assurance.
Banner: matched.

### 4. What does it mean to be justified by faith? (strong; dense_top 0.941, bm25 18)
- Justification By Faith | Rom 4:5 | 0.0307 | 2. "faith is imputed to him for righteousness..."
- The Lord our Righteousness | Jer 23:6 | 0.0285 | 2. Directly on faith imputed for righteousness.
- Justification By Faith | Rom 4:5 | 0.026 | 2. Defines justification as clearing from accusation.
Banner: matched. Best single query.

### 5. Romans 8 (strong; dense_top 0.854, bm25 78)
- The Original, Nature, Property, and Use of the Law | Rom 7:12 | 0.0304 | 0. Romans 7, not 8.
- On Predestination | Rom 8:29-30 | 0.030 | 2. Expounds Romans 8:29-30.
- The Spirit of Bondage and of Adoption | Rom 8:15 | 0.022 | 2. Quotes and expounds Romans 8:15.
Banner: acceptable; the reference match is lexical ("Rom"), so Rom 7 outranks the Rom 8 sermons. Also "THE FIRST FRUITS OF THE SPIRIT" (Rom 8:1) appears elsewhere in results, not top 3.

### 6. the prodigal son (strong; dense_top 0.825, bm25 2)
- The Use of Money | Luke 16:9 | 0.0325 | 0. Different parable (unjust steward).
- Awake, Thou That Sleepest | Eph 5:14 | 0.024 | 0. Awakening sermon, no prodigal.
- The Important Question | Matt 16:26 | 0.016 | 0. Not related.
Banner: wrong. Strong confidence on three misses. Probably the corpus has no sermon on Luke 15, which makes this a good abstain/weak case that the heuristic missed.

### 7. Sermon on the Mount (strong; dense_top 0.840, bm25 100)
- Upon our Lord's Sermon on the Mount, Discourse 1 | Matt 5:1-4 | 0.031 | 2. Opening of the series.
- Same sermon, Discourse 1 | 0.029 | 2. Beatitudes text.
- Same sermon, Discourse 1 | 0.027 | 2. Same sermon again.
Banner: matched. All three are chunks of the same discourse, so a user gets no spread.

### 8. the good Samaritan (weak; dense_top 0.821, bm25 0)
- The Almost Christian | Acts 26:28 | 0.0164 | 1. Doing good to others, no parable.
- The Great Assize | Rom 14:10 | 0.0164 | 0. Judgment, not relevant.
- The Important Question | Matt 16:26 | 0.0164 | 0. Not relevant.
Banner: matched (weak, honest).

### 9. How should I pray when I'm anxious? (weak; dense_top 0.858, bm25 0)
- The Means of Grace | Mal 3:7 | 0.0164 | 2. "When trouble and heaviness take hold upon him... pour out his soul before God; 'always to pray and not to faint.'" Very good.
- The More Excellent Way | 1 Cor 12:31 | 0.0164 | 1. Advice on varying prayers to inward state.
- On Visiting the Sick | Matt 25:36 | 0.0164 | 0. About tracts.
Banner: weak undersells a strong top hit.

### 10. How do I deal with doubt in my faith? (weak; dense_top 0.884, bm25 0)
- On Patience | Jas 1:4 | 0.0164 | 2. "The faith of a babe in Christ... mingled with doubts or fears."
- Of Evil Angels | Eph 6:12 | 0.0164 | 2. "If he inject doubts whether you are a child of God..."
- Justification By Faith | Rom 4:5 | 0.0164 | 1. Definition of faith.
Banner: weak undersells the result.

### 11. What is Christian perfection? (strong; dense_top 0.938, bm25 100)
- Christian Perfection | Phil 3:12 | 0.0325 | 2. "does not imply an exemption either from ignorance or mistake, or infirmities."
- Christian Perfection | Phil 3:12 | 0.030 | 2. Same sermon, 1 John 3 discussion.
- Christian Perfection | Phil 3:12 | 0.030 | 2. Same sermon.
Banner: matched. All three chunks from one sermon.

### 12. Why does God allow suffering? (strong; dense_top 0.891, bm25 7)
- The Important Question | Matt 16:26 | 0.032 | 0. Pleasure from doing good, not suffering.
- The Important Question | Matt 16:26 | 0.024 | 0. Same, quoting "Let not the Stoic boast".
- God's Love to Fallen Man | Rom 5:15 | 0.016 | 1. "how much good does he continually bring out of this evil... holiness and happiness out of pain." Closest, but ranked third.
Banner: strong is overconfident. I did not check which sermon would be the ideal answer.

### 13. How should I treat my enemies? (none / ABSTAIN; dense_top 0.810, bm25 2)
Note shown: "Low confidence: these passages may not answer your question. This is a rough automatic check (a heuristic)..."
- On Friendship with the World | Jas 4:4 | 0.0164 | 1. "We are to bear them tender compassion when we see them forsaking their own mercies."
- The Ministerial Office | Heb 5:4 | 0.0164 | 0. Relations with the clergy's critics.
- Sermon on the Mount, Discourse 3 | Matt 5:8-12 | 0.0164 | 2. "In conversing with them use all mildness... Reprove them... bless."
Banner: false abstain. The corpus plainly contains relevant material (Sermon on the Mount discourses on loving enemies), so a user would be told "low confidence" on a answerable question.

### 14. What does the Bible say about money and riches? (weak; dense_top 0.894, bm25 0)
- Sermon on the Mount, Discourse 8 | Matt 6:19-23 | 0.0164 | 2. "desiring, resolving to be rich, coveting after money, the root of all evil."
- The Mystery of Iniquity | 2 Thes 2:7 | 0.0164 | 1. "the genuine tendency of riches"; a passing section of a different sermon.
- The Danger of Riches | 1 Tim 6:9 | 0.0164 | 2. Directly on riches.
Banner: weak undersells a good result.

### 15. How do I know if I am truly born again? (strong; dense_top 0.869, bm25 100)
- The New Birth | John 3:7 | 0.031 | 2. "You must be born again."
- The New Birth | John 3:7 | 0.028 | 2. Foundation of the new birth.
- The New Birth | John 3:7 | 0.028 | 2. Account of the new birth, three questions.
Banner: matched. Strictly the "how do I know" part is better served by "The Marks of the New Birth", which showed up in query 16 instead.

### 16. What is the witness of the Spirit? (strong; dense_top 0.917, bm25 100)
- THE WITNESS OF THE SPIRIT, Discourse I | Rom 8:16 | 0.032 | 2. "What is this witness or testimony of our spirit..."
- The Marks of the New Birth | John 3:8 | 0.031 | 1. Testimony of conscience, hope; adjacent.
- The Witness of the Spirit, Discourse II | 2 Cor 1:12 | 0.029 | 2. Same topic, second discourse.
Banner: matched.

### 17. How can I overcome temptation? (strong; dense_top 0.872, bm25 7)
- On Temptation | 1 Cor 10:13 | 0.031 | 2. Good.
- On Family Religion | Josh 24:15 | 0.027 | 0. About "this evil" in a family, only loosely.
- The End of Christ's Coming | 1 John 3:8 | 0.026 | 1. Vice and virtue, indirect.
Banner: fine for rank 1, results 2 and 3 are weak.

### 18. What is the narrow way to heaven? (strong; dense_top 0.896, bm25 6)
- Sermon on the Mount, Discourse 11 | Matt 7:13-14 | 0.032 | 2. Broad way / strait gate.
- Sermon on the Mount, Discourse 12 | Matt 7:15-20 | 0.032 | 1. "Every broad way is infallibly a false one"; false prophets.
- Sermon on the Mount, Discourse 11 | Matt 7:13-14 | 0.029 | 2. "Enter ye in at the strait gate."
Banner: matched.

### 19. How should Christians worship together? (strong; dense_top 0.856, bm25 4)
- Catholic Spirit | 2 Ki 10:15 | 0.023 | 1. Unity and conscience, not worship order.
- The Ministerial Office | Heb 5:4 | 0.016 | 0. Uniting the flock in small companies.
- Sermon on the Mount, Discourse 5 | Matt 5:17-20 | 0.016 | 1. "attending and partaking of the Christian sacrifice."
Banner: strong is generous. "On Attending the Church Service" exists (it surfaced for the cookie query) and would be the ideal answer, but it is not in the top 3 here.

### 20. Is it okay to feel angry at God? (weak; dense_top 0.879, bm25 0)
- THE FIRST FRUITS OF THE SPIRIT | Rom 8:1 | 0.0164 | 0. Assaults from the world and the heart; not anger.
- Sermon on the Mount, Discourse 2 | Matt 5:5-7 | 0.0164 | 1. "if anger at persons be a temper contrary to love..."
- Christian Perfection | Phil 3:12 | 0.0164 | 1. "all anger is not evil. Our Lord looked round with anger."
Banner: matched (weak, honest).

### 21. What is repentance? (strong; dense_top 0.924, bm25 100)
- The Scripture Way of Salvation | Eph 2:8 | 0.032 | 2. "This is the repentance, and these the fruits meet for repentance."
- The Repentance of Believers | Mark 1:15 | 0.031 | 2. Direct.
- The Scripture Way of Salvation | Eph 2:8 | 0.030 | 2. "repentance, rightly understood."
Banner: matched.

### 22. Who won the Super Bowl last year? (weak, NOT abstain; dense_top 0.755, bm25 100)
Note shown: "These passages may not answer your question. They are the closest matches, not strong ones."
- On Love | 1 Cor 13:3 | 0.023 | 0. A battle-death anecdote.
- The General Spread of the Gospel | Is 11:9 | 0.020 | 0. Luther on revival.
- The Important Question | Matt 16:26 | 0.017 | 0.
Banner: should have been `none`/abstain. bm25_hits is 100 even though nothing sensible matches, so common words ("who", "last", "year") likely drive that signal.

### 23. best chocolate chip cookie recipe (weak, NOT abstain; dense_top 0.752, bm25 100)
- On Obedience to Parents | Col 3:20 | 0.025 | 0. Child rearing.
- Catholic Spirit | 2 Ki 10:15 | 0.024 | 0. Conscience.
- On Attending the Church Service | 1 Sam 2:17 | 0.022 | 0.
Banner: same failure as 22; "best" and "recipe"-adjacent words give lexical hits.

### 24. What is the current price of bitcoin? (none / ABSTAIN; dense_top 0.746, bm25 0)
- On the Danger of Increasing Riches | Ps 62:10 | 0.0164 | 0. Wealth and charity, not price.
- The Danger of Riches | 1 Tim 6:9 | 0.0164 | 0.
- Sermon on the Mount, Discourse 5 | Matt 5:17-20 | 0.0164 | 0. Honest dealing in trade.
Banner: correct. Note the user still sees three results below the low-confidence banner unless they press "Hide low-confidence results".

### 25. How do I fix a flat bicycle tire? (none / ABSTAIN; dense_top 0.755, bm25 0)
- On the Fall of Man | Gen 3:19 | 0.0164 | 0. Anatomy.
- The Late Work of God in North America | Ezek 1:16 | 0.0164 | 0. "wheel in the middle of a wheel."
- The Reward of the Righteous | Matt 25:34 | 0.0164 | 0.
Banner: correct, and a fun one to show: the "wheel" hit is a lexical coincidence.

## (a) Five best queries for the demo video
1. **What does it mean to be justified by faith?** Grades 2,2,2, highest dense_top of the set (0.941), strong banner earned. Clean, doctrinal, and a core Wesley subject.
2. **What is the witness of the Spirit?** Top hit is literally "The Witness of the Spirit, Discourse I", with Discourse II also in top 3. Shows the engine finding the right sermon from a plain question.
3. **How do I know if I am truly born again?** A real church-member question; all three results are "The New Birth" and read as directly relevant. Strong banner is earned.
4. **What is the narrow way to heaven?** Finds Sermon on the Mount discourses 11 and 12 on Matt 7:13-14 from everyday wording, no reference given. Good demonstration of semantic matching.
5. **How should I pray when I'm anxious?** Best "pastoral" moment: the top excerpt ("When trouble and heaviness take hold... always to pray and not to faint") is a great fit. Caveat: the banner says weak, so use it only if the narration embraces "closest matches" or after the confidence fix below. If that is unwanted, substitute **What is repentance?** (2,2,2, strong).

Pair with one abstention for contrast: **What is the current price of bitcoin?** (correctly abstains, yet see (c)).
Avoid on camera: "the prodigal son", "Why does God allow suffering?", "How should I treat my enemies?", and both Super Bowl/cookie queries.

## (b) Weakest queries and hunches (all hunches, not verified in code)
- **the prodigal son** (0,0,0 yet strong). Hunch: the corpus has no Luke 15 sermon, and the "strong" label came from the dense score (0.82) plus a tiny agreement signal, not from relevance. The top hit's score (0.0325) equals the maximum RRF for a rank-1-in-both-lists chunk, so both retrievers agreed on a wrong answer ("son"/"money" semantics).
- **Why does God allow suffering?** (0,0,1 yet strong). Hunch: dense retrieval latches onto "good/pleasure/happiness" in "The Important Question" (appears twice); the doubled hits from one sermon also crowd out better sermons.
- **How should I treat my enemies?** (relevant material exists, abstained). Hunch: bm25_hits was only 2 and the RRF scores are all the single-list value 0.0164, i.e. the lexical list and dense list had no overlap. The abstain rule seems to key on agreement or a dense_top threshold around 0.81, which this relevant query just fell under. Wesley's wording is "love your enemies"/"them that persecute you", far from the query's vocabulary.
- **the good Samaritan**: honest weak. Hunch: no dedicated sermon; the parable is probably only mentioned in passing.
- **Under-confident weak banners (pray when anxious, doubt, money and riches)**: all have bm25_hits 0 and every result at score 0.0164 (= 1/61, dense-only rank 1). Hunch: the rule treats "no lexical hit" as weak regardless of dense_top (0.86 to 0.89, as high as the strong queries). Conversational phrasing that does not share Wesley's vocabulary is penalized.
- **Repeated chunks from one sermon**: queries 7, 11, 15 return three chunks of the same sermon in the top 3. Hunch: no per-sermon diversification (the full result list of 10 may do better, but top 3 is what the video shows).
- **Romans 8** ranks a Romans 7 sermon first. Hunch: reference queries are handled as plain text; no scripture-reference parsing against the `scripture` field.

## (c) Did abstention behave?
Partly.
- True abstains: bitcoin (24) and bicycle (25) correctly returned `abstain: true`, level `none`. Both had dense_top about 0.75 and bm25_hits 0.
- Missed abstains: Super Bowl (22) and cookie recipe (23) returned level `weak`, `abstain: false`, with a gentler "closest matches" note, even though nothing relevant was returned. Their dense_top (0.755, 0.752) is as low as the two true abstains; the difference is bm25_hits=100, so lexical hits on common words appear to turn off abstention. If the video shows an off-topic query, use the bitcoin or bicycle one, not a sports or food one.
- False abstain: "How should I treat my enemies?" (13) abstained although the corpus has relevant sermons.
- On-topic but unanswerable queries ("the prodigal son") did not abstain at all and were labelled strong.
- Net: out of 4 off-topic queries, 2 abstained (50%), and 1 of 21 on-topic queries abstained wrongly. Heuristic wording in the note ("a rough automatic check") is honest about this.

## (d) Latency (informational)
Client wall time per request (curl, local, includes HTTP): p50 64 ms, p95 69 ms, min 55, max 84 (n=25).
Server `took_ms`: p50 56 ms, p95 62 ms, min 47, max 77 (n=25).
Requests were serial and spaced; this says nothing about concurrent load. First query was not noticeably slower than the rest (the service was already warm).

## Recommendations (no code changed here)
1. Retune the confidence rule so a high dense_top with bm25_hits 0 is not automatically weak, and so a very low dense_top (under about 0.78) abstains even when bm25_hits is large (stopword hits). Check whether bm25_hits should ignore stopwords.
2. Consider a per-sermon cap or merge in the top results.
3. Consider parsing scripture references ("Romans 8") to boost the `scripture` field match.
4. If a `why` explanation is expected in the UI, it is not in the API response today; confirm whether that is intended.

## PR BODY

Report-only spot check of 25 queries against the live demo, to pick demo-video queries. Adds `reports/W5-DEMO-QUERY-SPOTCHECK.md` only.

`git diff --stat origin/main...HEAD`:

```
DIFFSTAT_PLACEHOLDER
```
