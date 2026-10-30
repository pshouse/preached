# Abstain rule, 2026-10-30T14:35:08-04:00

API path (hybrid RRF, top 100, `dedupe_adjacent`, k=10). Rule: `src/preached/abstain.py`. Questions: 35 answerable, 5 unanswerable (LLM-written labels, pending human review). Commit `abbf735a3c286cb44c325de124543267387b784c` (dirty).

Headline is leave-one-out (LOO): each question is judged with a floor fitted on the other 39. An abstained answerable question counts as a miss.

| model | eval | floor | abstain precision | abstain recall | flagged (weak or none) recall | false abstain | weak on answerable | R@5 → with abstain | MRR@10 → with abstain |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| granite-english-r2 | **LOO** | refit per fold (range 0.7988–0.8129) | 1.000 | 0.600 | 0.800 | 0.000 | 0.029 | 0.657 → 0.657 | 0.540 → 0.540 |
| granite-english-r2 | in-sample | 0.813 | 1.000 | 0.800 | 0.800 | 0.000 | 0.029 | 0.657 → 0.657 | 0.540 → 0.540 |
| granite-english-r2 | no floor | none | n/a | 0.000 | 0.800 | 0.000 | 0.029 | 0.657 → 0.657 | 0.540 → 0.540 |

Per question (signals and levels; `agree` = a shown passage is in both BM25's and dense's top 100):

## granite-english-r2

| id | answerable | BM25 hits | dense top | agree | R@5 | in-sample | LOO | no floor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| u-smartphones | no | 0 | 0.7815 | no |  | none | none | weak |
| u-nuclear-weapons | no | 0 | 0.7864 | no |  | none | none | weak |
| u-vaccines | no | 0 | 0.7987 | no |  | none | none | weak |
| u-book-of-mormon | no | 0 | 0.8129 | no |  | none | weak | weak |
| u-pretrib-rapture | no | 100 | 0.8279 | yes |  | strong | strong | strong |
| q-worry | yes | 100 | 0.8282 | yes | 0.0 | strong | strong | strong |
| k-luke-22-19 | yes | 55 | 0.8322 | yes | 1.0 | strong | strong | strong |
| k-philippians-3-12 | yes | 100 | 0.8348 | yes | 1.0 | strong | strong | strong |
| q-original-sin | yes | 100 | 0.8440 | yes | 1.0 | strong | strong | strong |
| k-matthew-6-34 | yes | 84 | 0.8489 | no | 1.0 | weak | weak | weak |
| q-prayer | yes | 100 | 0.8558 | yes | 0.0 | strong | strong | strong |
| q-satan | yes | 100 | 0.8559 | yes | 1.0 | strong | strong | strong |
| q-money | yes | 100 | 0.8588 | yes | 0.0 | strong | strong | strong |
| q-temptation | yes | 100 | 0.8622 | yes | 0.0 | strong | strong | strong |
| k-romans-8-16 | yes | 73 | 0.8642 | yes | 1.0 | strong | strong | strong |
| q-backsliders | yes | 100 | 0.8656 | yes | 1.0 | strong | strong | strong |
| q-catholic-spirit | yes | 100 | 0.8689 | yes | 1.0 | strong | strong | strong |
| q-evil-speaking | yes | 100 | 0.8690 | yes | 1.0 | strong | strong | strong |
| q-assurance | yes | 100 | 0.8701 | yes | 0.0 | strong | strong | strong |
| q-mourning | yes | 100 | 0.8711 | yes | 1.0 | strong | strong | strong |
| q-forgiveness | yes | 100 | 0.8712 | yes | 1.0 | strong | strong | strong |
| k-gain-all-you-can | yes | 100 | 0.8716 | yes | 1.0 | strong | strong | strong |
| k-2-corinthians-2-11 | yes | 66 | 0.8753 | yes | 1.0 | strong | strong | strong |
| q-salvation | yes | 100 | 0.8772 | yes | 0.0 | strong | strong | strong |
| q-riches | yes | 100 | 0.8824 | yes | 0.0 | strong | strong | strong |
| q-faith-works | yes | 100 | 0.8836 | yes | 0.0 | strong | strong | strong |
| q-means | yes | 100 | 0.8836 | yes | 1.0 | strong | strong | strong |
| k-1-corinthians-10-13 | yes | 57 | 0.8851 | yes | 1.0 | strong | strong | strong |
| q-justification | yes | 100 | 0.8872 | yes | 0.0 | strong | strong | strong |
| q-heaviness | yes | 100 | 0.8880 | yes | 0.0 | strong | strong | strong |
| q-sin-believers | yes | 100 | 0.8895 | yes | 1.0 | strong | strong | strong |
| q-perfection | yes | 100 | 0.8940 | yes | 0.5 | strong | strong | strong |
| q-wilderness | yes | 100 | 0.8983 | yes | 1.0 | strong | strong | strong |
| k-witness-of-the-spirit | yes | 100 | 0.8993 | yes | 0.0 | strong | strong | strong |
| q-new-birth | yes | 100 | 0.9015 | yes | 0.5 | strong | strong | strong |
| q-communion | yes | 100 | 0.9035 | yes | 1.0 | strong | strong | strong |
| q-wandering-thoughts | yes | 100 | 0.9113 | yes | 1.0 | strong | strong | strong |
| q-self-denial | yes | 100 | 0.9154 | yes | 1.0 | strong | strong | strong |
| k-christian-perfection | yes | 100 | 0.9306 | yes | 1.0 | strong | strong | strong |
| k-means-of-grace | yes | 100 | 0.9384 | yes | 1.0 | strong | strong | strong |

Unlabelled probes (not used to fit; no ground truth), level with the in-sample floor:

| query | BM25 hits | dense top | agree | level |
| --- | --- | --- | --- | --- |
| What did Wesley say about worry? | 0 | 0.8179 | no | weak |
| How can I know that I am a child of God? | 9 | 0.9061 | yes | strong |
| What did Wesley say about money? | 100 | 0.8531 | yes | strong |
| Romans 8:16 | 73 | 0.8642 | yes | strong |
| What did Wesley say about drinking gin? | 0 | 0.8121 | no | none |
| What did Wesley say about slavery? | 4 | 0.8165 | yes | strong |
| What did Wesley say about electricity? | 8 | 0.8141 | yes | strong |
| Is it okay for Christians to play video games? | 100 | 0.8059 | yes | weak |
| What did Wesley say about dinosaurs? | 0 | 0.7950 | no | none |
| What did Wesley think about the internet? | 0 | 0.7934 | no | none |
| Did Wesley support the American Revolution? | 0 | 0.7983 | no | none |
| What did Wesley teach about climate change and the environment? | 0 | 0.8057 | no | none |

