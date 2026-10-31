# W4-DEMO-DRYRUN: demo script dry run against main

Report only. No code, test, docs, label or index changes; `docs/DEMO-SCRIPT.md` and `docs/SUBMISSION-DRAFT.md` are untouched (other branches own them).

## Setup

- Branch `qa/w4-demo-dryrun` from `origin/main` at `e160e55` (a descendant of `63d8a43`). `git status` was clean before and after.
- Server: `HF_HOME=/cache/huggingface uv run app/server.py --port 8123` (loopback), index `/cache/index/wesley.sqlite` opened read-only. The index sha256 was identical before and after the run (including the full unittest run). Stopped by exact PID (python 120, uv wrapper 116).
- Every query went through `GET /api/search?mode=hybrid&k=5&library=wesley&q=...`, the page's own path. Latency is wall time of one curl-style request, not a p50; the server was not pinned to a core.
- Network used: only what the demo itself does (YouTube dry-run listing; archive.org range request for two of the sermon MP3s).

## Step table

| # | Script step | Command | Result | Top result vs script | Latency |
| --- | --- | --- | --- | --- | --- |
| 1 | Problem card | none | n/a (no app step) | n/a | n/a |
| 2a | Money query | `/api/search?...&q=how should a Christian use money` | PASS | Matches. `strong`, bm25 15 hits, dense top 0.9087, agreement true. 1 The Use of Money `wesley-050-c0007` 0:05:17 (317.48), Tim Cote; 2 `wesley-050-c0004` 0:03:31 (211.47); 3 Sermon on the Mount D8 `wesley-028-c0076` 0:38:29 (2309.57). | 65 ms |
| 2b | Assurance query | `...&q=How can I know that I am a child of God?` | PASS | Matches. `strong`, dense 0.906. 1 Witness of the Spirit II `wesley-011-c0025` 0:13:00 (780.35); 2 Witness I `wesley-010-c0010` 0:05:07 (307.49); 3 `wesley-010-c0043` 0:22:30 (1350.88). | 70 ms |
| 3 | No-answer banner | `...&q=what does Wesley say about cryptocurrency` | PASS | Matches. level `none`, `abstain: true`, note text identical to script, bm25 0 hits, dense top 0.7955. Closest: Use of Money `wesley-050-c0005` 0:04:07 (247.85); Danger of Riches `wesley-087-c0069` 0:36:29 (2189.2). | 76 ms |
| 3b | "Worry" button (avoid) | `...&q=What did Wesley say about worry?` (button text from `app/static/index.html:48`) | PASS (as warned) | `weak`; top On Riches `wesley-108-c0038` 0:18:30 (1110.29). Matches the script's warning. | 57 ms |
| 4 | Side by side | `GET /api/side?q=how should a Christian use money&k=5` | PASS | Classic column same three passages as 2a. Church column: `present: false, empty: true, message: "Nothing from your church yet.", sample: false, label: "Your church"`. Wording matches the script. | 62 ms |
| 5 | Privacy (README) | none | PASS | README.md:62 still holds the sentences about names, announcements, prayer requests, testimonies and the 0.870 / listen-through rule. `reports/W3-PRIV-SKIP.md:67` still says 635/730 = 0.870. | n/a |
| 6 | YouTube dry run | `uv run --extra youtube import/youtube.py "https://www.youtube.com/watch?v=BGoD6CIpLWQ" --library demo --privacy privacy.example.toml --dry-run` | PASS | Exactly `BGoD6CIpLWQ	Are speeches public domain?	2012-08-06	322`. Nothing written (no `demo` file in `/cache/index`, `git status` clean). | 1.7 s |
| 7 | Healthz | `curl localhost:8123/healthz` | PASS | `ok: true, library: wesley, chunks: 8383, model: granite-english-r2, backend: onnx, dense: true, fallback: false, church: null`, `index_version` 198339...e363b2 (matches the checklist). | 21 ms |
| 8 | Closing | none | n/a | n/a | n/a |
| P1 | CLI: Spurgeon fear of death | `uv run search/query.py "fear of death" --mode hybrid -k 3 --library spurgeon` | PASS | Matches: Looking Unto Jesus 0:31:39 (1899.94), score 0.0325, Alan Chant. | 1.4 s (process start included) |
| P2 | CLI: money | `uv run search/query.py "how should a Christian use money" --mode hybrid -k 3` | PASS | Same top two as the page. | 1.4 s |

### Fallback queries (script lines 93-100)

| Query | Script says | Main gives (page path) | Status |
| --- | --- | --- | --- |
| `What did Wesley say about money?` | 1 `wesley-050-c0006` 0:04:47 (287.16); 2 Danger of Riches 0:10:37 (637.22); `strong` | 1 same, 0:04:47; 2 Danger of Riches `wesley-087-c0021` **0:10:22 (622.25)**; 3 Sermon on the Mount D8 `wesley-028-c0077` 0:38:53; `strong` | second hit STALE |
| `the witness of the Spirit` | `wesley-010-c0005` 0:02:49 (169.96), score 0.0308 | same, score 0.0308; `strong` | OK |
| `Romans 8:16` | `strong`, top Witness of the Spirit II | `strong`; top `wesley-011-c0000` Witness II 0:00:32, then Witness I 0:00:33 | OK |
| `take no thought for tomorrow` | `wesley-029-c0002` **0:01:52 (112.32)**, score 0.0325 | same chunk id, but the page shows **0:01:09 (69.24)**, score 0.0325, `strong` | timestamp STALE on page path (112.32 is the CLI value) |
| `What has Wesley taught about forgiving someone who wronged me` | `wesley-026-c0072` 0:37:19 (2239.57); second Justification By Faith 0:18:10 (1090.4) | same two; level is **`weak`** (bm25 0 hits), so a low-confidence label may show | OK, add the `weak` note |
| `I don't know how to pray anymore` | `wesley-026-c0027` 0:13:17 (797.8); second On Visiting the Sick **0:16:23 (983.96)** | first same; second On Visiting the Sick `wesley-098-c0031` **0:15:50 (950.74)**; level `weak` | second hit STALE |

## Phone / judge checks from HTTP alone

- `GET /` returns 200, 4,347 bytes, with `<meta name="viewport" content="width=device-width, initial-scale=1">`. `/static/app.css` (7,068 B), `/static/app.js` (23,521 B) and `/static/favicon.svg` all 200 with correct types. CSP `media-src 'self' https://archive.org https://*.archive.org` allows the audio.
- CSS has `@media (min-width: 640px)` and `(min-width: 800px)` (`app/static/app.css:377`, `:386`), so Side by side stacks under 800 px. The stacked phone layout has not been checked in a real browser (`reports/W3-SIDE.md`). This dry run cannot check it either.
- Jump to the moment: every hit has `audio_url`, `start_s`, `end_s`; the player builds `audio_url#t=<start_s - 0.75>` (`app/static/app.js:44-62`) and then seeks (`:170`). The CLI prints the same fragment (`...sermonsfirstseries_51_wesley_64kb.mp3#t=316.73` for the top hit). `archive.org/download/...` answers a Range request with 302 then 206, `audio/mpeg`, `content-range: bytes 1000000-1000100/15351296` (shot 2 sermon 50) and `/23664128` (sermon 28, card 3), so seeking into the middle works. That does not prove playback on a phone (autoplay rules, iOS media fragments): untested.
- Bad inputs: empty `q` and missing `q` give 400; unknown path 404; `library=spurgeon` and `library=cc-speech` give 400 on this wesley server, as the script says (one library per process).
- The `Worry` button text differs from the `take no thought` fallback, as the script says.

## Numeric claims checked against main

| Claim | Where | Main today | Status |
| --- | --- | --- | --- |
| 8,383 chunks | DEMO-SCRIPT:10, :77; SUBMISSION-DRAFT table | `/healthz` `chunks: 8383`; `reports/W1-C.md:192` 8,383 | OK |
| index_version 198339...e363b2 | DEMO-SCRIPT:10, :77 | identical | OK |
| 987 tests, 0 skipped | SUBMISSION-DRAFT:42 | `Ran 987 tests in 237.9s`, `OK` on `e160e55` (all skip sources present on this box) | OK. Cited sha `47da348` is stale (see below). |
| Rate limit 120/60 s default, 60/60 s via `serve.sh` | DEMO-SCRIPT checklist | `app/server.py:248-249` (120, 60 s); `scripts/serve.sh:93-94` (60, 60). Not hammered live. | OK |
| ~56 ms p50 on one pinned core | DEMO-SCRIPT:64-65; SUBMISSION-DRAFT:21, :35 | `reports/W3-CPU.md:79` says 56 / 68 ms at 1 thread. Here, unpinned, single requests were 49-76 ms (server `took_ms` 58-74 on the three demo queries). Consistent; not a p50. | OK, keep "desktop, one core" wording |
| Embedder alone RSS 683 MiB, peak 903 MiB | DEMO-SCRIPT:65; SUBMISSION-DRAFT:35 | `reports/W3-RSS.md` | OK as cited, but see inconsistency below |
| Full server 722.7 MiB at start / ~728 MiB after queries / peak ~969 MiB | DEMO-SCRIPT:65; SUBMISSION-DRAFT:35 | This run (not the same box state, one sample): `PREACHED_RSS_BYTES 764747776` at start = 729.3 MiB; VmRSS 801,348 kB = **782.6 MiB** after about 45 queries; VmHWM 975,164 kB = **952.4 MiB**. | start and peak are close; "~728 MiB after queries" is about 55 MiB below this run. Say "about 730 MiB at start, under 1 GiB peak". Not a claim to cite as measured. |
| "RSS 683 MiB" vs table | `reports/W3-CPU.md:79` | The pick-table row says **960 MiB** RSS after load; DEMO-SCRIPT/SUBMISSION-DRAFT quote 683 MiB (embedder alone). Two different numbers for "RSS" exist in the repo. | inconsistency: a judge reading `W3-CPU.md` sees 960 MiB |
| Wesley 143 recordings, 71.14 h | SUBMISSION-DRAFT:17 | not rechecked here (reports only) | not checked |

## Required edits (proposed; for the branches that own the files)

`docs/DEMO-SCRIPT.md`
1. `:10` and `:77`: commit `bbdb1ba` is stale. Proposed: "`main` at or after `e160e55` (queries re-run live on it)". Checklist `:77`: "Branch: `main` at or after `e160e55`; `git status` clean."
2. `:79`: "fill in: ______" for the Tailscale URL is still blank on main. Patrick must supply the tailnet name before recording (blocker, see below). Also the default port is 8000; a 8123 run here shows `--port` works.
3. `:95` (money fallback): replace "then The Danger of Riches, 0:10:37 (637.22)" with "then The Danger of Riches, `wesley-087-c0021`, 0:10:22 (622.25)".
4. `:98` (worry fallback): page path top hit is `wesley-029-c0002` at **0:01:09 (69.24)**, not 0:01:52 (112.32); score 0.0325 and `strong` are right. Proposed: "`wesley-029-c0002`, 0:01:09 (69.24) on the page (0:01:52 / 112.32 from `search/query.py`); verify the text on the card before using".
5. `:100` (prayer fallback): second hit "On Visiting the Sick, 0:15:50 (950.74)" (not 0:16:23 / 983.96); add "level `weak`".
6. Forgiveness row (`:99`): add "level `weak`; the page may show the low-confidence label on the cards".
7. `:65` (shot 7 backing): add that a fresh run on `e160e55` started at 729.3 MiB and peaked at 952 MiB (VmHWM), after about 45 queries 782.6 MiB; or drop "about 728 MiB after queries". Resolve the 683 vs 960 MiB wording against `reports/W3-CPU.md:79`.

`docs/SUBMISSION-DRAFT.md`
1. `:3`, `:42`: `47da348` and `bbdb1ba` are stale shas. Tests re-run today on `e160e55` still give `Ran 987 tests`, `OK`, so the count holds; update the sha: "on `main` (`e160e55`)". `:3` should say demo queries were re-checked at `e160e55`.
2. `:35` memory row: same note as DEMO-SCRIPT edit 7 ("about 728 MiB after queries" vs 782.6 MiB seen here), and the 683 vs 960 MiB point above.
3. No other wording found that conflicts with main's behaviour (church column empty state, abstain banner, 8,383 chunks, publish gate in README.md:37).

## Blockers and risks for recording

- Blocker (Patrick action): the tailnet URL is still blank in the script (`DEMO-SCRIPT.md:79`). Nothing here can fill it.
- No blocker in the app itself: all three on-camera queries, the side-by-side empty state, `/healthz`, the CLI line and the YouTube dry run reproduce exactly.
- Audio plays from archive.org (302 then 206); the recording machine must be online. Phone playback, autoplay and the stacked mobile layout are not verified here.
- Fallback rows 1, 4 and 6 above would be caught out on camera if used as written (wrong second hit or timestamp).
- The `weak` level on the forgiveness and prayer fallbacks and `none` on a bare "Worry" query mean those are poor first impressions; stay on the three primary queries.
- No accuracy or "improves" claims are made or supported by this report.
