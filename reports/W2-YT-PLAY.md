# W2-YT-PLAY: play YouTube results

Branch `feat/w2-yt-play`, cut from `origin/main` at `23bc496` (merge of PR #4). Report written 2026-10-30.

## What was done

A YouTube hit was not playable. The page put the stored watch URL on the `<audio>` element, and the Content-Security-Policy allows media only from archive.org. The CLI hid every non-archive URL, including a real YouTube watch link.

The page now treats a validated YouTube watch URL as a link instead of a player button. archive.org results still use the existing Play button and the `#t=` seek. There is no iframe and no embed. The CSP was not loosened.

`search/query.py` prints that validated watch link on the play line. archive.org links are unchanged. Anything else, including `https://www.youtube.com.evil.com/watch?v=...` and `javascript:`, still prints `n/a (unsafe URL hidden)`. Control characters are still stripped from text that is printed, and from a URL only after it has passed validation.

`PREROLL_S` is defined once, in `preached.search`. `src/preached/youtube/listing.py` imports it. `preached.search` does not import the YouTube package, so the import does not cycle. `watch_url` still sets `t=` to `int(max(0, start_s - PREROLL_S))`.

Tests that built `Video("samplevid001", ...)` used a 12-character id. Those fixtures now use `samplevid01`.

## How a YouTube result plays

The API is unchanged. A hit still carries the stored `audio_url`, `https://www.youtube.com/watch?v=<id>&t=<seconds>s`. The page accepts that URL when all of these hold:

- scheme `https`
- host `youtube.com`, `www.youtube.com`, or `m.youtube.com` (the importer's hosts, except `youtu.be`, which is not a `/watch` URL)
- no username or password, and port 443 or the default
- path `/watch`
- one `v` parameter of 11 characters (`[A-Za-z0-9_-]`)

The link text is `Watch on YouTube at` plus the same clock the Play button already uses (`formatTime`, so 95 seconds is `0:01:35`). `target` is `_blank`. `rel` is `noopener noreferrer`. The href is the stored string. The `&t=` pre-roll stays, and the page does not add `#t=`.

Opening the link is YouTube's own player at that `t=`. The in-page `<audio>` element never receives the URL, which is why playback no longer depends on `media-src`.

The CLI prints the same stored string on the `play:` line. It does not append `#t=`. An archive.org URL still gets `#t=` at `max(0, start_s - 0.75)`.

## CSP unchanged

`app/server.py` still sends:

```
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self' https://archive.org https://*.archive.org; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
```

`media-src` does not name YouTube. There is no `frame-src`, no `unsafe-inline`, and no `unsafe-eval`.

## How to run

```
uv run python -m unittest discover -s tests
uv run search/query.py "your question" --mode bm25 -k 5
uv run app/server.py
uv run app/server.py --library <slug> --bm25-only
```

## Results

`uv run python -m unittest discover -s tests` from this worktree: **179 tests, OK, 0 skipped** (2.2 seconds). Deno is installed, so `tests/test_app_js.py` ran the page checks in Deno instead of skipping them. `origin/main` has 173 `def test_` methods; the three `AppJsTests` are the ones that skip when Deno is absent.

The six new tests are the shared `PREROLL_S` identity check, the watch-URL acceptor and rejector, the CLI play line for YouTube / archive.org / hostile URLs, the printed play lines, and the exact CSP string.

Headless Chromium loaded `app/static/app.js` and rendered four cards. The YouTube card was one link, `Watch on YouTube at 0:01:35`, href `https://www.youtube.com/watch?v=abcdefghijk&t=94s`, `target="_blank"`, `rel="noopener noreferrer"`, with no `<button>` and no `<iframe>`. Clicking the archive.org card's `Play from 0:00:32` set the player to `https://archive.org/download/x/y.mp3#t=32.06`. `https://www.youtube.com.evil.com/watch?v=...` stayed on the old Play button. `javascript:` produced no link and no button.

## Open issues

The page still labels `source_url` "Read this sermon on CCEL". For a YouTube import that field is the watch URL without `t=`, so the card shows that label under the new Watch link. That label predates this branch. This task did not change it.

`youtu.be/<id>` is not a watch link here. Stored `audio_url` values are `https://www.youtube.com/watch?v=<id>&t=<seconds>s`, which is the form the link and the CLI accept. The importer still allows `youtu.be` as a channel or video URL for yt-dlp.

Any other `https` URL that is not a watch URL still gets a Play button. The CSP blocks playback unless the host is archive.org. The CLI hides those URLs. That split was left as it was.

## Dependencies

None added.
