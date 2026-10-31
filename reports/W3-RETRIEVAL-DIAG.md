# W3-RETRIEVAL-DIAG: why plain-language questions miss (analysis only)

Branch `docs/w3-retrieval-diag`, from origin/main `5779961`. Agent: Claude (Opus 5.5). Date: 2026-10-31.

Revised by W3-DIAG-FIX (CTO #42 r1): labelling, disclosure and caveats only. Every number is as computed; none was changed. Item-by-item map: `reports/W3-DIAG-FIX.md`.
Revised again by W3-DIAG-FIX2 (CTO #42 r2): the `diag.py` hash claim corrected (§8), scratch scripts opened `immutable=1`, p-015 moved LEX → VOCAB (blind LEX 5, VOCAB 5), a §4 note, a chunk-content hash. Map: `reports/W3-DIAG-FIX2.md`.

**This changes no search code, no index, no eval set, and no grades.** The only file added by the original report is this report; the scratch scripts behind it are now committed in `reports/w3-retrieval-diag/` (see §8). Large intermediate outputs stay in `/cache/w3-retrieval-diag/` (outside the repo). Every number marked *exploratory* below comes from those scratch scripts, not from shipped code.

## Bottom line

- **On the questions written blind, the biggest single cause of misses is BM25 inside the fusion, not the embedding model.** ("Blind" is the `plain-blind` group: 30 questions written by an LLM agent, Grok, before it read the corpus, `provenance: llm-written:grok`. Every label on them was proposed by an LLM, Claude, and none is confirmed by a person.) Granite dense alone puts an acceptable passage in the top 10 for 11 of 28 blind questions. The shipped hybrid does it for 3 of 28. On 8 of the 28, dense has one in the top 10 and hybrid does not. Hybrid never rescues one that dense missed (0 of 28). All `plain-blind` numbers in this report are post-hoc, not held out (§5). On the 25 `plain` questions fusion is a wash (it loses 2, gains 3). Everyday questions are long and full of incidental words ("lie awake", "years ago", "drinking", "fires", "church"). The FTS query ORs all of them, BM25 finds Wesley passages that share those words but not the subject, and RRF at equal weight gives them as much say as the dense list.
- **The second cause is vocabulary**: modern words with no 18th-century bridge, such as "scared of dying" vs "fear of death" and "jealous" vs "envy". Wesley's own "jealous over ourselves" means watchful, so it is a false friend. It is the primary cause for 4 of the 7 `plain` misses and 5 of the 25 blind misses (post-hoc, not held out).
- **The blind score is also partly a measurement problem.** Blind questions have a median of 5 labels; `plain` questions have 17. On 6 of the 25 blind misses, the shipped top 10 already holds an unlabelled passage that, in my reading, plausibly answers the question. "My reading" is Claude's, the same model family that proposed every blind label. These are flagged for Patrick below and were **not** regraded. If Patrick confirmed all of them, blind hit@10 for the shipped default would go from 3/28 to 9/28 (post-hoc, not held out). That is a what-if, not a result.
- **Chunk size is not the problem.** The labelled chunks have a median of 123 words against a corpus median of 122. Context smoothing with neighbouring chunks did not help (exploratory: −0.04 on `plain`, +0.04 on blind (post-hoc, not held out), both inside noise).
- **Recommended first intervention (zero dependencies, no RSS or latency cost):** give BM25 half weight in RRF only when the FTS query is the natural-language OR form, and keep full weight for AND/NEAR keyword and scripture queries. Exploratory: blind lenient hit@10 goes from 0.107 to 0.286 (+0.18 [+0.04, +0.32], 5 wins, 0 losses; post-hoc, not held out). `plain` goes from 0.72 to 0.76, and scripture and title keyword queries are unchanged. Overall it is +0.07 [+0.01, +0.14], with 7 wins and 1 loss (`q-worry`). Multiplicity: V10 is the best of 12 variants compared with V0 across 6 groups, picked after the fact, and the intervals are not adjusted for that. On the blind questions V10 equals V3 by construction (§6). These numbers support no accuracy claim. The confirmatory test is a fresh blind set, frozen and committed before any ranker runs on it (§7 #1 step d). That test, and a re-check of the abstain rule, come before Patrick decides.

## 1. Method and settings

- **Rankers.** These are the shipped ones, on the raw ranker path (`search/bench.py` without `--dedupe`):
  - BM25: FTS5 `porter unicode61`, `to_fts_query`.
  - Granite English R2 dense: revision `47ea694b`, CPU fp32 query vectors, document vectors from `/cache/index/wesley.sqlite`.
  - Hybrid: RRF k=60 with equal weights (the default `hybrid` mode).
- **Baseline run.** `search/bench.py --models granite-english-r2` reproduces the submission numbers exactly:
  - `plain`: nDCG@10 strict 0.028, lenient hit@10 0.72.
  - `plain-blind`: lenient hit@10 0.107 (3 of 28).
- **Per-question dump.** `diag.py` asks each ranker for its top 100 on every `plain` and `plain-blind` question, through the same `Searcher` calls the bench uses. Its top 5s match the bench's `top10` lists on all 55 questions × 3 rankers (0 mismatches).
- **Labels.**
  - "Labelled" means a chunk that contains the normalised quote of any label (`metrics.contains_quote`). Grade 2 and grade 1 both count, including the proposed ones; this is the *lenient* set.
  - "First label B/D/H" is the rank of the first such chunk in the BM25, dense, and hybrid top 100.
  - The shipped default is judged a hit if a labelled chunk is in its top 10 (lenient hit@10, the headline the submission draft cites).
- **Categories.** I assigned them by reading every top-5 chunk against the question and its labels, one primary category per question, for the shipped hybrid:

  | code | meaning |
  | --- | --- |
  | HIT | A labelled chunk is in the hybrid top 10. Not a failure. Strict may still miss. |
  | LEX | Other: a BM25 false friend. Dense has a labelled chunk, or the right sermon, near the top, but BM25 matches incidental words and RRF buries it. |
  | VOCAB | Vocabulary gap: modern vs 18th-century wording. Neither ranker reaches the answer. |
  | THEME | Wrong sermon, same theme. |
  | PASSAGE | Other: the right sermon, but a different passage from the labelled one. |
  | GRADE | Suspected grading gap: a plausibly correct passage in the hybrid top 10 is unlabelled. |
  | AMBIG | The question is ambiguous or too short, or its answer in Wesley is thin (1 to 3 labels, or a stretch). |
  | CHUNK | Chunk too long or too short. Assigned 0 times; see §3. |
  | UNANS | Unanswerable item. Not scored. |

- **Supporting statistics.** `stats.py` computes:
  - Query/label overlap: the best share of the question's content stems that appear in any labelled chunk.
  - Labelled chunk length.
  - Fusion loss or gain: dense hits in the top 10 and hybrid does not, or the reverse.
- **Not human-reviewed.** The categories and flags are one LLM reader's judgment (me), with no second reader and no review by a person. The GRADE flags come from Claude, the same model family that proposed every `plain-blind` label (EVAL-GRADE, `found_by: llm-proposed:claude`).

**Sources:** `eval/questions.jsonl` (labels as on main; the grade-1 and blind labels are proposed and unconfirmed), `/cache/corpus/wesley/chunks.jsonl` (8,383 chunks), `/cache/index/wesley.sqlite`, `search/models.toml`, `reports/EVAL-GRADE.md`, and `eval/README.md`.

**Disclosure:** the 30 `plain-blind` questions were written by an LLM agent (Grok; `provenance: llm-written:grok`), and every label on them was proposed by an LLM (Claude; `status: proposed`, `found_by: llm-proposed:claude`). None is confirmed by a person. The GRADE flags in §4 also come from Claude.

## 2. Per-question table

Each cell gives the sermon number and chunk number (`093·38` = `wesley-093-c0038`).

| mark | meaning |
| --- | --- |
| **bold** with ² or ¹ | Contains a grade-2 or grade-1 label |
| † | From a grade-2 sermon but unlabelled |
| ⚑ | Suspected grading gap (§4) |

The *expected* column gives the grade-2 sermon(s), then the number of grade-1 labels and their sermons. Sermon titles are in the appendix. "1st label B/D/H" is the rank of the first labelled chunk in the top 100 for BM25, dense, and hybrid; – means none.

| id | question | expected | BM25 top 5 | dense top 5 | hybrid top 5 | 1st label B/D/H | category | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| q-worry-plain | Bills keep piling up and I lie awake fretting about how we'll get by next month. How do I stop being so anxious about what's coming? | ²029 +12¹ (028 029 105) | 093·10 053·32 133·46 133·47 093·38 | 050·34 093·38 084·46 093·37 073·52 | 093·38 093·10 093·36 027·64 041·17 | 12/22/32 | VOCAB | "fretting/anxious" vs Wesley's "take no thought for the morrow" / "uneasy care"; BM25 matches "lie awake", "month" (On Redeeming the Time, Whitefield memoir); dense matches "to-morrow" in The Use of Money |
| q-assurance-plain | Some days I feel sure God has forgiven me and other days I'm not sure at all. Is there any way to actually be certain I belong to him? | ²010 +18¹ (010 011 013 018 021 043 062 072 106 128) | 009·19 094·13 084·56 042·17 123·38 | **010·16**¹ 045·33 011·31 087·61 029·13 | 002·32 042·17 **010·16**¹ 009·19 045·33 | 49/1/3 | HIT | dense finds 010 at 1; strict misses because the single grade-2 passage is one chunk of 010 |
| q-money-plain | Is it okay to work hard for a bigger paycheck, or should a follower of Jesus not care about getting ahead? | ²050 +17¹ (028 029 050 068 087 089 116 126 140) | 082·54 095·51 082·53 102·10 030·12 | 089·27⚑ 140·37 033·14 108·43 094·46 | 094·46 027·89 094·48 001·32 094·47 | 54/11/13 | THEME | other work/money sermons (More Excellent Way, Family Religion) instead of 050 "Gain all you can"; 089-c0027 (diligence in business to please God) is plausible |
| q-riches-plain | I've done well in business and now have a lot more than I need. Could having all this be bad for me spiritually? | ²087 +20¹ (028 061 068 087 108 112 116 126) | 089·41 081·13 089·40 081·14 078·9 | 050·32 050·31 089·29 094·46 093·29 | 050·34 138·25 002·36 101·39 024·5 | 12/24/28 | THEME | The Use of Money's business passages instead of The Danger of Riches; "business" pulls BM25 to In What Sense we are to Leave the World |
| q-prayer | How should I pray when I am alone? What did Wesley say about private prayer? | ²026 +10¹ (016 024 025 026 046 089) | **016·37**¹ 091·39 **025·75**¹ 101·41 025·76 | **046·23**¹ 024·12 **089·21**¹ 101·41 **025·75**¹ | **025·75**¹ 101·41 **016·37**¹ **089·21**¹ **026·18**¹ | 1/1/1 | HIT |  |
| q-forgiveness | Someone hurt me and I cannot let it go. What did Wesley say about forgiving people who wrong us? | ²026 +4¹ (023 026 046) | 098·54 002·17 140·30 028·76 033·38 | **026·72**¹ **026·73**¹ 005·30 026·71⚑ 138·22 | **026·72**¹ 026·71⚑ **026·73**¹ 128·46 **026·3**² | 8/1/1 | HIT | 026-c0071 states the same condition ("if we forgive, and as we forgive") and is unlabelled |
| q-perfection-plain | Is it possible to stop sinning altogether and love God with my whole heart before I die, or will I always fall short? | ²040 +15¹ (019 040 042 043 076 083 085 110) | 005·6 001·3 081·39 **019·55**¹ 081·40 | 006·36 019·49 083·13⚑ 076·58⚑ 087·63 | **019·55**¹ 081·40 006·36 001·3 **043·54**¹ | 4/8/1 | HIT |  |
| q-heaviness-plain | I've felt low and weighed down for months, even though I still trust God. Is something wrong with me spiritually? | ²047 +16¹ (021 047 089) | 077·37 076·9 021·67 078·39 076·10 | 077·52 016·59 029·31 087·60 087·62 | 021·67 016·59 086·2 029·69 016·88 | –/27/59 | VOCAB | the rewrite removed "heaviness" (title word, by design), so "low, weighed down" has no lexical or semantic bridge to 047 |
| q-mourning-plain | My little boy passed away last month and I can't stop crying. How do I go on after losing a child? | ²135 +8¹ (047 135) | 001·50 095·36 021·77 096·23 093·36 | 095·36 **047·30**¹ 047·31 **135·24**¹ 099·52 | 095·36 133·40 095·35 095·37 137·41 | –/2/14 | LEX | dense has a labelled 047 chunk at 2 and a 135 chunk at 4; BM25 "child/little/crying" fills the hybrid list with On the Education of Children |
| q-satan-plain | Something keeps pulling me away from God and wearing me down until I want to give up. How do I stand firm? | ²042 +19¹ (019 042 046 047 072 078 082) | 119·15 137·71 030·53 077·36 110·22 | 016·80 **078·43**¹ **078·44**¹ 014·64 **082·54**¹ | 119·16 082·9 141·10 016·80 119·15 | –/2/6 | HIT |  |
| q-temptation-plain | I keep getting pulled toward something I know is wrong and I feel too weak to say no. Will God help me get through it? | ²082 +14¹ (014 029 040 068 072 078 080 082 085) | **082·54**¹ 082·53† 093·45 094·46 094·48 | 078·44 016·80 028·9 041·7 085·36 | **082·54**¹ 094·48 **085·37**¹ 078·44 016·80 | 1/11/1 | HIT | hit chunk 082-c0054 shares "get through" with the question |
| q-communion-plain | How often should I take the bread and the cup at church? Is a few times a year enough? | ²101 +16¹ (016 025 085 101) | 016·50 **025·73**¹ 101·47† **016·54**¹ **101·49**¹ | **101·2**¹ **101·50**¹ **101·49**¹ 101·12† **101·1**¹ | **101·49**¹ **025·73**¹ **101·50**¹ **025·74**¹ **025·88**¹ | 2/1/1 | HIT | hit chunk 101-c0049 shares "times a year" |
| q-means-plain | Do things like praying, reading the Bible and going to church actually help me get closer to God, or are they just habits? | ²016 +16¹ (004 016 037 043 084 092 098) | 116·17 027·49 027·50 053·56 016·79⚑ | 033·40 037·66 033·39 089·25 **084·33**¹ | 016·79⚑ 016·78⚑ 016·75† 045·72 **016·15**¹ | 33/5/5 | HIT | hybrid 1-3 are unlabelled 016 chunks that list the means ("hearing, reading, meditating, praying, and partaking of the Lord's Supper") |
| q-salvation-plain | I'll never be good enough for heaven no matter how hard I try. So how does anybody get right with God? | ²001 +19¹ (001 003 005 006 011 021 025 030 033 043 085 120) | 094·48 107·62 082·54 082·53 098·12 | **006·53**¹ **006·52**¹ 076·73 076·8 068·42 | **006·53**¹ 024·78 **006·52**¹ 032·10 093·29 | 7/1/1 | HIT | lenient only: 006-c0053 "not good enough"; grade-2 sermon 001 never in top 10 |
| q-justification-plain | Does God only accept good people, or will he forgive someone who has done terrible things? | ²005 +19¹ (001 005 006 011 019 020 035 043 053) | 026·3 140·42 116·0 129·49 032·4 | 026·72 **006·53**¹ 005·32⚑ 021·44 **005·29**¹ | **006·53**¹ **005·29**¹ 026·3 026·72 015·32 | 6/2/1 | HIT | 005-c0032 ("not a saint but a sinner that is forgiven") is unlabelled, dense 3 |
| q-faith-works-plain | If trusting Jesus is what puts me right with God, does it matter how I live or whether I help people? Do the things I do count for anything? | ²043 +14¹ (001 005 017 020 027 033 035 043 085 091 099 116) | 116·48 029·31 107·27 086·52 028·68 | 029·31 029·13 029·14 029·15 016·59 | 029·31 028·68 029·13 029·19 028·69 | 10/14/6 | HIT |  |
| q-new-birth-plain | People at church say I need God to give me a whole fresh start on the inside. What actually changes in a person when that happens? | ²045 +18¹ (001 014 018 019 043 045 083 107 125) | 104·18 044·56 024·72 099·27 107·12 | **045·37**¹ 125·21⚑ **045·72**¹ 087·60 093·44 | 044·56 010·42 125·21⚑ **125·22**¹ 014·72 | 12/1/4 | HIT | 125-c0021 ("This change ... is properly the new birth") unlabelled, hybrid 3 |
| q-sin-believers-plain | I gave my life to Jesus years ago but I still catch myself being proud and doubting. Does that mean I was never really saved? | ²013 +16¹ (008 013 014 043 072 082 083 123) | 082·26 123·13 120·35 123·12 065·35 | 042·51 017·16 016·40 014·53 **072·54**¹ | 120·35 006·21 042·51 120·36 006·22 | 28/5/7 | HIT |  |
| q-original-sin-plain | Are people good deep down and just pick up bad habits, or is something wrong with us from the very start? | ²044 +13¹ (013 044 045 053 095 123) | 096·31 076·9 129·14 130·14 076·10 | 102·17 093·32 050·35 105·8 102·3 | 076·9 093·32 082·17 124·16 028·79 | –/10/22 | VOCAB | "good deep down / bad habits" vs "every imagination of the thoughts of his heart was only evil"; best query/label overlap 0.10 |
| q-catholic-spirit-plain | My friend goes to a church that teaches very differently from mine. Can we still be close and work together without pretending our differences don't matter? | ²039 +22¹ (020 038 039 053 074 115) | 111·17 038·37 016·82 107·12 020·8 | **039·5**¹ 038·36⚑ 038·38 115·24 **039·26**¹ | 038·36⚑ 038·38 **039·5**¹ 038·37 038·31 | 12/1/3 | HIT |  |
| q-backsliders-plain | I walked away from God years ago. I want to come back, but I'm scared he won't have me. Is it too late? | ²086 +11¹ (008 024 068 086) | 131·47 087·69 131·9 112·12 102·33 | 019·43 098·28 019·42 087·61 133·96 | 084·17 133·63 080·7 080·8 019·43 | –/41/79 | VOCAB | signature term removed; BM25 "years ago" finds anecdotes (Late Work of God in North America, The Rich Man and Lazarus) |
| q-self-denial-plain | Do I really have to give up things I want in order to follow Jesus? How much is God asking me to let go of? | ²048 +12¹ (048 105 108) | 075·44 030·55 136·11 026·27 016·31 | 029·82 083·13 116·30 024·17 050·61 | 042·50 **048·43**¹ 116·30 **048·35**¹ 048·55† | 19/11/2 | HIT |  |
| q-wandering-thoughts-plain | When I pray, my mind keeps drifting off to my shopping list and my job. Is God upset with me for that? | ²041 +9¹ (041) | 052·10 052·11 052·45 127·29 127·30 | 101·41 029·69 **041·37**¹ 093·25 041·36† | 026·19 **041·48**¹ 014·30 016·58 105·47 | 25/3/2 | HIT |  |
| q-wilderness-plain | A few years ago I felt so close to God and full of joy. Now I feel empty and far away from him. What happened, and can I get that back? | ²046 +19¹ (021 028 046 138) | 131·9 133·22 133·21 130·14 133·13 | 087·62 045·33 **021·71**¹ **028·9**¹ 046·12⚑ | 045·33 084·17 087·62 131·9 133·22 | –/3/6 | HIT | 046-c0012 (loss of joy, peace) is unlabelled, dense 5 |
| q-evil-speaking-plain | Is it wrong to talk about a coworker behind their back if everything I say is true? | ²049 +10¹ (014 022 030 049 080) | 101·30 065·36 014·31 006·60 088·51 | 049·32† **049·2**² 075·50 099·10 049·20† | 014·31 081·51 095·64 081·50 038·67 | 22/2/8 | HIT | dense has the grade-2 chunk at 2; hybrid drops it to 8 (BM25 "behind", "back") |
| p-001 | I don't know how to pray anymore. It just feels like I'm talking to the ceiling and nothing comes back. | ²016 +7¹ (016 021 026 046 089 141) | **016·76**¹ 123·38 003·53 016·75† 003·54 | **026·27**¹ 089·24 **016·80**² 016·77† **026·18**¹ | **016·76**¹ 016·75† **016·80**² 041·47 026·2 | 1/1/1 | HIT |  |
| p-002 | my mom died last month and i cant stop crying at work. does the sad part ever get smaller | ²047 +5¹ (047 135) | 052·23 133·93 048·19 015·44 126·28 | 099·51 135·6 135·24⚑ 135·4⚑ 135·7⚑ | 078·39 002·42 028·62 009·34 **047·29**² | 79/8/5 | HIT | dense 2-5 are On Mourning for the Dead chunks, unlabelled for this question; 135-c0024 is labelled for q-mourning-plain |
| p-003 | We are so broke. I feel guilty buying the kids anything that isn't on sale. What are we supposed to do with money when there isn't enough? | ²050 +3¹ (029 050) | 050·41† 050·40† 140·36 050·21† 050·24† | 050·47† 028·76 088·32 028·78 050·48† | 050·42† 050·48† 050·41† 028·80 028·76 | –/27/60 | PASSAGE | top 5 are all from the grade-2 sermon 050 but about not spending on luxuries; the labelled passage (provide necessities first) is not reached |
| p-004 | sorry this is a mess. my wife says shes done trying and i dont even know what im asking i just dont want my family to fall apart | none (unanswerable) | 094·22 094·23 094·15 095·39 133·42 | 099·53 095·56 094·22 095·57 050·54 | 094·22 094·23 094·15 095·39 095·56 | –/–/– | UNANS | top hits are On Family Religion; no abstain check here |
| p-005 | I'm not even sure God is real anymore. I go on Sundays because my family does, but I feel like I'm faking it. | ²070 +2¹ (002 016) | 123·38 107·37 094·46 094·13 133·42 | 095·27 087·61 037·63 088·43 134·52 | 010·37 008·33 095·27 123·38 087·61 | –/–/– | AMBIG | doubt about God's existence; 3 thin labels (grade 2 in The Case of Reason); no ranker reaches a labelled sermon in top 10 |
| p-006 | theres something i did a long time ago that i never told anyone. i say ive moved on but i still feel dirty about it | ²008 +5¹ (005 006 007 008 046) | 077·36 014·7 014·8 077·35 082·32 | 035·46 **046·60**¹ 093·42 087·72 080·35 | 014·7 014·24 035·46 077·36 **046·60**¹ | –/2/5 | HIT |  |
| p-007 | I yelled at my kids again tonight and I saw the look on my daughter's face. I don't want to be this angry. | ²139 +6¹ (009 022 033 043 065) | 137·47 137·46 040·97 028·77 019·42 | 096·37 095·22 095·42 040·97 095·61 | 040·97 033·51⚑ 022·13⚑ 064·31 096·37 | –/7/14 | GRADE | hybrid 2-3 are 033-c0051 ("Beware ... of outward expressions of anger") and 022-c0013 (anger at persons contrary to love), both unlabelled in sermons that hold other labels for this question |
| p-008 | i told everyone i quit drinking and then i bought a bottle on the way home. i dont know why i keep doing this | ²065 +3¹ (009 078) | 061·22 101·26 090·36 090·35 020·46 | 065·36⚑ 065·37† 050·24 052·44 050·23 | 101·35 101·26 053·67 101·34 101·27 | –/45/86 | LEX | dense 1-2 are 065 (the grade-2 sermon) drunkard passages; BM25 "drinking" matches "eating and drinking unworthily" in The Duty of Constant Communion |
| p-009 | I can be in a full room at church and still feel completely alone. I don't have one person I could call. | ²107 +1¹ (028) | 073·14 134·13 116·18 045·32 107·1† | 024·12⚑ 024·18 024·11⚑ 081·59 074·24 | 074·21 104·3 104·2 132·19 024·12⚑ | –/18/37 | GRADE | dense 1-3 / hybrid 5 are 024 "Christianity is essentially a social religion" passages, unlabelled |
| p-010 | work has taken over my whole life and im still behind. is it bad that i daydream about quitting and disappearing for a while | ²050 +3¹ (024 079 089) | 129·17 015·22 112·49 086·54 046·40 | 078·9 050·34† 050·33† 093·13 **024·13**¹ | 077·35 138·25 078·9 129·17 050·34† | –/5/11 | LEX | dense has a labelled chunk at 5; BM25 "while", "taken", "whole life" pulls in Earthquakes and The Great Assize |
| p-011 | They found something on the scan and I have to wait two weeks to know how bad it is. I can't sleep. What do I even say to God? | ²089 +4¹ (028 029 082 098) | 093·13 093·6 132·8 007·12 105·7 | 003·5 093·12 140·34 133·76 093·31 | 133·76 093·23 078·42 133·75 003·5 | –/6/14 | LEX | BM25 "sleep" pulls On Redeeming the Time; dense labelled at 6 |
| p-012 | my son is 15 and he wont talk to me. if i ask about school he shuts the door. i feel like im losing him | ²094 | 026·1 094·45† 031·38 026·22 031·39 | 133·40 094·32† 094·40† 096·23 096·50 | 094·40† 030·54 094·41† 094·45† 094·42† | –/–/– | AMBIG | one label only; top 5 are all from the grade-2 sermon 094 but about choosing a school; the answer is thin |
| p-013 | Someone at church told people something about me that isn't true, and now half the room is weird with me. They still smile. Do I have to just let it go? | ²049 +3¹ (026 038 083) | 077·35 134·25 053·12 094·55 053·11 | 032·39 049·11⚑ 032·45 081·41 100·19 | 094·54 098·53 032·39 077·35 049·11⚑ | –/42/84 | GRADE | 049-c0011 holds the same Matt 18:15 text as the grade-2 quote, which begins "First," and so matches only 049-c0013; dense 2, hybrid 5 |
| p-014 | im scared of dying. like actually scared, not just wondering. i think about it when i try to fall asleep | ²137 +4¹ (007 009 028 062) | 114·15 123·44 046·70 002·10 133·83 | 054·32 121·37 041·43 014·35 068·65 | 121·37 112·61 009·66 082·2 133·83 | –/9/22 | VOCAB | "scared of dying" vs "fear of death" (overlap 0); BM25 "fall asleep" noise; dense labelled at 9 |
| p-015 | God feels far. I used to feel something when I prayed and now it's just quiet, and I don't know if I did something wrong. | ²046 +5¹ (046 077 138) | 120·29 076·9 043·41 014·7 014·15 | 045·33 026·27 028·9⚑ 089·24 087·60 | 045·33 016·79 014·15 045·32 077·55 | 93/–/– | VOCAB | "God feels far / just quiet" vs Wesley's "darkness", "desertion", "doubts and fears"; dense has no labelled chunk and no chunk from the expected sermon (046); dense 3 is 028-c0009 ("how soon is our foolish heart darkened ... doubts and fears"), labelled grade 1 for q-wilderness-plain but not here, and not in the hybrid top 10 |
| p-016 | help i messed up bad | ²006 +8¹ (006 008 021 024 059 086) | (no rows) | 124·15 087·65 099·53 134·59 107·60 | 124·15 087·65 099·53 134·59 107·60 | –/18/18 | AMBIG | four words, so FTS ANDs them: BM25 returns 0 rows; dense finds a labelled chunk at 18 |
| p-017 | why wont he answer | ²030 +5¹ (016 030 047) | 086·26 086·25 | 082·48 014·60 053·72 101·18 101·41 | 082·48 086·26 014·60 086·25 053·72 | –/–/– | AMBIG | "he" is unresolved; FTS ANDs "wont" and "answer", and "wont" matches archaic "are wont to" in A Call to Backsliders |
| p-018 | Can God forgive me if I don't feel sorry the way people say I should? I mostly just feel numb. | ²006 +4¹ (005 008 011 043) | 040·97 014·15 043·11 014·14 094·13 | 026·72 005·30 026·73 021·44 021·66 | 021·44 026·72 098·54 043·9 027·87 | –/32/66 | THEME | "forgive" pulls forgiving-others passages (Sermon on the Mount 6) instead of 006 "not contrite enough" |
| p-019 | i get jealous of my friends and their vacations and then i hate that this is who i am | ²139 +3¹ (013 014 022) | 039·43 039·1 141·56 099·9 133·71 | 135·13 135·14 141·52 080·41 037·27 | 046·32 080·23 046·31 096·39 080·30 | –/79/– | VOCAB | modern "jealous" is Wesley's "envy"; his "jealous over ourselves" (watchful) is a false friend (080-c0023 in hybrid) |
| p-020 | My dad was mean when I was little. Now I have a baby and I'm scared I'm going to turn into him. | ²094 | 123·38 114·15 108·29 014·81 023·76 | 096·24 133·40 133·39 095·66 110·31 | 023·81 096·24 123·38 133·40 114·15 | –/60/– | AMBIG | one label, a stretch; dense returns On Obedience to Parents ("spare the rod") |
| p-021 | ive been praying for my sister for months and she just keeps getting worse. im starting to feel stupid for asking | ²030 +5¹ (016 022 024 030 098) | 004·58 041·36 105·33 016·78 **022·77**¹ | 041·48 089·23 023·81 016·80⚑ 096·47 | 025·75 016·80⚑ 076·67 016·79 026·27 | 5/37/16 | GRADE | hybrid 2 is 016-c0080 "always to pray and not to faint" (grade 2 for p-001), unlabelled here |
| p-022 | Our church is splitting into sides and people are talking about each other. I love these people but I don't want to pick a team. | ²075 +5¹ (023 039 049 053) | 028·77 074·1 053·78 088·45 068·33 | 075·26⚑ 075·25† 075·47† **075·48**² 104·49 | 132·46 075·3† 115·27 074·1 075·2† | 7/4/17 | LEX | dense 1-4 are On Schism with the grade-2 chunk at 4; BM25 "church", "talking", "sides" pulls Of the Church / separation passages; 075-c0026 is also plausible |
| p-023 | i work sunday mornings so we can pay rent. i miss church and i feel guilty and i also cant quit the shift | none (unanswerable) | 134·37 132·17 134·36 053·17 107·37 | 093·22 093·32 093·31 101·41 068·50 | 134·37 134·38 107·37 115·30 093·38 | –/–/– | UNANS |  |
| p-024 | i keep looking at stuff on my phone late at night that i shouldnt. i delete the apps and then i put them right back. i feel gross | ²023 +4¹ (008 009 046 048) | 047·23 121·17 084·17 133·47 034·66 | 093·14 093·13 093·42 093·31 134·40 | 113·43 014·15 093·37 093·14 047·23 | 37/–/77 | VOCAB | euphemism ("stuff on my phone") with no Wesley wording (lust, unclean); dense goes to sleep/time passages |
| p-025 | My doctor put me on medicine for anxiety and a lady at church said that means I'm not trusting God. I still take the pill. Am I wrong? | ²047 +2¹ (047 077) | 016·58 065·36 016·59 141·63 120·29 | 016·59 072·54 016·58 067·60 059·28 | 016·59 016·58 016·57 052·99 067·60 | –/9/21 | VOCAB | "medicine/pill" vs "natural causes still produce natural effects"; dense labelled at 9, hybrid 21 |
| p-026 | cant stop scrolling tiktok at like 2am and then i feel like everyone else has a better life. is that just me being weak | ²093 +2¹ (089 093) | 140·10 065·27 140·9 141·8 098·54 | 093·42† 068·50 134·40 093·14† 050·15 | 078·39 077·35 093·42† 140·10 068·50 | –/–/– | PASSAGE | dense 1 and hybrid 3 are 093 (the grade-2 sermon) chunks, but not the labelled passage; "tiktok", "scrolling" have no Wesley analogue |
| p-027 | I met a guy on a dating app and we might get serious. Is that a bad way to find someone to marry, or is it fine? | ²081 +3¹ (037 080) | 031·3 094·48 094·47 031·4 021·45 | 080·42⚑ 080·51 080·52 100·14 052·83 | 118·33 023·12 133·20 100·8 081·35† | –/40/81 | GRADE | dense 1 is 080-c0042: Wesley's marriage-to-an-unbeliever snare, unlabelled (080 holds a grade-1 label) |
| p-028 | im scared about the climate and that my kids wont get a normal future. i lie awake thinking about fires and floods. what do i do with that | ²029 +4¹ (029 033 067) | 130·28 064·32 064·31 060·46 093·10 | 129·41 129·42 140·13 **029·63**² 129·39 | 129·39 093·10 003·4 129·48 073·18 | –/4/18 | LEX | dense has the grade-2 chunk at 4; BM25 "fires", "floods", "lie awake" pulls Earthquakes, Of Hell, Redeeming the Time |
| p-029 | My company is replacing people with AI and I might not have a job next year. How do I stop panicking? | ²029 +4¹ (029 052) | 107·26 132·20 131·28 131·25 131·24 | 050·33 050·14 050·34 050·13 127·27 | 127·27 081·39 127·0 050·33 107·26 | –/47/95 | THEME | "job" pulls The Use of Money employment passages, not 029 "uneasy care" |
| p-030 | is it ok if church is just me watching the livestream in bed. i havent actually gone in months and i kinda dont want to | ²025 +2¹ (024 048) | 122·31 013·69 084·48 122·32 027·18 | 024·12⚑ 024·13 093·22 081·59 027·76 | 115·30 093·22 025·73† 046·40 014·29 | –/10/23 | GRADE | hybrid 6 is 024-c0012 (social religion, unlabelled); 024 social-religion chunks at dense 1-2 (unlabelled); dense labelled at 10; BM25 "bed", "months" noise |

## 3. Category counts (shipped hybrid, lenient)

| category | `plain` (n=25) | `plain-blind` (n=30: 28 answerable + 2 unanswerable) |
| --- | --- | --- |
| HIT (labelled chunk in top 10) | 18 | 3 |
| LEX: BM25 false friend, fusion buries dense's hit | 1 | 5 |
| VOCAB: vocabulary gap | 4 | 5 |
| GRADE: suspected grading gap | 0 | 6 |
| AMBIG: ambiguous, too short, or thin answer | 0 | 5 |
| THEME: wrong sermon, same theme | 2 | 2 |
| PASSAGE: right sermon, other passage | 0 | 2 |
| CHUNK: chunk too long or short | 0 | 0 |
| UNANS (not scored) | – | 2 |
| **misses** | **7** | **25** |

Mechanical signals behind the categories (`stats.py`):

| signal | `plain` | `plain-blind` |
| --- | --- | --- |
| lenient hit@10, BM25 / dense / hybrid | 8 / 17 / 18 | 3 / 11 / 3 |
| fusion loss (dense top 10 hit, hybrid not) | 2 | **8** |
| fusion gain (hybrid top 10 hit, dense not) | 3 | 0 |
| median best query/label stem overlap | 0.31 | 0.15 |
| questions with zero overlap with every label | 0 | 6 |
| median labels per question | 17 | 5 |
| median labelled chunk length (words) | 123.5 | 123 |

The corpus median chunk length is 122 words.

**Why LEX and fusion matter more on blind questions.**

- The blind questions imitate how people type: an LLM (Grok) wrote them lowercase, run-on and full of situational words. That is an LLM's imitation of how people type, not questions typed by people.
- `to_fts_query` ORs every non-stopword. That includes "keep", "get", "feel", "like", "still", "back", "years", and "ago", none of which are in `fts.STOP`.
- BM25 then rewards Wesley's anecdotes and memoirs, which are full of exactly those words:
  - "years ago" leads to *The Late Work of God in North America* and the Whitefield and Fletcher memoirs.
  - "lie awake" leads to *On Redeeming the Time*.
  - "drinking" leads to "eating and drinking unworthily".
- Removing a filler list alone barely helps (exploratory V5: blind +0.04). The noise is in content words too ("fires", "floods", "face", "bed"). What helps is giving the BM25 list less say on this query shape (§5).

**Vocabulary examples.**

| question wording | Wesley's wording |
| --- | --- |
| "scared of dying" | "fear of death" |
| "jealous" | "envy" (his "jealous" means watchful) |
| "medicine", "pill" | "natural causes still produce natural effects" |
| "fretting about bills" | "take no thought for the morrow", "uneasy care" |
| "good deep down" | "only evil continually" |
| "stuff on my phone" | (no 18th-century analogue) |

Dense recovers some of these (p-014 at rank 9, p-025 at 9), but not into the top 5.

**Short queries.**

- `p-016` "help i messed up bad" has four content terms, so FTS ANDs them and BM25 returns **0 rows**. Hybrid falls back to dense, which finds a labelled chunk at 18.
- `p-017` "why wont he answer" ANDs "wont" and "answer". It matches the archaic "are wont to" in *A Call to Backsliders*.

These are AMBIG in the table; the AND rule itself is documented behaviour (`src/preached/fts.py`), not a bug.

## 4. Suspected grading gaps (for Patrick; NOT regraded)

**Patrick: do the #43 label pass before reading this section.** Its leaning notes ("weaker", "already grade N") would bias your verdicts.

These unlabelled chunks are in a top 5 above and, in my reading, plausibly meet the bar in `eval/pool/BRIEF.md`. I have changed nothing. Each needs Patrick's call. The flags are Claude's judgment, and Claude is the same model family that proposed every `plain-blind` label, so a flag and the label it questions are not independent readings. Only Patrick's verdicts are.

The "why it looks acceptable" column and its leaning words ("weaker", "already grade N", "already a HIT") are for the director and CTO only. They stay out of anything the labeller sees; PR #43's blind sheet covers that. The #43 sheet `reports/W3-LABEL-SHEET.csv` at `8ee909f` has blank verdict and notes columns and none of these phrases. The only matches for "already" or "acceptable" are inside Wesley's own chunk text.

| question | chunk | why it looks acceptable | where it ranks |
| --- | --- | --- | --- |
| p-007 (yelling at kids, anger) | `wesley-033-c0051` | "Beware, not only of outward expressions of anger ... but of every inward emotion contrary to love" | hybrid 2 |
| p-007 | `wesley-022-c0013` | "if anger at persons be a temper contrary to love, how can there be a cause ... that will justify it" | hybrid 3 |
| p-009 (alone at church) | `wesley-024-c0011`, `-c0012` | "Christianity is essentially a social religion ... to turn it into a solitary religion, is indeed to destroy it" | dense 1–3, hybrid 5 |
| p-013 (lied about at church) | `wesley-049-c0011` | Contains the same Matt 18:15 text as the grade-2 quote. The quote starts with `First, "If thy brother...`, so it only matches `049-c0013`. **This is a quote-matching artefact, not a judgment.** | dense 2, hybrid 5 |
| p-015 (God feels far) | `wesley-028-c0009` | "how soon is our foolish heart darkened! ... Doubts and fears again overwhelm us". **Already grade 1 for `q-wilderness-plain`.** | dense 3 |
| p-021 (praying for sister, worse) | `wesley-016-c0080` | "pour out his soul before God; 'always to pray and not to faint'". **Already grade 2 for `p-001`.** | hybrid 2 |
| p-027 (dating app, marriage) | `wesley-080-c0042` | "the person I am about to marry is not a religious person ... This is a snare indeed!" | dense 1, hybrid 7 |
| p-030 (livestream instead of church) | `wesley-024-c0012` | social religion, as above | dense 1, hybrid 6 |
| p-002 (mother died, crying) | `wesley-135-c0004`, `-c0007`, `-c0024` | *On Mourning for the Dead*. `c0024` is **already grade 1 for `q-mourning-plain`.** | dense 2–5 (question is already a HIT) |
| p-008 (drinking relapse) | `wesley-065-c0036` | Wesley's Moorfields drunkard, "I believe he got drunk no more ... do not despise poor drunkards!" (weaker: addressed to the reprover) | dense 1 |
| p-022 (church splitting) | `wesley-075-c0026` | "nothing can divide those whom love has united ... want of love is always the real cause" | dense 1 |
| q-means-plain | `wesley-016-c0078`, `-c0079` | "continues in God's way, in hearing, reading, meditating, praying, and partaking of the Lord's Supper, till God ... speaks to his heart" | hybrid 1–2 (already a HIT) |
| q-justification-plain | `wesley-005-c0032` | "it is not a saint but a sinner that is forgiven ... God justifieth not the godly, but the ungodly" | dense 3 (already a HIT) |
| q-new-birth-plain | `wesley-125-c0021` | "This change, from spiritual death to spiritual life, is properly the new birth" | hybrid 3 (already a HIT) |
| q-wilderness-plain | `wesley-046-c0012` | loss of joy and peace, in the grade-2 sermon | dense 5 (already a HIT) |
| q-forgiveness | `wesley-026-c0071` | "All our trespasses and sins are forgiven us, if we forgive, and as we forgive, others" | dense 4 (already a HIT) |
| q-catholic-spirit-plain | `wesley-038-c0036` | differences in administering ordinances need not divide (weaker) | hybrid 1 (already a HIT) |
| q-perfection-plain | `wesley-083-c0013`, `wesley-076-c0058` | "perfect love of God", "loving the Lord your God with all your heart" (weaker) | dense 3–4 (already a HIT) |
| q-money-plain | `wesley-089-c0027` | "His end in all his labour is, to please God ... with diligence" (weaker) | dense 1 |

**What-if, not a result.** Count every flagged chunk as acceptable and recompute lenient hit@10:

| ranker | `plain-blind` (post-hoc, not held out), now → with flags | `plain`, now → with flags |
| --- | --- | --- |
| shipped hybrid | 3 → 9 of 28 | 18 → 19 of 25 |
| dense | 11 → 17 of 28 | 17 → 18 of 25 |

The blind 0.107 is therefore partly sparse labelling. **The ranking problem in §3 is still real**: even with every flag counted, dense beats hybrid on blind questions.

**Two consistency issues worth one rule each.**

1. *Cross-question inconsistency.* The same chunk is labelled for one question and not for a near-duplicate:
   - `135-c0024`: q-mourning-plain vs p-002.
   - `028-c0009`: q-wilderness-plain vs p-015.
   - `016-c0080`: p-001 vs p-021.

   A review pass could show Patrick, for each blind question, the labels already given to its nearest `plain` sibling.
2. *Quote-boundary artefact (p-013).* A quote that begins with a list marker ("First,") fails to match another chunk carrying the same scripture. `eval/validate.py` could warn when a grade-2 quote minus its first two words matches more chunks than the full quote does. That is a proposal only; nothing was changed.

## 5. Eval-validity notes (Patrick's standard: test capability, not leak titles)

- **No title leakage found in `plain-blind`.** An LLM agent (Grok) wrote the questions before it read the corpus. The one title word (`p-003` "money") was already noted in EVAL-GRADE.
- **`plain` rewrites: pooling bias, not author leakage.**
  - In 4 of the 23 rewrites, the question shares a two-word phrase with one of its *grade-1* quotes:
    - `q-communion-plain` "times a year" ~ `101-c0048/49` "three times a year".
    - `q-salvation-plain` "good enough" ~ `006-c0052/53`.
    - `q-temptation-plain` "get through" ~ `082-c0054`.
    - `q-satan-plain` "give up" ~ `042-c0030/50`.
  - In the first three, that chunk is the hybrid's rank-1 hit.
  - Those grade-1 labels were added *after* the rewrites, by pooling the rankers' top 20. So the question author did not see them. The rankers surfaced them through the shared phrase, and the grader then accepted them.
  - The leak lint only checks grade-2 quotes. This bias inflates `plain` lenient hit@10 (0.72) a little. The fix is a lint note on grade-1 overlaps, not a rewrite.
- **Label density differs by group** (median 17 vs 5). Comparisons *across* groups (`plain` 0.72 vs blind 0.11) mix ranking quality with how wide the labels are. Compare rankers within a group.
- **Ambiguous or thin blind items:**
  - `p-016` and `p-017` are 4-word fragments with an unresolved "he". Fine as a robustness probe; poor as a passage-ranking item.
  - `p-012` and `p-020` have one label each, and the grade 2 is a stretch.
  - `p-005` has 3 labels and its grade 2 is in *The Case of Reason Impartially Considered*.

  Patrick may want to keep them but report them separately, or mark them `ambiguous`.
- **Small n.** 28 blind and 25 `plain` questions: one question moves a group mean by 0.04. All differences below come with paired-bootstrap 95% intervals (`preached.stats.paired_bootstrap`, the bench's own).
- **I read every blind failure before designing the experiments.** So no `plain-blind` number in §6 is held out, for any variant: V3, V4, V10 and V11 as much as the starred V7 and V12. Every one is post-hoc. The OR-shape rule behind V10 and V11 is close to a "long question" detector, and the blind questions are the long ones (26 of 28 answerable ones take the OR form). From here on `plain-blind` can only serve as an in-sample check. The confirmatory test is a fresh blind set (§7 #1 step d).

## 6. Exploratory experiments (scratch only, NOT product code)

Exploratory numbers, from `reports/w3-retrieval-diag/experiments.py`:

- Granite English R2 on CPU, raw ranker top 10, same labels and `bench.score` as `search/bench.py`.
- Each cell is lenient hit@10 / lenient nDCG@10, with the paired Δ hit@10 against V0, its 95% CI, and wins/ties/losses.
- V0 reproduces the bench exactly.
- `*` marks a variant that uses a question-derived lexicon (V7, V12: the archaic map was written after reading the questions). This is separate from post-hoc. **Every** variant was designed after I had read every blind failure (§5), so every `plain-blind` cell below is post-hoc, not held out, starred or not.
- Multiplicity: 12 variants (V1 to V12) compared with V0 across 6 groups, with the best picked afterwards. The 95% intervals are not adjusted for this.


Variant definitions:

| variant | what it does |
| --- | --- |
| V0 | Shipped hybrid: RRF k=60, equal weights. |
| V1, V2 | Dense only; BM25 only. |
| V3, V4 | RRF with BM25 weight 0.5 or 0.25, for every query. |
| V5 | Adds a generic colloquial filler list to the FTS stopwords ("keep", "get", "feel", "like", "still", ...). |
| V6 | V5 plus BM25 weight 0.5. |
| V7\* | V5 plus a hand-written modern→18th-century synonym list appended to the BM25 query only ("scared"→"fear afraid", "jealous"→"envy", "drinking"→"drunkenness drunkard", ...). I wrote the list after reading the questions, so it is contaminated. |
| V8, V9 | Dense score plus 0.5 × the mean of the two neighbouring chunks' scores (a cheap "longer chunk" probe, no re-embedding), fused with BM25 or alone. |
| V10 | BM25 weight 0.5 **only when `to_fts_query` builds an OR query** (more than 4 content terms, no scripture reference). AND and NEAR keyword queries keep weight 1. |
| V11 | As V10, with weight 0.25. |
| V12\* | V10 plus V7's expansion. |

Results table:

| variant | plain (n=25) | plain-blind (n=28; post-hoc, not held out) | names-topic (n=23) | title-keyword (n=3) | scripture-keyword (n=7) | all (n=86) |
| --- | --- | --- | --- | --- | --- | --- |
| V0 hybrid_rrf (shipped) | 0.720 / 0.132 | 0.107 / 0.027 | 0.957 / 0.402 | 1.000 / 0.544 | 1.000 / 0.513 | 0.616 / 0.216 |
| V1 dense only | 0.680 / 0.155 (-0.04 [-0.20, +0.12] 2/20/3) | 0.393 / 0.073 (+0.29 [+0.14, +0.46] 8/20/0) | 0.913 / 0.338 (-0.04 [-0.22, +0.09] 1/20/2) | 1.000 / 0.661 (+0.00 [+0.00, +0.00] 0/3/0) | 0.857 / 0.394 (-0.14 [-0.43, +0.00] 0/6/1) | 0.674 / 0.215 (+0.06 [-0.03, +0.15] 11/69/6) |
| V2 bm25 only | 0.320 / 0.037 (-0.40 [-0.60, -0.20] 0/15/10) | 0.107 / 0.011 (+0.00 [-0.14, +0.14] 2/24/2) | 0.913 / 0.279 (-0.04 [-0.13, +0.00] 0/22/1) | 1.000 / 0.462 (+0.00 [+0.00, +0.00] 0/3/0) | 1.000 / 0.486 (+0.00 [+0.00, +0.00] 0/7/0) | 0.488 / 0.145 (-0.13 [-0.21, -0.05] 2/71/13) |
| V3 rrf, bm25 weight 0.5 | 0.760 / 0.149 (+0.04 [+0.00, +0.12] 1/24/0) | 0.286 / 0.054 (+0.18 [+0.04, +0.32] 5/23/0) | 0.957 / 0.395 (+0.00 [-0.13, +0.13] 1/21/1) | 1.000 / 0.590 (+0.00 [+0.00, +0.00] 0/3/0) | 0.857 / 0.487 (-0.14 [-0.43, +0.00] 0/6/1) | 0.674 / 0.227 (+0.06 [-0.01, +0.13] 7/77/2) |
| V4 rrf, bm25 weight 0.25 | 0.760 / 0.150 (+0.04 [+0.00, +0.12] 1/24/0) | 0.357 / 0.066 (+0.25 [+0.11, +0.43] 7/21/0) | 0.913 / 0.377 (-0.04 [-0.22, +0.09] 1/20/2) | 1.000 / 0.605 (+0.00 [+0.00, +0.00] 0/3/0) | 0.857 / 0.490 (-0.14 [-0.43, +0.00] 0/6/1) | 0.686 / 0.227 (+0.07 [-0.01, +0.15] 9/74/3) |
| V5 rrf, bm25 filler stopwords | 0.720 / 0.137 (+0.00 [-0.12, +0.12] 1/23/1) | 0.143 / 0.022 (+0.04 [+0.00, +0.11] 1/27/0) | 0.957 / 0.407 (+0.00 [+0.00, +0.00] 0/23/0) | 1.000 / 0.544 (+0.00 [+0.00, +0.00] 0/3/0) | 1.000 / 0.513 (+0.00 [+0.00, +0.00] 0/7/0) | 0.628 / 0.216 (+0.01 [-0.02, +0.06] 2/83/1) |
| V6 V5 + bm25 weight 0.5 | 0.720 / 0.143 (+0.00 [-0.12, +0.12] 1/23/1) | 0.286 / 0.048 (+0.18 [+0.04, +0.32] 5/23/0) | 0.957 / 0.397 (+0.00 [-0.13, +0.13] 1/21/1) | 1.000 / 0.590 (+0.00 [+0.00, +0.00] 0/3/0) | 0.857 / 0.487 (-0.14 [-0.43, +0.00] 0/6/1) | 0.663 / 0.224 (+0.05 [-0.02, +0.12] 7/76/3) |
| V7 rrf, bm25 archaic expansion* | 0.800 / 0.164 (+0.08 [-0.08, +0.24] 3/21/1) | 0.250 / 0.042 (+0.14 [+0.04, +0.29] 4/24/0) | 0.957 / 0.402 (+0.00 [+0.00, +0.00] 0/23/0) | 1.000 / 0.544 (+0.00 [+0.00, +0.00] 0/3/0) | 1.000 / 0.513 (+0.00 [+0.00, +0.00] 0/7/0) | 0.686 / 0.230 (+0.07 [+0.01, +0.14] 7/78/1) |
| V8 rrf, dense neighbour-smoothed | 0.680 / 0.132 (-0.04 [-0.16, +0.08] 1/22/2) | 0.143 / 0.032 (+0.04 [+0.00, +0.11] 1/27/0) | 0.913 / 0.391 (-0.04 [-0.13, +0.00] 0/22/1) | 1.000 / 0.589 (+0.00 [+0.00, +0.00] 0/3/0) | 1.000 / 0.546 (+0.00 [+0.00, +0.00] 0/7/0) | 0.605 / 0.218 (-0.01 [-0.06, +0.03] 2/81/3) |
| V9 dense neighbour-smoothed only | 0.720 / 0.154 (+0.00 [-0.16, +0.16] 2/21/2) | 0.214 / 0.052 (+0.11 [-0.04, +0.25] 4/23/1) | 0.957 / 0.343 (+0.00 [-0.13, +0.13] 1/21/1) | 1.000 / 0.650 (+0.00 [+0.00, +0.00] 0/3/0) | 0.857 / 0.387 (-0.14 [-0.43, +0.00] 0/6/1) | 0.640 / 0.207 (+0.02 [-0.06, +0.10] 7/74/5) |
| V10 rrf, bm25 0.5 on OR-queries | 0.760 / 0.149 (+0.04 [+0.00, +0.12] 1/24/0) | 0.286 / 0.054 (+0.18 [+0.04, +0.32] 5/23/0) | 0.957 / 0.395 (+0.00 [-0.13, +0.13] 1/21/1) | 1.000 / 0.544 (+0.00 [+0.00, +0.00] 0/3/0) | 1.000 / 0.513 (+0.00 [+0.00, +0.00] 0/7/0) | 0.686 / 0.227 (+0.07 [+0.01, +0.14] 7/78/1) |
| V11 rrf, bm25 0.25 on OR-queries | 0.760 / 0.150 (+0.04 [+0.00, +0.12] 1/24/0) | 0.357 / 0.066 (+0.25 [+0.11, +0.43] 7/21/0) | 0.913 / 0.377 (-0.04 [-0.22, +0.09] 1/20/2) | 1.000 / 0.544 (+0.00 [+0.00, +0.00] 0/3/0) | 1.000 / 0.513 (+0.00 [+0.00, +0.00] 0/7/0) | 0.698 / 0.227 (+0.08 [+0.01, +0.15] 9/75/2) |
| V12 V10 + archaic expansion* | 0.800 / 0.170 (+0.08 [-0.08, +0.24] 3/21/1) | 0.286 / 0.052 (+0.18 [+0.04, +0.32] 5/23/0) | 1.000 / 0.398 (+0.04 [+0.00, +0.13] 1/22/0) | 1.000 / 0.544 (+0.00 [+0.00, +0.00] 0/3/0) | 1.000 / 0.513 (+0.00 [+0.00, +0.00] 0/7/0) | 0.709 / 0.233 (+0.09 [+0.02, +0.16] 9/76/1) |

Readings:

- **Fusion weight is the lever.** V3/V4 lift blind hit@10 by +0.18 or +0.25 with 0 losses (post-hoc, not held out). Applied to every query, they cost one scripture-keyword question (−1 of 7).
  - V10/V11 apply the weight to the OR query shape only. They keep scripture and title keyword queries unchanged and give the same blind lift. On the blind questions that is by construction: 26 of the 28 take the OR form, where V10 is V3. Of the other two, `p-016` gets no BM25 rows, and `p-017` (AND form) has identical top-10 scores under both. So every blind cell of V10 equals V3's, and V11's equals V4's. The same holds on `plain` and names-topic, where every query is OR-form.
  - V11 (0.25) costs 2 names-topic questions; V10 (0.5) is a 1/21/1 tie there.
  - V10 wins: q-money, q-mourning-plain, p-007, p-010, p-011, p-022, p-028. Loss: q-worry.
- **Expansion adds little on top of reweighting.** Blind is 0.286 for both V10 and V12. Alone (V7) it helps less than reweighting, and its numbers are contaminated.
- **Neighbour smoothing (V8/V9) and filler stopwords alone (V5) do not move anything outside noise.**
- **Granite query prefixes (dense only, `prefixes.py`; the card says no prefix).**

  | query prefix | `plain` lenient hit@10 | blind lenient hit@10 (post-hoc, not held out) |
  | --- | --- | --- |
  | none | 0.68 | 0.393 |
  | `query: ` | 0.72 | 0.250 |
  | `question: ` | 0.68 | 0.321 |
  | Arctic-style | 0.72 | 0.107 |

  This is the overfitting trap in miniature: tuned on `plain`, a prefix would look like a win and would hurt the blind questions. Keep the card's format.
- **Not run:**
  - Any reranker: none is in `/cache/huggingface`, and the task forbids new downloads.
  - The `--dedupe` (API) path.
  - The abstain rule under any variant.

## 7. Proposals, ranked

Prerequisite for all of them: Patrick's label pass on §4. Otherwise every comparison on blind questions runs against labels with a median of 5 per question.

**1. Query-shape-aware fusion weight (V10).**

| | |
| --- | --- |
| What | In `Searcher.hybrid`, pass `weights=[1.0, 0.5]` to `reciprocal_rank_fusion` when `to_fts_query(query)` is the OR form. AND and NEAR stay at `[1, 1]`. This is a few lines. `rank.reciprocal_rank_fusion` already takes `weights`. |
| Expected effect | Exploratory: blind lenient hit@10 0.107→0.286 (+0.18 [+0.04, +0.32]; post-hoc, not held out); `plain` +0.04; names-topic tie; keyword groups unchanged; overall +0.07 [+0.01, +0.14], 7 wins and 1 loss. Best of 12 variants across 6 groups, no interval adjustment; on blind questions V10 equals V3 by construction. |
| Cost | No dependencies, no RSS, no latency: the same two lists, different sums. |
| Overfitting risk | Low to moderate. One parameter on a 2-point grid (0.5, 0.25), fixed before the run. But I had read the blind failures, and the hypothesis came from EVAL-GRADE's dense-vs-hybrid result on the same questions. The OR-shape rule is close to a long-question detector, and the blind questions are the long ones. |
| Side effects to check | The abstain rule uses BM25/dense agreement and a dense floor (`search/abstain.toml`). Rerun `bench.py --abstain` on both paths, plus `--dedupe`. Do not refit the floor on proposed labels. |
| Honest test | (a) Freeze the grid {0.5, 0.25} and the OR-shape rule in a committed note **before** running. This is the PR #43 pre-registration, `reports/W3-FUSION-PREREG.md`: grid and rule frozen in their own commit, and labels re-frozen after Patrick's pass and before any run. (b) Select on `plain` + `names-topic` + keyword groups only, breaking ties toward the milder weight. On this data that gives 0.5. (c) Report `plain-blind` only as an in-sample check. It is **not** a held-out number for V10 or any §6 variant: V10's blind result is already computed and published above, and I read every blind failure before designing the variants. (d) **The confirmatory test**, required before any accuracy claim and not only before shipping: a fresh blind set of 20–30 questions, frozen and committed before any ranker runs on it. It is written by a person or by an LLM that has not seen the corpus, and if an LLM writes it, it is disclosed as LLM-written (a `provenance` field, as on `plain-blind`). |

**2. BM25 query hygiene and archaic expansion.**

| | |
| --- | --- |
| What | (a) A filler stoplist for the OR form only. (b) A modern→18th-century synonym map for the BM25 query only. |
| Expected effect | Alone, small (V5 ≈ 0; V7\* blind +0.14). On top of #1, about +0.04 on `plain` and names-topic and nothing on blind (V12\*). It would mostly help BM25-only mode, which the page offers. |
| Cost | Zero dependencies, microseconds. |
| Overfitting risk | **High.** The map is trivially fitted to the eval questions, and false friends are real ("jealous", "wont"). |
| Honest test | Build the map without the eval set: from a general modern/KJV glossary, or automatically, by mapping modern words that are frequent in questions but rare in the corpus to their nearest corpus words by Granite cosine. Have someone who has not read the questions freeze it. Evaluate once on the fresh blind set (#1 step d); `plain-blind` is an in-sample check only. Rank below #1 because #1 gets the same blind lift with less risk. |

**3. Cross-encoder reranker on the top 30–50 candidates.**

| | |
| --- | --- |
| What | Rerank the top 30–50 candidates (hybrid V10 or dense) with a cross-encoder. Untested here: no reranker is cached. |
| Candidates | Only models with a clean lineage under AGENTS.md §3, checked by base and teacher model, not just by name. **Excluded:** anything BGE- (BAAI) or Jina-derived; GTE (Alibaba), including `gte-reranker-modernbert-base`; Qwen3-Reranker; mxbai-rerank-v2 (Qwen2.5 base); and DeepSeek-derived models. The MS MARCO data is licensed for non-commercial research purposes only, which rules out `cross-encoder/ms-marco-*` unless Patrick decides otherwise. **Candidate, needing Patrick's approval:** IBM `granite-embedding-reranker-english-r2`. Per the CTO's r1 check it is 149M parameters, Apache-2.0, on the Granite R2 base, with no MS MARCO in training. I have not re-verified that here. The revision to pin is still unconfirmed, and nothing has been or may be downloaded without Patrick's approval. |
| Expected effect | This is the only option that reads question and passage together, so it is the one most likely to fix VOCAB, THEME and PASSAGE misses (§3: 9 blind + 6 `plain`). Size unknown until measured. |
| Cost | A new weight download (Patrick to approve). About 150M parameters: estimated +300–600 MB RSS fp32, less with the existing ONNX int8 path. CPU latency is unmeasured; my estimate is 0.3–1.5 s for 30 pairs on the Sprite. If it uses sentence-transformers in the product, that is a new dependency; an ONNX export avoids it. |
| Overfitting risk | Low if used off the shelf (no tuning). Moderate if k or a fusion with the reranker score is tuned. |
| Honest test | Same split as #1. Measure RSS and p95 latency with `scripts/bench_api.py` before any decision. |

**4. Chunk size or overlap, neighbour context, title/summary fields. Not recommended now.**

- The labelled chunks are the corpus median length.
- Neighbour smoothing did nothing (V8/V9).
- The chunker is frozen by `eval/README.md`.
- A title template for dense documents cost EmbeddingGemma 0.23 R@5 (`docs/research/embeddings.md`). BM25 already indexes titles.
- Generated summaries would be an LLM paraphrase of the preacher stored in the product, even if hidden. That conflicts with "the AI never writes summaries or paraphrases" (AGENTS.md §2). I recommend no.

**5. Granite query/passage prompt formats. Not recommended.**

The card says no prefix, and §6 shows prefixes hurt the blind questions (−0.07 to −0.29).

**Not a retrieval change, but cheap: query-shape routing in the UI.** For the OR shape, the abstain banner could say "results for everyday wording are less reliable". That is a product decision for Patrick; no proposal is made here.

## 8. How to rerun (exact commands)

The scripts behind every number here are committed in `reports/w3-retrieval-diag/` (added by W3-DIAG-SCRIPTS). They are scratch analysis, not product code: nothing under `src/`, `app/` or `tests/` imports them, and `unittest discover -s tests` does not collect them. They were copied from `/cache/w3-retrieval-diag/scripts/` with only two kinds of change: usage docstrings, and paths made configurable (`PREACHED_CACHE` for the index and corpus, which `preached.paths` already honours and which defaults to `/cache`; an optional chunks path and output path for `stats.py`; an optional work directory for `table.py`). The analysis logic is unchanged.

**Read-only (W3-DIAG-FIX, S4).** `diag.py`, `experiments.py` and `prefixes.py` open the index with a local `open_immutable()` helper (W3-DIAG-FIX2, S8; each does `import sqlite3` and a plain `sqlite3.connect(...)`, and the three files are listed in `RAW_CONNECTS` in `tests/test_hard_conditions.py` with one raw open each, so the raw-connect guard sees them; W3-DIAG-FIX3 replaced an earlier `store.sqlite3.connect` that the guard could not see): a sqlite URI with `mode=ro&immutable=1` plus `PRAGMA query_only`, so no WAL pragma, no DDL, no ALTER, and **no `-shm` or `-wal` file is created or touched**. (`store.connect`, used originally, runs `migrate`, which does the first three. W3-DIAG-FIX used the product's `open_readonly`, `mode=ro` only: it leaves the main file unchanged but SQLite creates `-shm` and an empty `-wal` beside it and rewrites `-shm` on every open, so "sha256 and mtime unchanged" covered the main file only. `open_readonly` is unchanged; `immutable=1` is safe here because nothing writes the index while the scripts run.) `stats.py` and `table.py` never touch the index. Their default output is now `$TMPDIR/w3-retrieval-diag/`, never the current directory or the repo root. The bench step below runs on a **copy** of the index, because `search/bench.py` opens its index with `connect` and re-syncs chunks into it (`ensure_chunks`).

```sh
cd <checkout of this branch>
W=/some/scratch/dir; mkdir -p $W
# baseline, identical to the shipped bench, on a COPY of the index: bench.py migrates and re-syncs chunks into its --index
cp /cache/index/wesley.sqlite $W/wesley.sqlite
uv run --group bench search/bench.py --models granite-english-r2 --index $W/wesley.sqlite \
  --out $W/bench-raw.json --note "W3-RETRIEVAL-DIAG baseline, raw ranker"
# per-question top 100 for bm25 / dense / hybrid on plain + plain-blind
uv run --group bench python reports/w3-retrieval-diag/diag.py $W/diag.json
# exploratory variants V0..V12 (prints per-group tables, writes JSON with per-question scores)
uv run --group bench python reports/w3-retrieval-diag/experiments.py $W/experiments.json > $W/experiments.txt
# Granite query-prefix probe (dense only)
uv run --group bench python reports/w3-retrieval-diag/prefixes.py > $W/prefixes.txt
# signals (chunks path and output path are optional), then the per-question table
python3 reports/w3-retrieval-diag/stats.py $W/diag.json /cache/corpus/wesley/chunks.jsonl $W/stats.json
cp reports/w3-retrieval-diag/categories.json reports/w3-retrieval-diag/flags.json $W/   # hand-written inputs
python3 reports/w3-retrieval-diag/table.py $W
```

With another cache location, set `PREACHED_CACHE=/path` (it must hold `index/wesley.sqlite` and `corpus/wesley/chunks.jsonl`) and pass that chunks path to `stats.py`. The query vectors are computed on CPU from the model in `HF_HOME` (see `preached.env`).

### Committed files and sha256

Current (W3-DIAG-FIX3: the three scripts changed again, for the raw-connect guard; W3-DIAG-FIX2: `diag.py`, `experiments.py` and `prefixes.py` changed for S8, `categories.json` for S9; `stats.py`, `table.py` and `flags.json` are as in W3-DIAG-FIX), with the W3-DIAG-SCRIPTS (`832a198`) values for comparison:

| file | sha256 now | sha256 at `832a198` |
| --- | --- | --- |
| `reports/w3-retrieval-diag/diag.py` | `6bf041cea3beac9620adf05cc3beb226b86264db5cb7e1de307b624b771566bd` | `5f8a30977dc391e65e6d31577a87f96ddd4da2b50dedd9734faae8ff8ff3d59b` |
| `reports/w3-retrieval-diag/experiments.py` | `ca606acb2ccaefdd2eb1b92f69f988e01cc697149b30472e57b1f383ac28c1c0` | `185ca95ceaafcbc9eb454f6752c79d0feea0200d2212ec401c1055fa90375ede` |
| `reports/w3-retrieval-diag/prefixes.py` | `69d175c8be460ed99025267503fabf1364443aaed526fb24520d405dfdf994a8` | `53de16cadc74792f451b64e9f4d5899d179cf4d28508af638457cd65cee4024e` |
| `reports/w3-retrieval-diag/stats.py` | `b37a6e8d28b6b54c067f4c0153fa171c4ed156bab52713d2d1f811dc23bf3c58` | `3bf7e8173777181cda906b73bfc160a50a7ecdb46e6d926c0052459a23cf60a5` |
| `reports/w3-retrieval-diag/table.py` | `cb993d5a834f09eeaf303155de0748c4d2db7c9a28dea20b39d80ccf05f2e87b` | `1f1543ac03d051dc0f8ec95963ff5206c9fcd05f5d178d670c2d0493c71311d4` |
| `reports/w3-retrieval-diag/categories.json` (hand-written, input to `table.py`) | `c17aeb7eedce94c51a3a020c532f803140bf98d3b95b259e1ea500e6760de10f` | `e320527e193fe3ddd635dd63c6d56a9ed5ba2585a4285aa22aa4c4485d051477` |
| `reports/w3-retrieval-diag/flags.json` (hand-written, input to `table.py`) | `bbb39c2c1b1acd4ed6c5c6b328b919a710fe9e362d3bd2198cfec378c2b95823` | same |

**Original scratch scripts (restored; `832a198` dropped this table).** The first version of this report (`a2bcbec`) gave the first 12 hex of the scripts as run, in `/cache/w3-retrieval-diag/scripts/`. Those files are untouched. Four of the five full sha256 match the published prefixes. **`diag.py` does not:** `a2bcbec` published `9dfaeb558806`, but the full hash below begins `9dfaeb5588c7`. The published value was a transcription error, not a different file (see "`diag.py` hash provenance" below):

| script in `/cache/w3-retrieval-diag/scripts/` | sha256 (a2bcbec published the first 12 hex; `diag.py`: published `9dfaeb558806`, correct `9dfaeb5588c7`) |
| --- | --- |
| `diag.py` | `9dfaeb5588c7061d79c6530faed01fb10d63bafa0c0e068141bc29ec7334cd72` |
| `experiments.py` | `120b33f3c765294a4b5ced424d136c03b02f8897d94d9fa851149161c518d9cc` |
| `prefixes.py` | `1e10b254cfe7e896eed2650f3abe44216bcb87d40a9fdec05c0c7fd8ce919e78` |
| `stats.py` | `e5d48880615c45a4705547b2ecded6b9cf706f08183c4e519152940f2c28e8f4` |
| `table.py` | `5b8f514960ee7ce67a76aaa26c514be427105957f06be561e91a34a33feb5e37` |

**`diag.py` hash provenance (W3-DIAG-FIX2).** The correct value is the full hash in the table, first 12 hex `9dfaeb5588c7`. The `9dfaeb558806` in `a2bcbec` agrees with it in the first 10 hex digits and differs only in the last two (`06` vs `c7`). A different version of the file would not share 10 hex digits by chance (about 1 in 10^12), so the published value is a mistyped copy of this file's hash, not the hash of an earlier file. The pasted draft in `/cache/w3-retrieval-diag/report-end.md` already carries the wrong value, so the error was made when the table was written, and no earlier copy of `diag.py` survives to compare. The file's mtime (04:52:36) is 12 s before `diag.json`'s (04:52:48), and a run takes about a minute, so I cannot show from timestamps alone that the file was not edited just as the run started. What does show it: running this `diag.py` from `/cache/w3-retrieval-diag/scripts/` (on an index copy) now writes a `diag.json` that is byte-identical to the published one (sha256 `a875192f…2c3e1f`).

Small results are in `reports/w3-retrieval-diag/results/`: `experiments.txt` (the §6 tables), `prefixes.txt`, `stats.json` (the §2 signals), `bench-raw.md` (the baseline), `variants.md`. The large intermediates (`diag.json` 975 KB, `experiments.json` 818 KB, `bench-raw.json` 378 KB) are not committed; regenerate them with the commands above.

### Inputs that come from `/cache` (not in the repo)

The index is identified by what it holds, not by a whole-file hash: a byte hash of a SQLite file changes with page layout and cannot be checked against another build. Check these values, read-only, in your copy:

| index content (`/cache/index/wesley.sqlite`) | value |
| --- | --- |
| `meta` `embeddings:granite-english-r2` → `fingerprint` | `13e0ed78bb32d86b` (dim 768, fp32) |
| `meta` `chunks_sha256` (sha256 of the chunk file the index loaded, `chunks_aligned.jsonl`) | `198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2` |
| rows in `chunks` | 8,383 |
| rows in `embeddings` with `model = 'granite-english-r2'` | 8,383 |
| sha256 over `chunk_id, sermon_title, scripture, text` of every `chunks` row (S10; see below) | `801b4552f4945bd4b7c9d4d97ced7ae9bd7b4d615ecaa92579a60f8482eee375` |

```sh
python3 - <<'EOF'
import sqlite3
c = sqlite3.connect("file:/cache/index/wesley.sqlite?mode=ro&immutable=1", uri=True); c.execute("PRAGMA query_only = ON")
print(dict(c.execute("SELECT key, value FROM meta WHERE key IN ('chunks_sha256', 'embeddings:granite-english-r2')")))
print(c.execute("SELECT count(*) FROM chunks").fetchone(), c.execute("SELECT count(*) FROM embeddings WHERE model = 'granite-english-r2'").fetchone())
EOF
```

The content hash is computed as: rows ordered by `chunk_id`; each row is its four fields joined by `\x1f` (NULL as empty), plus `\n`; sha256 of the whole stream.

```sh
python3 - <<'EOF'
import sqlite3, hashlib
c = sqlite3.connect("file:/cache/index/wesley.sqlite?mode=ro&immutable=1", uri=True)
h = hashlib.sha256(); n = 0
for row in c.execute("SELECT chunk_id, sermon_title, scripture, text FROM chunks ORDER BY chunk_id"):
    h.update("\x1f".join("" if v is None else str(v) for v in row).encode() + b"\n"); n += 1
print(n, h.hexdigest())   # 8383 801b4552f494...
EOF
```

`stats.py` reads the text file directly: `/cache/corpus/wesley/chunks.jsonl` (8,383 chunks), sha256 `110dd51989a982c44bbeeb7db6025c8a07a635cfeaef9e360ecbd16dcede016f`.

The eval set (`eval/questions.jsonl`) and the model revision (Granite English R2 `47ea694b`) are as in §1. A reviewer with their own copy should check these values first; if they differ, the numbers need not match.

### Reproduction check (rerun from the committed scripts, 2026-10-31)

Every script was rerun from `reports/w3-retrieval-diag/` against the inputs above, into a scratch directory, and compared with the original outputs in `/cache/w3-retrieval-diag/`:

- `diag.py` -> `diag.json`: identical (parsed JSON equal).
- `experiments.py` -> `experiments.json`: identical (parsed JSON equal); `experiments.txt` identical apart from a model-loading progress-bar line.
- `prefixes.py` -> `prefixes.txt`: identical apart from the same progress-bar line.
- `stats.py` -> `stats.json`: byte-identical. Printed headline: `plain-blind 28 lenient hit@10 bm25/dense/hybrid 3 11 3 fusion_loss 8 fusion_gain 0`; `plain 25 ... 8 17 18 fusion_loss 2 fusion_gain 3`. So dense 11/28 vs hybrid 3/28 reproduces exactly.
- `table.py` -> `table.md`, `legend.md`: byte-identical (§2 and the Appendix); category counts as in §3.
- V10 and the other variants (`experiments.txt`): identical to §6.
- `search/bench.py` baseline: every score and CI identical. Only the timestamp, the commit hash in the header, and the latency columns (wall-clock, e.g. hybrid_rrf p50/p95 `115.6 / 138.0` vs `114.6 / 138.3` ms) differ between runs.

**Rerun after the read-only change (W3-DIAG-FIX, 2026-10-31).** The `0baa33c` scripts were run against a copy of the index, and the read-only scripts against `/cache/index/wesley.sqlite` itself. `diag.json`, `experiments.json`, `experiments.txt`, `prefixes.txt`, `stats.json`, the `stats.py` printout, `table.md`, `legend.md` and the category counts are byte-identical. The index file's sha256 (`909afd60…7fe972b`) and mtime were the same before and after. The bench step on an index copy gave identical scores and CIs (only the timestamp and latency differ). After that, the S6 recategorisation changed two rows of `table.md` (p-015, p-030) and no count. Details: `reports/W3-DIAG-FIX.md`.

**Rerun after the immutable change and the p-015 recategorisation (W3-DIAG-FIX2, 2026-10-31).** `diag.json`, `experiments.json`, `experiments.txt`, `prefixes.txt`, `stats.json` are byte-identical to the committed results and to the `/cache/w3-retrieval-diag/` originals (`diag.json` sha256 `a875192f…2c3e1f`). On an index copy with the sidecar check, the directory held only `wesley.sqlite` while the `mode=ro&immutable=1` connection was open and after it closed; plain `mode=ro` on a copy leaves `-shm` and `-wal`. The full `diag.py` run on a copy also left only `wesley.sqlite`. The `/cache/index/wesley.sqlite` sha256 (`909afd60…7fe972b`) and mtime, and the `-shm` and `-wal` mtimes, did not change across the run. The only intended change is p-015 (LEX → VOCAB): blind LEX 6 → 5, VOCAB 4 → 5. Details: `reports/W3-DIAG-FIX2.md`.

The run took about 1 minute per script on this box (24 cores, CPU query vectors, cached document vectors).

## 9. Results summary, open issues, exclusions

- **Results:** §2 (55 rows), §3 (counts), §4 (24 flagged chunks on 18 questions), §6 (12 variants).
- **Full suite:** `uv run python -m unittest discover -s tests && uv lock --check`: 772 tests OK and the lock is unchanged. The log shows a `sqlite3.OperationalError: locked` traceback printed by a test that exercises a locked database; the suite passes.
- **Open issues and risks:**
  - Categories and flags are one LLM reader's judgment.
  - Every label used is proposed or unconfirmed, as before.
  - No `plain-blind` number is held out, for any variant (§5); a fresh blind set is the confirmatory test (§7 #1 d).
  - The `plain-blind` questions are LLM-written (Grok) and all their labels and the §4 flags are LLM (Claude) judgments; none is confirmed by a person.
  - The abstain and `--dedupe` paths are untested under any variant.
- **Excluded:**
  - Reranker experiments: no cached model, and downloads are not allowed.
  - Re-chunking: frozen, and the evidence is against it.
  - LLM-written summaries: product rule.
  - No PRC-origin model was considered.
- **Process notes:**
  - `sandbox.sh` and `gh` are not on this machine (as in W3-BUNDLE-TAR2). The branch was made with `git worktree add -b docs/w3-retrieval-diag ... origin/main`.
  - The PR has to be opened by hand: https://github.com/pshouse/preached/compare/main...docs/w3-retrieval-diag?expand=1 (title "W3: retrieval diagnosis (analysis only)").
- **Dependencies added:** none.

## Appendix: sermon numbers in the tables

| no. | title |
| --- | --- |
| 001 | Salvation by Faith |
| 002 | The Almost Christian |
| 003 | Awake, Thou That Sleepest |
| 004 | Scriptural Christianity |
| 005 | Justification By Faith |
| 006 | The Righteousness of Faith |
| 007 | The Way to the Kingdom |
| 008 | THE FIRST FRUITS OF THE SPIRIT |
| 009 | The Spirit of Bondage and of Adoption. |
| 010 | THE WITNESS OF THE SPIRIT, Discourse I |
| 011 | The Witness of the Spirit, Discourse II |
| 013 | On Sin in Believers |
| 014 | The Repentance of Believers |
| 015 | The Great Assize |
| 016 | The Means of Grace |
| 017 | The Circumcision of the Heart |
| 018 | The Marks of the New Birth |
| 019 | The Great Privilege of those that are Born of God |
| 020 | The Lord our Righteousness |
| 021 | Upon our Lord's Sermon on the Mount, Discourse 1 |
| 022 | Upon our Lord's Sermon on the Mount, Discourse 2 |
| 023 | Upon our Lord's Sermon on the Mount, Discourse 3 |
| 024 | Upon our Lord's Sermon on the Mount, Discourse 4 |
| 025 | Upon our Lord's Sermon on the Mount, Discourse 5 |
| 026 | Upon our Lord's Sermon on the Mount, Discourse 6 |
| 027 | Upon our Lord's Sermon on the Mount, Discourse 7 |
| 028 | Upon our Lord's Sermon on the Mount, Discourse 8 |
| 029 | Upon our Lord's Sermon on the Mount, Discourse 9 |
| 030 | Upon our Lord's Sermon on the Mount, Discourse 10 |
| 031 | Upon our Lord'S Sermon on the Mount, Discourse 11 |
| 032 | Upon our Lord's Sermon on the Mount, Discourse 12 |
| 033 | UPON OUR LORD'S SERMON ON THE MOUNT, Discourse 13 |
| 034 | The Original, Nature, Property, and Use of the Law |
| 035 | The Law Established through Faith, Discourse I |
| 037 | The Nature of Enthusiasm |
| 038 | A Caution against Bigotry |
| 039 | Catholic Spirit |
| 040 | Christian Perfection |
| 041 | Wandering Thoughts |
| 042 | Satan's Devices |
| 043 | The Scripture Way of Salvation |
| 044 | Original Sin |
| 045 | The New Birth |
| 046 | The Wilderness State |
| 047 | Heaviness through Manifold Temptations |
| 048 | Self-denial |
| 049 | The Cure of Evil-speaking |
| 050 | The Use of Money |
| 052 | The Reformation of Manners |
| 053 | On the Death of the Rev. Mr. George Whitefield |
| 054 | On Eternity |
| 059 | God's Love to Fallen Man |
| 060 | The General Deliverance |
| 061 | The Mystery of Iniquity |
| 062 | The End of Christ's Coming |
| 064 | The New Creation |
| 065 | The Duty of Reproving our Neighbour |
| 067 | On Divine Providence |
| 068 | The Wisdom of God's Counsels |
| 070 | The Case of Reason Impartially Considered |
| 072 | Of Evil Angels |
| 073 | Of Hell |
| 074 | Of the Church |
| 075 | On Schism |
| 076 | On Perfection |
| 077 | Spiritual Worship |
| 078 | Spiritual Idolatry |
| 079 | On Dissipation |
| 080 | On Friendship with the World |
| 081 | In What Sense we are to Leave the World |
| 082 | On Temptation |
| 083 | On Patience |
| 084 | The Important Question |
| 085 | On Working out our own Salvation |
| 086 | A Call to Backsliders |
| 087 | The Danger of Riches |
| 088 | On Dress |
| 089 | The More Excellent Way |
| 090 | An Israelite Indeed |
| 091 | On Charity |
| 092 | On Zeal |
| 093 | On Redeeming the Time |
| 094 | On Family Religion |
| 095 | On the Education of Children |
| 096 | On Obedience to Parents |
| 098 | On Visiting the Sick |
| 099 | The Reward of the Righteous |
| 100 | On Pleasing all Men |
| 101 | The Duty of Constant Communion J.W. |
| 102 | Of Former Times |
| 104 | On Attending the Church Service |
| 105 | On Conscience |
| 106 | On Faith |
| 107 | On God's Vineyard |
| 108 | On Riches |
| 110 | On the Discoveries of Faith |
| 111 | On the Omnipresence of God |
| 112 | The Rich Man and Lazarus |
| 113 | The Difference Between Walking by Sight, and Walking by Faith |
| 114 | The Unity of the Divine Being |
| 115 | The Ministerial Office |
| 116 | Causes of the Inefficacy of Christianity |
| 118 | On a Single Eye |
| 119 | On Worldly Folly |
| 120 | On the Wedding Garment |
| 121 | Human Life a Dream |
| 122 | On Faith |
| 123 | The Deceitfulness of the Human Heart |
| 124 | The Heavenly Treasure in Earthen Vessels |
| 125 | On Living Without God |
| 126 | On the Danger of Increasing Riches |
| 127 | The Trouble and Rest of Good Men |
| 128 | Free Grace |
| 129 | The Cause and Cure of Earthquakes |
| 130 | National Sins and Miseries |
| 131 | The Late Work of God in North America |
| 132 | On Laying the Foundation of the New Chapel, Near the City-Road, London |
| 133 | Preached on Occasion of the Death of the Rev. Mr. John Fletcher, Vicar of |
| 134 | True Christianity Defended |
| 135 | On Mourning for the Dead |
| 136 | On Corrupting the Word Of God |
| 137 | On the Resurrection of the Dead |
| 138 | On Grieving the Holy Spirit |
| 139 | On Love |
| 140 | On Public Diversions |
| 141 | On the Holy Spirit |
