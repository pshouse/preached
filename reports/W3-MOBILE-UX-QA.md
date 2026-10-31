# W3-MOBILE-UX-QA: first-time-user QA of the phone web page

Branch `fix/w3-mobile-ux` from `origin/main` (`bbdb1ba`). Frontend only: `app/static/index.html`, `app.css`, `app.js`, plus `tests/test_mobile_ux.py` and this report. `app/server.py`, `docs/DEPLOY.md`, `docs/SUBMISSION-DRAFT.md` and `docs/DEMO-SCRIPT.md` are untouched.

## 1. What was done

Audited the page as a first-time visitor on a 375 × 812 phone screen, fixed eight problems, deferred four low ones (listed below), and pinned the fixes with 8 new tests.

**How the audit ran.** `uv run app/server.py --port 8765` (loopback, default `/cache/index/wesley.sqlite`, ONNX hybrid) drove headless Chromium through the DevTools protocol. A throwaway Deno script, kept outside the repo, set up the browser:

- device emulation 375 × 812, DPR 2, `mobile: true`, touch on
- for each scenario: load, measure, screenshot

Measurements per scenario:

- `scrollWidth` vs `clientWidth` (horizontal scroll)
- every `a`, `button`, `input`, `select`, `audio` and `[tabindex]` smaller than 44 × 44 px
- any text under 14 px
- any element wider than the viewport
- the status line and the text of the first three cards

Scenarios:

- home page
- `?q=worry`
- `?q=how do I know I'm forgiven`
- a nonsense query (`zxqv blorp fnarg`, which abstains)
- a whitespace-only query
- a 360-character `?q=` deep link
- a 320-character query set directly on the input
- tapping a "Try one" chip
- `fetch` rejected (network error)
- `fetch` returning 500
- `fetch` delayed 20 s (slow)
- side by side (`view=side`; the church column is empty because no church index is configured)
- tapping Play, then reading the `<audio>` state

### Issues found

| # | Issue | Where | Severity | Status |
|---|---|---|---|---|
| 1 | After tapping Search or a chip on a phone, **nothing visible changes**. The status line and results start ~720 px down, below the form and chips, and the keyboard stays open. A first-time user thinks the button did nothing. | `app.js` `runSearch` / submit | High | Fixed |
| 2 | The **fixed player bar shows before anything is playable** ("Choose Play on a passage." + an empty 0:00 audio control, 103 px). On first load it covers the fourth chip ("Romans 8:16") and 13 % of the screen. | `index.html` `#player-bar` | Medium | Fixed |
| 3 | **Low-confidence banner not announced** to screen readers. Only `#status` is a live region, so a screen reader hears "10 passages." and never the "Low confidence…" warning (or the BM25-fallback note). | `index.html` `#confidence`, `#note` | Medium | Fixed |
| 4 | **"Read this sermon on CCEL" tap target is 219 × 19 px**, on every card. | `app.css` `.text-link a` | Medium | Fixed |
| 5 | A `?q=` deep link longer than 300 characters shows a **raw server error**: "Search failed: q must be 1 to 300 characters." | `app.js` `init` | Low | Fixed |
| 6 | The held-audio caption runs two sentences together: "…(LibriVox volunteer) Press play on the bar…". | `app.js` `playClip` | Low | Fixed |
| 7 | The skip link is 40 px tall (keyboard-only, visible on focus). | `app.css` `.skip` | Low | Fixed |
| 8 | The YouTube watch link opens a new tab without saying so to screen readers. | `app.js` `renderCard` | Low | Fixed |
| 9 | Footer credit links (LibriVox, Internet Archive, CCEL) are 18–40 px tall. | `index.html` footer | Low | Deferred: inline links in a sentence, covered by the WCAG 2.5.8 inline exception. Padding them would break the paragraph. |
| 10 | When the browser holds autoplay, the caption wraps to 4 lines and the bar grows to 169 px. That is taller than `.wrap`'s 8.5 rem bottom padding, so the last lines of the footer can sit under the bar until it is dismissed. | `app.css` `.player` | Low | Deferred: only in the held-audio case, only the footer is affected, and there is no dismiss control. A real fix (shorter caption or dynamic padding) is a design call. |
| 11 | A whitespace-only query shows "Enter a question." above the previous results, which stay on screen. | `app.js` submit | Low | Deferred: the `required` attribute already blocks a truly empty submit with the browser's own prompt. Whitespace-only is an edge case, and clearing a person's results on a typo is arguably worse. |
| 12 | In side by side on a phone, the church column comes after all 5 Wesley cards. | `app.css` `.sides` | Low | Deferred: this is the documented phone layout (stacked columns). The status line at the top already reads "…Your church. Nothing from your church yet." A jump link would be a redesign. |
| 13 | The `.mark` "PREACHED" wordmark is 12.5 px and the card kicker 13.6 px. | `app.css` | Info | Not changed: uppercase, letter-spaced labels, not body text. Body text is 16 px and the quote 16.8 px. |

### Checked and found fine (no change)

- **Horizontal scroll:** none at 375 px in any scenario (`scrollWidth == clientWidth == 375`), including long excerpts and side by side.
- **Zoom:** viewport is `width=device-width, initial-scale=1`, and pinch zoom is not disabled. Inputs and selects are 16 px, so iOS Safari does not zoom on focus.
- **Tap targets:** inputs, selects, Search, chips, Play, Hide low-confidence and Try again are all ≥ 44 px tall.
- **States:**
  - Loading shows "Searching the sermons." with a spinner (no spinner under reduced motion), and `aria-busy` on the results section.
  - Empty shows "Nothing found in these sermons. Try other words, or a Bible verse…".
  - Abstain shows "10 passages." plus the dashed low-confidence banner and a "Hide low-confidence results" toggle.
  - Network error shows "Could not reach the search. Check your connection and try again." plus Try again.
  - A 500 shows "The search had a problem on our side…" with the server's detail hidden.
  - A slow (20 s) response stays in the loading state. A new search aborts the old one.
- **Rule 2 (cite sermon + timestamp, playable):** every card on the real queries shows "Sermon N · wesley-NNN", the title, scripture, a range (e.g. `0:01:32–0:02:25`) and "Play from 0:01:32", with `aria-label="Play sermon 41 from 0:01:32"`.
- **Player jump:** tapping Play on the first `worry` hit (`start_s` 92.02) loaded `…_42_wesley_64kb.mp3#t=91.27` and set `currentTime` to 91.27 (start minus the 0.75 s pre-roll). Headless Chromium then held the audio (`paused: true`) under its autoplay policy, and the "Press play on the bar…" fallback appeared as designed.
- **Privacy rule (flagged cards):** an `audio_withheld` hit renders "Text only: audio is withheld for this passage." with no times, no Play button and no recording or watch link, even if the hit still carries an `audio_url`. The real index had no flagged Wesley passages, so this was checked in the Deno fake DOM (new test), not live.
- **Rule 1 (no AI speaking for the preacher):** all page copy describes the tool ("Preached finds passages; it never writes or paraphrases"). Cards contain only Wesley's text, metadata and the reader credit. No summarising or answer-style copy anywhere.
- **Keyboard and labels:**
  - The form has `role="search"`. `q`, `mode` and `view` each have a `<label for>`. Enter submits (`enterkeyhint="search"`).
  - The results section is labelled by a visually hidden h2. Side-by-side columns get h2s and cards get h3s.
  - The hide toggle keeps focus and `aria-pressed`.
  - Focus order follows the DOM: skip link, question, mode, view, Search, chips, status actions, cards.

### Fixes (smallest change each)

1. `revealResults()` (`app.js`): when a search starts and the results section's top is not in the upper 60 % of the viewport, it calls `scrollIntoView({block: "start"})`. There is no scroll when it is already on screen (wide screens, Try again). `.results-section` gets `scroll-margin-top`. On submit from the question box, the input is blurred so the phone keyboard closes. Re-measured: after tapping a chip, "10 passages.", the banner and the first card are on screen.
2. `#player-bar` starts `hidden`. `playClip` shows it on the first Play, inside the click handler, so `play()` is still a user gesture. Re-measured: player height 0 at load, 169 px after Play (held case).
3. `#note` and `#confidence` moved into `<div class="notices" aria-live="polite">`, right after `#status`. No JS change, and `#status`'s text is unchanged (existing tests pin it). Visual change: the fallback note now sits under the count line instead of above it.
4. `.card .text-link a` gets `display: inline-flex; min-height: 44px`. Re-measured: no card link under 44 px.
5. `MAX_QUERY = 300` (same as the input's `maxlength` and the server's check). A deep-link `?q=` is cut to that length before searching. Re-measured: a 360-character link shows results.
6. Caption separator `". Press play…"`.
7. `.skip` gets `min-height: 44px`.
8. The watch link gets `aria-label="Watch on YouTube at H:MM:SS (opens in a new tab)"`.

## 2. How to run it

```
uv run python -m unittest tests.test_mobile_ux -v      # new tests (Deno part skips without deno)
uv run python -m unittest discover -s tests            # full suite
uv lock --check
uv run app/server.py --port 8765                       # then open http://127.0.0.1:8765/ in a phone-sized window
```

## 3. Results and numbers

- Full suite: **979 tests, OK, 0 skipped** (971 on `bbdb1ba` + 8 new). `uv lock --check`: OK.
- New tests (`tests/test_mobile_ux.py`):
  - **Static (7):**
    - viewport meta present, zoom not disabled
    - labels, `role="search"`, `enterkeyhint`, `required`
    - banner and note inside a polite live region, not nested in `#status`
    - player bar starts hidden
    - 44 px minimum on the card link, Play, skip link and buttons; 16 px selects; `scroll-margin-top`
    - `MAX_QUERY` == input `maxlength` == server limit
    - no answer-style or speaking-for-the-preacher copy
  - **Deno fake DOM (1):**
    - a timed card cites sermon title + range and has one labelled Play
    - a flagged (`audio_withheld`) card has no play control, no recording or watch link and no time, and still names the sermon
    - the watch link announces the new tab
    - the player bar appears on Play and seeks to 91.27
    - `revealResults` scrolls only when the results are off screen
    - the held-audio caption reads as two sentences
- Mutation check: reverting the player-bar unhide, or the `audio_withheld` branch, makes `test_mobile_ux` fail.
- Live audit at 375 × 812 after the fixes: 0 px horizontal overflow in all scenarios. The only sub-44 px targets left are the three inline footer links (#9).

## 4. Open issues, risks, not checked

- **No real phone was used.** Everything above is Chromium emulation (mobile viewport, touch, DPR 2). Not verified:
  - iOS Safari and Android Chrome behaviour: keyboard closing on `blur()`, `env(safe-area-inset-bottom)` under the home indicator, native `<audio>` control size, and whether a real tap's `play()` starts audio (in headless it was held by autoplay policy, so the seek was checked, not the sound).
  - Media-fragment `#t=` support on iOS. `seekWhenReady` covers it in code, but it is untested on a device.
  - Screen-reader output (VoiceOver/TalkBack). The live-region change follows the usual pattern (children shown inside an always-present `aria-live` container), but I could not listen to it.
- Deferred items #9–#12 above.
- `MAX_QUERY` mirrors the server's 300-character limit by hand. The new test fails if the two drift.
- No server change was needed.

## 5. Dependencies added

None. The audit used the Chromium and Deno already on this machine, through a throwaway script outside the repo. The tests are stdlib `unittest` plus the existing optional Deno runner.

## 6. Follow-up: CTO should-fixes on PR #53 (`fix/w3-mobile-ux-2`)

Scope: `app/static/app.js`, `tests/test_mobile_ux.py`, this report, and the `MAX_QUERY` constant in `app/server.py`.

- **N1:** the summary said "fixed six, deferred five". The table has 8 fixed and 4 deferred (plus 1 info, not changed). Corrected in section 1.
- **S1:** the submit handler blurs the input only when `matchMedia("(pointer: coarse)")` matches (`isTouchScreen()`). On desktop the caret stays.
- **S2:** the deep-link cap is `capQuery()`: `Array.from(s).slice(0, MAX_QUERY).join("")`, by code point like the server, so an emoji is never cut into U+FFFD. `app/server.py` has a named `MAX_QUERY = 300`, used at the existing check and in its message. The pin test reads the constant from `server.py`, compares it with `app.js` and the input's `maxlength`, and requires `len(query) > MAX_QUERY`.
- **S3:** the Deno test dumps the whole withheld card (text, `href`, `src`, class, every attribute name and value, every `data-*`) for two hits (archive.org and YouTube `audio_url`). The only URL allowed is the hit's text `source_url`; the `audio_url`, `archive.org`, `youtube`, `.mp3` and `audio_url` must not appear anywhere. If `deno` is missing the behaviour class is skipped with the reason "SKIPPED, deno not installed: the withheld-card URL scan, the touch-only blur and the code-point query cap were NOT exercised". **A run without Deno does not test S1, S2 or S3.** This run had Deno.
- **S4:** behavioural tests in the Deno fake DOM run `init()`: submit blurs on a coarse pointer, does not blur on a fine pointer or without `matchMedia`; a 360-character ASCII link and a 360-emoji link are capped at 300 code points with no U+FFFD and no split pair; a short link is untouched.

### Mutant proofs (each applied alone, `tests.test_mobile_ux` run, then reverted)

| Mutant | Result |
|---|---|
| S1: drop `isTouchScreen() &&` (always blur) | FAIL: "desktop: input keeps focus on submit: got 1, want 0" |
| S2: `capQuery` uses `text.slice(0, MAX_QUERY)` | FAIL: "emoji link capped by code point: got 150, want 300" |
| S2: deep link not capped at all | FAIL: "ascii link capped: got 360, want 300" |
| S2: server check back to literal `len(query) > 300` | FAIL: pin test, `len(query) > MAX_QUERY` not found |
| S3: `card.dataset.src = hit.audio_url` on the withheld card | FAIL: "flagged: only the text source URL is on the card" |
| S3: `card.setAttribute("data-a", hit.audio_url)` on the withheld card | FAIL: same |

The S1, S2 and S3 Deno checks are in one test method (`test_cards_player_and_scroll`), so a failure is identified by its message, not by a separate test name.

## 7. Follow-up: CTO #63 r1 changes

Scope: `tests/test_mobile_ux.py` and this report. `app/static/app.js` and `app/server.py` are unchanged.

- **MF1:** `submitFrom()` reassigned `window.matchMedia` on every call, so the old "no matchMedia" check ran with a fake present. `submitFrom(null)` now deletes `window.matchMedia` and installs nothing; the test also asserts `"matchMedia" in window` is false, and any throw fails the Deno run. Mutant proof: with `isTouchScreen` changed to `!window.matchMedia || window.matchMedia("(pointer: coarse)").matches` (blur when matchMedia is missing), the test FAILS with "no matchMedia: input keeps focus on submit: got 1, want 0". `app.js` was then restored byte for byte (`git diff 3d59132 -- app/static/app.js` is empty).
- **S1:** set `PREACHED_REQUIRE_DENO=1` in review and deploy runs. With it set and no `deno` on PATH, the suite fails (`RequireDenoTests` and `test_cards_player_and_scroll`) instead of skipping. Without it, a missing Deno still skips, and **that run does not test the withheld-card URL scan, the touch-only blur or the code-point cap.** Checked both ways: no deno on PATH gives a failure with the variable and a skip without it; the suite passes with deno and the variable set.
- **S2 (no code change):** the 2 KiB URL cap (`MAX_TARGET`, `app/server.py:223`) binds before `MAX_QUERY` for non-ASCII input. 300 emoji percent-encode to about 3.6 KB, so `GET /?q=<300 emoji>` returns 414 before `app.js` runs. The 300 code-point cap in `capQuery()` is only reached by shorter deep links.
- **Nit:** `maxlength="300"` counts UTF-16 code units, so the input box stops at 150 emoji. The client is stricter than the server's 300 code-point cap.
