# W4-DEMO-DRYRUN-2: demo script re-run against today's main

Report only. One new file. `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md`, `docs/DEPLOY.md` and `README.md` are untouched (open PRs #74, #80 and pending work own them). No retrieval-quality claim is made here.

## Bottom line

**Every demo step still works on main (`9fe33ca`). Every query, rank, timestamp, confidence level and banner in `docs/DEMO-SCRIPT.md` matches what the live server returns.** No recording blocker. What is stale is bookkeeping: the pinned sha, the test count, and a few line cites. The one number to word carefully is latency (see step 7).

## Setup

- Branch `qa/w4-demo-dryrun-2` from `origin/main` `9fe33ca` (94 commits after `a40706b`, the sha the script pins). `git status` was clean before; my checkout was on `fix/w3-listen-backlog` with a clean tree, and I only created the new branch.
- Cache safety: `PREACHED_CACHE`, `HF_HOME`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `DENO_DIR` all pointed at a `mktemp -d` dir under `/tmp` (`HF_HUB_OFFLINE=1`). The temp dir held a copy of only `index/wesley.sqlite` (later also `spurgeon.sqlite`, 3 MB) and the pinned ONNX folder `47ea694b…` minus `model.int8.onnx`. The model dir and the index files were `a-w`.
  - **Finding:** with the whole copy read-only the server refuses to start: `wesley.sqlite is not a SQLite index (attempt to write a readonly database)`. The index file is WAL-mode, so SQLite must create `-shm`/`-wal` beside it. I made the temp `index/` directory (not the file, which stays `0444`) owner-writable; the server then opened it "read-only" and created `-shm`/`-wal` in the temp copy. A pure read-only mount of the index directory will not serve. Worth a line in DEPLOY if the Sprite mounts `index/` read-only (the bundle path may handle this; not tested here).
- Server: `uv run app/server.py --port 8765` (the documented way, loopback). Stopped by exact PID (`kill 198`, the python child; the `uv` parent exited with it). No `pkill`/`killall`.
- Temp copy deleted at the end after asserting its resolved path was under `tempfile.gettempdir()`.
- Network used: only the demo's own: YouTube dry-run listing, and a 1000-byte `Range` request to archive.org for the card 1 and card 3 MP3s.
- Machine: i9-12900K (24 threads), the same CPU model as the latency claim.
- Not run: the full test suite (not part of this task; only a collection count, see numeric checks).

## Step table

All through `GET /api/search?mode=hybrid&k=5&library=wesley&q=…` (the page's path). "Matches" means the Expected line in `docs/DEMO-SCRIPT.md` is reproduced exactly (title, chunk id, timestamp, level, snippet start).

| Shot | Command | Result | Top result (title, timestamp) | Matches script? | Latency (wall / `took_ms`) |
| --- | --- | --- | --- | --- | --- |
| 1 | none | n/a | n/a | n/a | n/a |
| 2a | `curl 'localhost:8765/api/search?q=how+should+a+Christian+use+money&mode=hybrid&k=5&library=wesley'` | PASS | The Use of Money, `wesley-050-c0007`, 0:05:17 (317.48), Tim Cote; then `-c0004` 0:03:31; then Sermon on the Mount D8 `wesley-028-c0076` 0:38:29. Level `strong`, dense top 0.909, bm25 hits 15, agreement true | Yes, all three, snippets too | 95 ms / 87 |
| 2b | same, `q=How can I know that I am a child of God?` | PASS | The Witness of the Spirit, Discourse II, `wesley-011-c0025`, 0:13:00 (780.35); then `wesley-010-c0010` 0:05:07; then `wesley-010-c0043` 0:22:30. `strong` | Yes | 125 ms / 122 |
| 3 | same, `q=what does Wesley say about cryptocurrency` | PASS | The Use of Money `wesley-050-c0005` 0:04:07; The Danger of Riches `wesley-087-c0069` 0:36:29. `abstain: true`, level `none`, bm25 hits 0, dense top 0.796, note text identical to the script's banner | Yes | 81 ms / 79 |
| 3 (avoid) | `q=What did Wesley say about worry?` (the "Worry" chip) | PASS (still weak) | On Riches `wesley-108-c0038` 0:18:30, then The Danger of Riches 0:36:51 (the baronet/smoke story). Level `weak` | Yes: the "avoid on camera" advice still holds | 76 ms |
| 4 | `curl '…/api/side?q=how+should+a+Christian+use+money&k=3'` | PASS | Classic column "John Wesley" = same 3 passages as 2a. `church`: `label: "Your church", present: false, empty: true, message: "Nothing from your church yet."`. CLI `search/query.py … --mode bm25 --side` prints the same empty state | Yes | 126 ms |
| 5 | none (README paragraph) | n/a | `README.md` "YouTube channel import" still has the names / announcements / prayer / testimonies sentences and the 0.870 figure | Yes | n/a |
| 6 | `uv run --extra youtube import/youtube.py "https://www.youtube.com/watch?v=BGoD6CIpLWQ" --library demo --privacy privacy.example.toml --dry-run` | PASS | `BGoD6CIpLWQ	Are speeches public domain?	2012-08-06	322`, exit 0, 2.5 s, nothing written | Yes, byte for byte | 2.5 s |
| 7 | `curl localhost:8765/healthz` | PASS | `ok: true, library: wesley, chunks: 8383, model: granite-english-r2, backend: onnx, dense: true, fallback: false, church: null`, `index_version` 198339…e363b2 (same as the checklist), `model_sha256 3861025a…` | Yes | 26 ms |
| 7 | 32 warm `/api/search` calls, 8 queries, 0.6 s apart, server unpinned, 1 ORT thread | measured | p50 72 ms / p95 86 ms wall (`took_ms` p50 70 / p95 84) | **Not the 56 ms the script says** (see edit 2; not attributed) | n/a |
| 7 | `/proc/<pid>/status` after the run | measured | VmRSS 800,460 kB (782 MiB), VmHWM 974,920 kB (952 MiB) | Within "under 1 GiB"; peak is at the top of "950 to 970 MiB" | n/a |
| 8 | none | n/a | n/a | n/a | n/a |

Fallback table (all via the page path), all match `docs/DEMO-SCRIPT.md`:

| Query | Top result | Level | Matches? |
| --- | --- | --- | --- |
| `What did Wesley say about money?` | The Use of Money `wesley-050-c0006` 0:04:47, then The Danger of Riches `wesley-087-c0021` 0:10:22 | strong | Yes |
| `the witness of the Spirit` | THE WITNESS OF THE SPIRIT, Discourse I, `wesley-010-c0005` 0:02:49 | strong | Yes |
| `Romans 8:16` | The Witness of the Spirit, Discourse II (`wesley-011-c0000`, 0:00:32) | strong | Yes |
| `take no thought for tomorrow` | Sermon on the Mount D9 `wesley-029-c0002` 0:01:09 (69.24) | strong | Yes |
| `What has Wesley taught about forgiving someone who wronged me` | Sermon on the Mount D6 `wesley-026-c0072` 0:37:19, then Justification By Faith 0:18:10 | weak | Yes |
| `I don't know how to pray anymore` | Sermon on the Mount D6 `wesley-026-c0027` 0:13:17, then On Visiting the Sick `wesley-098-c0031` 0:15:50 | weak | Yes |
| CLI `search/query.py "fear of death" --mode hybrid -k 3 --library spurgeon` | Looking Unto Jesus, 0:31:39 (1899.94), score 0.0325, Alan Chant | n/a | Yes |

## Required edits to the owner docs (do not apply here)

`docs/DEMO-SCRIPT.md`

1. `:10` and `:77` pin `a40706b` ("every query below was re-run live on it"; "`main` at or after `a40706b`"). Main is 94 commits past it. Proposed `:10` wording: "…on `main` (re-run again at `9fe33ca`; every query below returned the same top results, levels and timestamps)". Proposed `:77`: keep "at or after `a40706b`" or say "tree-relative: any main that passes the checklist below".
2. `:62-66` latency. This run measured p50 72 ms / p95 86 ms (unpinned, warm, 1 ORT thread, same i9-12900K), not 56 ms. The 56 / 68 ms figure is from `reports/W3-CPU.md:79` with the process pinned to one core, and that is how it is cited. The narration at `:64` ("A search takes about 56 milliseconds on my desktop, on one core") was **not reproduced under demo conditions** (unpinned, k=5, 8 queries 0.6 s apart, n=32: p50 72 / p95 86 ms). A pinned run with the W3-CPU method was not done, so the gap is not attributed. The setups also differ from the `reports/W3-CPU.md:149` bench in four ways: k=5 vs 10; 8 demo queries vs the 40 eval queries; calls 0.6 s apart vs back to back; n=32 vs 120. The 8 queries are listed below. Proposed narration: "A search takes well under a tenth of a second on a desktop CPU, one core of compute." Or measure a pinned run with the W3-CPU method before recording if 56 ms is wanted.

   The 8 queries of the n=32 run (4 calls each): I could not recover the exact list. The latency script and its notes were in my temp dir, which was deleted, and nothing on the branch records them; I will not guess. The queries reported in this file (step table and fallback table) are the ones I ran for correctness, not necessarily the latency set.
3. `:81` rate limit: still correct (`app/server.py:263` default 120, `scripts/serve.sh:93` 60 per 60 s). No change.
4. Add a pre-flight line for the per-client caps now documented in README: 4 connections and 4 requests in flight per IP (`PREACHED_MAX_CLIENT_CONNECTIONS`, `PREACHED_MAX_CLIENT_REQUESTS`); over the cap the server answers `503` with `Retry-After: 1`. Proposed wording: "Don't open more than 4 tabs or connections to the demo server at once; a fifth gets `503` (an HTML 'Unavailable. Retrying.' page that refreshes after 1 s in a browser)." Verified below. Nothing in the demo path approaches it.

`docs/SUBMISSION-DRAFT.md`

5. `:3` and `:42` pin `a40706b` and "998 pass, 0 skipped". Collection on main (`9fe33ca`) now finds **1081** tests (`unittest` loader `countTestCases()`), so "998" is stale. I did not run the suite (not in scope), so no pass count is known for main. Proposed wording: keep "over 970 tests" (still true) and replace the exact-count clause with "1081 tests are collected on `9fe33ca`; the last full pass run was 998 on `a40706b`", or re-run the suite at submission time on a machine with all skip sources and put that number in.
6. `:42` skip-source cites. Checked against main: `tests/test_embed_backend.py` `:657 :707 :714 :739 :718` still point at the condition line (the `skipTest` is the next line, fine); `:1076` and `:1143` point at the line before the condition (an assignment), and the condition is the next line. Drifted: `tests/test_app_js.py:439` and `:618` (deno skips are now `need_deno` at `:432-437`, used at `:454` and `:635`); `tests/test_eval_leak.py:231` (skip at `:233`). `tests/test_mobile_ux.py:318`, `tests/test_privacy_wire_fix.py:248` (the `need_deno(self)` call), `tests/test_privacy_merge.py:217`, `tests/test_coverage.py:291`, `tests/test_shutdown.py:173` still hold.
7. `:41` cites `README.md:37` for the church gate ("approved, status ok, coverage clear"). On main `README.md:37` is a code fence; the paragraph is `README.md:39`. Proposed: cite `README.md:39` (or "README, 'Another library is a separate SQLite file' paragraph" tree-relative).
8. Numbers checked and still correct: 8,383 chunks (`/healthz`; `reports/W1-C.md:192`), mean 98.5% / min 93.1% (`reports/W1-C.md:190`), `reports/W3-RSS.md:23` (683 MiB) and `:114` (903 MiB), `reports/W3-CPU.md:79` and `:148`, 635 of 730 / 0.870, model name `granite-english-r2`, ONNX fp32 / 1 thread. The embedder-plus-server memory claim ("peak 950 to 970 MiB, under 1 GiB") held: this run peaked at 952 MiB. `reports/W4-DEMO-PREP.md:55` and `:73` cite lines are the rows quoted. Not re-measured by me: 143 recordings, 71.14 h (corpus manifests, not part of this run), the CC/model-pin claims and the 149 MiB runtime figure.

No "accuracy", "improves" or "better" wording appears in either doc; the only retrieval-quality sentence is the pre-registered one (CTO #54).

## What a judge hits on a phone (HTTP-only checks)

- `GET /` returns 200, 4,347 bytes, `text/html`, with `<meta name="viewport" content="width=device-width, initial-scale=1">`. CSS has `@media (min-width: 640px)` and `(min-width: 800px)`; below 800 px the side-by-side columns stack. `/static/app.js` 200. The stacked-phone layout has still not been looked at in a real browser (`reports/W3-SIDE.md`); this check proves only that the page and its assets load.
- HTML 503 page: with 4 idle connections held from one client IP, a 5th request with `Accept: text/html` got `503`, `Content-Type: text/html`, `Retry-After: 1`, body `<meta http-equiv="refresh" content="1">…Unavailable. Retrying.`. With `Accept: application/json` it got `503` and `{"error":"unavailable"}`. After the connections closed `/` returned 200 again. This matches the #77 behaviour; a judge who hits the cap sees a self-retrying page, not raw JSON.
- Player jumps to the moment: every result carries `audio_url`, `start_s`, and the page subtracts a `PREROLL_S = 0.75` (`app/static/app.js:44`); CLI play links use `#t=` = start − 0.75 (card 3: 2308.82 vs start 2309.57). archive.org served a 1000-byte `Range` request (206) at the card 1 offset (317 s into `sermonsfirstseries_51…mp3`) and for the card 3 file, so seeking works with no full download. Not verified: actual audible playback in a browser (the machine's audio and the player are not HTTP-checkable). The `audio.currentTime` set happens in `app.js:174-176`.
- Error paths are JSON: `/nope` 404, `/api/search` with no `q` 400.
- Not tested, by choice: the 429 rate limit (it would use the 120/60 s budget and the demo never nears it).

## Recording blockers

None. Things to watch, in order of likelihood:

1. Latency narration (edit 2): the live page will feel like 70-130 ms, not 56 ms. Do not say "56 ms" on camera unless the server is pinned to one core.
2. The tailnet name is still blank in the checklist (`______`), as before.
3. Audio streams from archive.org; the machine must be online.
4. Do not run more than 4 simultaneous connections to the demo URL.

## Cache before/after (rule 5)

Snapshot: `find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`, 132,666 lines before, 132,667 after. `/cache/index/*`, `/cache/models/*`, `/cache/huggingface`, `/cache/uv` and everything else are **identical**. The only difference is under `/cache/xdg/deno/` (a Deno cache, no data):

```
/cache/xdg/deno/dep_analysis_cache_v2-shm        mtime 19:23:04 -> 19:42:46
/cache/xdg/deno/dep_analysis_cache_v2-wal        1619192 -> 1627432 bytes
/cache/xdg/deno/node_analysis_cache_v2           mtime changed, same size
/cache/xdg/deno/node_analysis_cache_v2-shm       mtime 19:23:04 -> 19:42:46
/cache/xdg/deno/gen/file/work/preached           20 -> 54 bytes
/cache/xdg/deno/gen/file/work/preached/$deno$eval.mts.js   new, 657 bytes
```

Attribution: I cannot prove this was not mine. The ambient shell environment has `XDG_CACHE_HOME=/cache/xdg`, `UV_CACHE_DIR=/cache/uv` and `HF_HOME=/cache/huggingface`. Every command that ran uv, Python or anything that could reach deno set those, plus `DENO_DIR`, to the temp copy first (the temp `deno/` dir did get written at 19:42:31, so `DENO_DIR` was honored there). Test collection runs no deno, and no repo code runs `deno eval`: the tests use `deno run --no-config <tempfile>` only inside test methods (`tests/test_app_js.py:445` and `:647`, `tests/test_mobile_ux.py:331`, `tests/test_privacy_wire_fix.py:272`, `tests/test_privacy_merge.py:231`, all at `9fe33ca`), and I ran no test methods. So nothing I ran is known to have used deno. What wrote the temp `deno/` dir at 19:42:31 is unknown. The `$deno$eval.mts.js` under `/cache/xdg/deno/gen/file/work/preached` came from a `deno eval` run with `/work/preached` as the working directory; that is not repo code. At the 19:42:46 write only my latency script was running, so it was probably another process using the shared `/cache/xdg`. No index, model, transcript, audio or label file was touched. Flagging it per rule 5; nothing needs to be repaired, since a Deno cache regenerates.

## PR BODY

Demo dry run 2 against main `9fe33ca`: every DEMO-SCRIPT step passes; stale items (a40706b pin, 998 test count, latency 56 ms not reproduced (unpinned p50 72 ms; gap not attributed), three drifted line cites) are listed with proposed wording in `reports/W4-DEMO-DRYRUN-2.md`. Report only; the four owner docs are untouched.

Diff stat (`git diff --stat origin/main...HEAD`):

```
 reports/W4-DEMO-DRYRUN-2.md | 112 ++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 112 insertions(+)
```
