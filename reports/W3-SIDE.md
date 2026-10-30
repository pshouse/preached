# W3-SIDE: classic library beside your church

Branch `feat/w3-side`, from `origin/main` at `e2ddbc7`. No new dependencies. No new models. Gaston Community Church was not imported, stored, or shown. The church column in tests is fixture text, and a library whose slug is `sample` (or whose meta `sample` is `1`) is labelled sample data.

## What was done

One question, two libraries. Each library is still its own SQLite file under `/cache/index/<slug>.sqlite`. A search reads one connection, so a hit from the other file cannot appear in that list. That is the same layout Wesley and a YouTube import already use. A combined table would have been a new way for rows to leak.

The church mark is one row in the `meta` table that file already has: `role` = `church`. `import/youtube.py --your-church` sets it after a real import (not `--dry-run`) and clears the mark on any other file in the index directory, so only one library stays marked. The slug `sample` also writes `sample` = `1`. Siblings are opened for writing only when they are already marked, so a Wesley file in the same directory is not migrated just to be inspected.

The server still has one classic library (`--library`, default `wesley`). It also opens a church file when `--church-index` or `--church-library` names one, or when exactly one other index in `/cache/index` is marked `church`. Zero matches, several matches, or a missing file does not stop the server and does not pick a file at random. That side is empty.

`GET /api/search?library=<slug>` searches only an open library. Any other slug is a 400 (`library must be wesley` when that is the only open file, so the old error text still holds). Omitting `library` still searches the classic file.

`GET /api/side` runs that same search once per side and returns the top `k` hits from each (default 10, max 25). Each hit has the same fields as `/api/search` (`chunk_id`, sermon, scripture, excerpt, `start_s`, `end_s`, `audio_url`, `reader`, `text_source`, `source_url`, `score`). Each side has its own `mode`, `note`, `abstain`, and `confidence`, using `search_with_confidence`. A church file with no usable vectors falls back to BM25 on that side only. The classic side keeps its own searcher.

A missing church file is HTTP 200:

```json
{
  "library": null,
  "label": "Your church",
  "sample": false,
  "present": false,
  "empty": true,
  "message": "Nothing from your church yet.",
  "mode": null,
  "results": [],
  "note": null,
  "abstain": false,
  "confidence": null
}
```

`abstain` stays false there because no search ran. A church file that was searched and found nothing still abstains (`confidence.level` is `none`), and `message` is the same sentence. The page shows that sentence instead of the low-confidence banner when there are no passages. When a side does return passages, the existing strong / weak / low-confidence rules apply to that side only. Low-confidence passages stay visible under the banner unless the person hides them.

The page adds a View control: John Wesley, or Side by side. Side by side calls `/api/side?k=5`. The single-library view still calls `/api/search?library=wesley&k=10`. Both columns use `renderCard`, so an archive.org hit is the audio player and a YouTube hit is the stored watch link. On a phone the columns stack, each under its heading. At 800px and wider they sit next to each other. Sample data is titled `Your church (sample data)`. CSP is unchanged: no inline script, no new host. YouTube is still a link, not `media-src`.

`search/query.py --side` prints the same two sections. `--church-index` or `--church-library` names the church file; otherwise it uses the single marked file under `/cache/index`. A missing file prints `Nothing from your church yet.` and exits 0. The CLI still prints the ranker's raw top `-k` (default 5). The API still de-dupes, as it did before this branch.

## How to run it

From `/work/preached/.worktrees/feat/w3-side`:

```bash
uv run python -m unittest discover -s tests
uv run search/query.py "what did Wesley say about worry" --mode bm25 --side
uv run app/server.py
```

Open http://127.0.0.1:8000 and choose View → Side by side. Or open `/?view=side&q=Romans%208:16`.

Mark a fixture library (this does not fetch Gaston Community Church; that channel is still refused before yt-dlp):

```bash
uv run --extra youtube import/youtube.py "https://www.youtube.com/watch?v=VIDEO" --library sample --your-church
uv run app/server.py --church-library sample
uv run search/query.py "mercy" --mode bm25 --side --church-library sample
```

`GET /api/side?q=mercy&mode=bm25&k=5` returns both columns. `GET /api/search?q=mercy&library=sample&mode=bm25` returns only that file.

## Results

`uv run python -m unittest discover -s tests`: **252 tests, all passing** (14.8s). Deno is installed; the page test ran the card renderer, the watch link, the archive player, the empty church sentence, the sample-data heading, and the per-side low-confidence toggle. There is no browser in this environment, so the layout was not clicked through in a real viewport. The CSS test checks that two columns appear only inside the `min-width: 800px` rule.

New coverage:

- A token that exists in only one library is absent from the other library's `/api/search` results, including play URLs and sermon ids.
- An unknown `library` slug is a 400 and returns no rows.
- `/api/side` abstains on the side that has no hits and does not abstain on the side that has BM25 hits.
- With a fixture floor of 0.5, the same query is `strong` on the classic vectors and `weak` on the orthogonal church vectors.
- A missing church file is 200 with `Nothing from your church yet.`
- A church file with no matching vectors does not drop the classic side; that column is BM25 and says so.
- `search/query.py --side` prints both headings and does not mix excerpts. A missing `--church-index` is the empty sentence, not an error.
- `--your-church` on a dry-run writes nothing. On a real import it marks that file, sets `sample` for the slug `sample`, and clears the mark on a sibling.

## Open issues

- If more than one file is marked `church` and the process is not given `--church-library` or `--church-index`, the church side is empty. The server logs the slugs. It does not guess.
- The single-library page still sends `library=wesley`. A server started with `--library` set to something else will reject that request, as it did before.
- The page asks for 5 hits per side. The API default remains 10, matching `/api/search`.
- The CLI list is not de-duplicated. The API list is. That split is the one `README.md` already describes for a single search.
- Empty church passages are a real abstain in the JSON. The page and the CLI show the empty sentence and skip the low-confidence banner, because there is nothing to read.
- No congregation archive is connected. Do not point `--church-library` at Gaston Community Church audio until the pastor's permission is confirmed. The importer still refuses that channel before any fetch.
- A browser pass of the stacked layout was not run here.

## Dependencies

None. The standard library, the existing SQLite file per library, and the existing Deno test (skipped when `deno` is missing). No model was added.
