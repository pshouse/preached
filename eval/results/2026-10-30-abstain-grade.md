# Abstain rule, 2026-10-30T17:09:27-04:00

API path (hybrid RRF, top 100, `dedupe_adjacent`, k=10). Rule: `src/preached/abstain.py`. Questions: 86 answerable, 7 unanswerable (LLM-written labels, pending human review). Commit `9125354c6712e8b604c8ff475c5420a189829288`.

Headline is leave-one-out (LOO): each question is judged with a floor fitted on all the others. An abstained answerable question counts as a miss.

| model | eval | floor | abstain precision | abstain recall | flagged (weak or none) recall | false abstain | weak on answerable | R@5 → with abstain | MRR@10 → with abstain |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| granite-english-r2 | **LOO** | refit per fold (range 0.7753–0.7984) | 0.000 | 0.000 | 0.571 | 0.012 | 0.023 | 0.291 → 0.291 | 0.229 → 0.229 |
| granite-english-r2 | in-sample | 0.775 | n/a | 0.000 | 0.571 | 0.000 | 0.035 | 0.291 → 0.291 | 0.229 → 0.229 |
| granite-english-r2 | no floor | none | n/a | 0.000 | 0.571 | 0.000 | 0.035 | 0.291 → 0.291 | 0.229 → 0.229 |
| embeddinggemma-2 | **LOO** | refit per fold (range 0.6735–0.7413) | 0.000 | 0.000 | 0.571 | 0.012 | 0.023 | 0.296 → 0.296 | 0.216 → 0.216 |
| embeddinggemma-2 | in-sample | 0.673 | n/a | 0.000 | 0.571 | 0.000 | 0.035 | 0.296 → 0.296 | 0.216 → 0.216 |
| embeddinggemma-2 | no floor | none | n/a | 0.000 | 0.571 | 0.000 | 0.012 | 0.296 → 0.296 | 0.216 → 0.216 |

Per group, leave-one-out (in-sample in parentheses). Answerable groups: share abstained (false abstain) and share weak. Unanswerable: share abstained and share flagged weak or none.

| model | group | n | abstained | weak or flagged | R@5 → with abstain |
| --- | --- | --- | --- | --- | --- |
| granite-english-r2 | names-topic | 23 | 0.000 (0.000) | 0.000 (0.000) | 0.565 → 0.565 |
| granite-english-r2 | plain | 25 | 0.000 (0.000) | 0.000 (0.000) | 0.040 → 0.040 |
| granite-english-r2 | scripture-keyword | 7 | 0.000 (0.000) | 0.143 (0.143) | 1.000 → 1.000 |
| granite-english-r2 | title-keyword | 3 | 0.000 (0.000) | 0.000 (0.000) | 0.667 → 0.667 |
| granite-english-r2 | unanswerable | 5 | 0.000 (0.000) | 0.800 (0.800) | |
| granite-english-r2 | plain-blind | 28 | 0.036 (0.000) | 0.036 (0.071) | 0.071 → 0.071 |
| embeddinggemma-2 | names-topic | 23 | 0.000 (0.000) | 0.000 (0.000) | 0.587 → 0.587 |
| embeddinggemma-2 | plain | 25 | 0.000 (0.000) | 0.000 (0.000) | 0.040 → 0.040 |
| embeddinggemma-2 | scripture-keyword | 7 | 0.000 (0.000) | 0.000 (0.000) | 1.000 → 1.000 |
| embeddinggemma-2 | title-keyword | 3 | 0.000 (0.000) | 0.000 (0.000) | 0.667 → 0.667 |
| embeddinggemma-2 | unanswerable | 5 | 0.000 (0.000) | 0.800 (0.800) | |
| embeddinggemma-2 | plain-blind | 28 | 0.036 (0.000) | 0.071 (0.107) | 0.071 → 0.071 |

Per question (signals and levels; `agree` = a shown passage is in both BM25's and dense's top 100):

## granite-english-r2

| id | group | answerable | BM25 hits | dense top | agree | R@5 | in-sample | LOO | no floor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| u-smartphones | unanswerable | no | 0 | 0.7815 | no |  | weak | weak | weak |
| u-nuclear-weapons | unanswerable | no | 0 | 0.7864 | no |  | weak | weak | weak |
| u-vaccines | unanswerable | no | 0 | 0.7987 | no |  | weak | weak | weak |
| u-book-of-mormon | unanswerable | no | 0 | 0.8129 | no |  | weak | weak | weak |
| p-004 | plain-blind | no | 100 | 0.8202 | yes |  | strong | strong | strong |
| u-pretrib-rapture | unanswerable | no | 100 | 0.8279 | yes |  | strong | strong | strong |
| p-023 | plain-blind | no | 100 | 0.8363 | yes |  | strong | strong | strong |
| p-016 | plain-blind | yes | 0 | 0.7754 | no | 0.0 | weak | none | weak |
| p-024 | plain-blind | yes | 100 | 0.7834 | yes | 0.0 | strong | strong | strong |
| p-027 | plain-blind | yes | 100 | 0.7902 | yes | 0.0 | strong | strong | strong |
| p-029 | plain-blind | yes | 100 | 0.7937 | yes | 0.0 | strong | strong | strong |
| p-017 | plain-blind | yes | 2 | 0.7985 | no | 0.0 | weak | weak | weak |
| q-worry-plain | plain | yes | 100 | 0.7998 | yes | 0.0 | strong | strong | strong |
| p-012 | plain-blind | yes | 100 | 0.8018 | yes | 0.0 | strong | strong | strong |
| p-026 | plain-blind | yes | 100 | 0.8018 | yes | 0.0 | strong | strong | strong |
| p-019 | plain-blind | yes | 100 | 0.8026 | yes | 0.0 | strong | strong | strong |
| p-008 | plain-blind | yes | 100 | 0.8042 | yes | 0.0 | strong | strong | strong |
| p-028 | plain-blind | yes | 100 | 0.8057 | yes | 0.0 | strong | strong | strong |
| p-020 | plain-blind | yes | 100 | 0.8081 | yes | 0.0 | strong | strong | strong |
| p-007 | plain-blind | yes | 100 | 0.8180 | yes | 0.0 | strong | strong | strong |
| p-010 | plain-blind | yes | 100 | 0.8194 | yes | 0.0 | strong | strong | strong |
| p-006 | plain-blind | yes | 100 | 0.8205 | yes | 0.0 | strong | strong | strong |
| q-evil-speaking-plain | plain | yes | 100 | 0.8224 | yes | 0.0 | strong | strong | strong |
| p-021 | plain-blind | yes | 100 | 0.8260 | yes | 0.0 | strong | strong | strong |
| p-030 | plain-blind | yes | 100 | 0.8269 | yes | 0.0 | strong | strong | strong |
| p-014 | plain-blind | yes | 100 | 0.8280 | yes | 0.0 | strong | strong | strong |
| q-worry | names-topic | yes | 100 | 0.8282 | yes | 0.0 | strong | strong | strong |
| q-original-sin-plain | plain | yes | 100 | 0.8283 | yes | 0.0 | strong | strong | strong |
| k-luke-22-19 | scripture-keyword | yes | 55 | 0.8322 | yes | 1.0 | strong | strong | strong |
| p-005 | plain-blind | yes | 100 | 0.8340 | yes | 0.0 | strong | strong | strong |
| k-philippians-3-12 | scripture-keyword | yes | 100 | 0.8348 | yes | 1.0 | strong | strong | strong |
| p-013 | plain-blind | yes | 100 | 0.8395 | yes | 0.0 | strong | strong | strong |
| p-003 | plain-blind | yes | 100 | 0.8402 | yes | 0.0 | strong | strong | strong |
| q-mourning-plain | plain | yes | 100 | 0.8413 | yes | 0.0 | strong | strong | strong |
| p-002 | plain-blind | yes | 100 | 0.8414 | yes | 1.0 | strong | strong | strong |
| q-original-sin | names-topic | yes | 100 | 0.8440 | yes | 1.0 | strong | strong | strong |
| p-011 | plain-blind | yes | 100 | 0.8444 | yes | 0.0 | strong | strong | strong |
| k-matthew-6-34 | scripture-keyword | yes | 84 | 0.8489 | no | 1.0 | weak | weak | weak |
| p-001 | plain-blind | yes | 100 | 0.8496 | yes | 1.0 | strong | strong | strong |
| q-money-plain | plain | yes | 100 | 0.8501 | yes | 0.0 | strong | strong | strong |
| q-satan-plain | plain | yes | 100 | 0.8504 | yes | 0.0 | strong | strong | strong |
| q-backsliders-plain | plain | yes | 100 | 0.8515 | yes | 0.0 | strong | strong | strong |
| q-sin-believers-plain | plain | yes | 100 | 0.8536 | yes | 0.0 | strong | strong | strong |
| q-means-plain | plain | yes | 100 | 0.8537 | yes | 0.0 | strong | strong | strong |
| q-riches-plain | plain | yes | 100 | 0.8548 | yes | 0.0 | strong | strong | strong |
| p-025 | plain-blind | yes | 100 | 0.8552 | yes | 0.0 | strong | strong | strong |
| q-catholic-spirit-plain | plain | yes | 100 | 0.8555 | yes | 0.0 | strong | strong | strong |
| q-prayer | plain | yes | 100 | 0.8558 | yes | 0.0 | strong | strong | strong |
| q-satan | names-topic | yes | 100 | 0.8559 | yes | 1.0 | strong | strong | strong |
| q-heaviness-plain | plain | yes | 100 | 0.8579 | yes | 0.0 | strong | strong | strong |
| q-money | names-topic | yes | 100 | 0.8588 | yes | 0.0 | strong | strong | strong |
| q-wilderness-plain | plain | yes | 100 | 0.8612 | yes | 0.0 | strong | strong | strong |
| q-new-birth-plain | plain | yes | 100 | 0.8617 | yes | 0.0 | strong | strong | strong |
| q-temptation | names-topic | yes | 100 | 0.8622 | yes | 0.0 | strong | strong | strong |
| q-salvation-plain | plain | yes | 100 | 0.8623 | yes | 0.0 | strong | strong | strong |
| p-022 | plain-blind | yes | 100 | 0.8635 | yes | 0.0 | strong | strong | strong |
| k-romans-8-16 | scripture-keyword | yes | 73 | 0.8642 | yes | 1.0 | strong | strong | strong |
| q-wandering-thoughts-plain | plain | yes | 100 | 0.8644 | yes | 0.0 | strong | strong | strong |
| p-015 | plain-blind | yes | 100 | 0.8650 | yes | 0.0 | strong | strong | strong |
| q-backsliders | names-topic | yes | 100 | 0.8656 | yes | 1.0 | strong | strong | strong |
| q-assurance-plain | plain | yes | 100 | 0.8672 | yes | 0.0 | strong | strong | strong |
| p-009 | plain-blind | yes | 100 | 0.8677 | yes | 0.0 | strong | strong | strong |
| q-catholic-spirit | names-topic | yes | 100 | 0.8689 | yes | 1.0 | strong | strong | strong |
| q-evil-speaking | names-topic | yes | 100 | 0.8690 | yes | 1.0 | strong | strong | strong |
| q-temptation-plain | plain | yes | 100 | 0.8692 | yes | 0.0 | strong | strong | strong |
| q-assurance | names-topic | yes | 100 | 0.8701 | yes | 0.0 | strong | strong | strong |
| q-self-denial-plain | plain | yes | 100 | 0.8703 | yes | 0.0 | strong | strong | strong |
| q-mourning | names-topic | yes | 100 | 0.8711 | yes | 1.0 | strong | strong | strong |
| q-forgiveness | plain | yes | 100 | 0.8712 | yes | 1.0 | strong | strong | strong |
| k-gain-all-you-can | scripture-keyword | yes | 100 | 0.8716 | yes | 1.0 | strong | strong | strong |
| q-perfection-plain | plain | yes | 100 | 0.8720 | yes | 0.0 | strong | strong | strong |
| k-2-corinthians-2-11 | scripture-keyword | yes | 66 | 0.8753 | yes | 1.0 | strong | strong | strong |
| q-faith-works-plain | plain | yes | 100 | 0.8763 | yes | 0.0 | strong | strong | strong |
| q-communion-plain | plain | yes | 100 | 0.8772 | yes | 0.0 | strong | strong | strong |
| q-salvation | names-topic | yes | 100 | 0.8772 | yes | 0.0 | strong | strong | strong |
| q-riches | names-topic | yes | 100 | 0.8824 | yes | 0.0 | strong | strong | strong |
| q-justification-plain | plain | yes | 100 | 0.8827 | yes | 0.0 | strong | strong | strong |
| q-faith-works | names-topic | yes | 100 | 0.8836 | yes | 0.0 | strong | strong | strong |
| q-means | names-topic | yes | 100 | 0.8836 | yes | 1.0 | strong | strong | strong |
| k-1-corinthians-10-13 | scripture-keyword | yes | 57 | 0.8851 | yes | 1.0 | strong | strong | strong |
| q-justification | names-topic | yes | 100 | 0.8872 | yes | 0.0 | strong | strong | strong |
| q-heaviness | names-topic | yes | 100 | 0.8880 | yes | 0.0 | strong | strong | strong |
| q-sin-believers | names-topic | yes | 100 | 0.8895 | yes | 1.0 | strong | strong | strong |
| q-perfection | names-topic | yes | 100 | 0.8940 | yes | 0.5 | strong | strong | strong |
| p-018 | plain-blind | yes | 100 | 0.8944 | yes | 0.0 | strong | strong | strong |
| q-wilderness | names-topic | yes | 100 | 0.8983 | yes | 1.0 | strong | strong | strong |
| k-witness-of-the-spirit | title-keyword | yes | 100 | 0.8993 | yes | 0.0 | strong | strong | strong |
| q-new-birth | names-topic | yes | 100 | 0.9015 | yes | 0.5 | strong | strong | strong |
| q-communion | names-topic | yes | 100 | 0.9035 | yes | 1.0 | strong | strong | strong |
| q-wandering-thoughts | names-topic | yes | 100 | 0.9113 | yes | 1.0 | strong | strong | strong |
| q-self-denial | names-topic | yes | 100 | 0.9154 | yes | 1.0 | strong | strong | strong |
| k-christian-perfection | title-keyword | yes | 100 | 0.9306 | yes | 1.0 | strong | strong | strong |
| k-means-of-grace | title-keyword | yes | 100 | 0.9384 | yes | 1.0 | strong | strong | strong |

Unlabelled probes (not used to fit; no ground truth), level with the in-sample floor:

| query | BM25 hits | dense top | agree | level |
| --- | --- | --- | --- | --- |
| What did Wesley say about worry? | 0 | 0.8179 | no | weak |
| How can I know that I am a child of God? | 9 | 0.9061 | yes | strong |
| What did Wesley say about money? | 100 | 0.8531 | yes | strong |
| Romans 8:16 | 73 | 0.8642 | yes | strong |
| What did Wesley say about drinking gin? | 0 | 0.8121 | no | weak |
| What did Wesley say about slavery? | 4 | 0.8165 | yes | strong |
| What did Wesley say about electricity? | 8 | 0.8141 | yes | strong |
| Is it okay for Christians to play video games? | 100 | 0.8059 | yes | strong |
| What did Wesley say about dinosaurs? | 0 | 0.7950 | no | weak |
| What did Wesley think about the internet? | 0 | 0.7934 | no | weak |
| Did Wesley support the American Revolution? | 0 | 0.7983 | no | weak |
| What did Wesley teach about climate change and the environment? | 0 | 0.8057 | no | weak |

## embeddinggemma-2

| id | group | answerable | BM25 hits | dense top | agree | R@5 | in-sample | LOO | no floor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| p-023 | plain-blind | no | 100 | 0.6914 | yes |  | strong | strong | strong |
| p-004 | plain-blind | no | 100 | 0.6948 | yes |  | strong | strong | strong |
| u-nuclear-weapons | unanswerable | no | 0 | 0.6956 | no |  | weak | weak | weak |
| u-smartphones | unanswerable | no | 0 | 0.7043 | no |  | weak | weak | weak |
| u-book-of-mormon | unanswerable | no | 0 | 0.7366 | no |  | weak | weak | weak |
| u-vaccines | unanswerable | no | 0 | 0.7413 | no |  | weak | weak | weak |
| u-pretrib-rapture | unanswerable | no | 100 | 0.7473 | yes |  | strong | strong | strong |
| p-029 | plain-blind | yes | 100 | 0.6361 | yes | 0.0 | weak | weak | strong |
| p-026 | plain-blind | yes | 100 | 0.6713 | yes | 0.0 | weak | weak | strong |
| p-016 | plain-blind | yes | 0 | 0.6736 | no | 0.0 | weak | none | weak |
| p-012 | plain-blind | yes | 100 | 0.6738 | yes | 0.0 | strong | strong | strong |
| p-006 | plain-blind | yes | 100 | 0.6853 | yes | 0.0 | strong | strong | strong |
| p-024 | plain-blind | yes | 100 | 0.6862 | yes | 0.0 | strong | strong | strong |
| p-027 | plain-blind | yes | 100 | 0.6937 | yes | 0.0 | strong | strong | strong |
| p-008 | plain-blind | yes | 100 | 0.6946 | yes | 0.0 | strong | strong | strong |
| p-019 | plain-blind | yes | 100 | 0.6979 | yes | 0.0 | strong | strong | strong |
| p-014 | plain-blind | yes | 100 | 0.7017 | yes | 0.0 | strong | strong | strong |
| p-025 | plain-blind | yes | 100 | 0.7023 | yes | 0.0 | strong | strong | strong |
| p-030 | plain-blind | yes | 100 | 0.7048 | yes | 0.0 | strong | strong | strong |
| p-002 | plain-blind | yes | 100 | 0.7051 | yes | 1.0 | strong | strong | strong |
| p-009 | plain-blind | yes | 100 | 0.7057 | yes | 0.0 | strong | strong | strong |
| p-007 | plain-blind | yes | 100 | 0.7099 | yes | 0.0 | strong | strong | strong |
| p-021 | plain-blind | yes | 100 | 0.7167 | yes | 0.0 | strong | strong | strong |
| q-mourning-plain | plain | yes | 100 | 0.7237 | yes | 0.0 | strong | strong | strong |
| p-001 | plain-blind | yes | 100 | 0.7252 | yes | 1.0 | strong | strong | strong |
| q-heaviness-plain | plain | yes | 100 | 0.7253 | yes | 0.0 | strong | strong | strong |
| p-028 | plain-blind | yes | 100 | 0.7259 | yes | 0.0 | strong | strong | strong |
| p-013 | plain-blind | yes | 100 | 0.7269 | yes | 0.0 | strong | strong | strong |
| p-005 | plain-blind | yes | 100 | 0.7349 | yes | 0.0 | strong | strong | strong |
| p-017 | plain-blind | yes | 2 | 0.7368 | yes | 0.0 | strong | strong | strong |
| p-011 | plain-blind | yes | 100 | 0.7388 | yes | 0.0 | strong | strong | strong |
| q-evil-speaking-plain | plain | yes | 100 | 0.7401 | yes | 0.0 | strong | strong | strong |
| p-020 | plain-blind | yes | 100 | 0.7418 | yes | 0.0 | strong | strong | strong |
| q-wandering-thoughts-plain | plain | yes | 100 | 0.7433 | yes | 0.0 | strong | strong | strong |
| p-010 | plain-blind | yes | 100 | 0.7440 | yes | 0.0 | strong | strong | strong |
| q-temptation-plain | plain | yes | 100 | 0.7462 | yes | 0.0 | strong | strong | strong |
| q-original-sin-plain | plain | yes | 100 | 0.7462 | yes | 0.0 | strong | strong | strong |
| q-means-plain | plain | yes | 100 | 0.7490 | yes | 0.0 | strong | strong | strong |
| q-wilderness-plain | plain | yes | 100 | 0.7513 | yes | 0.0 | strong | strong | strong |
| p-022 | plain-blind | yes | 100 | 0.7535 | yes | 0.0 | strong | strong | strong |
| q-worry-plain | plain | yes | 100 | 0.7547 | yes | 0.0 | strong | strong | strong |
| q-self-denial-plain | plain | yes | 100 | 0.7552 | yes | 0.0 | strong | strong | strong |
| k-luke-22-19 | scripture-keyword | yes | 55 | 0.7564 | yes | 1.0 | strong | strong | strong |
| q-faith-works-plain | plain | yes | 100 | 0.7581 | yes | 0.0 | strong | strong | strong |
| q-sin-believers-plain | plain | yes | 100 | 0.7583 | yes | 0.0 | strong | strong | strong |
| q-riches-plain | plain | yes | 100 | 0.7597 | yes | 0.0 | strong | strong | strong |
| q-catholic-spirit-plain | plain | yes | 100 | 0.7625 | yes | 0.0 | strong | strong | strong |
| q-worry | names-topic | yes | 100 | 0.7628 | yes | 0.0 | strong | strong | strong |
| q-backsliders-plain | plain | yes | 100 | 0.7629 | yes | 0.0 | strong | strong | strong |
| k-philippians-3-12 | scripture-keyword | yes | 100 | 0.7632 | yes | 1.0 | strong | strong | strong |
| p-015 | plain-blind | yes | 100 | 0.7641 | yes | 0.0 | strong | strong | strong |
| q-original-sin | names-topic | yes | 100 | 0.7652 | yes | 0.0 | strong | strong | strong |
| p-018 | plain-blind | yes | 100 | 0.7660 | yes | 0.0 | strong | strong | strong |
| q-money-plain | plain | yes | 100 | 0.7660 | yes | 0.0 | strong | strong | strong |
| p-003 | plain-blind | yes | 100 | 0.7662 | yes | 0.0 | strong | strong | strong |
| q-forgiveness | plain | yes | 100 | 0.7663 | yes | 1.0 | strong | strong | strong |
| k-matthew-6-34 | scripture-keyword | yes | 84 | 0.7696 | yes | 1.0 | strong | strong | strong |
| q-satan-plain | plain | yes | 100 | 0.7703 | yes | 0.0 | strong | strong | strong |
| q-backsliders | names-topic | yes | 100 | 0.7723 | yes | 1.0 | strong | strong | strong |
| q-assurance-plain | plain | yes | 100 | 0.7731 | yes | 0.0 | strong | strong | strong |
| q-communion-plain | plain | yes | 100 | 0.7732 | yes | 0.0 | strong | strong | strong |
| q-communion | names-topic | yes | 100 | 0.7744 | yes | 0.0 | strong | strong | strong |
| k-gain-all-you-can | scripture-keyword | yes | 100 | 0.7747 | yes | 1.0 | strong | strong | strong |
| q-salvation-plain | plain | yes | 100 | 0.7760 | yes | 0.0 | strong | strong | strong |
| q-wilderness | names-topic | yes | 100 | 0.7766 | yes | 1.0 | strong | strong | strong |
| q-salvation | names-topic | yes | 100 | 0.7791 | yes | 1.0 | strong | strong | strong |
| q-new-birth | names-topic | yes | 100 | 0.7798 | yes | 0.0 | strong | strong | strong |
| q-catholic-spirit | names-topic | yes | 100 | 0.7832 | yes | 1.0 | strong | strong | strong |
| k-2-corinthians-2-11 | scripture-keyword | yes | 66 | 0.7841 | yes | 1.0 | strong | strong | strong |
| q-perfection-plain | plain | yes | 100 | 0.7853 | yes | 0.0 | strong | strong | strong |
| q-prayer | plain | yes | 100 | 0.7885 | yes | 0.0 | strong | strong | strong |
| q-evil-speaking | names-topic | yes | 100 | 0.7886 | yes | 1.0 | strong | strong | strong |
| q-mourning | names-topic | yes | 100 | 0.7889 | yes | 1.0 | strong | strong | strong |
| q-faith-works | names-topic | yes | 100 | 0.7897 | yes | 0.0 | strong | strong | strong |
| k-witness-of-the-spirit | title-keyword | yes | 100 | 0.7910 | yes | 0.0 | strong | strong | strong |
| q-assurance | names-topic | yes | 100 | 0.7923 | yes | 0.0 | strong | strong | strong |
| q-new-birth-plain | plain | yes | 100 | 0.7926 | yes | 0.0 | strong | strong | strong |
| q-justification | names-topic | yes | 100 | 0.7939 | yes | 0.0 | strong | strong | strong |
| q-justification-plain | plain | yes | 100 | 0.7951 | yes | 0.0 | strong | strong | strong |
| k-romans-8-16 | scripture-keyword | yes | 73 | 0.7954 | yes | 1.0 | strong | strong | strong |
| q-satan | names-topic | yes | 100 | 0.7961 | yes | 1.0 | strong | strong | strong |
| q-heaviness | names-topic | yes | 100 | 0.7975 | yes | 1.0 | strong | strong | strong |
| q-temptation | names-topic | yes | 100 | 0.7988 | yes | 1.0 | strong | strong | strong |
| q-perfection | names-topic | yes | 100 | 0.8020 | yes | 0.5 | strong | strong | strong |
| q-money | names-topic | yes | 100 | 0.8053 | yes | 0.0 | strong | strong | strong |
| k-1-corinthians-10-13 | scripture-keyword | yes | 57 | 0.8077 | yes | 1.0 | strong | strong | strong |
| q-riches | names-topic | yes | 100 | 0.8082 | yes | 0.0 | strong | strong | strong |
| q-means | names-topic | yes | 100 | 0.8181 | yes | 1.0 | strong | strong | strong |
| q-wandering-thoughts | names-topic | yes | 100 | 0.8184 | yes | 1.0 | strong | strong | strong |
| k-christian-perfection | title-keyword | yes | 100 | 0.8274 | yes | 1.0 | strong | strong | strong |
| k-means-of-grace | title-keyword | yes | 100 | 0.8341 | yes | 1.0 | strong | strong | strong |
| q-self-denial | names-topic | yes | 100 | 0.8382 | yes | 1.0 | strong | strong | strong |
| q-sin-believers | names-topic | yes | 100 | 0.8442 | yes | 1.0 | strong | strong | strong |

Unlabelled probes (not used to fit; no ground truth), level with the in-sample floor:

| query | BM25 hits | dense top | agree | level |
| --- | --- | --- | --- | --- |
| What did Wesley say about worry? | 0 | 0.7733 | no | weak |
| How can I know that I am a child of God? | 9 | 0.8028 | yes | strong |
| What did Wesley say about money? | 100 | 0.7603 | yes | strong |
| Romans 8:16 | 73 | 0.7954 | yes | strong |
| What did Wesley say about drinking gin? | 0 | 0.7084 | no | weak |
| What did Wesley say about slavery? | 4 | 0.7791 | yes | strong |
| What did Wesley say about electricity? | 8 | 0.7671 | yes | strong |
| Is it okay for Christians to play video games? | 100 | 0.7176 | yes | strong |
| What did Wesley say about dinosaurs? | 0 | 0.7249 | no | weak |
| What did Wesley think about the internet? | 0 | 0.7179 | no | weak |
| Did Wesley support the American Revolution? | 0 | 0.7451 | no | weak |
| What did Wesley teach about climate change and the environment? | 0 | 0.7256 | no | weak |

