# Demo script: 5-minute screen recording (draft for Patrick)

Hard limit is 5:00 (BRIEF.md). This plan totals **4:45** (per-section estimates in each heading and the total line), leaving 15 s of slack. Patrick records and narrates. Nothing here is submitted or deployed.

**Rules for the recording**
- Show only what is on `main` today. Real church sermons in the side-by-side column and public exposure are **coming**; they are named in narration once and never shown.
- Use only the public-domain Wesley library on screen. No Gaston Community Church audio, titles or transcripts. No real names of members anywhere.
- Every result shown is the preacher's own words. Never imply the app wrote an answer.

Results below were produced by running the real code on `main` (re-run at `9fe33ca`; same top results, levels and timestamps). `main` is now `3a93147`, which adds the per-result "why" line (#88) and a demo-query spot check (#90, `reports/W5-DEMO-QUERY-SPOTCHECK.md`). #88 does not change ranking (`Searcher._pack` only attaches `why`, `src/preached/search.py`), but the excerpt cleanup in that range can change a snippet's first words, and the "why" numbers have **not** been captured for these queries, so read them off the screen in pre-flight. The money and assurance results were run against `/cache/index/wesley.sqlite` (8,383 chunks, `index_version` 198339...e363b2) through the page's own path, `/api/search?mode=hybrid&k=5&library=wesley`. The page de-duplicates adjacent chunks, so its first card can differ from `search/query.py`; the numbers here are the page's. Timestamps are h:mm:ss of the sermon audio (`start_s`); the play link starts 0.75 s earlier.

## Shots

### 1. The problem (0:00 to 0:35, 35 s)
- **On screen:** a plain title card ("Preached") for 5 s, then a browser tab of a church sermon archive (any generic list of 100+ audio files, or a slide with "143 recordings, 71 hours"). Keep it generic; no real church.
- **Query:** none.
- **Expected result:** n/a.
- **Narration:** "I'm a deacon, and I run the tech and media at my church. We have years of sermons, and nobody can find anything in them. If you're hurting and you remember the pastor said something about it, you have to guess which Sunday. So I built Preached: you ask a question, and you hear the answer in the preacher's own words."

### 2. Ask a question, jump to the moment, see why (0:35 to 2:10, 95 s: 45 s money and Play, 20 s why, 30 s second question)
- **On screen:** the Preached page at the Tailscale URL, View = "John Wesley", How to search = "Words and meaning". Zoom so the card text is readable.
- **Query (type it slowly):** `how should a Christian use money`
- **Expected result (verified):** banner-free, confidence `strong` (dense top 0.909, BM25 and dense agree).
  1. **The Use of Money**, `wesley-050-c0007`, 0:05:17 (start_s 317.48), read by Tim Cote. Snippet: "The fault does not lie in the money, but in them that use it. It may be used ill: and what may not? But it may likewise be used well: ..."
  2. The Use of Money, `wesley-050-c0004`, 0:03:31 (211.47): "An excellent branch of Christian wisdom is here inculcated by our Lord on all his followers, namely, the right use of money ..."
  3. Upon our Lord's Sermon on the Mount, Discourse 8, `wesley-028-c0076`, 0:38:29 (2309.57): "If we waste our money we are not only guilty of wasting a talent which God has given us ..."
- **Actions:** press Play on card 1. Let it run about 10 s so the audience hears the reader start at the passage, not at the top of the sermon. Point at the sermon title, the time, and the cited text source. Then play card 3 for a few seconds to show it jumps across sermons.
- **The "why" beat (20 s):** stop the audio, zoom on the smaller line under card 1 (below the cited-text link). It is the UI's own words, one line per card, in this exact form: `Found by both keyword (#N) and meaning (#M) search · similarity 0.NN` (`app/static/app.js:217-235`, rendered at `:312-313`). When a passage came from only one list it reads `Found by keyword search only (#N)` or `Found by meaning search only (#M)`, with the same ` · similarity 0.NN` ending whenever the meaning list contains it. Read the real N, M and similarity for this query off the screen in pre-flight; none are recorded here. Optionally open the page's "What the confidence notes mean" drop-down (`app/static/index.html:63-75`) for the sentence "Similarity is how close a passage's meaning is to your question on the search model's own scale. It is not a percentage or a chance of being right, and even unrelated passages score fairly high."
- **Why narration:** "Under every result it tells you how it was found: by keyword search, by meaning search, or both, and where each ranked it. The similarity is how close the meaning is, on the model's own scale. It's not a percentage, and not a promise it's right. You can see why a passage is listed." (If card 1 reads "meaning search only", say that instead; do not say "both" unless the line does.) Do not read the similarity as a score of correctness.
- **Narration:** "I'll ask something a regular person would ask: how should a Christian use money. Notice every answer is a real passage with the sermon and the time on it. I press Play and it starts right at that moment, in the middle of the sermon, about a second before the words begin. Nothing here is written by an AI. The AI found it; Wesley said it. The voice you hear is a LibriVox volunteer reading Wesley's published sermon (the recordings are public domain in the US)."
- **Second question, same shot, 30 s:** type `What is the narrow way to heaven?` (an everyday phrase, no Scripture reference given).
  - **Expected (from #90 query 18, run on the live demo before the why line shipped; confirm in pre-flight):** level `strong`, dense top 0.896, 6 keyword hits. Top three, all from *Upon our Lord's Sermon on the Mount*: Discourse 11 (Matt 7:13-14, broad way and strait gate), Discourse 12 (Matt 7:15-20, "Every broad way is infallibly a false one"), and Discourse 11 again ("Enter ye in at the strait gate"). #90 graded them 2, 1, 2. Cards 1 and 3 are the same discourse, so do not say "three different sermons".
  - **Narration:** "Now a plain-English question, with no Bible reference. It finds Wesley's sermon on the narrow gate and the broad way, and the line underneath shows which searches found it."
  - Previous second question, still verified at `9fe33ca` and a good fallback: `How can I know that I am a child of God?` (the page's "Assurance" button). Strong; 1. **The Witness of the Spirit, Discourse II**, `wesley-011-c0025`, 0:13:00 (780.35); 2. THE WITNESS OF THE SPIRIT, Discourse I, `wesley-010-c0010`, 0:05:07 (307.49); 3. Discourse I, `wesley-010-c0043`, 0:22:30 (1350.88).

### 3. When there is no good answer (2:10 to 2:45, 35 s)
- **On screen:** same page.
- **Query:** `what does Wesley say about cryptocurrency`
- **Expected result (verified):** level `none`, the page shows a low-confidence banner: "Low confidence: these passages may not answer your question. This is a rough automatic check (a heuristic), so read them and judge for yourself." The closest cards are The Use of Money (0:04:07, `wesley-050-c0005`) and The Danger of Riches (0:36:29, `wesley-087-c0069`). BM25 found nothing (0 hits), dense top 0.796.
- **Narration:** "Wesley never heard of cryptocurrency. On a question like this Preached says so: it says these may not answer your question and shows you the closest matches anyway, so you can judge. It's a rough automatic check, not a promise, and it does miss some. I'd rather it say 'I'm not sure' than pretend."
- **Do not generalise this.** #90 (`reports/W5-DEMO-QUERY-SPOTCHECK.md`, section c) found the check abstained on 2 of 4 off-topic queries (bitcoin and bicycle yes; Super Bowl and cookie recipe only said "weak"), and abstained wrongly on one answerable question ("How should I treat my enemies?"). Never say "it knows when it can't answer". Say "it flags some of them". The `cryptocurrency` result above is the one verified at `9fe33ca`; if it differs on `3a93147`, use `What is the current price of bitcoin?` (#90 query 24: level `none`, abstain) or `How do I fix a flat bicycle tire?` (#90 query 25: level `none`, abstain; the "wheel in the middle of a wheel" hit is a funny lexical coincidence).
- **Optional (5 s):** press the page's "Hide low-confidence results" button (`app/static/index.html:78`) to show the passages collapse ("Low-confidence results hidden.", `app/static/app.js:338`).
- **Avoid on camera** (from #90, where the confidence label did not match the results): `the prodigal son` (strong, but 0,0,0), `Why does God allow suffering?` (strong, mostly off target), `How should I treat my enemies?` (false abstain), `Who won the Super Bowl last year?` and `best chocolate chip cookie recipe` (should abstain, did not), and the pastoral phrasings that read `weak` despite good results (`How should I pray when I'm anxious?`, `How do I deal with doubt in my faith?`, `What does the Bible say about money and riches?`). The `weak` ones are fine only if you narrate "closest matches". Also avoid the page's "Worry" example button. It returns a `weak` result (top card On Riches, 0:18:30, about a man annoyed by smoke from a fire) and is a poor first impression.

### 4. Side by side: a classic preacher and your own pastor (2:45 to 3:15, 30 s)
- **On screen:** set View = "Side by side", re-run `how should a Christian use money`.
- **Expected result (verified through `/api/side`):** the left column is **John Wesley** with the same passages. The right column is **"Your church"** and says: "Nothing from your church yet." This is honest: since PR #37 `main` can fill that column from a church library, but only through the publish gate (approved, reviewed sermons) and only when a church library is named and `PREACHED_CHURCH_SIDE=enabled` is set. No real church data is loaded, and the church path has only been run on synthetic fixtures (`tests/test_church_wire.py`), so this server has no church and shows the empty state.
- **Narration:** "This is the part I'm most excited about. On the left, church history. On the right, your own pastor. That column is empty for now, because I won't show a church sermon until the pastor has given permission and a person has reviewed every recording. After that, a member can hear Wesley and their own pastor on the same question."
- **Do not** narrate this as working with a real church. If you want sample data, say "sample data" aloud and show only the empty state; this server serves no sample church library.

### 5. Privacy and keeping people in the loop (3:15 to 3:50, 35 s)
- **On screen:** the README "YouTube channel import" paragraph, scrolled to the sentences about names, announcements, prayer requests and testimonies (a terminal or editor is fine). Do not open any real review file.
- **Query:** none.
- **Expected result:** n/a.
- **Narration:** "A pastor tells stories about real people. So when a church imports its sermons, names are redacted and those passages get no play button. Announcements, prayer requests and testimonies are never indexed. And nothing goes live until a person has listened to the whole recording. The automatic rules caught about 87 percent of the words on a small AI-written test set, so the human listen is the real safeguard, not the software."
- Backing: `reports/W3-PRIV-SKIP.md` (635 of 730 words, 0.870, synthetic test set).

### 6. Any church can import its YouTube channel (3:50 to 4:15, 25 s)
- **On screen:** a terminal at the repo root (paths below are repo-relative).
- **Command (verified, dry run, no writes):**
  `uv run --extra youtube import/youtube.py "https://www.youtube.com/watch?v=BGoD6CIpLWQ" --library demo --privacy privacy.example.toml --dry-run`
- **Expected result (verified):** one tab-separated line: `BGoD6CIpLWQ	Are speeches public domain?	2012-08-06	322`. That is a Creative Commons test clip from a non-church channel (`reports/W2-YT.md`).
- **Narration:** "A church just pastes its YouTube channel. Preached lists the videos, pulls the audio only as a working file, transcribes it with timestamps, and keeps the video on YouTube. Here's a dry run on a public test clip: it lists what it would import and writes nothing. For a real church it also needs a privacy file and a human review."
- Do **not** run it without `--dry-run` on camera and do not point it at the Gaston channel (the importer refuses that channel until permission is confirmed).

### 7. Runs on a small CPU box (4:15 to 4:35, 20 s)
- **On screen:** `reports/W3-CPU.md` pick table, or a terminal running `curl localhost:PORT/healthz` showing `"backend": "onnx"`, `"chunks": 8383`.
- **Expected result (verified `/healthz`):** `ok: true, library: wesley, chunks: 8383, model: granite-english-r2, backend: onnx, dense: true, fallback: false`.
- **Narration:** "No GPU, no chat model, no vector database. One SQLite file and one small embedding model on a CPU. A search takes under a tenth of a second on a desktop CPU. A church doesn't need a server room."
- Backing, by setup (they are different measurements, never compare one with another). Latency: say "under a tenth of a second on a desktop CPU". Backing: `reports/W3-CPU.md`, latency table row "ONNX fp32, 4 threads, full chip" (p50 28.2 ms, p95 34.5 ms; do not read the numbers out on camera) (4 ONNX Runtime threads; the demo server defaults to 1 via `PREACHED_ORT_INTRA_OP_THREADS`). Method as that report words it: "`/api/search` hybrid, k=10, 40 queries × 3 repeats, one warmup excluded"; the report does not say whether the queries ran back-to-back, and this is not a demo-query measurement. **Embedder alone** (no server, no index): 683 MiB RSS, peak (VmHWM) 903 MiB, `reports/W3-RSS.md:23` and `:114`. **Full server with the Wesley index**, single runs on a desktop: about 730 MiB at start, about 730 to 780 MiB after queries, peak 950 to 970 MiB, under 1 GiB (`reports/W4-DEMO-PREP.md:55` and `:73`; fresh run in `reports/W4-DEMO-DRYRUN.md`). The 960 MiB "RSS after load" in `reports/W3-CPU.md:79` is a pre-#26 figure from that report's own `/api/search` bench server (`W3-CPU.md:148`), not comparable to either. So "under 1 GiB of RAM for the whole server" is the safe thing to say. Say "on my desktop CPU" if asked; it has not been measured on a Sprite.

### 8. Why it matters to a church (4:35 to 4:45, 10 s; trim to fit)
- **On screen:** back to the results page with the Wesley card playing, or the title card.
- **Narration:** "Every church has a library of teaching nobody can search. Preached lets a person in a hard week hear what their own pastor, and the church before them, actually said, in their own voice, and gets out of the way."

**Timing estimate (spoken pace about 150 words a minute; Patrick should time one read-through): 35 + 95 + 35 + 30 + 35 + 25 + 20 + 10 = 285 s = 4:45.** That leaves 15 s of slack under the 5:00 limit. If a take runs long, cut in this order: shot 8 (10 s), the second question in shot 2 (30 s), the Play-card-3 jump (10 s).

## Pre-flight checklist

Do this the day before and again right before recording.

- [ ] Branch: `main` (tree-relative: any main that passes this checklist; query results last re-run at `9fe33ca`, the why line and spot check landed after, see the top of this file); `git status` clean.
- [ ] **Index:** `/cache/index/wesley.sqlite` (default; do not use `wesley-onnx-*.sqlite` copies or `cc-speech.sqlite`). `curl http://HOST:PORT/healthz` must show `"chunks": 8383`, `"index_version": "198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2"` (Patrick's `/cache` build; update if the index is rebuilt), `"backend": "onnx"`, `"fallback": false`, `"church": null`. If `fallback` is true the server is on BM25 only and the results above will differ.
- [ ] **Start the server** (loopback, from the repo): `uv run app/server.py` (default 127.0.0.1:8000). For the Tailscale URL, follow `docs/DEPLOY.md` ("Bind `PREACHED_HOST=127.0.0.1`... `tailscale serve` to that loopback port, add the tailscale hostname to `PREACHED_HOSTS`"). **URL over Tailscale:** `http://<this machine's tailnet name>:PORT` (the actual name is not recorded anywhere in the repo; fill in: ______ ; Patrick's placeholder). Open it once from the recording browser and run one search before hitting record. A tailnet-only demo exists; the public URL is Patrick's decision.
- [ ] Do not record the public Sprite URL; there is no public exposure (`docs/DEPLOY.md`, "Going public").
- [ ] Rate limit: 120 requests per 60 s by default, 60 per 60 s via `scripts/serve.sh`. Don't hammer the page between takes; if you see 429 wait a minute.
- [ ] Per-client cap: more than 4 connections from one IP get a `503` (a self-refreshing HTML "Unavailable. Retrying." page in a browser, `Retry-After: 1`). Keep to one tab, and no more than 4 connections to the demo server at once.
- [ ] **Browser:** private window, no extensions, bookmarks bar hidden, zoom 125% to 150% so card text reads at 1080p, window about 1280 px wide (the Side by side columns appear at 800 px and wider). Close other tabs and any email or chat.
- [ ] **Audio:** play-through works (audio streams from archive.org, so the machine must be online). Click Play on one card before recording to warm the connection. Set system volume so the LibriVox reader is audible under your voice, or mute the system and re-record over it.
- [ ] **Mic:** headset or USB mic, test level (peaks around -12 dB), room quiet, notifications off.
- [ ] Recording: 1080p, cursor visible, screen recorder set to capture system audio if you want the sermon audio in the video.
- [ ] No church files on screen: Finder/terminal windows must not show `/cache/youtube`, `/cache/index/church*`, or review files.
- [ ] Re-run every query in this script once; if any top result differs from the "Expected" lines, update the script or use a fallback.
- [ ] **Narrow-way cards and why lines:** run `What is the narrow way to heaven?` live and read the three cards and each card's "Found by" line. #90's cards (Sermon on the Mount Discourse 11, Discourse 12, Discourse 11 again; level `strong`) were captured before the why line shipped. If the cards or the levels differ, switch to the fallback question `How can I know that I am a child of God?` and its expected results in shot 2.
- [ ] **Why line:** on the money query, confirm every card shows a grey line starting "Found by" (it is hidden only when the server sends no `why`). Write down the keyword rank, meaning rank and similarity on card 1 so the narration matches what the viewer sees. If a card says "meaning search only", the narration must say that.

## Fallback queries (if one returns a weak result)

All run on the same index through the page path. Verified from `search/query.py` unless marked "(page path)"; confirm on the page in pre-flight, because the page de-duplicates.

| Instead of | Try | Expected top result |
| --- | --- | --- |
| money | `What did Wesley say about money?` (the "Money" button) | The Use of Money, `wesley-050-c0006`, 0:04:47 (287.16); then The Danger of Riches, `wesley-087-c0021`, 0:10:22 (622.25). (page path) Level `strong`. |
| assurance | `the witness of the Spirit` | THE WITNESS OF THE SPIRIT, Discourse I, `wesley-010-c0005`, 0:02:49 (169.96): "What is this witness or testimony of our spirit; what is the testimony of God's Spirit ..." Score 0.0308. |
| assurance | `Romans 8:16` (the "Romans 8:16" button) | (page path) Level `strong`; top hit The Witness of the Spirit, Discourse II. |
| worry | `take no thought for tomorrow` | Upon our Lord's Sermon on the Mount, Discourse 9, `wesley-029-c0002`. **Page path: 0:01:09 (69.24)**; `search/query.py` shows 0:01:52 (112.32). Verify the text on the card before using: "...shall he not much more clothe you, O ye of little faith? Therefore take no thought, saying, What shall we eat?..." Score 0.0325, level `strong` (both rankers agree). Use this instead of the "Worry" button. |
| any | `What does it mean to be justified by faith?` | #90 query 4: `strong`, dense top 0.941, graded 2,2,2: Justification By Faith (Rom 4:5), The Lord our Righteousness, Justification By Faith again. The best single query in #90. Not yet seen with the why line. |
| any | `What is the witness of the Spirit?` | #90 query 16: `strong`; THE WITNESS OF THE SPIRIT, Discourse I first, Discourse II third (graded 2,1,2). |
| any | `How do I know if I am truly born again?` | #90 query 15: `strong`, graded 2,2,2, all three from The New Birth (no spread across sermons). |
| forgiveness | `What has Wesley taught about forgiving someone who wronged me` | Upon our Lord's Sermon on the Mount, Discourse 6, `wesley-026-c0072`, 0:37:19 (2239.57): "If," saith he, "ye forgive men their trespasses, your heavenly Father will also forgive you ..." Second: Justification By Faith, 0:18:10 (1090.4). (page path) Level `weak` (BM25 found 0 hits), so the cards may show the "closest matches, not strong ones" note. |
| prayer | `I don't know how to pray anymore` | Sermon on the Mount, Discourse 6, `wesley-026-c0027`, 0:13:17 (797.8) ("the end of your praying is not to inform God ..."); second On Visiting the Sick, `wesley-098-c0031`, 0:15:50 (950.74) (page path). Level `weak`. Mixed quality; use only if you need a third question. |
| prayer | `How should I pray when I'm anxious?` | #90 query 9: top card The Means of Grace ("When trouble and heaviness take hold upon him ... always to pray and not to faint"), graded 2, but the banner reads `weak`, so the "closest matches" note shows. Use only if you narrate that; otherwise `What is repentance?` (#90 query 21, `strong`, graded 2,2,2). |

**Spurgeon and Edwards.** They are real libraries but the page serves one library per process (`uv run app/server.py --library spurgeon`), and they have no quality evaluation (`reports/W3-LIB.md`). Not recommended for the video. If you want a one-line mention, this CLI result is strong: `uv run search/query.py "fear of death" --mode hybrid -k 3 --library spurgeon` gives *Looking Unto Jesus*, 0:31:39 (1899.94): "And you that fear death, why fear to die? Jesus died before you, and he passed through the iron gates ..." (score 0.0325, read by Alan Chant). Their money query is weak (Spurgeon top hit is about Sunday school teachers); do not use it.

## Things not to say

- Don't say "accuracy", "percent correct", "improves" or "better" about search. The only retrieval-quality sentence to use, verbatim: "In a pre-registered evaluation (58 questions; relevance labels drafted with AI help, a subset confirmed blind by a human), the tuned fusion weight was statistically indistinguishable from the baseline (hit@10 51 vs 50; paired difference +0.017, 95% CI −0.034 to +0.086)." Do not quote any other eval number. Demo with the preacher's own vocabulary or topics, not everyday phrasing.
- Don't say the app is live for any church, public, or deployed. It is not.
- Don't say the audio is Wesley's voice. It is a modern volunteer reading (LibriVox).
- Don't say it "summarizes" or "answers". It finds.
- Don't say the confidence check "knows when it can't answer", and don't say it has been improved or retuned. A retune is planned but not done; the check on `main` is the rough heuristic the page describes.
- Don't call the "why" line an explanation of correctness. It says which search lists found the passage and where it ranked; similarity is "not a percentage or a chance of being right" (`app/static/index.html:75`).
