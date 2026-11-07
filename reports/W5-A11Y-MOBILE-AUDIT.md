# W5 accessibility and phone UX audit

Reviewed the served UI as it stands on `origin/main` at `6d07f64c944a483e8e107ffbd0673eed17e2359c`. The branch was cut from `8d46f143f5fb44fb9d01cd2357eaf99404a40d24`; main moved before publish (merges of #92, #93, #94, and #96). `git diff 8d46f143f5fb44fb9d01cd2357eaf99404a40d24 6d07f64c944a483e8e107ffbd0673eed17e2359c -- app/static` is empty, so every `app/static` line cite is the same on both commits. `app/server.py` and `docs/DEPLOY.md` cites are the lines on `6d07f64`, read from that tree. Scope is this report. No file under `app/`, `src/`, `tests/`, or `docs/` was edited. Findings that need code are recommendations.

The page judges open is `app/static/index.html`, styled by `app/static/app.css` and driven by `app/static/app.js`. `app/server.py` sends that file unchanged for `GET /` (`_send_page`, `2342`–`2348`). Two other bodies matter on a phone: the accept-thread HTML 503 (`2918`–`2922`) and the JSON 503 the handler returns when the process is disabled (`2250`–`2255`).

## How this was probed

No browser and no screen reader. Layout, contrast, focus, and announcements are reasoned from the CSS and from the DOM the script builds. Live bytes are from two loopback processes, both `python app/server.py --bm25-only --host 127.0.0.1` with a one-chunk synthetic Wesley index under `/tmp` (sermon id `wesley-001`, one timed passage). `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, and `TORCH_HOME` were fresh directories under `/tmp/a11y-audit.VPTyeN/`, plus a scratch `UV_PYTHON_INSTALL_DIR`. `ORT_DISABLE_TELEMETRY=1`. The live environ matched those paths. The log line was `BM25 only; the embedding model was not loaded`. Church side was not started. `ss` showed `LISTEN` on `127.0.0.1` only (backlog 128).

| Process | Port | PID | Extra environment |
| --- | --- | --- | --- |
| Page and API | 36335 | 528 | defaults (`PREACHED_DISABLED` unset, connection caps at the code defaults) |
| Disabled and over-cap | 36337 | 660 | `PREACHED_DISABLED=1`, `PREACHED_MAX_CLIENT_CONNECTIONS=1` |

Each process was stopped by that PID. `find /cache -maxdepth 3 -printf '%p %s %T@\n' | sort` was identical before and after (1640 lines, sha256 `7e6961c7f38f52e84c7807ae8bf546375aca4e71c8fe3bf84a7cca1b260736c5`).

Those processes were the server at `8d46f14`. On `6d07f64` the page file, `_OVER_CAP_HTML` (`2918`–`2922`), and the disabled branch (`2250`–`2255`) are the same text: `{"error": "unavailable"}` for every path except `/healthz`, and `/healthz` stays `{"ok": false, "disabled": true}`. An up `/healthz` on `6d07f64` also adds `slots_stuck` when `ok` is true (`app/server.py:2318`). The probe did not capture that field, and the server was not started again after main moved.

`GET /` on port 36335 returned `HTTP/1.1 200 OK`, `Content-Type: text/html; charset=utf-8`, `Content-Length: 5521`, and a body byte-identical to `app/static/index.html`. Same check for the three static files.

## Already fixed (cite, do not re-open)

`reports/W3-MOBILE-UX-QA.md` fixed eight phone issues. They are still in this tree, and tests pin them:

| What | Where now | Test |
| --- | --- | --- |
| Search scrolls the results up, and a touch keyboard is blurred | `revealResults` `app/static/app.js:566`–`572`; blur only when `(pointer: coarse)` matches `327`–`329`, `655`–`658` | `tests/test_mobile_ux.py` (`test_cards_player_and_scroll`) |
| Player bar is hidden until the first Play | `index.html:96` `hidden`; unhide in `playClip` `186`–`187` | `test_player_bar_starts_hidden` |
| Classic low-confidence banner and BM25 note are in a polite live region | `#note` and `#confidence` inside `.notices` `index.html:58`–`61` | `test_confidence_banner_is_announced` |
| "Read this sermon on CCEL" is at least 44px tall | `app.css:329`–`333` | `test_tap_targets_and_text_size` |
| A `?q=` longer than 300 code points is cut before search | `capQuery` `app.js:323`–`325`, `682`–`685` | same Deno test |
| Held-audio caption is two sentences | `app.js:201`–`202` | same Deno test (the text; F-02 is that nothing announces it) |
| Skip link is at least 44px tall | `app.css:41` | `test_tap_targets_and_text_size` |
| Watch link says it opens a new tab | `app.js:281` | same Deno test |
| Viewport allows pinch zoom; inputs are 16px | `index.html:5`; `app.css:96` | `test_viewport_allows_zoom` |

Items 9–13 in that report are still open. They are listed at the end and are not given new IDs.

## Page weight and network

Served on port 36335, `Cache-Control: no-store` on each:

| URL | Bytes | Content-Type |
| --- | --- | --- |
| `/` | 5521 | `text/html; charset=utf-8` |
| `/static/app.css` | 7668 | `text/css; charset=utf-8` |
| `/static/app.js` | 25013 | `text/javascript; charset=utf-8` |
| `/static/favicon.svg` | 321 | `image/svg+xml` |

Total for a first load: **38523 bytes**, all from this origin. CSP on those responses is `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self' https://archive.org https://*.archive.org; connect-src 'self'; font-src 'self'; …` (`app/server.py:206`–`219`). There is no font request, no analytics, and no `preconnect` / `prefetch`.

External URLs that appear in the files and are not fetched on load:

- Credit links in the HTML (`https://ccel.org/ccel/wesley/sermons`, `https://librivox.org/`, `https://archive.org/`). Ordinary `<a href>`. The browser fetches them when the link is opened.
- `app.js` builds `https://www.youtube.com/watch?v=` only as a watch link (`79`–`84`). `media-src` does not allow YouTube, and the script never assigns that URL to `<audio>`.
- The favicon's `xmlns="http://www.w3.org/2000/svg"` is an identifier. It is not a request.
- Archive.org audio is requested only after Play sets `audio.src` (`app.js:194`). That is the one external transfer, and it is the recording.

## Semantics, keyboard, and what is exposed

Landmarks on the static page: `header.mast` (banner, because it is not inside a section), `form role="search"` (`index.html:22`), `section#results-section` named by the visually hidden h2 (a region), `footer.colophon` (contentinfo), and `section.credits` named "Credits" (a region inside the footer). There is no `<main>` and no `<nav>`.

Heading order, classic view: `h1` "John Wesley, in his own words" (`18`), visually hidden `h2` "Results" (`56`), one `h3` per card (`app.js:247`), then `h2` "Credits" (`89`). Side by side inserts two more `h2`s ("Classic library: …", "Your church") from `renderSide` (`438`) before the card `h3`s. Levels are not skipped on the way down.

The three fields have `<label for>` (`24`, `28`, `36`). The Search control is `type="submit"`. The four examples are `type="button"` inside `role="group"` labelled by "Try one" (`47`). Hide and Try again are buttons (`78`–`79`). Archive playback is a `<button class="play">` (`284`–`287`). A YouTube hit is an `<a class="play" target="_blank" rel="noopener noreferrer">` (`277`–`282`). The CCEL line is an `<a>` (`304`–`308`). Nothing in `app.js` listens for `keydown` or sets `tabindex` greater than 0. The only `preventDefault` is on submit (`648`). Keyboard operation of the form, the chips, the `<details>` (`62`–`76`), and the play controls is the browser's own.

`:focus-visible` draws a 3px outline (`app.css:396`–`401`). On the dark bar the outline colour is `#f3eee4` (`401`). The skip link is shown on `:focus` by undoing its transform (`32`–`46`). Its `href` is `#q` (`index.html:14`), which is the next tab stop after the skip link itself, so activating it does not pass any control. See F-07.

## Contrast

Ratios use the WCAG 2.x relative-luminance formula on the hex values in `app.css:4`–`10`. The stylesheet sets no root `font-size`, so the px figures below assume the usual 16px root. AA thresholds: 4.5:1 for text under 24px (or under 18.5px when bold), 3:1 for large text and for a boundary that identifies a control.

| Pair | Where | Ratio | AA text |
| --- | --- | --- | --- |
| `#1c1915` on `#f3eee4` | Body, headings, labels, the wordmark | 15.14:1 | Pass |
| `#1c1915` on `#fffaf3` | Input text, card titles, note text | 16.86:1 | Pass |
| `#3f3a33` on `#f3eee4` | Lede, examples, colophon, the levels copy | 9.74:1 | Pass |
| `#3f3a33` on `#fffaf3` | Kicker, scripture, reader, "why" line | 10.85:1 | Pass |
| `#f3eee4` on `#1c1915` | Buttons, skip link, player caption | 15.14:1 | Pass |
| `#f3eee4` on `#000000` | Button hover (`app.css:111`) | 18.16:1 | Pass |
| `#1c1915` on `#ffffff` | `prefers-contrast: more` (`446`–`452`) | 17.51:1 | Pass |

The focus outline is `#1c1915` on `#f3eee4` (15.14:1) and, inside the player, `#f3eee4` on `#1c1915` (15.14:1). Input and button borders are `1px solid` `#1c1915`. Those pass 3:1.

The card rule does not. `--line` `#d9d0c2` on `#f3eee4` is **1.32:1**, and on `#fffaf3` is **1.47:1**. The card fill `#fffaf3` on the page `#f3eee4` is **1.11:1**. `prefers-contrast: more` sets `--line` and `--ink-soft` to `#1c1915`, which repairs it. See F-10. Placeholder colour is not set, so it stays the browser default and is not a ratio from this stylesheet.

Small type that still passes contrast, already recorded as info in `reports/W3-MOBILE-UX-QA.md` item 13: `.mark` is `0.78rem` and weight 700 (`app.css:57`–`63`), about 12.5px; `.kicker` is `0.85rem` and weight 600 (`272`–`279`), about 13.6px. Body copy is `1rem`. Quotes are `1.05rem` (`294`–`299`).

## Layout at 360px and 412px

The base rules are the phone layout. `@media (min-width: 640px)` (`415`) only enlarges the `h1` and puts mode, view, and Search on one row. `@media (min-width: 800px)` (`424`) is the only place the two libraries sit side by side. Both 360 and 412 are under both breakpoints, so the form is one column and the two libraries stack, with a top border between them (`249`–`253`).

`* { box-sizing: border-box }` (`13`). `.wrap` padding is `1.25rem 1rem 8.5rem` (`26`–`30`): 16px on each side, so the column is 328px at 360 and 380px at 412. Nothing sets a fixed width, a `min-width` above that column, or `100vw`. `.side-col` sets `min-width: 0` (`246`). Quotes and the "why" line use `overflow-wrap: anywhere` (`299`, `320`). Chips wrap (`121`–`125`). From the stylesheet, neither width should scroll sideways. This was not measured in a viewport.

Controls with `min-height: 44px`: `button` (`100`), `input` and `select` (`88`), the confidence `<summary>` (`165`), `.card .text-link a` (`332`), `.card a.play` (`338`), `.skip` (`41`). Chip and Search widths are the label plus `padding: 0.5rem 1rem`. The stylesheet does not set a width under 44px on those controls. The gap between chips is `0.5rem`.

`audio` is `width: 100%` only (`394`). Its pause, seek, and volume controls have no 44px minimum in this CSS. Footer and credit links are inline in a `0.92rem` paragraph (`355`–`370`); the line box is about 22px. That is the deferred item 9 below.

Bottom padding of the page is `8.5rem` (136px at a 16px root). The player is `position: fixed; bottom: 0` (`372`–`380`). A one-line caption is `0.92rem` at the inherited 1.5 line-height (about 22px), plus `0.65rem` top padding, a `0.35rem` gap, the browser's audio control (height not in the CSS), and `0.7rem` bottom padding. The about-103px figure for a short caption is W3 item 2 (`reports/W3-MOBILE-UX-QA.md:43`): the empty player bar on first load ("Choose Play on a passage." plus an empty audio control, 103 px). Item 10 is the 169px figure, measured when the held-audio sentence wrapped to four lines, which is taller than 136px. The safe-area term in that padding is inert; see F-04.

`prefers-reduced-motion: reduce` (`441`–`444`) sets `scroll-behavior: auto` and disables the spinner animation. `revealResults` calls `scrollIntoView({ block: "start" })` with no `behavior`, so it follows that property and should jump rather than animate. There is no `prefers-color-scheme` rule. See F-09.

## States

Copy is `MESSAGES` in `app.js:332`–`344`. Classic search writes the status into `#status`, which is `role="status" aria-live="polite"` (`index.html:57`), and writes the note and the confidence banner into `.notices`, which is `aria-live="polite"` (`58`).

| State | What the classic page shows | Announced? |
| --- | --- | --- |
| Loading | "Searching the sermons." plus a CSS spinner, and `aria-busy="true"` on the section (`470`–`474`, `591`–`593`) | The text is inside the busy section. See F-05. The spinner is decorative (`content: ""`, `192`–`202`). Reduced motion leaves the shape and drops the spin (`443`). |
| Empty | Probe: `GET /api/search?q=zzznomatchtoken&mode=bm25&k=2&library=wesley` → `200`, `results: []`, `abstain: true`, and a low-confidence `confidence.note`. `describeResponse` hits the empty branch first (`373`–`376`) and sets the status to "Nothing found in these sermons. Try other words, or a Bible verse such as Romans 8:16." The banner is not shown. | Yes, via `#status`. The empty `<ol id="results">` stays in the tree (`resetState` sets `hidden` false and removes the children, `477`–`479`). |
| Low confidence, classic, results present | Banner text in `#confidence`, toggle "Hide low-confidence results" with `aria-pressed` (`514`–`516`). Hiding replaces the status with "Low-confidence results hidden." and keeps focus on the toggle (`544`–`550`). | Yes, on the classic path. The side-by-side path is F-03. |
| Weak | `confidence.note`, or the fallback sentence in `MESSAGES.weak` (`385`–`387`), into `#confidence`. | Yes, classic path. |
| BM25 fallback | Probe: `GET /api/search?q=grace&mode=hybrid&k=1&library=wesley` → `200`, `"note": "Embeddings are not loaded; results are BM25 only."` `showResults` puts that in `#note` (`508`). | Yes, classic path. Side by side is F-03. |
| Network, 5xx, garbled | "Could not reach the search. …", "The search had a problem on our side. Try again in a moment.", or "The search sent back something unexpected. Try again." (`452`–`458`, `553`–`560`). Status ≥ 500 returns the generic sentence before any `error` string is read (`455`). A 4xx with an `error` string is shown as "Search failed: " plus that string (`456`). Probe 400s: `{"error": "q is required"}` (26 bytes) and `{"error": "q must be 1 to 300 characters"}` (42 bytes). | The status node gets the sentence and the class `is-error`. Focus stays where it was. Try again appears when a query was sent (`560`) and is not focused. |
| In-page over-cap | `fetch` sends `Accept: application/json` (`612`). That 503 is JSON `{"error":"unavailable"}`, status ≥ 500, so the page shows the "problem on our side" sentence. | Yes, via `#status`. |
| Document over-cap | The HTML page in F-01. The app script never runs. | The page has no live region. It reloads itself. |
| Disabled | `GET /` is JSON. See F-06. | A browser shows the JSON text. |
| Whitespace-only submit | "Enter a question." written straight onto `#status` (`650`–`653`). Previous cards stay. | The status is a live region, so the sentence can be announced. Already deferred (item 11 below). A truly empty field never reaches this handler: the input is `required` (`index.html:25`). |

Side-by-side status, from the same hybrid probe's `/api/side` body (`classic.note` is the embeddings sentence, `church.message` is "Nothing from your church yet."): `showSides` sets `#status` to "Classic library: John Wesley. 1 passage. Your church. Nothing from your church yet." (`526`–`528`). The embeddings sentence is rendered only as a plain `<p class="note">` inside the column (`440`).

## Audio and the timestamp

For the probed hit (`start_s` 92.02, `end_s` 145, sermon number 1, reader "A. Volunteer", archive.org URL), `renderCard` builds:

- A paragraph `0:01:32–0:02:25` (`formatTime`, `15`–`23`, always `H:MM:SS`).
- A button whose visible text is "Play from 0:01:32" and whose accessible name is the `aria-label` "Play sermon 1 from 0:01:32" (`284`–`287`). The name replaces the visible text for a screen reader, and it does not contain that visible text. See F-11.
- On click, `playClip` seeks to `playStart` 91.27 (start minus `PREROLL_S` 0.75). `PREROLL_S` is defined at `app.js:44`. `playStart` is `46`–`50`. The click sets `#now-playing` to "Salvation by Faith · 0:01:32 · Read by A. Volunteer (LibriVox volunteer)". If `play()` rejects, that becomes the same sentence plus ". Press play on the bar if the browser held the audio." (`199`–`207`).

The time range is text, not a second control. The jump is the button (archive) or the watch link (YouTube). Enter and Space activate the button. Enter activates the link. The `<audio>` is the pause and seek control, and it is last in the document, after the footer (`96`–`100`). It has `controls` and `preload="none"`, and no `aria-label` or `aria-labelledby`. `#now-playing` is not a live region and is not associated with the audio. See F-02.

`.play.is-playing` draws an outline (`app.css:350`–`353`) and sets no `aria-pressed` or `aria-current`. A second press of the same button calls `playClip` again (`291`–`293`). It does not pause. There is no `ended` or `pause` listener (`639`–`642` listens for `loadedmetadata`, `canplay`, and `durationchange` only).

## Findings

| ID | Severity | Finding |
| --- | --- | --- |
| F-01 | High | The over-cap HTML page has no viewport and reloads every second |
| F-02 | Medium | The player has no name, and the held-audio instruction is not announced |
| F-03 | Medium | Side by side keeps the confidence and fallback notes out of the live region |
| F-04 | Low | The safe-area `env()` term is inert without `viewport-fit=cover` |
| F-05 | Low | "Searching the sermons." is written while an ancestor is `aria-busy="true"` |
| F-06 | Low | A disabled `GET /` is raw JSON on a phone navigation |
| F-07 | Low | There is no main landmark, and the skip link targets the next control |
| F-11 | Low | The play button's accessible name does not contain its visible label (WCAG 2.5.3) |
| F-08 | Info | Changing View runs a new search with no warning (Patrick's call) |
| F-09 | Info | The page has no dark-mode colours |
| F-10 | Info | The card border is below the 3:1 non-text threshold |

### F-01 — High — the over-cap page is not usable on a phone

A browser navigation that arrives while this peer is already at `DEFAULT_MAX_CLIENT_CONNECTIONS` (4, `app/server.py:247`) is answered on the accept thread. `docs/DEPLOY.md:628` records that rule, including the meta refresh of the same 1 second. `docs/DEPLOY.md:1074`–`1077` records the empty-`PREACHED_TRUSTED_PROXIES` caveat behind `tailscale serve`: every proxied request is limited as `127.0.0.1`, so every phone shares one cap of 4 connections. The sanctioned exposure path is `PREACHED_TRUSTED_PROXIES=127.0.0.1` (`docs/DEPLOY.md:996`–`1000`, item 9 at `1117`–`1121`), where loopback is exempt from the per-peer cap, so the accept-time 503 is reached only when all 32 connection slots are held and nothing can be evicted (`docs/DEPLOY.md:628`–`629`). At that 32-slot saturation a page load on the `/healthz` reserve gets the handler's JSON 503 (`app/server.py:2261`–`2268`, `_reserved` and not health, body `{"error": "unavailable"}`), as does the per-key slot-busy 503 (`app/server.py:2280`–`2291`, `acquire_slot` refused, the same JSON). Today only the accept-thread over-cap path serves HTML. Under the sanctioned config the page appears at global saturation (the many-phones-at-once case, which is why it stays High); under the empty-proxy config, at 4 connections across all clients. A peer already at that cap may take its own oldest idle keep-alive once that socket has been quiet for 1 second (`docs/DEPLOY.md:628`), and the new connection uses that slot. The over-cap 503 is written on the accept thread and does not start a handler or spend a rate-limit bucket (`app/server.py:2786`–`2790`, `2811`–`2837`), so the 1 s refresh is a bounded per-tab retry (1 connection/s/tab), not a self-amplifying load. The refusal log at `2788` goes through `RefusalLog.note` (`app/server.py:501`–`511`), one line per class per second. A tab that then gets the page loads the four first-load resources, so tabs that recover together are a mild synchronized herd. The F-01 fix must update the coupling comment at `app/server.py:2915`–`2916`, the "meta refresh of the same 1 second" sentence at `docs/DEPLOY.md:628`, and the `content="{retry-after}"` assertion at `tests/test_html_503.py:199` if the refresh is lengthened while `Retry-After` stays 1. This probe did not run Tailscale and did not load the page from a phone. It held one connection and sent a second with Chrome's navigation `Accept`.

On port 36337, 29 of 30 such requests returned this response (the other one was the JSON body, which `docs/DEPLOY.md` already describes for a request whose headers were not buffered yet):

```
HTTP/1.1 503 Service Unavailable
Content-Type: text/html; charset=utf-8
Content-Length: 176
Connection: close
Retry-After: 1
Cache-Control: no-store

<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta http-equiv="refresh" content="1"><title>Unavailable</title></head><body><p>Unavailable. Retrying.</p></body></html>
```

Those bytes are `_OVER_CAP_HTML` (`app/server.py:2918`–`2922`). The page has a title and one sentence. It has no viewport meta. Mobile browsers then use their fallback layout width of about 980 CSS pixels and scale it into the device width, so on a 390px-wide phone the text is about two-fifths of the authored size. `<meta http-equiv="refresh" content="1">` reloads the page every second. There is no control to pause or extend that, which is WCAG 2.2.1 (Level A) on this response. A screen reader has about a second to say "Unavailable. Retrying." before the document is replaced. There is no heading and no landmark.

An in-page search does not hit this HTML. `fetch` sends `Accept: application/json` (`app.js:612`), the body is JSON, and `failureMessage` shows "The search had a problem on our side. Try again in a moment."

Recommendation (PR-A, with F-06): one small constant HTML document with `width=device-width, initial-scale=1`, an `h1`, and the sentence "Preached is busy. This page will try again in a moment." Keep `Retry-After: 1` for API clients. Make the meta refresh 5 seconds or more, or replace it with a "Try again" link to `/`, so the sentence can be read. The page stays constant: no request bytes, no script, and no external URL. Keep the negative assertions in `tests/test_html_503.py` (the query, the peer, and `http://` / `https://` stay out of the body). If the refresh is lengthened while `Retry-After` stays 1, update the coupling comment at `app/server.py:2915`–`2916` ("Retry-After and the meta refresh are this same delay"), the "meta refresh of the same 1 second" sentence at `docs/DEPLOY.md:628`, the pinned `content="1"` at `tests/test_html_503.py:198`, and the `content="{retry-after}"` assertion at `tests/test_html_503.py:199`. `tests/test_html_503.py::test_html_navigation_gets_a_refreshing_page` pins the current refresh and the current sentence; that test has to move with the copy. Re-pin every `docs/DEPLOY.md` cite that moves. The missing security headers on this same response are already F-04 in `reports/W5-HTTP-SECURITY-AUDIT.md`.

Covered today: the test above asserts status 503, `text/html`, `Retry-After: 1`, the refresh, and that the query is not echoed. It does not require a viewport or a way to pause the reload.

### F-02 — Medium — the player is unnamed, and the held-audio line is silent

`index.html:96`–`100`:

```html
<div class="player" id="player-bar" hidden>
  <div class="player-inner">
    <p id="now-playing">Choose Play on a passage.</p>
    <audio id="player" controls preload="none"></audio>
  </div>
</div>
```

`playClip` (`182`–`208`) unhides the bar, starts playback, and writes the caption. The caption node is not `aria-live`. The audio node is not `aria-labelledby="now-playing"`. Focus is left on the card button. The audio element is the last focusable control in the document, after every card and the footer links, so Pause is a long tab from the passage that was just activated. On a phone the bar is painted at the bottom, which does not change that order.

When the browser holds `play()`, the only instruction is the second sentence on `#now-playing` (`199`–`203`). `reports/W3-MOBILE-UX-QA.md` fixed the wording and recorded that headless Chromium held the audio. iOS does this often. The sentence is not in a live region, so a screen reader is not told to use the bar. Focus stays on the card button. A focus move, if any, belongs only in this held-audio branch.

The accessible name uses `formatTime`, which is always `H:MM:SS` (`15`–`23`). The probed passage's visible text is "Play from 0:01:32" and its name is "Play sermon 1 from 0:01:32" (`284`–`287`). The name does not contain the visible label. That is F-11 (WCAG 2.5.3 Label in Name, Level A). A spoken time such as "1 minute 32 seconds" would move the name further from the words on the button, so the fix leaves the clock in the name as `H:MM:SS`.

`.play.is-playing` is visual only (`app.css:350`–`353`). The button does not toggle pause. Pressing it again calls `playClip` (`291`–`293`).

`audio` has no `min-height` (`394`). The 44px rule used everywhere else does not apply to the only pause and seek controls.

Recommendation (PR-B): name the audio with `aria-labelledby="now-playing"`. Do not put `aria-live` on `#now-playing`. That would announce the caption over the sermon audio on every Play. Announce only the held-audio sentence, through its own live region, and move focus to the bar only in the held-audio branch (`app.js:199`–`203`), if at all. Do not set `aria-pressed`. A pressed state would say the button pauses, and a second press does not pause. Leave the `is-playing` outline visual-only, or set `aria-current="true"`. Do not put a spoken time in the `aria-label`. The name should start with the visible text, for example `Play from 0:01:32, sermon 1` (F-11). Give `audio` `min-height: 44px`. `tests/test_mobile_ux.py` already asserts the held-audio string and that the bar unhides; extend that Deno check to the accessible name, live membership of the held-audio sentence, and label-in-name.

Covered today: the bar starts hidden, the caption string, the seek to start minus 0.75s, and the `aria-label` "Play sermon 41 from 0:01:32" (`tests/test_mobile_ux.py:208`). No test checks a name on `<audio>`, a live region for the held-audio sentence, or that the name contains the visible label.

### F-11 — Low — the play name does not contain the visible label

WCAG 2.5.3 Label in Name (Level A). `renderCard` sets the visible text to "Play from " plus `formatTime` (`app.js:284`) and the `aria-label` to "Play " plus the sermon name plus " from " plus the same clock (`284`–`287`). For the probed hit that is visible "Play from 0:01:32" and name "Play sermon 1 from 0:01:32". The name does not contain the visible label, so a voice-control user who says the words on the button does not hit it. The same shape holds for any sermon number: visible "Play from H:MM:SS", name "Play sermon N from H:MM:SS".

Recommendation: ship the rename with F-02 in PR-B. The accessible name starts with the visible text, for example `Play from 0:01:32, sermon 1`. Do not replace the clock with a spoken time.

Covered today: `tests/test_mobile_ux.py:208` requires the current name "Play sermon 41 from 0:01:32". It does not require the name to contain "Play from 0:01:32".

### F-03 — Medium — side by side does not announce the warning the classic view announces

Classic search puts the low-confidence banner and the BM25 note in `.notices` (`index.html:58`–`61`). That was `reports/W3-MOBILE-UX-QA.md` item 3.

`showSides` (`519`–`541`) never calls `setText` on `#note` or `#confidence`. `resetState` clears both: `#note` at `app.js:487` and `#confidence` at `488`. The status line is the two headings and the two counts only (`526`–`528`). `renderSide` (`435`–`448`) appends the fallback note and the confidence note as plain paragraphs (`440`, `442`). They have no `aria-live` and no `role`.

The live hybrid side body on port 36335 has `classic.note` "Embeddings are not loaded; results are BM25 only." and `church.message` "Nothing from your church yet." The live region therefore gets the counts and the empty-church sentence. The embeddings sentence is only in the column.

The same split is what the Deno test locks in for a low-confidence column. `tests/test_app_js.py:674` asserts the status text does not contain "heuristic", while `renderSide` still builds the banner as a child paragraph. A screen reader user who hears the status and does not walk the column misses "Low confidence: these passages may not answer your question." The lede invites this view (`index.html:19`).

Recommendation (PR-C): write each side's fallback note and confidence note into `.notices`. Keep the column text for someone who scrolls. Keep the assertion at `tests/test_app_js.py:674` ("status is not the banner"); the `#status` composition does not change. Add assertions that after `showSides`, `#note` carries `<side heading>: <fallback note>` and `#confidence` carries `<side heading>: <confidence note>` (the latter only when that side's results are shown), both are visible and inside `.notices`, and no column node carries `aria-live`.

Covered today: `test_confidence_banner_is_announced` checks the static classic nodes only. `test_side_by_side_rendering` checks the column text and that the status omits "heuristic". It does not check a live region on the column note.

### F-04 — Low — the safe-area term is dead code until cover is turned on

The player padding is `0.65rem 1rem calc(0.7rem + env(safe-area-inset-bottom))` (`app.css:379`). The viewport is `width=device-width, initial-scale=1` (`index.html:5`). It does not contain `viewport-fit=cover`. With no `viewport-fit=cover`, WebKit keeps the layout viewport out of the unsafe area, so `env(safe-area-inset-*)` stays 0. The `env()` term adds nothing. It is dead code, not a visible defect. The only gap under the audio element is `0.7rem` (about 11px). The home-indicator inset on current iPhones is 34px when cover is on. Turning cover on is what would introduce the overlap.

`.wrap`'s bottom padding is a fixed `8.5rem` (`29`). It does not add the inset. Turning cover on without also growing that padding makes the held-audio bar (already measured at 169px in the W3 report, item 10, taller than 136px) cover the footer by the inset as well.

This was not looked at on a device. `reports/W3-MOBILE-UX-QA.md` left `env(safe-area-inset-bottom)` under the home indicator as unverified.

Held. Any F-04 change needs a check on a real iPhone first (Patrick's real-client rule). Only after that check: add `viewport-fit=cover` to the viewport meta, and change the page's bottom padding to `calc(8.5rem + env(safe-area-inset-bottom))`, keeping the player's existing `calc`. `test_viewport_allows_zoom` already requires `width=device-width` and `initial-scale=1` and rejects `user-scalable` and `maximum-scale`. A cover change would add a positive check for `viewport-fit=cover` in that same test. It is not a queued PR.

Covered today: the viewport test above. It does not mention `viewport-fit`.

### F-05 — Low — loading text is written inside `aria-busy="true"`

`runSearch` calls `setBusy(true)` and then sets the status to "Searching the sermons." (`591`–`593`). `setBusy` sets `aria-busy` on `#results-section` (`470`–`474`), which is the ancestor of `#status`. ARIA says assistive technologies may hide changes inside a busy subtree until `aria-busy` goes back to false. The results update is safe: `showResults` and `showSides` call `setBusy(false)` before they write the status (`504`, `521`). The loading sentence is the one written while busy. A hybrid search on the real model can take long enough that silence matters. This was not heard on a screen reader.

Recommendation (PR-D, with F-07): put `aria-busy` on `#results` and `#sides` only, leave `#status` in place, and keep `is-loading` on `#results-section`. The loading sentence stays outside the busy nodes. Both this and F-07 ship as one PR. Update the `aria-busy` assertions at `tests/test_app_js.py:380` (`"true"` while loading) and `:382` (`"false"` after) so they name `#results` and `#sides`.

Covered today: that assertion checks the attribute value. It does not check that the loading sentence is outside the busy subtree.

### F-06 — Low — the kill switch serves JSON to a phone navigation

With `PREACHED_DISABLED=1`, this request:

```
curl -sS -D - -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" http://127.0.0.1:36337/
```

returned `HTTP/1.1 503 Service Unavailable`, `Content-Type: application/json; charset=utf-8`, `Content-Length: 24`, body `{"error": "unavailable"}`. The handler does that for every path except `/healthz` (`2250`–`2255`), with no branch on `Accept`. A phone browser shows the JSON. `/healthz` is the other body, `{"ok": false, "disabled": true}`, which is what a monitor should keep.

Recommendation (PR-A, with F-01): for a disabled `GET /` and `HEAD /` with a browser `Accept`, send the same constant HTML page as F-01, including its viewport and with no one-second refresh. Keep `/healthz` as `{"ok": false, "disabled": true}` and `/api/*` on JSON. F-06 can be its own PR immediately after F-01 if that is easier, and it must reuse F-01's constant. Keep the kill-switch assertion at `tests/test_deploy.py:229` green (a disabled `/api/search` body is `{"error": "unavailable"}`) and the JSON 503 assertions at `tests/test_exposure.py:577`, `:1190`, and `:1330`. Add an HTML-on-`/` test and a JSON-on-`/api/search` test. The kill switch must stay tested. Re-pin every `docs/DEPLOY.md` cite the edit moves.

Covered today: `tests/test_deploy.py:229` expects the JSON error for a disabled `/api/search`. The new tests are the HTML page on `GET /` with a browser `Accept`, and JSON on `/api/search`.

### F-07 — Low — no main landmark, and the skip link does not skip

The skip link is the first tab stop and points at `#q` (`index.html:14`). The next tab stop is `#q`. The header text in between is not focusable, so the link passes no control. After a search, the useful skip is to `#results-heading`.

There is no `<main>`. Screen-reader landmark navigation has banner, search, the results region, and contentinfo, and no main.

Recommendation (PR-D, with F-05): wrap the form, the examples, and `#results-section` (`index.html:22`–`83`) in `<main id="main">`, not only the results, and point the skip link at `#main`. The F-05 route in this PR is `aria-busy` on `#results` and `#sides`, with `#status` left in place and `is-loading` kept on `#results-section`. Re-pin the `index.html` cites in `docs/DEMO-SCRIPT.md:28`, `:42`, `:123` and `docs/SUBMISSION-DRAFT.md:34`. Add a `<main>` and skip-target assertion next to the `aria-busy` assertions this PR already updates (`tests/test_app_js.py:380` and `:382`).

Covered today: no test looks for a main landmark or for the skip target.

### F-08 — Info — the View select searches by itself (Patrick's call)

Mode waits for Search. View does not. After a query exists, `change` on `#view` calls `runSearch(lastSearch)` (`666`–`671`). The label is "View" (`index.html:36`). Nothing near it says that picking "Side by side" replaces the results. On a phone the native picker commits as soon as the choice is tapped.

Updating results in place is a change of content, not a change of context, so this is not a 3.2.2 failure. The note is advisory. The View auto-search is deliberate demo UX for side by side. Removing it is Patrick's product decision, and it is not a queued fix.

Advisory options, for that decision: leave the listener, remove the `change` listener and let the next Search use the new value, or add a sentence under the label ("Changing the view searches again."). No current test asserts that a view change starts a fetch.

Covered today: nothing in `tests/test_app_js.py` or `tests/test_mobile_ux.py` listens for this `change` handler.

### F-09 — Info — no dark colours

`app.css` handles `prefers-reduced-motion` (`441`) and `prefers-contrast: more` (`446`). It has no `prefers-color-scheme`. A phone set to dark mode gets the light page (`#f3eee4` background, `#1c1915` text). Text contrast on that pair is 15.14:1, so the page stays readable. It will look like a bright sheet in a dark room.

Recommendation: one `@media (prefers-color-scheme: dark)` that remaps the seven colour variables in `:root` (`app.css:4`–`10`: `--bg`, `--bg-raised`, `--ink`, `--ink-soft`, `--line`, `--focus`, `--paper`) and checks the same pairs still clear 4.5:1. Keep the player as light text on a dark bar, or swap it deliberately and update `.player :focus-visible`. Optional for the demo. Wait, with F-10.

Covered today: no test reads `prefers-color-scheme`.

### F-10 — Info — the card edge is faint

`--line` `#d9d0c2` on `--bg` `#f3eee4` is 1.32:1 (`app.css:8` and `265`). The card fill on the page is 1.11:1. WCAG 1.4.11's 3:1 line applies when the edge is the only thing that identifies a control. The play button and the inputs have their own `#1c1915` borders, which pass. The card edge is grouping. `prefers-contrast: more` already sets `--line` to `#1c1915` (`446`–`452`).

Recommendation: only if a sighted pass on a phone says the cards dissolve into the page, darken `--line` toward `#6b645b` or similar until the ratio on `#f3eee4` is at least 3:1. Not required for the demo.

Covered today: no contrast test.

## Still open from the W3 phone QA

These are unchanged on `8d46f14` and on `6d07f64` (`app/static` is the same bytes). Details and the original measurements are in `reports/W3-MOBILE-UX-QA.md`. They are not new findings.

| W3 item | Still true because | Severity there |
| --- | --- | --- |
| 9 | Footer and credit links are inline. `.credits a` and `.colophon` set no `min-height` (`app.css:355`–`370`). Line box about 22px. WCAG 2.5.8's inline exception is why it was deferred. | Low |
| 10 | Held-audio caption can grow the fixed bar past the `8.5rem` bottom padding. F-04 makes that worse if cover is turned on without growing the padding. | Low |
| 11 | A whitespace-only submit sets "Enter a question." and leaves the previous cards (`app.js:650`–`653`). | Low |
| 12 | Under 800px the church column is after every Wesley card (`app.css:237`–`253`). The status line does name the church first. | Low |
| 13 | `.mark` about 12.5px, `.kicker` about 13.6px. Both pass contrast (table above). | Info |

## Checked and sound

- One `h1`. Card titles are `h3`. Column titles are `h2`. The credits heading is an `h2`. No level is skipped on the way down.
- `lang="en"` on the document (`index.html:2`). Passage text is English.
- Zoom is allowed. Inputs and selects are `font-size: 1rem`, which is the usual way to keep iOS Safari from zooming on focus. `test_viewport_allows_zoom` pins the meta.
- `enterkeyhint="search"` and `required` on the question (`25`).
- Buttons are buttons and links are links, including YouTube versus the archive player.
- Classic empty, error, fallback, and low-confidence copy is plain language and is written into a polite live region. A 5xx returns the generic sentence and does not append the server's `error` string (`455`).
- `textContent` is how result text gets into the page (`app.js:3`, `11`). The probed markup-style risk is unchanged from the existing escaping tests.
- Reduced motion turns off the spinner and the smooth scroll (`441`–`444`).
- `prefers-contrast: more` collapses soft grey to the ink colour (`446`–`452`).
- First load is 38523 bytes, same origin, no third-party request until Play.
- At 360px and 412px the stylesheet is the single-column layout. Author-drawn controls other than the inline footer links and the native audio widget are given a 44px minimum height.

## Prioritized fixes

Four PRs, each with a test, plus two held items. Sequencing: PR-A any time (it shares no files with B-D and must not move any parity hash); then PR-B -> PR-C -> PR-D, merged serially, each rebased on the one before and restating parity on its own final head, because all three move the `/static/app.js` hash (PR-D also `/`), and PR-B and PR-D both re-pin the same `app.js`/`index.html` line cites in `docs/DEMO-SCRIPT.md:28`, `:42`, `:123` and `docs/SUBMISSION-DRAFT.md:34`, so PR-D goes last.

1. **PR-A: F-01 + F-06, server 503 pages.** Both live in `app/server.py` and share one constant page.
   - The page gets a viewport, an `<h1>`, the sentence, and a refresh of 5 s or more, or a Try again link to `/`.
   - It stays constant: no request bytes, no script, and no external URL. Keep the negative assertions in `tests/test_html_503.py`.
   - `Retry-After: 1` may stay for API clients. If the refresh is lengthened while that header stays 1, update the coupling comment at `app/server.py:2915`–`2916`, the "meta refresh of the same 1 second" sentence at `docs/DEPLOY.md:628`, the pinned `content="1"` at `tests/test_html_503.py:198`, and the `content="{retry-after}"` assertion at `tests/test_html_503.py:199`.
   - F-06: serve that same page for a disabled `GET /` and `HEAD /` with a browser `Accept`. Keep `/healthz` (`{"ok": false, "disabled": true}`) and `/api/*` on JSON.
   - Keep the kill-switch tests green. `tests/test_deploy.py:229` asserts a disabled `/api/search` body of `{"error": "unavailable"}`. `tests/test_exposure.py:577`, `:1190`, and `:1330` assert that same JSON body on the in-flight and reconnect 503s. Add an HTML-on-`/` test and a JSON-on-`/api/search` test. The kill switch must stay tested.
   - Rule 4: re-pin every `docs/DEPLOY.md` cite the edit moves, and the `CITED` pins in `tests/test_deploy_alerts.py`.
   - Real client: headless Chromium at a phone viewport against a loopback over-cap server.
   - Parity: PR-A shares no files with B-D and must not move any parity hash. These paths are not probed by the #97 harness (normal mode, no over-cap).
   - F-06 may be a separate PR immediately after F-01. It must reuse F-01's constant page.
2. **PR-B: F-02 as corrected above, the 44px audio height, and F-11.**
   - Name the audio with `aria-labelledby="now-playing"`.
   - Announce only the held-audio sentence, in a live region. An optional focus move only in that branch (`app.js:199`–`203`).
   - Fix the name so it starts with the visible text (WCAG 2.5.3). Example: `Play from 0:01:32, sermon 1`.
   - `audio { min-height: 44px }`.
   - No `aria-pressed`. A second press calls `playClip` again (`app.js:291`–`293`) and does not pause, so a pressed state would misstate the control. Leave the `is-playing` outline visual-only, or use `aria-current="true"`.
   - No spoken time in the name.
   - Do not make `#now-playing` itself `aria-live` (it would announce the caption over the sermon audio on every Play).
   - Extend the `tests/test_mobile_ux.py` Deno check: accessible name, live membership of the held-audio sentence, and label-in-name.
3. **PR-C: F-03.** Write the side-by-side notes into `.notices`. Keep the `tests/test_app_js.py:674` assertion that the status is not the banner, since the `#status` composition does not change. After `showSides`, `#note` carries `<side heading>: <fallback note>` and `#confidence` carries `<side heading>: <confidence note>` (the latter only when that side's results are shown); both are visible and inside `.notices`, and no column node carries `aria-live`.
4. **PR-D: F-05 + F-07.** `<main id="main">` wraps the form, the examples, and `#results-section` (`index.html:22`–`83`), not only the results, and the skip link points at `#main`. `aria-busy` goes on `#results` and `#sides`, with `#status` left in place and `is-loading` kept on `#results-section`. Update the `tests/test_app_js.py:380` and `:382` `aria-busy` assertions so they name those two nodes, and add a `<main>` and skip-target assertion. Re-pin the `index.html` cites in `docs/DEMO-SCRIPT.md:28`, `:42`, `:123` and `docs/SUBMISSION-DRAFT.md:34`.

**Held: F-04.** A real-iPhone check comes first. The `env()` term is dead code until `viewport-fit=cover` is on, and turning cover on is what would introduce the overlap. Only after that check, add cover plus the padding.

**Held: F-08.** Patrick's product call. The auto-search is deliberate demo UX for side by side. It is a change of content, not a 3.2.2 failure, and it is not a queued fix.

**Wait:** F-09 and F-10.

### Parity with the harness landed in #97

`docs/PARITY.md` is on `origin/main`. The `http` and `no-church` sets include the raw bytes of `/` and `/static/app.js` (`docs/PARITY.md:76`). PR-B, PR-C, and PR-D all move the `/static/app.js` hash, and PR-D also moves `/`, so each moves those two sets by design. They are merged serially, PR-B then PR-C then PR-D, each rebased on the one before and restating parity on its own final head. Each of those PRs must:

- report a record-level diff of the probes that moved: `/static/app.js` for PR-B, PR-C, and PR-D, and also `/` for PR-D, with the new sha256 of each equal to `git show <head>:app/static/<file> | sha256sum`;
- show every other set unchanged;
- re-baseline the refs in `docs/PARITY.md` on that PR's own final head. #97 has landed, and this tree has the page.

An `app.css`-only edit does not move those hashes. PR-A shares no files with B-D and must not move any parity hash, so it can land any time. An F-04 change that edits `index.html` would move `/` as well.

## Limits

No phone, no Chromium, no VoiceOver, and no TalkBack. Overlap of the home indicator, the real size of the native audio controls, and whether a screen reader drops one of two polite live regions were not observed. Announcement findings are the accessible names and live-region membership in the DOM. The synthetic index had one chunk, so a low-confidence response that still contains passages was not returned live; that path is the code in `describeResponse` (`377`–`384`) and the existing Deno fixture. The probe's hybrid request did return a real fallback `note`, which is the side-by-side case F-03 cites.

The parity harness landed in #97 hashes the raw bytes of `/` and `/static/app.js` inside the `http` and `no-church` sets (`docs/PARITY.md:76`). PR-B, PR-C, and PR-D move the `/static/app.js` hash, and PR-D also moves `/`, so each moves those two sets by design. The prioritized fix list records what each of those PRs must show.

## PR BODY

R3 of the accessibility and phone UX audit (PR #100). Report text only. No file under `app/`, `src/`, `tests/`, or `docs/` is edited. `origin/main` `ebc058de95a3c8b6eb3ef51332702c3f8993c3be` was merged as `f22270f13ff7bbd3716a4ce91f158ba51d36595e` (no conflicts). Cited files changed since `3aef7ca`: `docs/PARITY.md` (added), `tests/cache_guard.py`, `tests/test_cache_guard.py`, `tests/test_cache_guard_immutable_fuzz.py`, `tests/test_parity_hash.py` (added), and `tests/test_reject_method_slot.py`. `app/server.py`, `app/static/*`, `docs/DEPLOY.md`, `docs/DEMO-SCRIPT.md`, and `docs/SUBMISSION-DRAFT.md` are unchanged, so no `docs/DEPLOY.md` cite was re-pinned and `tests/test_deploy_alerts.py` is untouched.

Severities: F-01 High; F-02 and F-03 Medium; F-04 Low; F-11 Low (new, WCAG 2.5.3 Label in Name); F-05, F-06, F-07 Low; F-08, F-09, F-10 Info. F-08 is Patrick's product decision. The fix list is four PRs (PR-A F-01+F-06, PR-B F-02 as corrected plus the 44px audio height and F-11, PR-C F-03, PR-D F-05+F-07), with F-04 and F-08 held and F-09 and F-10 waiting. F-02 does not set `aria-pressed`, does not put a spoken time in the name, does not move focus on every Play, and does not make `#now-playing` itself live.

No tests were run. `find /cache -xdev -printf '%p\t%s\t%T@\n' | sort` before the edit and after the report text was written: 132824 lines both times, sha256 `3ca707d7aba4f2aa682a6497f9e481bad4c8087d9304142444a746ace64bca64`, no path, size, or mtime difference. No cache env var was pointed at `/cache`.

R3 content head: `447f6afa433721555451590451cdeef2874824f0` (parent of the commit that records this sha).

`git diff --stat origin/main...HEAD`:

```
 reports/W5-A11Y-MOBILE-AUDIT.md | 427 ++++++++++++++++++++++++++++++++++++++++
 1 file changed, 427 insertions(+)
```

## R2

CTO r1 CONDITIONAL on PR #100 at `3877f7ed249ba9095de51921c23ccb4b48555d68`. This round edits only `reports/W5-A11Y-MOBILE-AUDIT.md`. `origin/main` is `3aef7cacf1907fa7ed57a5251b3894dec6618f00`. It was merged as `01a125c3ff65dcb1af2c0e9b211a278f141a683d` (parents `3877f7e` and `3aef7ca`). `git merge` reported no conflicts. No `--ours` or `--theirs`. The files this report cites (`app/server.py`, `app/static/app.js`, `app/static/app.css`, `app/static/index.html`, `docs/DEPLOY.md`, `tests/test_html_503.py`, `tests/test_app_js.py`, `tests/test_mobile_ux.py`, `tests/test_deploy.py`, `tests/test_exposure.py`, `reports/W3-MOBILE-UX-QA.md`) are the same blob on this branch and on `3aef7ca`. Every cite below was read on that tree. None had moved, so nothing in `docs/DEPLOY.md` or `tests/test_deploy_alerts.py` was re-pinned. `docs/PARITY.md` is not on `3aef7ca`.

| Item | Where it now sits |
| --- | --- |
| MF1. Both reachability cases, the accept-thread 503 (no handler, no rate-limit bucket), the bounded 1 s retry, and the three cites the F-01 fix must update | `:153`. The same fix cites are in the recommendation at `:172` and in PR-A at `:328` |
| MF2 (a). No `aria-pressed`. A second press calls `playClip` (`app.js:291`–`293`) and does not pause | Recommendation `:199`. PR-B bullet `:340`. The audio section states the same fact at `:133` |
| MF2 (b). No spoken time in the name. The name must start with the visible text. New Low finding for WCAG 2.5.3 | `:193`, recommendation `:199`, finding F-11 at `:203`–`:209`, table row `:146`, PR-B `:338` and `:341` |
| MF2 (c). Announce the held-audio sentence. Move focus only in that branch (`app.js:199`–`203`), if at all | `:199` and PR-B `:337` |
| MF2 (d). Do not make `#now-playing` itself `aria-live` | `:199` and PR-B `:342` |
| MF2, F-04 downgraded to Low. Dead code until cover is on. Real iPhone check first | Table `:142`. Heading `:225`. Held paragraph `:233`. Fix item `:347` |
| S1. F-08 is Info and Patrick's call. In-place results are a change of content, not a 3.2.2 failure | Table `:147`. Heading `:269`. Wording `:273`. Held item `:349` |
| S2. #97 hashes `/` and `/static/app.js`. Edits to `index.html` or `app.js` move those hashes by design | Limits `:367`. The PR obligations are `:353`–`:361` |
| N1. `resetState` clears `#note` at `app.js:487` and `#confidence` at `488` | `:215` |
| N2. The 103px figure is W3 item 2 (`reports/W3-MOBILE-UX-QA.md:43`). Item 10 is the 169px figure | `:100` |
| N3. `:root` has seven colour variables (`--bg`, `--bg-raised`, `--ink`, `--ink-soft`, `--line`, `--focus`, `--paper`) | `:283` |
| N4. `PREROLL_S` is `app.js:44`. `46`–`50` is `playStart` | `:129` |
| N5. CSP cite `app/server.py:206`–`219` left as written. `219` is `frame-ancestors`. The closing paren is `220` | `:51` |
| Severity table. F-01 High; F-02 and F-03 Medium; F-04, F-05, F-06, F-07 Low; F-11 Low; F-08, F-09, F-10 Info | `:137`–`:149` |
| Fix list. Four PRs and two held items. PR-A any time (no parity-hash move); then PR-B, PR-C, PR-D serially. PR-C keeps the status-is-not-the-banner assertion and adds the `.notices` assertions. PR-D wraps `index.html:22`–`83` in `<main>` and puts `aria-busy` on `#results` and `#sides` | `:321`–`:361` |
| PR BODY synced to those severities and that fix list | `:369` |

No suite was run. Cache snapshots are in the PR BODY above.

## R3

CTO r2 CONDITIONAL at `23093fa1b1a4e6a64c8b5e2ccaa8b4b60be39263`. This round edits only `reports/W5-A11Y-MOBILE-AUDIT.md`. `origin/main` `ebc058de95a3c8b6eb3ef51332702c3f8993c3be` was merged as `f22270f13ff7bbd3716a4ce91f158ba51d36595e` (no conflicts). No `--ours` or `--theirs`. `git diff --stat 3aef7ca..origin/main -- app/ docs/ tests/` shows `docs/PARITY.md` (added), `tests/cache_guard.py`, `tests/test_cache_guard.py`, `tests/test_cache_guard_immutable_fuzz.py`, `tests/test_parity_hash.py` (added), and `tests/test_reject_method_slot.py`. `app/server.py`, `app/static/*`, `docs/DEPLOY.md`, `docs/DEMO-SCRIPT.md`, and `docs/SUBMISSION-DRAFT.md` did not change. Nothing in `docs/DEPLOY.md` or `tests/test_deploy_alerts.py` was re-pinned.

| Item | Where it now sits |
| --- | --- |
| MF3 (a). PR-A any time (no shared files, no parity-hash move); then PR-B -> PR-C -> PR-D, merged serially, each rebased on the one before and restating parity on its own final head, because all three move the `/static/app.js` hash (PR-D also `/`) and PR-B and PR-D re-pin the same cites | Sequencing `:323`. PR-A parity bullet `:333`. Parity obligations `:353`–`:361` |
| MF3 (b). Keep `tests/test_app_js.py:674` ("status is not the banner"). After `showSides`, `#note` is `<side heading>: <fallback note>` and `#confidence` is `<side heading>: <confidence note>` (only when that side's results are shown); both visible and inside `.notices`; no column node carries `aria-live` | Recommendation `:221`. PR-C `:344` |
| MF3 (c). `<main id="main">` wraps the form, the examples, and `#results-section` (`index.html:22`–`83`), not only the results. The skip link points at `#main`. F-05 is `aria-busy` on `#results` and `#sides`, with `#status` left in place and `is-loading` kept on `#results-section`. PR-D re-pins `docs/DEMO-SCRIPT.md:28`, `:42`, `:123` and `docs/SUBMISSION-DRAFT.md:34` | F-05 recommendation `:241`. F-07 recommendation `:265`. PR-D `:345` |
| Nit 1. Split into two bullets: "No spoken time in the name." and "Do not make `#now-playing` itself `aria-live`" | `:341` and `:342` |
| Nit 2. Empty-proxy (4-connection) case: a peer already at its cap may take its own oldest idle keep-alive once that socket has been quiet for 1 second (`docs/DEPLOY.md:628`) | `:153` |
| Nit 3. F-11 moved into the Low group, after F-07 and before F-08 | Table `:146` |
| Nit 4. At 32-slot saturation a page load on the `/healthz` reserve gets the handler's JSON 503 (`app/server.py:2261`–`2268`), as does the per-key slot-busy 503 (`app/server.py:2280`–`2291`). Only the accept-thread over-cap path serves HTML | `:153` |

Cites read on merged `origin/main` `ebc058de95a3c8b6eb3ef51332702c3f8993c3be`, same lines as on `b1a2b24`: `app/server.py:2250`–`2255` is the kill switch (`{"error": "unavailable"}` except `/healthz`, which stays `{"ok": false, "disabled": true}`); `:2261`–`2268` is `_reserved` and not health, JSON `{"error": "unavailable"}`; `:2280`–`2291` is `acquire_slot` refused, the same JSON; `docs/DEPLOY.md:628` includes "A peer already at its cap may take its own oldest idle keep-alive once that socket has been quiet for 1 second"; `app/static/index.html:22` opens `<form id="search-form"` and `:83` closes `</section>` (`#results-section`); `tests/test_app_js.py:674` is the label "status is not the banner"; `docs/DEMO-SCRIPT.md:28` cites `app.js:217-235`, `:312-313`, and `index.html:63-75`; `:42` cites `index.html:78` and `app.js:338`; `:123` cites `index.html:75`; `docs/SUBMISSION-DRAFT.md:34` cites `app.js:217-235`, `:312-313`, and `index.html:75`; `docs/PARITY.md:76` says the `/` and `/static/app.js` byte hashes are in `http` and `no-church`.

No suite was run. Cache snapshots are in the PR BODY above.
