# W4-DEMO-PREP: demo script and submission draft

Branch `docs/w4-demo-prep` from `origin/main` (`180a0a4` at first; since merged up to `cd3ad8f`, see the fix tables at the bottom). Docs only: `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md`, this report. No code, no new dependency. Nothing deployed or submitted.

## How to run (re-verify the script)

```bash
uv run app/server.py --port 8765            # then curl /healthz and /api/search?q=...&k=5&mode=hybrid&library=wesley
uv run search/query.py "<query>" --mode hybrid -k 3 [--library spurgeon|edwards]
uv run --extra youtube import/youtube.py "https://www.youtube.com/watch?v=BGoD6CIpLWQ" --library democheck --privacy privacy.example.toml --dry-run
uv run python -m unittest discover -s tests
```

## Verified by running

- `/healthz` on a local server (Wesley index, ONNX fp32): `ok`, 8,383 chunks, `backend onnx`, `fallback false`, `church null`, `index_version` 198339...e363b2.
- Through `/api/search` (the page's path): "how should a Christian use money" (strong), "How can I know that I am a child of God?" (strong), "what does Wesley say about cryptocurrency" (level `none`, low-confidence note, BM25 0 hits), "What did Wesley say about worry?" (level `weak`; so the page's Worry button is kept off camera). Sermon, timestamp and snippet for each are in the script.
- Through `search/query.py` (CLI; differs from the page because the page de-duplicates adjacent chunks): the fallback queries and the Spurgeon and Edwards queries.
- `/api/side`: classic column is John Wesley; church column is "Nothing from your church yet." with `present: false`.
- YouTube importer `--dry-run` on the Creative Commons test clip printed `BGoD6CIpLWQ  Are speeches public domain?  2012-08-06  322` and wrote no index file.
- `uv run python -m unittest discover -s tests`: 738 tests, OK on `cd3ad8f` (6 skip on machines without the `/cache` ONNX artifacts; 693 when first run on `180a0a4`).

## Word count

Project description: **245 words** (limit 250; first draft was 247), counted with a whitespace split of the text between the heading and "Honest technical claims" in `docs/SUBMISSION-DRAFT.md`; the count is printed in that heading.

## Dropped or softened

- **Church side-by-side with a filled column:** the side-by-side church column is not wired on main (a church library alone is served behind the publish gate, `README.md:37`). The shot shows the empty "Nothing from your church yet." state and says so. No "sample data" column exists to show.
- **Any "percent of questions answered correctly" claim:** the eval labels are AI-drafted and human review is pending (`eval/README.md`); numbers are quoted only with that caveat.
- **Latency on a Sprite / "small box" figure:** only measured on one pinned core of an i9-12900K; stated as such. RSS is 683 MiB after the #26 fix (`W3-RSS.md`), peak (VmHWM) about 969 MiB during model load.
- **Spurgeon and Edwards retrieval quality:** none measured (12/12 smoke only), so they are not featured.
- **Competitor comparisons with numbers:** only BRIEF.md's positioning text exists; no number used.
- **Romans 8:16 fallback:** level `strong`, top hit Witness of the Spirit II, marked "(page path)" in the script.
- **Money button query ("What did Wesley say about money?"):** level `strong`, marked "(page path)" in the script.

## Open items for Patrick

- Fill in the Tailscale URL in the pre-flight checklist; no tailnet was running on this machine and the name is not in the repo.
- Skim every "Expected" line against the page on recording day.
- Eval human review in `eval/review/review-2026-10-30.csv` is still pending; the submission text says so.
- No `gh` in this sandbox: see the push note below.

## Push

`gh` is not installed in this sandbox, so the branch is pushed and no PR was opened. Open it against `main` titled "W4: demo script + submission draft (for Patrick's review)".

## CTO r1 fixes

Merged `origin/main` (`efdf8ab`) into the branch (merge commit). Docs only.

| Item | Change |
| --- | --- |
| Must-fix 1 | Kept the retrieval row; added a caveat in the draft's claims table and the demo script's "Things not to say": headline mostly measures title lookup; plain-language nDCG@10 0.028, R@5 0.040 (`EVAL-DELEAK.md:7`); blind questions 3 of 28, 0.11 (`EVAL-GRADE.md:20`); demo works best in the preacher's own vocabulary or by topic. Caveat text is 62 words. Row also notes 0.614 comes from the bench script with dedupe, not the web page. |
| Must-fix 2 | RSS now 683 MiB (`W3-RSS.md`), measured 722.7 MiB at start / about 728 MiB after queries on `efdf8ab` (figures as given in the review; not independently re-measured). Tests 693 -> 729 (re-run: OK). References 180a0a4 -> efdf8ab. |
| Must-fix 3 | Anchoring citation -> `W1-C.md:190`; 8,383 chunks -> `W1-C.md:192` and `W1-B.md`. The 0.42 s / 0.76 s figures are dropped (no measurement data in the repo). |
| Must-fix 4 | Shot 5 narration: "a small synthetic test set written by an AI". |
| Must-fix 5 | Description sentence replaced with the suggested wording. |
| Should-fix | "church serving not wired" narrowed to the side-by-side column (`README.md:37`); shot 6 runs from repo root; pre-flight index_version marked "update if the index is rebuilt"; fallback rows filled (Romans 8:16 strong, top hit Witness of the Spirit II; Money button strong); "must listen" reworded as process (`--ack-review` is all the software enforces); 0.614 source noted. |

Final description word count: **245** (limit 250), same whitespace-split method. Head SHA: see the commit pushed after this report (stated in the hand-off).

## CTO r2 fixes

Merged `origin/main` (`cd3ad8f`) into the branch (merge commit). Docs only. Suite re-run on the merged branch: 738 tests, OK. The 6 skips are environmental (granite ONNX artifacts are not in `/cache`), so they are worded that way, not as a product fact.

| Item | Change |
| --- | --- |
| Must-fix 1 | The body of this report now reads cleanly: base SHA, test count (738), word count (245), church column, RSS, Romans 8:16 and Money lines were updated in place. The r1 table is kept. |
| Must-fix 2 | `SUBMISSION-DRAFT.md` line 3 and the claims row now say `cd3ad8f` and "738 tests pass ... 6 skip on machines without the `/cache` ONNX artifacts"; `DEMO-SCRIPT.md` lines 10 and 77 say `cd3ad8f`. |
| S1 | Shot 2 narration now says the recordings are "public domain in the US", matching the README. |
| S2 | Fallback table header: "unless marked (page path)"; Romans 8:16 and Money rows marked "(page path)". |
| S3 | CPU claim row and shot 7 backing give peak VmHWM about 969 MiB during model load (figure as given in the review; `W3-RSS.md` records 903 to 908 MiB on its own harness). |
| S4 | Note only: if #37 merges before recording or submission, re-check every "side-by-side church column is not wired" line in `DEMO-SCRIPT.md` and `SUBMISSION-DRAFT.md`. |
| S5 | Shot 7 narration: "on my desktop, on one core". |

Description word count: **245** (limit 250), unchanged, same whitespace-split method. S6 (README) not touched.
