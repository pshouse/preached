# W4-SUBMIT-POST63: demo script and submission draft checked against main after #63

Docs and reports only. Base `origin/main` = `a40706b` (PR #63 merge); branch `docs/w4-submit-post63`. Files changed: `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md`, `reports/W4-SUBMIT-FINAL-PASS.md` (appended), this report.

## What #63 changed

`git diff 048e72f a40706b -- app/`: (1) the submit handler blurs the search box only on a coarse pointer (touch), so on desktop the caret stays; (2) a `?q=` deep link is capped at 300 code points (`capQuery`) instead of 300 UTF-16 units; (3) `MAX_QUERY = 300` named in `app/server.py` (same limit, same message text). No ranking, page copy, button label, layout, CSS or HTML change. `app/static/index.html` and `app.css` are untouched since `ad78a75`.

## Method

`HF_HOME=/cache/huggingface PREACHED_CACHE=/cache uv run app/server.py --port 8123` (127.0.0.1 only), stopped after. `/healthz`: `ok`, 8383 chunks, `granite-english-r2`, `onnx`, `fallback: false`, `church: null`, `index_version` 198339...e363b2. Queries through `/api/search?mode=hybrid&k=5&library=wesley` and `/api/side`; page copy read from `app/static/index.html` and `app.js`. No browser was driven, so touch behaviour is read from code and #63's Deno tests, not seen.

## Step by step

| Step | Result | Evidence |
| --- | --- | --- |
| 1 Problem | pass (no app content) | n/a |
| 2 Money | pass | `strong`, dense top 0.909, 15 BM25 hits; cards `wesley-050-c0007` 317.48, `wesley-050-c0004` 211.47, `wesley-028-c0076` 2309.57. View and How-to-search labels ("John Wesley", "Words and meaning") match `index.html` |
| 2 Assurance | pass | `strong`; `wesley-011-c0025` 780.35, `wesley-010-c0010` 307.49, `wesley-010-c0043` 1350.88. "Assurance" button text and query match `index.html` |
| 3 No good answer | pass | level `none`, `abstain` true, 0 BM25 hits, dense top 0.796; banner text equals the script's quote and `MESSAGES.low`; cards `wesley-050-c0005` 247.85, `wesley-087-c0069` 2189.2. "Worry" button (`What did Wesley say about worry?`) is still `weak`, so the avoid-note stands |
| 4 Side by side | pass | `/api/side`: classic column same top ids; church column `present: false`, "Nothing from your church yet."; `church: null` in healthz |
| 5 Privacy | pass (not re-run) | README and `reports/W3-PRIV-SKIP.md`, untouched by #63 |
| 6 YouTube dry run | pass | printed `BGoD6CIpLWQ	Are speeches public domain?	2012-08-06	322`, nothing written |
| 7 CPU box | pass | `/healthz` matches the expected line; latency and memory cites are reports, untouched |
| 8 Why it matters | pass (no app content) | n/a |
| Pre-flight | pass, sha refreshed | rate limits, bind, 800 px side-by-side breakpoint unchanged in code; browser step "window about 1280 px wide" unaffected |
| Fallback table | not re-run | ranking code untouched by #63; values were verified on `ad78a75` and `git diff ad78a75 a40706b -- src search` is empty (`app/` only) |

No step is "changed". The script never mentions keyboard behaviour or deep links, so the desktop-keeps-focus change and the code-point cap need no wording. Nothing was reworded.

## Refreshed

- `a40706b` replaces `ad78a75` at DEMO-SCRIPT:10, :77 and SUBMISSION-DRAFT:3, :42. The page code changed, so the old sha would claim a state that is not main.
- Test count: `PREACHED_CACHE=/cache PREACHED_REQUIRE_DENO=1 uv run python -m unittest discover -s tests` on `a40706b`: **`Ran 998 tests in 252.027s`, `OK`, 0 skipped** (was 995; #63 and the batch tests added 3). deno present. `/cache/index/wesley.sqlite` sha256 identical before and after. SUBMISSION-DRAFT:42 updated: 998, 252.027 s, `PREACHED_REQUIRE_DENO=1` noted, and two skip-site lines that moved: `tests/test_mobile_ux.py:239` -> `:318`, `tests/test_eval_leak.py:191` -> `:231`. The other skip lines are unchanged. The headline "over 970" is still true.

## #61 nits

- N1: appended to `reports/W4-SUBMIT-FINAL-PASS.md` (addendum). Current cite is `reports/W3-CONFIRMATORY.md` (SUBMISSION-DRAFT:33); it contains 51 vs 50 of 58, +0.017, CI [−0.034, +0.086].
- N2: already present, `reports/W4-SUBMIT-FINAL-PASS.md:61` ("`ad78a75` ... Suite re-run on `ad78a75`"). Nothing changed.

## Untouched on purpose

CTO claim sentence verbatim; no accuracy/improves/better claim; Tailscale placeholder (DEMO-SCRIPT:79) kept; track, tagline and tone untouched.

## Unverified

Real-browser behaviour (touch blur, phone layout, audio playback); same gaps as `reports/W3-MOBILE-UX-QA.md` and `W3-SIDE.md`.
