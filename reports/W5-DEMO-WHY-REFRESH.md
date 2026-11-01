# W5 demo script and submission draft refresh (docs only)

Base: `origin/main` 3a93147a3c71ea2a5127dc77a82a2628d6b5b07f, branch `docs/w5-demo-why-refresh`. Files changed: `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md`, this report. No code, no tests run, nothing read from `/cache`, no server started (so no cache snapshot diff applies: none of PREACHED_CACHE, PREACHED_ONNX_DIR, HF_HOME, DENO_DIR, XDG_CACHE_HOME, UV_CACHE_DIR was set or touched). Neither doc is cited in `docs/DEPLOY.md` or `tests/test_deploy_alerts.py` (grep, no hits), so nothing to re-pin.

## What changed and why

DEMO-SCRIPT
- New 20 s "why" beat inside shot 2: zoom on the grey line under card 1, UI words below, narration that does not overclaim.
- Second question swapped from the Assurance button query to `What is the narrow way to heaven?` (#90 query 18: strong, graded 2,1,2, finds Sermon on the Mount 11 and 12 from plain wording). The old query stays as a verified fallback. Money (shot 2) and cryptocurrency (shot 3) are kept: they were verified on the page at `9fe33ca`, and #90 did not test them; a #90 pick was swapped in only where it adds something (narrow way shows semantic matching). #90's other picks (justified by faith, witness of the Spirit, born again, repentance) are added to the fallback table with their grades.
- Shot 3 gets a "do not generalise" note from #90 section (c) (2 of 4 off-topic queries abstained; 1 false abstain), narration softened to "on a question like this", bitcoin and bicycle as fallbacks that abstained in #90, and an optional "Hide low-confidence results" 5 s.
- "Avoid on camera" list extended with #90's mislabelled queries (prodigal son, suffering, enemies, Super Bowl, cookie, and the three `weak`-but-good phrasings).
- Pre-flight: a why-line check, and the staleness of `9fe33ca` stated at the top. "Things not to say" adds: no "knows when it can't answer", no claim of a retune, the why line is not a correctness claim.
- Sections 4 and 5 narration trimmed so the longer shot 2 fits.

SUBMISSION-DRAFT
- Description mentions the per-result "how it was found" with rank; banner sentence now says "often" (honest after #90); Spurgeon/Edwards clause dropped from the description to stay under 250 (they remain in the claims table).
- New claims-table row for why; banner row carries the #90 numbers; "Not claimed" lists the retune. Status line now says `3a93147`, and says the test-suite and demo-query rows were last run at `9fe33ca` and not re-run.
- The confidence retune ADR/prereg (#93) is untouched and is not claimed done.

## Feature claims and cites (all read on `3a93147`)

| Claim | Cite |
| --- | --- |
| Result carries `why` with keyword_rank, meaning_rank, similarity, found_by | `src/preached/search.py:63-90` (`Why`, `found_by` at 79-82, `as_dict` at 84-90) |
| Server emits it | `app/server.py:732` |
| Page line text "Found by both keyword (#N) and meaning (#M) search", "Found by keyword search only (#N)", "Found by meaning search only (#M)", " · similarity 0.NN" | `app/static/app.js:217-235` |
| Rendered as `<p class="why">` under the card, after the source link | `app/static/app.js:312-313`; style `app/static/app.css:306-322` |
| Similarity sentence and confidence drop-down | `app/static/index.html:63-75` |
| "Hide low-confidence results" button; "Low-confidence results hidden." | `app/static/index.html:78`; `app/static/app.js:338` |
| Low and weak banner wording | `app/static/app.js:336-339` |
| "Words and meaning" and "Side by side" labels | `app/static/index.html:30`, `:39` |
| Ranking unchanged by #88 | `git diff 9fe33ca 3a93147 -- src/preached/search.py`: `_pack` only attaches `why`; the other change is the excerpt paragraph-number regex |
| Abstain 2 of 4 off-topic, 1 false abstain in 21 | `reports/W5-DEMO-QUERY-SPOTCHECK.md` section (c) |

## Chosen queries and #90 evidence

| Use | Query | Evidence |
| --- | --- | --- |
| Shot 2 main | `how should a Christian use money` | Verified at `9fe33ca` (existing script); not in #90 |
| Shot 2 second | `What is the narrow way to heaven?` | #90 q18: strong, dense_top 0.896, 6 keyword hits, grades 2,1,2; #90 demo pick 4 |
| Shot 3 | `what does Wesley say about cryptocurrency` | Verified `none` at `9fe33ca`; #90 supports the type (bitcoin q24, bicycle q25 abstain) but also shows 2 of 4 off-topic did not |
| Fallbacks | justified by faith (q4, 2,2,2, dense 0.941); witness of the Spirit (q16); born again (q15); repentance (q21); pray when anxious (q9, weak) | #90 |

## Limits (open)
- I could not capture the actual why numbers (ranks, similarity) for any demo query: that needs the live server on `/cache`, which this task forbids. The script says to read them off the screen in pre-flight. #90 ran before #88, so it has no `why` data either.
- Money, assurance and cryptocurrency results were last run at `9fe33ca`; the excerpt-regex change since can alter a snippet's first words. Pre-flight re-run is in the checklist.
- #90 pick queries were run on 9690f4f; ranking code is unchanged since, but not re-run.

## Timing estimate

Shot 1: 35 s. Shot 2: 95 s (45 money and Play, 20 why, 30 second question). Shot 3: 35 s. Shot 4: 30 s. Shot 5: 35 s. Shot 6: 25 s. Shot 7: 20 s. Shot 8: 10 s. Total 285 s = 4:45, 15 s slack (was 4:40 with 20 s). Estimates, not a timed read-through.

## Word counts (description block, `sed -n 11,21p | wc -w`)

Before: 231. After: 241. Limit 250.

## PR BODY

Docs-only refresh of the demo script and submission draft to match `main` 3a93147: adds the per-result "why" beat (UI wording cited to file:line), swaps in a #90 query, carries #90's confidence/abstain cautions, and mentions why-transparency in the description (231 to 241 words, limit 250). Does not touch or claim the confidence retune (#93). Why numbers for the demo queries are not recorded (no server run); pre-flight tells Patrick to read them live.

`git diff --stat origin/main..HEAD`:

```
 docs/DEMO-SCRIPT.md            | 48 ++++++++++++++++++++-------------
 docs/SUBMISSION-DRAFT.md       | 16 ++++++-----
 reports/W5-DEMO-WHY-REFRESH.md | 68 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 107 insertions(+), 25 deletions(-)
```
