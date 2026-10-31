# W4-DEMO-PREP: demo script and submission draft

Branch `docs/w4-demo-prep` from `origin/main` (`180a0a4`). Docs only: `docs/DEMO-SCRIPT.md`, `docs/SUBMISSION-DRAFT.md`, this report. No code, no new dependency. Nothing deployed or submitted.

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
- `uv run python -m unittest discover -s tests`: 693 tests, OK.

## Word count

Project description: **247 words** (limit 250), counted with a whitespace split of the text between the heading and "Honest technical claims" in `docs/SUBMISSION-DRAFT.md`; the count is printed in that heading.

## Dropped or softened

- **Church side-by-side with a filled column:** not on main (church serving is not wired). The shot shows the empty "Nothing from your church yet." state and says so. No "sample data" column exists to show.
- **Any "percent of questions answered correctly" claim:** the eval labels are AI-drafted and human review is pending (`eval/README.md`); numbers are quoted only with that caveat.
- **Latency on a Sprite / "small box" figure:** only measured on one pinned core of an i9-12900K; stated as such. RSS differs between harnesses (946 MiB vs 1.5 GiB), both given.
- **Spurgeon and Edwards retrieval quality:** none measured (12/12 smoke only), so they are not featured.
- **Competitor comparisons with numbers:** only BRIEF.md's positioning text exists; no number used.
- **Romans 8:16 fallback:** not run, labelled as such in the script.
- **Money button query ("What did Wesley say about money?"):** top result recorded but confidence level not checked.

## Open items for Patrick

- Fill in the Tailscale URL in the pre-flight checklist; no tailnet was running on this machine and the name is not in the repo.
- Skim every "Expected" line against the page on recording day.
- Eval human review in `eval/review/review-2026-10-30.csv` is still pending; the submission text says so.
- No `gh` in this sandbox: see the push note below.
