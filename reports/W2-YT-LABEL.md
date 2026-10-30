# W2-YT-LABEL: source labels and a rebuilt YouTube watch link

Branch `feat/w2-yt-label`, cut from `origin/main` at `e2ddbc7` (merge of PR #13). No PR opened.

## What was done

Two nits from the PR #13 review, plus the three should-fixes from the post-merge review of `edbbca5`.

1. A result card labeled every `source_url` "Read this sermon on CCEL". The label now follows the URL. `ccel.org` and a subdomain (`www.ccel.org`) stay "Read this sermon on CCEL". A YouTube watch URL that is the same video as the watch link on the card is not shown again. A different video is "Watch the source on YouTube". Any other https URL that `safeUrl` accepts is "Source". A watch host that fails the watch rules is not linked. `safeUrl` is still called first. Its acceptance is unchanged. The CSP string in `app/server.py` is unchanged.

2. Python `parse_qs` was dropping a blank `v=`, so `v=<id>&v=` passed, while the page's `URLSearchParams.getAll("v")` counted it and rejected the URL. Both sides now reject any second `v`, blank or not. `parse_qs` is called with `keep_blank_values=True`.

3. `youtube_watch_url` (Python) and `youtubeWatchUrl` (page) used to return the stored string, so `&t=javascript:...` and `&redirect=...` were copied onto the link. Both rebuild `https://www.youtube.com/watch?v=<11-char id>` and add `&t=<int>s` only when there is exactly one `t` that is a whole number of seconds from 0 through 24 h (`86400`), with an optional trailing `s`. Every other query parameter, the fragment, and an explicit port are dropped. A bad `t` drops `t=` and still links the video. The link string is built in one place, `_watch_link` / `watchLink`.

4. Import-time `watch_url` called `int()` on the play position. `int(inf)` raises `OverflowError`. `int(1e300)` is a huge `t=`. A non-finite or negative `start_s` now omits `t=`. Zero and a short positive start still seek at `t=0s` (the 0.75 s pre-roll clamps at zero). The seek is capped at the sermon duration when that duration is a positive finite number, and always at 24 h. The cap is applied to the float before `int()`. `pipeline._chunks_for` passes `video.duration_s`. `start_s` on the chunk is still the first word.

   PR #12's flagged-audio policy is not on main (`origin/main` is `e2ddbc7`, PR #13). `watch_url` is still the one function that turns a start time into a link. `duration_s` is keyword-only, so a shifted start can be another argument later. This branch does not apply that policy.

5. `hit_dict` runs `audio_url` through `public_audio_url` before it is sent. That is the page's allow-list: a rebuilt YouTube watch URL, any other `https` URL (`safeUrl`), or a same-origin path (`/fixture/a.mp3`, not `//host`, not `..`). A YouTube `/watch` URL that fails the watch rules is dropped instead of forwarded raw. `javascript:`, `data:`, and `http:` become JSON null. `GET /api/sermon` still returns the stored `audio_url`.

## How to run

From `/work/preached/.worktrees/feat/w2-yt-label`:

```bash
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_app_js tests.test_youtube.ListingTests tests.test_server.ServerTests.test_hit_dict_audio_url_matches_the_page_allow_list
```

`tests/test_app_js.py` runs the page checks with `deno run --quiet --no-prompt --no-config`. Node is not installed in this sandbox (`command -v node` finds nothing). Deno 2.9.8 is, so those checks ran. No Node dependency was added.

## Results

`uv run python -m unittest discover -s tests`: **246 tests, OK, 0 skipped**, 12.894 s. `origin/main` has 243 `def test_` methods. The three new methods are `test_youtube_watch_url_rebuilds_validated_parts_only`, `test_watch_url_drops_non_finite_and_negative_and_caps`, and `test_hit_dict_audio_url_matches_the_page_allow_list`. The blank `v=`, hostile `t=`, extra `redirect=`, source-label, and cap cases are inside those and the existing Deno and CLI play-line tests.

Checked by those tests:

- `https://www.youtube.com/watch?v=abcdefghijk&v=` and `&v` and `v=&v=<id>` are None in Python and in Deno.
- `&t=javascript:alert(1)&redirect=https://evil.example` becomes `https://www.youtube.com/watch?v=abcdefghijk` on the page, in `youtube_watch_url`, on the CLI play line, and in `hit_dict`.
- `&t=11s&redirect=...` keeps `t=11s` and drops `redirect`. `t=86400` is kept. `t=86401s` drops `t=`.
- `m.youtube.com`, `youtube.com`, and `:443` rebuild onto `https://www.youtube.com/watch` with the same id and `t`.
- A card whose `source_url` is the same video as the watch link has one link. A different video is labeled "Watch the source on YouTube". `https://ccel.org.evil.com/...` is "Source", not CCEL. `javascript:` and `http://ccel.org/...` are not links.
- A card with no `start_s` still shows the YouTube source, because there is no watch link to duplicate.
- `watch_url(id, inf)`, `-inf`, `nan`, and `-1` return the watch URL with no `t=` and do not raise. `watch_url(id, 1e300)` is `&t=86400s`. With `duration_s=40` it is `&t=40s`. A chunk whose first word is at 100 s in a 40 s video stores `start_s` 100 and `audio_url` `...&t=40s`.

## Open issues

- `GET /api/sermon` still returns the stored `audio_url`. Only `hit_dict` (search results) filters it.
- `public_audio_url` keeps any other `https` URL, including one with userinfo, because `safeUrl` does. The CLI play line still hides those through `check_audio_url` (archive.org, no credentials).
- An out-of-range `t` on a stored URL is omitted. The import builder caps instead, because it has a real start time and a duration.
- `youtu.be/<id>` is still not a watch link. Stored `audio_url` values are `https://www.youtube.com/watch?v=<id>&t=<seconds>s`.
- The flagged-audio policy (play / shifted / none) is on `feat/w3-priv-wire`, not on main. This branch does not read it.

## Dependencies

None added.
