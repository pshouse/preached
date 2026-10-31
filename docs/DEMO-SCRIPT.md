# Demo script: 5-minute screen recording (draft for Patrick)

Hard limit is 5:00 (BRIEF.md). This plan totals **4:40**, leaving 20 s of slack. Patrick records and narrates. Nothing here is submitted or deployed.

**Rules for the recording**
- Show only what is on `main` today. Church library wiring and public exposure are **coming**; they are named in narration once and never shown.
- Use only the public-domain Wesley library on screen. No Gaston Community Church audio, titles or transcripts. No real names of members anywhere.
- Every result shown is the preacher's own words. Never imply the app wrote an answer.

All results below were produced by running the real code on `main` (`180a0a4`) against `/cache/index/wesley.sqlite` (8,383 chunks, `index_version` 198339...e363b2) through the page's own path, `/api/search?mode=hybrid&k=5&library=wesley`. The page de-duplicates adjacent chunks, so its first card can differ from `search/query.py`; the numbers here are the page's. Timestamps are h:mm:ss of the sermon audio (`start_s`); the play link starts 0.75 s earlier.

## Shots

### 1. The problem (0:00 to 0:35, 35 s)
- **On screen:** a plain title card ("Preached") for 5 s, then a browser tab of a church sermon archive (any generic list of 100+ audio files, or a slide with "143 recordings, 71 hours"). Keep it generic; no real church.
- **Query:** none.
- **Expected result:** n/a.
- **Narration:** "I'm a deacon, and I run the tech and media at my church. We have years of sermons, and nobody can find anything in them. If you're hurting and you remember the pastor said something about it, you have to guess which Sunday. So I built Preached: you ask a question, and you hear the answer in the preacher's own words."

### 2. Ask a question, jump to the moment (0:35 to 1:50, 75 s)
- **On screen:** the Preached page at the Tailscale URL, View = "John Wesley", How to search = "Words and meaning". Zoom so the card text is readable.
- **Query (type it slowly):** `how should a Christian use money`
- **Expected result (verified):** banner-free, confidence `strong` (dense top 0.909, BM25 and dense agree).
  1. **The Use of Money**, `wesley-050-c0007`, 0:05:17 (start_s 317.48), read by Tim Cote. Snippet: "The fault does not lie in the money, but in them that use it. It may be used ill: and what may not? But it may likewise be used well: ..."
  2. The Use of Money, `wesley-050-c0004`, 0:03:31 (211.47): "An excellent branch of Christian wisdom is here inculcated by our Lord on all his followers, namely, the right use of money ..."
  3. Upon our Lord's Sermon on the Mount, Discourse 8, `wesley-028-c0076`, 0:38:29 (2309.57): "If we waste our money we are not only guilty of wasting a talent which God has given us ..."
- **Actions:** press Play on card 1. Let it run about 10 s so the audience hears the reader start at the passage, not at the top of the sermon. Point at the sermon title, the time, and the cited text source. Then play card 3 for a few seconds to show it jumps across sermons.
- **Narration:** "I'll ask something a regular person would ask: how should a Christian use money. Notice every answer is a real passage with the sermon and the time on it. I press Play and it starts right at that moment, in the middle of the sermon, about a second before the words begin. Nothing here is written by an AI. The AI found it; Wesley said it. The voice you hear is a LibriVox volunteer reading Wesley's published sermon, public domain."
- **Second question, same shot, 25 s:** type `How can I know that I am a child of God?` (this is the page's "Assurance" example button; clicking it is fine).
  - **Expected (verified, `strong`):** 1. **The Witness of the Spirit, Discourse II**, `wesley-011-c0025`, 0:13:00 (780.35): "But this is confirmed, not only by experience of the children of God; thousands of whom can declare that they never did know themselves to be in the favour of God till it was directly witnessed to them by his Spirit ..." 2. THE WITNESS OF THE SPIRIT, Discourse I, `wesley-010-c0010`, 0:05:07 (307.49): "If any need farther light, he may receive it by attending on the ministry of God's Word ..." 3. Discourse I, `wesley-010-c0043`, 0:22:30 (1350.88).
  - **Narration:** "Same thing for a question about assurance. Two sermons by Wesley on exactly this, a few clicks apart."

### 3. When there is no good answer (1:50 to 2:25, 35 s)
- **On screen:** same page.
- **Query:** `what does Wesley say about cryptocurrency`
- **Expected result (verified):** level `none`, the page shows a low-confidence banner: "Low confidence: these passages may not answer your question. This is a rough automatic check (a heuristic), so read them and judge for yourself." The closest cards are The Use of Money (0:04:07, `wesley-050-c0005`) and The Danger of Riches (0:36:29, `wesley-087-c0069`). BM25 found nothing (0 hits), dense top 0.796.
- **Narration:** "Wesley never heard of cryptocurrency. So Preached tells you so: it says these may not answer your question and shows you the closest matches anyway, so you can judge. It's a rough automatic check, not a promise. I'd rather it say 'I'm not sure' than pretend."
- **Avoid on camera:** the page's "Worry" example button. It returns a `weak` result (top card On Riches, 0:18:30, about a man annoyed by smoke from a fire) and is a poor first impression.

### 4. Side by side: a classic preacher and your own pastor (2:25 to 3:05, 40 s)
- **On screen:** set View = "Side by side", re-run `how should a Christian use money`.
- **Expected result (verified through `/api/side`):** the left column is **John Wesley** with the same passages. The right column is **"Your church"** and says: "Nothing from your church yet." This is honest: church libraries are not served on `main` yet (coming, once the publish gate is wired).
- **Narration:** "This is the part I'm most excited about. On the left, how the question was answered through church history. On the right, your own pastor. Right now that column is empty, because I won't show a single church sermon until the pastor has given permission and a person has listened through every recording. When that's done, a member can hear Wesley and their own pastor on the same question, side by side."
- **Do not** narrate this as working with a real church. If you want sample data, say "sample data" aloud and show only the empty state; no sample church library is served by `main` today.

### 5. Privacy and keeping people in the loop (3:05 to 3:45, 40 s)
- **On screen:** the README "YouTube channel import" paragraph, scrolled to the sentences about names, announcements, prayer requests and testimonies (a terminal or editor is fine). Do not open any real review file.
- **Query:** none.
- **Expected result:** n/a.
- **Narration:** "Sermons are public teaching, but a pastor tells stories about real people. So when a church imports its sermons, names are redacted and those passages get no play button. Announcements, prayer requests and testimonies are never indexed at all. And nothing goes live until a person has listened to the whole recording. I tested the automatic rules and they're not enough alone; they caught about 87 percent of the words on a small test set I wrote. That's why the human listen is the real safeguard, not the software."
- Backing: `reports/W3-PRIV-SKIP.md` (635 of 730 words, 0.870, synthetic test set).

### 6. Any church can import its YouTube channel (3:45 to 4:10, 25 s)
- **On screen:** a terminal in a scratch directory outside the repo.
- **Command (verified, dry run, no writes):**
  `uv run --extra youtube import/youtube.py "https://www.youtube.com/watch?v=BGoD6CIpLWQ" --library demo --privacy privacy.example.toml --dry-run`
- **Expected result (verified):** one tab-separated line: `BGoD6CIpLWQ	Are speeches public domain?	2012-08-06	322`. That is a Creative Commons test clip from a non-church channel (`reports/W2-YT.md`).
- **Narration:** "A church just pastes its YouTube channel. Preached lists the videos, pulls the audio only as a working file, transcribes it with timestamps, and keeps the video on YouTube. Here's a dry run on a public test clip: it lists what it would import and writes nothing. For a real church it also needs a privacy file and a human review."
- Do **not** run it without `--dry-run` on camera and do not point it at the Gaston channel (the importer refuses that channel until permission is confirmed).

### 7. Runs on a small CPU box (4:10 to 4:30, 20 s)
- **On screen:** `reports/W3-CPU.md` pick table, or a terminal running `curl localhost:PORT/healthz` showing `"backend": "onnx"`, `"chunks": 8383`.
- **Expected result (verified `/healthz`):** `ok: true, library: wesley, chunks: 8383, model: granite-english-r2, backend: onnx, dense: true, fallback: false`.
- **Narration:** "No GPU, no chat model, no vector database. One SQLite file and one small embedding model on a CPU. A search takes about 56 milliseconds on a single thread. A church doesn't need a server room."
- Backing: `reports/W3-CPU.md` (56 ms p50 on one pinned CPU of a desktop i9; RSS 946 MiB in that harness). Say "on my desktop CPU, limited to one core" if asked; it has not been measured on a Sprite.

### 8. Why it matters to a church (4:30 to 4:40, 10 s; trim to fit)
- **On screen:** back to the results page with the Wesley card playing, or the title card.
- **Narration:** "Every church has a library of teaching nobody can search. Preached lets a person in a hard week hear what their own pastor, and the church before them, actually said, in their own voice, and gets out of the way."

**Total: 35 + 75 + 35 + 40 + 40 + 25 + 20 + 10 = 280 s = 4:40.**

## Pre-flight checklist

Do this the day before and again right before recording.

- [ ] Branch: `main` at or after `180a0a4`; `git status` clean.
- [ ] **Index:** `/cache/index/wesley.sqlite` (default; do not use `wesley-onnx-*.sqlite` copies or `cc-speech.sqlite`). `curl http://HOST:PORT/healthz` must show `"chunks": 8383`, `"index_version": "198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2"`, `"backend": "onnx"`, `"fallback": false`, `"church": null`. If `fallback` is true the server is on BM25 only and the results above will differ.
- [ ] **Start the server** (loopback, from the repo): `uv run app/server.py` (default 127.0.0.1:8000). For the Tailscale URL, follow `docs/DEPLOY.md` ("Bind `PREACHED_HOST=127.0.0.1`... `tailscale serve` to that loopback port, add the tailscale hostname to `PREACHED_HOSTS`"). **URL over Tailscale:** `http://<this machine's tailnet name>:PORT` (the actual name is not recorded anywhere in the repo; fill in: ______ ). Open it once from the recording browser and run one search before hitting record. No tailnet was running on the machine used to write this draft.
- [ ] Do not record the public Sprite URL; there is no public exposure (`docs/DEPLOY.md`, "Going public").
- [ ] Rate limit: 120 requests per 60 s by default, 60 per 60 s via `scripts/serve.sh`. Don't hammer the page between takes; if you see 429 wait a minute.
- [ ] **Browser:** private window, no extensions, bookmarks bar hidden, zoom 125% to 150% so card text reads at 1080p, window about 1280 px wide (the Side by side columns appear at 800 px and wider). Close other tabs and any email or chat.
- [ ] **Audio:** play-through works (audio streams from archive.org, so the machine must be online). Click Play on one card before recording to warm the connection. Set system volume so the LibriVox reader is audible under your voice, or mute the system and re-record over it.
- [ ] **Mic:** headset or USB mic, test level (peaks around -12 dB), room quiet, notifications off.
- [ ] Recording: 1080p, cursor visible, screen recorder set to capture system audio if you want the sermon audio in the video.
- [ ] No church files on screen: Finder/terminal windows must not show `/cache/youtube`, `/cache/index/church*`, or review files.
- [ ] Re-run every query in this script once; if any top result differs from the "Expected" lines, update the script or use a fallback.

## Fallback queries (if one returns a weak result)

All run on the same index through the page path. Verified from `search/query.py` unless noted; confirm on the page in pre-flight, because the page de-duplicates.

| Instead of | Try | Expected top result |
| --- | --- | --- |
| money | `What did Wesley say about money?` (the "Money" button) | The Use of Money, `wesley-050-c0006`, 0:04:47 (287.16); then The Danger of Riches, 0:10:37 (637.22). Level not recorded for this one; check for a banner. |
| assurance | `the witness of the Spirit` | THE WITNESS OF THE SPIRIT, Discourse I, `wesley-010-c0005`, 0:02:49 (169.96): "What is this witness or testimony of our spirit; what is the testimony of God's Spirit ..." Score 0.0308. |
| assurance | `Romans 8:16` (the "Romans 8:16" button) | Not run for this draft. Try it in pre-flight. |
| worry | `take no thought for tomorrow` | Upon our Lord's Sermon on the Mount, Discourse 9, `wesley-029-c0002`, 0:01:52 (112.32): "...shall he not much more clothe you, O ye of little faith? Therefore take no thought, saying, What shall we eat?..." Score 0.0325 (both rankers agree). Use this instead of the "Worry" button. |
| forgiveness | `What has Wesley taught about forgiving someone who wronged me` | Upon our Lord's Sermon on the Mount, Discourse 6, `wesley-026-c0072`, 0:37:19 (2239.57): "If," saith he, "ye forgive men their trespasses, your heavenly Father will also forgive you ..." Second: Justification By Faith, 0:18:10 (1090.4). |
| prayer | `I don't know how to pray anymore` | Sermon on the Mount, Discourse 6, `wesley-026-c0027`, 0:13:17 (797.8) ("the end of your praying is not to inform God ..."); second On Visiting the Sick, 0:16:23 (983.96). Mixed quality; use only if you need a third question. |

**Spurgeon and Edwards.** They are real libraries but the page serves one library per process (`uv run app/server.py --library spurgeon`), and they have no quality evaluation (`reports/W3-LIB.md`). Not recommended for the video. If you want a one-line mention, this CLI result is strong: `uv run search/query.py "fear of death" --mode hybrid -k 3 --library spurgeon` gives *Looking Unto Jesus*, 0:31:39 (1899.94): "And you that fear death, why fear to die? Jesus died before you, and he passed through the iron gates ..." (score 0.0325, read by Alan Chant). Their money query is weak (Spurgeon top hit is about Sunday school teachers); do not use it.

## Things not to say

- Don't say "accuracy" or "percent correct" about search. The only quality numbers are Recall@5 0.614, MRR@10 0.497 and nDCG@10 0.546 on 35 questions whose labels an AI drafted and a human has not yet reviewed (`eval/README.md`).
- Don't say the app is live for any church, public, or deployed. It is not.
- Don't say the audio is Wesley's voice. It is a modern volunteer reading (LibriVox).
- Don't say it "summarizes" or "answers". It finds.
