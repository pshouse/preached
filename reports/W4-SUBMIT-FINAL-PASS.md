# W4-SUBMIT-FINAL-PASS: DEMO-SCRIPT and SUBMISSION-DRAFT refreshed against main

Docs only. Base `origin/main` = `33573c7`; branch `docs/w4-submit-final`. Files changed: `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md`, this report.

## Verification on `33573c7`

- Server: `HF_HOME=/cache/huggingface PREACHED_CACHE=/cache uv run app/server.py --port 8123` (loopback), stopped by exact PID (python 154, uv wrapper 123). `/cache/index/wesley.sqlite` sha256 identical before and after server and test run. No index rebuilt or written; nothing under `/cache/index` named `demo` exists.
- `/healthz`: `ok`, 8383 chunks, `granite-english-r2`, `onnx`, `fallback: false`, `church: null`, `index_version` 198339...e363b2.
- All dry-run values re-queried through `/api/search?mode=hybrid&k=5&library=wesley` and `/api/side`. Every dry-run finding reproduced exactly (see changes). Primary queries unchanged: Use of Money `wesley-050-c0007` 0:05:17 (317.48), strong; Witness II `wesley-011-c0025` 0:13:00 (780.35), strong; cryptocurrency `none`, abstain, 0 BM25 hits; Worry button `weak`, `wesley-108-c0038` 1110.29; `/api/side` church column "Nothing from your church yet.".
- YouTube dry run printed `BGoD6CIpLWQ	Are speeches public domain?	2012-08-06	322`, nothing written.
- Tests: `PREACHED_CACHE=/cache uv run python -m unittest discover -s tests` on `33573c7`: **`Ran 995 tests in 225.048s`, `OK`**, no skip line (0 skipped). deno is on PATH; ONNX artifacts, index and asr-repro clips present on this box.
- Search code: `git diff bbdb1ba origin/main -- src search` is empty. Since then only `app/server.py` (logging and status-note handling), `app/static/*` (#53 page UI) and eval label files changed. So "search code unchanged since `bbdb1ba`; #53 changed only the page UI" is true for search and UI, but `app/server.py` also changed in logging/fallback-note code (not ranking); the script's wording says search code.

## Changes (old -> new, evidence)

| # | File:line | Old | New | Evidence |
| --- | --- | --- | --- | --- |
| 1 | DEMO-SCRIPT:10 | "`main` (`bbdb1ba`; results re-checked live on it)" | "`main` (`33573c7`; every query below was re-run live on it. Search code is unchanged since `bbdb1ba`; #53 changed only the page UI)" | `git diff bbdb1ba origin/main -- src search` empty; live re-run. Dry run item 1 |
| 2 | DEMO-SCRIPT:77 | "`main` at or after `bbdb1ba`" | "`main` at or after `33573c7`" | as above |
| 3 | DEMO-SCRIPT:79 | tailnet placeholder "fill in: ______" with the neutral tailnet/public sentence already present | placeholder kept and marked "Patrick's placeholder"; no URL written. S1: the stale "No tailnet was running..." wording was already gone on main; the neutral sentence "A tailnet-only demo exists; the public URL is Patrick's decision." is retained | file read at `33573c7` |
| 4 | DEMO-SCRIPT:95 | Danger of Riches 0:10:37 (637.22) | `wesley-087-c0021`, 0:10:22 (622.25), page path, strong | live query |
| 5 | DEMO-SCRIPT:98 | `wesley-029-c0002` 0:01:52 (112.32) | page path 0:01:09 (69.24); `query.py` shows 0:01:52 (112.32); verify text; score 0.0325, strong | live: 69.24, 0.03252 |
| 6 | DEMO-SCRIPT:99 | no level | page path, level `weak` (0 BM25 hits), low-confidence note may show | live: weak, bm25_hits 0 |
| 7 | DEMO-SCRIPT:100 | second hit 0:16:23 (983.96) | `wesley-098-c0031`, 0:15:50 (950.74), page path, level `weak` | live |
| 8 | DEMO-SCRIPT:65 | one run-on backing line mixing setups | memory split by setup: embedder alone 683 / 903 MiB (`W3-RSS.md:23`, `:114`); full server 722.7 / ~728 / ~969 MiB (`W4-DEMO-PREP.md:55`, `:73`, CTO figures, not agent-measured); `W3-CPU.md:79` 960 MiB named as a third setup (bench `/api/search` server with the index open, `W3-CPU.md:148`); "about 1 GiB" for the whole server | S3 and the 683 vs 960 resolution. W3-CPU.md:143-148 header and row read |
| 9 | DEMO-SCRIPT:106 | cited Recall@5 0.614, MRR, nDCG, 0.028, 3 of 28 | only CTO's pre-registered sentence, verbatim; "do not quote any other eval number"; also bans "improves"/"better" | hard rule |
| 10 | SUBMISSION-DRAFT:3 | `47da348`; queries last checked at `bbdb1ba` | `33573c7`; queries re-run on `33573c7` | live re-run |
| 11 | SUBMISSION-DRAFT:19 (description) | "...our evaluation questions were drafted by an AI and still await human review." | sentence removed (now "That check is a heuristic."). The old clause is stale (a subset has been human-confirmed) and the CTO sentence is not added to the 250-word-limited description | word count 245 -> **231** (limit 250), whitespace split of lines 11-21, same method as before |
| 12 | SUBMISSION-DRAFT:25 | AI-drafted, 35 questions, human review pending | only the pre-registered sentence is a retrieval-quality statement; labels AI-assisted, subset blind-confirmed | hard rule |
| 13 | SUBMISSION-DRAFT:33 | Recall@5 0.614 etc. with caveats | CTO sentence verbatim, "no accuracy, improves or better claim", backing `reports/W3-FUSION-PREREG.md` | hard rule. The sentence's numbers are CTO-supplied; I did not re-derive them |
| 14 | SUBMISSION-DRAFT:34 | "fitted to the same AI-drafted questions" | "fitted to the project's own evaluation questions" | consistency with 12 |
| 15 | SUBMISSION-DRAFT:35 | memory by setup (no 960) | adds "plan on roughly 1 GiB", agent-not-measured note, 960 MiB third setup | S3, same as 8. No figure from the dry run's single sample is cited |
| 16 | SUBMISSION-DRAFT:36 | "same metrics, cosine ..." | "cosine ..." (metrics clause removed) | quality-parity wording dropped under the hard rule |
| 17 | SUBMISSION-DRAFT:41 | "published passages (approved, status ok, coverage clear)" | adds `README.md:37` | S4: README.md:37 says "approved (`--ack-review`), import status `ok`, coverage check found nothing open". The draft already said "published passages" here; the task's "approved passages" wording was gone |
| 18 | SUBMISSION-DRAFT:42 | 987 tests on `47da348`; skip sites incl. `test_eval_leak.py:169` | 995 on `33573c7`, 0 skipped; every skip source listed with re-checked lines (`test_eval_leak.py:191`, others unchanged); says the count without them was not measured and not to quote "995 pass" for a machine lacking them | S2; `grep skipTest\|skipUnless tests/*.py` |
| 19 | SUBMISSION-DRAFT:49 | "Any 'accuracy' figure beyond the ones above" | no accuracy/improves/better claim; no retrieval figure beyond the pre-registered sentence | hard rule |

## Memory figures

The dry run's single sample (729.3 MiB start, 782.6 MiB after about 45 queries, 952 MiB peak) is **not cited**. For context only, my own single check of this run after 10 queries: VmRSS 801,392 kB, VmHWM 981,460 kB. Neither is a measurement. The doc says "roughly 1 GiB" with the CTO figures labelled as such.

## Patrick's remaining decisions (left visible)

- Track (SUBMISSION-DRAFT:6), tagline (:7), tone of narration.
- Tailnet name / public URL: `fill in: ______` in DEMO-SCRIPT:79. No URL written.
- Whether to add the pre-registered sentence to the description itself (omitted for the word limit).

## Unverified

- Phone playback (autoplay, iOS media fragments); only HTTP Range (302 then 206) checked in the dry run.
- Stacked phone layout below 800 px in a real browser (`reports/W3-SIDE.md`: not run).
- Pre-registered sentence figures (58 questions, 51 vs 50, +0.017, CI) are CTO-supplied; I did not recompute them (`grep` of the repo finds no file with the phrase "statistically indistinguishable").
- Test count without the skip sources.
- 143 recordings / 71.14 h (not rechecked; cited from `reports/W1-A.md`).
- The `W3-CPU.md` 960 MiB may predate the #26 fix; the docs say only which setup it is.
