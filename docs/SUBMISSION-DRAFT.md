# Submission draft (for Patrick's review)

Status: **draft, not submitted anywhere.** Deadline: Nov 27 2026, 11:59 PM ET (BRIEF.md). Everything below describes what is merged on `main` (`47da348`) today. The test-suite row was re-run on that commit (headline: over 970 tests; the exact count is in the table). Other figures keep the citations in the table; live demo queries were last re-checked at `bbdb1ba`. Re-check the claims list if anything merges before you submit.

- **Project name:** Preached
- **Track:** Discipleship & Spiritual Growth
- **Tagline:** Ask a question, hear the answer in the preacher's own words.

## Project description (245 words; limit 250)

Preached lets a church search its whole sermon archive by asking a question, then hear the answer in the preacher's own words.

Ask "How can I know that I am a child of God?" and Preached returns the exact passages, each with the sermon, a timestamp and a Play button that starts the audio just before the moment. It never writes an answer, summary or paraphrase. The AI only transcribes, embeds and ranks, with no chat model. That is a deliberate rule, so no pastor is ever made to say something he did not say.

Today the built-in library is John Wesley's 143 recordings (71.14 hours), with Spurgeon and Edwards as further public-domain libraries. A Side by side view is ready to set a classic preacher beside your own pastor; the church column stays empty until a church's sermons are published.

Any church can build its own library by pasting a YouTube channel. Imports are cautious: names are redacted, announcements, prayer requests and testimonies are never indexed, and our process has a person listen through each recording before publishing. We have not published any church's sermons.

When a question has no good answer, Preached says so with a low-confidence banner instead of bluffing. That check is a heuristic, and our evaluation questions were drafted by an AI and still await human review.

It needs only a CPU: no GPU, no vector database, one SQLite file, about 56 ms per search on one desktop CPU core.

## Honest technical claims and what backs them

Every figure is from a file in the repo. "Eval" figures use 35 answerable questions whose labels an AI agent drafted; a human review is **pending** (`eval/README.md`, "Human review"). Do not call them human-verified.

| Claim | Backing |
| --- | --- |
| No chat/LLM model in the product. The AI transcribes (Whisper), embeds (IBM Granite English R2) and ranks. Results are excerpts with sermon and timestamp. | `AGENTS.md` sections 1-2; `README.md`; `reports/W3-CPU.md` (model pin) |
| Wesley library: 143 of 143 recordings transcribed, 71.14 h, 0 failures; 8,383 searchable timed chunks. | `reports/W1-C.md:192` ("Timed chunks", 8,383), also `reports/W1-B.md`; 143 of 143 and 71.14 h from `reports/W1-A.md`; `/healthz` `chunks: 8383` (run on main for this draft, `reports/W4-DEMO-PREP.md`) |
| Transcript matched to the published CCEL text: mean 98.5% of canonical words anchored (min 93.1%). | `reports/W1-C.md:190` (coverage table) |
| Play position: the link starts 0.75 s before the stored start time as a safety margin. No measured offset is claimed: the repo holds no measurement data for the earlier 0.42 s / 0.76 s spot-check figures, so they are dropped. | `README.md`; `reports/W1-CLI.md` |
| Retrieval, bench path (hybrid, de-duplicated; from the bench script, not the web page): Recall@5 0.614, MRR@10 0.497, nDCG@10 0.546 on 35 answerable questions (AI-drafted labels, human review pending). **Caveat:** main's own evals say this headline mostly measured title lookup. On plain-language questions nDCG@10 is 0.028 and R@5 0.040; on questions written blind to the corpus the default finds an acceptable passage in the top 10 for 3 of 28 (0.11). So the demo works best when you ask in the preacher's own vocabulary or by topic, not in everyday words. | `README.md`; `reports/W3-CPU.md` Eval table; `eval/results/2026-10-30-dedupe-w3cpu-onnx-fp32.json`; `reports/EVAL-DELEAK.md:7`; `reports/EVAL-GRADE.md:20` |
| Low-confidence banner when a question has no good match; it is a heuristic fitted to the same AI-drafted questions, so its false-abstain rate is likely optimistic. | `reports/W3-POLISH.md` (caveats, section 6); run live in `reports/W4-DEMO-PREP.md` ("cryptocurrency") |
| Runs on a CPU: ONNX Runtime fp32, 1 thread; 56 ms p50 / 68 ms p95 per search on one pinned core of a desktop i9-12900K; memory, by setup: 683 MiB RSS / peak (VmHWM) 903 MiB is the embedder alone (`reports/W3-RSS.md`, after the #26 fix); 722.7 MiB at start / about 728 MiB after queries (`reports/W4-DEMO-PREP.md:55`) / peak about 969 MiB (`reports/W4-DEMO-PREP.md:73`) is the full server with the Wesley index (CTO review of `efdf8ab`, not re-measured by an agent); runtime install 149 MiB; torch not installed. | `reports/W3-CPU.md` (pick table); `reports/W3-RSS.md`. Measured on a desktop CPU, not on a Sprite or server. |
| ONNX answers are identical to the torch reference: same metrics, cosine of fp32 document vectors at least 0.99999988. int8 was rejected for quality. | `reports/W3-CPU.md` (Parity, Eval) |
| One SQLite file, FTS5 plus brute-force vectors, no vector database. | `AGENTS.md` section 2; `docs/DEPLOY.md` |
| Serve path has a bundle manifest check, read-only index, per-IP rate limit, kill file. Loopback or Tailscale only; public exposure is not done. | `docs/DEPLOY.md`; `reports/W3-DEPLOY-PREP.md` |
| YouTube channel import: lists a channel, downloads audio only as a working file, transcribes with timestamps, stores excerpt plus exact start and end seconds; the video stays on YouTube. Dry run verified against a Creative Commons test clip. | `README.md`; `reports/W2-YT.md`; `reports/W4-DEMO-PREP.md` |
| Church import privacy: names redacted; no play link on name passages; announcements, prayer requests and testimonies excluded; the review step requires `--ack-review`; the software cannot verify the listen, so that part is process. The exclusion rules caught 635 of 730 words (0.870) on an AI-written synthetic test set, so the human listen is the real control. | `reports/W3-PRIV-SKIP.md`; `docs/DEPLOY.md`; `BRIEF.md` privacy section |
| Side by side view exists, and since PR #37 the church column is wired through the publish gate: with a church library named (and `PREACHED_PRIVACY` plus `PREACHED_CHURCH_SIDE=enabled` set), `/api/side` returns its published passages (approved, status ok, coverage clear) beside the classic ones; with none, it returns the empty column ("Nothing from your church yet."), as on this demo. **Real church data is still not loaded**; the church path has only been run against synthetic fixtures. | `README.md:37`; `reports/40-W3-CHURCH-GATE-WIRE.md`; `tests/test_church_wire.py` `test_approved_church_passages_appear_beside_the_classic_side` (synthetic "sample" library: `present: true`, one approved passage, `Your church` label); live `/api/side` on main with no church: `present: false`, `message: "Nothing from your church yet."`, classic column unchanged (`reports/W4-SUBMIT-REFRESH.md`) |
| Test suite: over 970 tests. Exact run: 987 pass, 0 skipped, on `main` (`47da348`), only when the machine has every skip source: `/cache` ONNX artifacts (`tests/test_embed_backend.py:657`, `:707`, `:714`, `:739`, `:1076`, `:1143`); deno (`tests/test_app_js.py:439`, `:618`; `tests/test_mobile_ux.py:239`; `tests/test_privacy_wire_fix.py:246`; `tests/test_privacy_merge.py:217`); `/cache/asr-repro` clips (`tests/test_coverage.py:291`); the Wesley index and the pinned ONNX model (`tests/test_shutdown.py:173`); the chunked corpus (`tests/test_eval_leak.py:169`). A read-only model mount skips one more test (`tests/test_embed_backend.py:718`). Without any of these, some tests skip. | `uv run python -m unittest discover -s tests` on `47da348`: `Ran 987 tests in 242.526s`, `OK`, no skip line (`reports/W4-SUBMIT-NITS.md`) |
| Spurgeon (6 sermons, 4.32 h) and Edwards (39 tracks, 19.53 h) are separate libraries; they have **no retrieval-quality evaluation**, only a 12/12 smoke test. | `reports/W3-LIB.md` sections 1, 4, 5 |

## Not claimed (kept out on purpose)

- Any church's sermons being searchable or public (permission pending; no real church data is loaded. Main can serve a church library, in the side-by-side column or alone, only behind the publish gate, and has only been run on synthetic fixtures).
- A public URL (needs threat model, CTO sign-off, Patrick's approval, kill-switch drill: `docs/DEPLOY.md`).
- Any "accuracy" figure beyond the ones above, any user count, any comparison number against spurgeon.ai, SermonAudio or Sermon Shots.
- A stacked-phone-layout check in a real browser (`reports/W3-SIDE.md`: not run).
