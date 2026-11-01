# W4-SUBMIT-DRYRUN2-EDITS: dry run 2 findings applied to DEMO-SCRIPT and SUBMISSION-DRAFT

Docs only. Branch `docs/w4-submit-dryrun2` from `origin/main` `9fe33ca`. Neither doc is cited in `docs/DEPLOY.md` or `tests/test_deploy_alerts.py` (`grep -n "SUBMISSION-DRAFT\|DEMO-SCRIPT"` on both: no hits), so no DEPLOY re-pin.

| # | File:line (this branch) | Old | New | Evidence |
| --- | --- | --- | --- | --- |
| 1 | DEMO-SCRIPT.md:10 | "`main` (`a40706b`; every query below was re-run live on it)" | "`main` (re-run on main at `9fe33ca`; same top results, levels and timestamps)" | `reports/W4-DEMO-DRYRUN-2.md` step table: every Expected line reproduced on `9fe33ca` |
| 2 | DEMO-SCRIPT.md:64 | "about 56 milliseconds on my desktop, on one core" | "well under a tenth of a second on a desktop CPU" | dry run 2: unpinned p50 72 ms / p95 86 ms, wall 76-126 ms |
| 3 | DEMO-SCRIPT.md:65 | 56/68 ms "on one pinned CPU" | 56/68 ms kept, labelled the one-core pinned measurement (`reports/W3-CPU.md:79`), plus the unpinned 72/86 ms and a warning not to say 56 ms unpinned | `reports/W3-CPU.md:79`; dry run 2 step 7 |
| 4 | DEMO-SCRIPT.md:77 | "`main` at or after `a40706b`" | "`main` (tree-relative: any main that passes this checklist; last re-run at `9fe33ca`)" | `git rev-parse origin/main` = `9fe33ca` |
| 5 | DEMO-SCRIPT.md:82 | (absent) | pre-flight line: more than 4 connections from one IP get 503 (self-refreshing HTML page, `Retry-After: 1`) | dry run 2 "HTML 503 page" check (PR #77 behaviour) |
| 6 | DEMO-SCRIPT.md:79 | "No tailnet was running..." | not present on main; the line already reads "A tailnet-only demo exists; the public URL is Patrick's decision." Tailnet placeholder `______` left as is | `grep -n "No tailnet" docs/DEMO-SCRIPT.md`: no hit |
| 7 | SUBMISSION-DRAFT.md:3 | "`a40706b` ... over 970 tests; the exact count is in the table ... re-run on `a40706b`" | "checked at `9fe33ca` ... more than 1,000 tests ... re-run on `9fe33ca`" | suite run below |
| 8 | SUBMISSION-DRAFT.md:21 | "about 56 ms per search on one desktop CPU core" | "well under a tenth of a second per search on a desktop CPU" | as edit 2 |
| 9 | SUBMISSION-DRAFT.md:35 | 56/68 ms "on one pinned core"; peak "950 to 970 MiB" | pinned label kept with `W3-CPU.md:79`; unpinned 72/86 ms added; full-server peak "about 950 to 970 MiB ... re-observed at 952 MiB in PR #81"; embedder-alone 683/903 MiB still tagged separately | dry run 2: VmHWM 974,920 kB = 952 MiB; `reports/W3-RSS.md:23`, `:114`; `reports/W4-DEMO-PREP.md:55`, `:73` |
| 10 | SUBMISSION-DRAFT.md:41 (twice) | cite `README.md:37` | tree-relative: the README paragraph beginning "`--your-church` sets `meta.role`" ("a sermon appears only when it is approved") | `sed -n 37p README.md` is a code fence on main; the paragraph is the one at README.md:39 |
| 11 | SUBMISSION-DRAFT.md:42 | "998 pass, 0 skipped ... `PREACHED_CACHE=/cache uv run ...`" | "more than 1,000 tests; 1081 ran, OK, 10 skipped on `9fe33ca` with scratch caches"; skip sources listed; "only the maintainer's host verify gate runs against the real cache"; no `/cache` command | suite result below |
| 12 | SUBMISSION-DRAFT.md:42 cites | `test_app_js.py:439`, `:618`; `test_eval_leak.py:231`; embed_backend condition lines `:657 :707 :714 :739 :1076 :1143 :718` | `test_app_js.py:432-437` (`need_deno`), used at `:454`, `:635`; `test_eval_leak.py:233`; embed_backend `skipTest` lines `:658 :708 :715 :740 :1078 :1145 :719`; added `test_onnx_pin_repro.py:651`, `:774`, `test_deploy_regex.py:539` | `grep -n "skipTest\|skipUnless\|need_deno"` over those files on this branch |

Left alone: track, tone and tagline placeholders; no accuracy/"improves"/"better" wording; no 0.285/0.614/0.629; the pre-registered "statistically indistinguishable" sentence unchanged.

## Suite result

```
env: PREACHED_CACHE, PREACHED_ONNX_DIR, HF_HOME, DENO_DIR, XDG_CACHE_HOME, UV_CACHE_DIR = fresh mktemp dirs under /tmp; HF_HUB_OFFLINE=1
uv run python -m unittest discover -s tests          (HEAD 9fe33ca, run twice, second with -v)
Ran 1081 tests in 256.461s
OK (skipped=10)
```

The 10 skips (from the `-v` run): 6 in `test_embed_backend.py` (ONNX artifacts absent), 1 `test_eval_leak.py` (chunks/index absent), 2 `test_onnx_pin_repro.py` (Granite weights / ONNX artifacts absent), 1 `test_deploy_regex.py` (infra alerts yaml absent, not in this repo). Deno is installed, so deno tests ran. `test_shutdown.py:173` and `test_coverage.py:291` did not skip: they hard-code `/cache` paths (`REAL_INDEX`, `/cache/asr-repro`) and so read the real cache regardless of the env vars (read only; see below).

## Cache before/after (rule 5)

`find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`: 132,672 lines before, 132,672 after. One difference:

```
< /cache/index/cc-speech.sqlite-shm	32768	1793489381.69
> /cache/index/cc-speech.sqlite-shm	32768	1793490756.66   (19:52:36 EDT)
```

Same size; a WAL shared-memory file whose mtime moved. It fell during my second (`-v`) suite run, but no test I can find opens `/cache/index/cc-speech.sqlite` (the `cc-speech` tests use temp dirs), so I cannot attribute it to this run; another process on the host may have opened it. No index, model or data file changed. Nothing to repair.

Temp dirs removed only after asserting the resolved path is under `tempfile.gettempdir()`.

## Diff stat (`git diff --stat origin/main..HEAD`, before this line was added)

```
 docs/DEMO-SCRIPT.md                |  9 ++++----
 docs/SUBMISSION-DRAFT.md           | 10 ++++-----
 reports/W4-SUBMIT-DRYRUN2-EDITS.md | 44 ++++++++++++++++++++++++++++++++++++++
 3 files changed, 54 insertions(+), 9 deletions(-)
```

## CTO wording check (99-WH)

No doc edit needed; the 99-WG head (`8976d5d`) already satisfies all three rulings.

1. Latency: `grep -nE "56 ?ms"` hits only `docs/DEMO-SCRIPT.md:65` ("56 ms p50 / 68 ms p95 is the one-core pinned measurement ... do not say 56 ms on camera unless the server is pinned to one core") and `docs/SUBMISSION-DRAFT.md:35` ("is the one-core pinned measurement"), both qualified, each next to the unpinned p50 72 ms / p95 86 ms. No narration line uses 56 ms alone.
2. Test count: the only count is `docs/SUBMISSION-DRAFT.md:42` ("more than 1,000 tests; 1081 ran ... on `9fe33ca`"), headline plus exact count with its sha. `docs/SUBMISSION-DRAFT.md:3` says "more than 1,000 tests". `docs/DEMO-SCRIPT.md` has no test count.
3. Cache: `grep -n "PREACHED_CACHE=" docs/DEMO-SCRIPT.md docs/SUBMISSION-DRAFT.md` returns nothing. The suite row uses scratch caches and says only the maintainer's host verify gate runs against the real cache. The `/cache/...` mentions are index/clip paths, not suite commands.

Finish run: `uv run python -m unittest tests.test_deploy_alerts tests.test_deploy_regex` with PREACHED_CACHE, PREACHED_ONNX_DIR, HF_HOME, DENO_DIR, XDG_CACHE_HOME, UV_CACHE_DIR in fresh temp dirs: `Ran 17 tests`, `OK (skipped=1)`. Real `/cache` listing (paths, sizes, mtimes), 132,677 lines before and after: no difference.

## CTO amended latency ruling (99-WK-R2)

Exact phrase everywhere: "under a tenth of a second on a desktop CPU", optionally followed by "(p50 72 / p95 86 ms in a demo-style run, unpinned, k=5)" (the optional parenthetical is left out of both docs because the finish grep for `pinn` would match "unpinned"). Not "well under"; no 56/68 ms figure, no pinning attribution. Changed lines at this head:

- `docs/DEMO-SCRIPT.md:64` (narration): "well under a tenth of a second" -> "under a tenth of a second on a desktop CPU".
- `docs/DEMO-SCRIPT.md:65` (backing): removed the 56 ms / 68 ms one-core pinned figure and the "do not say 56 ms on camera unless pinned" warning; now gives the exact phrase only. Also "on my desktop CPU, limited to one core" -> "on my desktop CPU".
- `docs/SUBMISSION-DRAFT.md:21`: "well under a tenth of a second per search on a desktop CPU" -> "under a tenth of a second on a desktop CPU".
- `docs/SUBMISSION-DRAFT.md:35`: removed the 56/68 ms one-core pinned measurement and the "unpinned, warm, 1 ORT thread" wording; replaced with the exact phrase.

Earlier table rows 2, 3, 8 and 9 and the "CTO wording check (99-WH)" item 1 describe the superseded wording; this section replaces them.

Finish greps: `grep -nE '56 ?ms|68 ?ms|pinn' docs/DEMO-SCRIPT.md docs/SUBMISSION-DRAFT.md` and `grep -n 'well under' ...` print nothing. Test count stays "more than 1,000 tests". No `PREACHED_CACHE=` in either doc; no cache env was touched (docs-only, no tests run).

Cites kept (read at this head): `reports/W3-CPU.md:79` / `:148` are now cited only for the 960 MiB pre-#26 RSS figure; the other report and test cites are unchanged from the prior head, whose lines this commit does not move.

## CTO latency ruling R3 (99-WL)

Base head before this change: `5e0a8da9e9edd46b8c0fcca1f5813149e46849c5` (the 99-WK head).

Supersedes the 99-WK-R2 section above: the dry-run-2 72/86 ms figures cannot be reproduced (the 8 demo queries were lost), so they appear in neither doc.

`reports/W3-CPU.md` lines relied on (quoted; tree-relative):

- Method line (under "Latency, RSS, install size, cold start"): "`/api/search` hybrid, k=10, 40 queries × 3 repeats, one warmup excluded."
- Table row: "ONNX fp32, 4 threads, full chip | 28.2 ms | 34.5 ms" (p50, p95).

The word "pinned" comes only from the neighbouring 1-thread row, which the docs do not cite and nothing is attributed to it. W3-CPU.md does not say whether the queries ran back-to-back. The bench is that report's 40-query set, not the demo queries.

Option chosen: keep "under a tenth of a second on a desktop CPU" (p95 34.5 ms < 100 ms on the full-chip row) and cite W3-CPU.md with its method. No new benchmark was run.

Changed lines:

- `docs/DEMO-SCRIPT.md:65`: after the latency phrase, added the W3-CPU.md row, p50 28.2 / p95 34.5 ms, the method quote, a note that the report does not say back-to-back, and "do not read the numbers out on camera".
- `docs/SUBMISSION-DRAFT.md:35`: dropped "1 thread" (the cited row is 4 threads); added the same row, numbers and method after the phrase.
- Narration at `DEMO-SCRIPT.md:64` and `SUBMISSION-DRAFT.md:21` unchanged.

Finish grep (`72|86 ?ms|56 ?ms|68 ?ms|pinn|well under`) has one hit: `docs/DEMO-SCRIPT.md:100`, the chunk id `wesley-026-c0072`, unrelated.

## README quote check (CTO #74 SF)

The church/publish-gate paragraph ("`--your-church` sets `meta.role` ... a sermon appears only when it is approved (`--ack-review`)") is byte-identical on `origin/main` (README.md:39) and on `origin/docs/w4-readme-quickstart` (README.md:73, PR #74). The two quoted fragments in SUBMISSION-DRAFT.md:41 occur verbatim in both. The quote is tree-relative; no change needed. (Other README paragraphs, e.g. the `--library` one, differ between the two; they are not quoted.)

## PR BODY

Docs-only. Applies CTO latency ruling R3 (see section above); README quote verified on main and PR #74.

```
STAT
```
