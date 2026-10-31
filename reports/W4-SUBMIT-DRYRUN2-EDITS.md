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
