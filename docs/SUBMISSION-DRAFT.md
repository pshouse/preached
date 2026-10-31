# Submission draft (for Patrick's review)

Status: **draft, not submitted anywhere.** Deadline: Nov 27 2026, 11:59 PM ET (BRIEF.md). Everything below describes what is merged on `main` (`ad78a75`) today. The test-suite row was re-run on that commit (headline: over 970 tests; the exact count is in the table). Live demo queries were re-run on `ad78a75`; other figures keep the citations in the table. Re-check the claims list if anything merges before you submit.

- **Project name:** Preached
- **Track:** Discipleship & Spiritual Growth
- **Tagline:** Ask a question, hear the answer in the preacher's own words.

## Project description (231 words; limit 250)

Preached lets a church search its whole sermon archive by asking a question, then hear the answer in the preacher's own words.

Ask "How can I know that I am a child of God?" and Preached returns the exact passages, each with the sermon, a timestamp and a Play button that starts the audio just before the moment. It never writes an answer, summary or paraphrase. The AI only transcribes, embeds and ranks, with no chat model. That is a deliberate rule, so no pastor is ever made to say something he did not say.

Today the built-in library is John Wesley's 143 recordings (71.14 hours), with Spurgeon and Edwards as further public-domain libraries. A Side by side view is ready to set a classic preacher beside your own pastor; the church column stays empty until a church's sermons are published.

Any church can build its own library by pasting a YouTube channel. Imports are cautious: names are redacted, announcements, prayer requests and testimonies are never indexed, and our process has a person listen through each recording before publishing. We have not published any church's sermons.

When a question has no good answer, Preached says so with a low-confidence banner instead of bluffing. That check is a heuristic.

It needs only a CPU: no GPU, no vector database, one SQLite file, about 56 ms per search on one desktop CPU core.

## Honest technical claims and what backs them

Every figure is from a file in the repo. The only retrieval-quality statement this draft makes is the pre-registered result in the table below, worded exactly as given there. Its labels were drafted with AI help and only a subset was confirmed blind by a human, so do not call them human-verified.

| Claim | Backing |
| --- | --- |
| No chat/LLM model in the product. The AI transcribes (Whisper), embeds (IBM Granite English R2) and ranks. Results are excerpts with sermon and timestamp. | `AGENTS.md` sections 1-2; `README.md`; `reports/W3-CPU.md` (model pin) |
| Wesley library: 143 of 143 recordings transcribed, 71.14 h, 0 failures; 8,383 searchable timed chunks. | `reports/W1-C.md:192` ("Timed chunks", 8,383), also `reports/W1-B.md`; 143 of 143 and 71.14 h from `reports/W1-A.md`; `/healthz` `chunks: 8383` (run on main for this draft, `reports/W4-DEMO-PREP.md`) |
| Transcript matched to the published CCEL text: mean 98.5% of canonical words anchored (min 93.1%). | `reports/W1-C.md:190` (coverage table) |
| Play position: the link starts 0.75 s before the stored start time as a safety margin. No measured offset is claimed: the repo holds no measurement data for the earlier 0.42 s / 0.76 s spot-check figures, so they are dropped. | `README.md`; `reports/W1-CLI.md` |
| Retrieval quality (the only claim): "In a pre-registered evaluation (58 questions; relevance labels drafted with AI help, a subset confirmed blind by a human), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086)." No accuracy, "improves" or "better" claim is made. | `reports/W3-FUSION-PREREG.md`; CTO-approved wording |
| Low-confidence banner when a question has no good match; it is a heuristic fitted to the project's own evaluation questions, so its false-abstain rate is likely optimistic. | `reports/W3-POLISH.md` (caveats, section 6); run live in `reports/W4-DEMO-PREP.md` ("cryptocurrency") |
| Runs on a CPU: ONNX Runtime fp32, 1 thread; 56 ms p50 / 68 ms p95 per search on one pinned core of a desktop i9-12900K; memory, by setup (never compare across setups): **embedder alone** (no server, no index): 683 MiB RSS / peak (VmHWM) 903 MiB (`reports/W3-RSS.md:23`, `:114`, after the #26 fix); **full server with the Wesley index**, single runs on a desktop: about 730 MiB at start, about 730 to 780 MiB after queries, peak 950 to 970 MiB, under 1 GiB (`reports/W4-DEMO-PREP.md:55`, `:73`; `reports/W4-DEMO-DRYRUN.md`), so plan on roughly 1 GiB of RAM; the 960 MiB "RSS after load" in the `reports/W3-CPU.md:79` pick table is pre-#26, from that report's own `/api/search` bench server (`W3-CPU.md:148`); runtime install 149 MiB; torch not installed. | `reports/W3-CPU.md` (pick table); `reports/W3-RSS.md`. Measured on a desktop CPU, not on a Sprite or server. |
| ONNX answers are identical to the torch reference: cosine of fp32 document vectors at least 0.99999988. int8 was rejected for quality. | `reports/W3-CPU.md` (Parity, Eval) |
| One SQLite file, FTS5 plus brute-force vectors, no vector database. | `AGENTS.md` section 2; `docs/DEPLOY.md` |
| Serve path has a bundle manifest check, read-only index, per-IP rate limit, kill file. Loopback or Tailscale only; public exposure is not done. | `docs/DEPLOY.md`; `reports/W3-DEPLOY-PREP.md` |
| YouTube channel import: lists a channel, downloads audio only as a working file, transcribes with timestamps, stores excerpt plus exact start and end seconds; the video stays on YouTube. Dry run verified against a Creative Commons test clip. | `README.md`; `reports/W2-YT.md`; `reports/W4-DEMO-PREP.md` |
| Church import privacy: names redacted; no play link on name passages; announcements, prayer requests and testimonies excluded; the review step requires `--ack-review`; the software cannot verify the listen, so that part is process. The exclusion rules caught 635 of 730 words (0.870) on an AI-written synthetic test set, so the human listen is the real control. | `reports/W3-PRIV-SKIP.md`; `docs/DEPLOY.md`; `BRIEF.md` privacy section |
| Side by side view exists, and since PR #37 the church column is wired through the publish gate: with a church library named (and `PREACHED_PRIVACY` plus `PREACHED_CHURCH_SIDE=enabled` set), `/api/side` returns its published passages (approved, status ok, coverage clear: `README.md:37`) beside the classic ones; with none, it returns the empty column ("Nothing from your church yet."), as on this demo. **Real church data is still not loaded**; the church path has only been run against synthetic fixtures. | `README.md:37`; `reports/40-W3-CHURCH-GATE-WIRE.md`; `tests/test_church_wire.py` `test_approved_church_passages_appear_beside_the_classic_side` (synthetic "sample" library: `present: true`, one approved passage, `Your church` label); live `/api/side` on main with no church: `present: false`, `message: "Nothing from your church yet."`, classic column unchanged (`reports/W4-SUBMIT-REFRESH.md`) |
| Test suite: over 970 tests. Exact run: 995 pass, 0 skipped, on `main` (`ad78a75`), only when the machine has every skip source: `/cache` ONNX artifacts (`tests/test_embed_backend.py:657`, `:707`, `:714`, `:739`, `:1076`, `:1143`); deno (`tests/test_app_js.py:439`, `:618`; `tests/test_mobile_ux.py:239`; `tests/test_privacy_wire_fix.py:246`; `tests/test_privacy_merge.py:217`); `/cache/asr-repro` clips (`tests/test_coverage.py:291`); the Wesley index and the pinned ONNX model (`tests/test_shutdown.py:173`); the chunked corpus (`tests/test_eval_leak.py:191`). A read-only model mount skips one more test (`tests/test_embed_backend.py:718`). Without any of these, the same 995 tests are collected but those tests skip instead of pass; the count without them was not measured, so do not quote "995 pass" for a machine that lacks them. | `PREACHED_CACHE=/cache uv run python -m unittest discover -s tests` on `ad78a75`: `Ran 995 tests in 228.447s`, `OK`, no skip line (`reports/W4-SUBMIT-FINAL-PASS.md`) |
| Spurgeon (6 sermons, 4.32 h) and Edwards (39 tracks, 19.53 h) are separate libraries; they have **no retrieval-quality evaluation**, only a 12/12 smoke test. | `reports/W3-LIB.md` sections 1, 4, 5 |

## Not claimed (kept out on purpose)

- Any church's sermons being searchable or public (permission pending; no real church data is loaded. Main can serve a church library, in the side-by-side column or alone, only behind the publish gate, and has only been run on synthetic fixtures).
- A public URL (needs threat model, CTO sign-off, Patrick's approval, kill-switch drill: `docs/DEPLOY.md`).
- Any "accuracy", "improves" or "better" claim, any retrieval figure beyond the pre-registered sentence above, any user count, any comparison number against spurgeon.ai, SermonAudio or Sermon Shots.
- A stacked-phone-layout check in a real browser (`reports/W3-SIDE.md`: not run).
