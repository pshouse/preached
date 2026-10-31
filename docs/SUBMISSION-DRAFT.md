# Submission draft (for Patrick's review)

Status: **draft, not submitted anywhere.** Deadline: Nov 27 2026, 11:59 PM ET (BRIEF.md). Everything below describes what is merged on `main` today. Re-check the claims list if anything merges before you submit.

- **Project name:** Preached
- **Track:** Discipleship & Spiritual Growth
- **Tagline:** Ask a question, hear the answer in the preacher's own words.

## Project description (247 words; limit 250)

Preached lets a church search its whole sermon archive by asking a question, then hear the answer in the preacher's own words.

Ask "How can I know that I am a child of God?" and Preached returns the exact passages, each with the sermon, a timestamp and a Play button that starts the audio just before the moment. It never writes an answer, summary or paraphrase. The AI only transcribes, embeds and ranks, with no chat model. That is a deliberate rule, so no pastor is ever made to say something he did not say.

Today the built-in library is John Wesley's 143 recordings (71.14 hours), with Spurgeon and Edwards as further public-domain libraries. A Side by side view is ready to set a classic preacher beside your own pastor; the church column stays empty until a church's sermons are published.

Any church can build its own library by pasting a YouTube channel. Imports are cautious: names are redacted, announcements, prayer requests and testimonies are never indexed, and a person must listen through each recording before it can be published. We have not published any church's sermons.

When a question has no good answer, Preached says so with a low-confidence banner instead of bluffing. That check is a heuristic, and our evaluation questions were drafted by an AI and still await human review.

It runs on one small CPU server: no GPU, no vector database, one SQLite file, about 56 ms per search on a single thread.

## Honest technical claims and what backs them

Every figure is from a file in the repo. "Eval" figures use 35 answerable questions whose labels an AI agent drafted; a human review is **pending** (`eval/README.md`, "Human review"). Do not call them human-verified.

| Claim | Backing |
| --- | --- |
| No chat/LLM model in the product. The AI transcribes (Whisper), embeds (IBM Granite English R2) and ranks. Results are excerpts with sermon and timestamp. | `AGENTS.md` sections 1-2; `README.md`; `reports/W3-CPU.md` (model pin) |
| Wesley library: 143 of 143 recordings transcribed, 71.14 h, 0 failures; 8,383 searchable timed chunks. | `reports/W1-A.md` (run summary, "Timed chunks"); `/healthz` `chunks: 8383` (run on main for this draft, `reports/W4-DEMO-PREP.md`) |
| Transcript matched to the published CCEL text: mean 98.5% of canonical words anchored (min 93.1%). | `reports/W1-A.md` coverage table |
| Play position: a spot check against the audio found start times off by a median 0.42 s, max 0.76 s; the link starts 0.75 s early to cover it. This is a small spot check, not a full audio-accuracy benchmark. | `reports/W1-CLI.md` (lines citing the W1-C spot check); `reports/W1-C.md`; `README.md` |
| Retrieval on the page's path (hybrid, de-duplicated): Recall@5 0.614, MRR@10 0.497, nDCG@10 0.546 on 35 answerable questions (AI-drafted labels, human review pending). | `README.md`; `reports/W3-CPU.md` Eval table; `eval/results/2026-10-30-dedupe-w3cpu-onnx-fp32.json` |
| Low-confidence banner when a question has no good match; it is a heuristic fitted to the same AI-drafted questions, so its false-abstain rate is likely optimistic. | `reports/W3-POLISH.md` (caveats, section 6); run live in `reports/W4-DEMO-PREP.md` ("cryptocurrency") |
| Runs on a small CPU: ONNX Runtime fp32, 1 thread; 56 ms p50 / 68 ms p95 per search on one pinned CPU of an i9-12900K; RSS 946 MiB after model load in that harness (1.5 GiB in the bundle smoke); runtime install 149 MiB; torch not installed. | `reports/W3-CPU.md` (pick table); `reports/W3-DEPLOY-PREP.md` (smoke). Measured on one pinned core of a desktop CPU, not on a Sprite. |
| ONNX answers are identical to the torch reference: same metrics, cosine of fp32 document vectors at least 0.99999988. int8 was rejected for quality. | `reports/W3-CPU.md` (Parity, Eval) |
| One SQLite file, FTS5 plus brute-force vectors, no vector database. | `AGENTS.md` section 2; `docs/DEPLOY.md` |
| Serve path has a bundle manifest check, read-only index, per-IP rate limit, kill file. Loopback or Tailscale only; public exposure is not done. | `docs/DEPLOY.md`; `reports/W3-DEPLOY-PREP.md` |
| YouTube channel import: lists a channel, downloads audio only as a working file, transcribes with timestamps, stores excerpt plus exact start and end seconds; the video stays on YouTube. Dry run verified against a Creative Commons test clip. | `README.md`; `reports/W2-YT.md`; `reports/W4-DEMO-PREP.md` |
| Church import privacy: names redacted; no play link on name passages; announcements, prayer requests and testimonies excluded; reviewer must listen to the whole recording before approval. The exclusion rules caught 635 of 730 words (0.870) on an AI-written synthetic test set, so the human listen is the real control. | `reports/W3-PRIV-SKIP.md`; `docs/DEPLOY.md`; `BRIEF.md` privacy section |
| Side by side view exists. The church column is empty ("Nothing from your church yet.") until church serving is wired to the publish gate. | `reports/W3-SIDE.md`; live `/api/side` run in `reports/W4-DEMO-PREP.md` |
| Test suite: 693 tests pass on `main`. | `python -m unittest discover -s tests`, run for `reports/W4-DEMO-PREP.md` |
| Spurgeon (6 sermons, 4.32 h) and Edwards (39 tracks, 19.53 h) are separate libraries; they have **no retrieval-quality evaluation**, only a 12/12 smoke test. | `reports/W3-LIB.md` sections 1, 4, 5 |

## Not claimed (kept out on purpose)

- Any church's sermons being searchable or public (permission pending; church serving not wired).
- A public URL (needs threat model, CTO sign-off, Patrick's approval, kill-switch drill: `docs/DEPLOY.md`).
- Any "accuracy" figure beyond the ones above, any user count, any comparison number against spurgeon.ai, SermonAudio or Sermon Shots.
- A stacked-phone-layout check in a real browser (`reports/W3-SIDE.md`: not run).
