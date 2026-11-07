# W5-A11Y-PR-B-F02-F11: a named, quiet audio player (F-02) and Label in Name on Play (F-11)

Task id 99-XX4-PR-B-F02-F11 (parked grok taskdef 49-W5-A11Y-PR-B-F02-F11). Branch `fix/w5-a11y-player-name`, worktree `/work/preached/.worktrees/fix-w5-a11y-player-name`, base `origin/main` `2c8936583d3939ea5a8e5ae39c2af6eb62d7cbac`. The worktree's `git status` was clean before any edit.

## 1. What was done

**Pins re-verified on the base.** On `2c89365`, `app/static`, `tests/test_mobile_ux.py`, `tests/test_app_js.py`, `docs/DEMO-SCRIPT.md` and `docs/SUBMISSION-DRAFT.md` are byte-identical to `b1a2b24` (`git diff --quiet`). The sha256 values match the brief: `app.js` `0e21b3b3…6dac62`, `index.html` `ec6bcef6…9ddd86b`, `app.css` `06c9cb2d…f727525`. I read every line the brief pins, and each one held, so no adaptation was needed.

**`app/static/index.html`**
- `:96` (new, after the blank `:95`, outside `.wrap` and outside the bar): `<p id="player-announce" class="visually-hidden" role="status" aria-live="polite"></p>`. It has no `hidden` attribute and no text, and uses the existing `.visually-hidden` class with no new CSS.
- `:100` `<audio id="player" controls preload="none" aria-labelledby="now-playing">`.
- `#now-playing` (`:99`) is unchanged: no `aria-live`, `role` or `aria-atomic`. Lines `1`–`95` are byte-identical to main.

**`app/static/app.js`**
- `:182`–`:184`: `var HELD_AUDIO = "Press play on the bar if the browser held the audio.";`, with a two-line comment, placed above `playClip`.
- `playClip` `:186`–`:217`: on every call, `:194`–`:195` look up `#player-announce` and, behind `if (announce)`, set its text to `""` before `play()`. Inside the `catch`, after the token guard (`:208`), the held caption is `caption + ". " + HELD_AUDIO` (`:209`–`:210`), so the text is byte-identical to before, and `:211` `if (announce) announce.textContent = HELD_AUDIO;`. The success path announces nothing. There is no `.focus()`, `aria-pressed` or `aria-current`.
- `renderCard` `:296`: `button.setAttribute("aria-label", "Play from " + playLabel + ", " + sermonName);`. The visible text (`:293`), `sermonName` (`:295`), the caption and the watch link are unchanged.

**`app/static/app.css` `:394`**: `.player audio { width: 100%; min-height: 44px; }`, kept on one line, so no later `app.css` line moves.

**`tests/test_mobile_ux.py`** (the only test module with assertion changes; `tests/test_app_js.py` is untouched)
- New static test `PhonePageStaticTests.test_player_is_named_and_quiet`. It checks `aria-labelledby="now-playing"` on `#player`, that `#now-playing` has no `aria-live`/`role`/`aria-atomic`, and that `#player-announce` is a `p` with `role="status"`, `aria-live="polite"`, `class="visually-hidden"` and no `hidden`. It also checks that none of `player-bar`, `player-inner`, `results-section`, `notices` or `status` is among its parents, and that `min-height: 44px` is in `.player audio`. The existing `:88`, `:96`, `:99` and `:101`–`:104` are unchanged and green.
- `FAKE`: `player-announce` added to the ids, and `focus` now counts calls per node.
- `CHECKS`:
  - The play name is `"Play from 0:01:32, sermon 41"` with `indexOf(textContent) === 0`.
  - A new `sermon_number: null` card gives `"Play from 0:01:32, Wandering Thoughts"`, also a prefix match.
  - The existing `setTimeout` now chains four nested `setTimeout(…, 0)` stages: held, allowed, stale hold and no announcer, exactly as the brief specifies. `console.log("ok")` runs only at the very end.
  - Every stage checks that the button has no `aria-pressed` (and, as an extra, no `aria-current`) and that `audio`, `#player-bar`, `#now-playing`, `#player-announce` and the Play button have no focus calls.

**Re-pinned doc cites** (line numbers only): `docs/DEMO-SCRIPT.md:28`, `:42` and `docs/SUBMISSION-DRAFT.md:34` (table in §3).

**Parity pins**: #97 has merged, so `tests/test_parity_hash.py` `PINNED` and `PINNED_NO_WHY` were re-pinned, for `http` and `no-church` only (§3). `docs/PARITY.md` is unchanged, because my run is on the synthetic index, whose `index_version`/`model_sha256` don't match the page's tables (brief rule; see §4).

**Rulings followed**: no focus move at all; `is-playing` stays visual only (no `aria-pressed`/`aria-current`); the announcer sits outside the player bar and is in the tree from page load.

**Files not touched**: `app/server.py`, `tests/test_app_js.py`, `src/`, `search/`, `scripts/`, `eval/`, `docs/DEPLOY.md`, `tests/test_deploy_alerts.py`, `pyproject.toml`, `uv.lock`, `docs/PARITY.md`. **No file cited in `docs/DEPLOY.md` was edited, so DEPLOY cites and `CITED` pins are untouched**, and the full suite has zero `test_every_cited_file_line_holds_its_string` failures.

Commits: `c9a43d7` (code and tests), `cd33376` (doc cites), `897a5cf` (parity pins), then this report.

## 2. How to run it

All variables point at subdirectories of one `mktemp -d` (`/tmp/prb.FjLy` on this run). `PREACHED_GUARD_REAL_SRC` was unset.

```sh
S=$(mktemp -d)
export PREACHED_CACHE=$S/cache PREACHED_ONNX_DIR=$S/onnx HF_HOME=$S/hf HF_HUB_CACHE=$S/hf/hub \
  HUGGINGFACE_HUB_CACHE=$S/hf/hub DENO_DIR=$S/deno XDG_CACHE_HOME=$S/xdg TORCH_HOME=$S/torch \
  UV_CACHE_DIR=$S/uvcache UV_PYTHON_INSTALL_DIR=$S/uvpy HOME=$S/home \
  ORT_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 PREACHED_REQUIRE_DENO=1
unset PREACHED_GUARD_REAL_SRC
# focused (project env in $S/venv)
UV_PROJECT_ENVIRONMENT=$S/venv uv sync --frozen
UV_PROJECT_ENVIRONMENT=$S/venv uv run --frozen python -m unittest tests.test_mobile_ux tests.test_app_js
# full suite: a /tmp worktree at HEAD with an in-tree .venv (test_deploy/test_shutdown use ROOT/.venv)
git worktree add --detach $S/full HEAD && cd $S/full
UV_PROJECT_ENVIRONMENT=$S/full/.venv uv sync --frozen
UV_PROJECT_ENVIRONMENT=$S/full/.venv uv run --frozen python -m unittest discover -s tests
```

The mutant runner, parity record dumper and CDP driver were local, uncommitted scripts under the temp dir. Mutants ran in a detached `/tmp` worktree, so every overwrite was under `tempfile.gettempdir()` (asserted before each write).

## 3. Results

Host `preached-sandbox` (12th Gen Intel Core i9-12900K), Python 3.12.16, uv 0.13.6, deno 2.9.8, Chromium 155.0.8059.84.

**Focused** (worktree, HEAD `897a5cf`): `Ran 20 tests in 0.445s, OK`. No skips. `RequireDenoTests` passed, and `test_cards_player_and_scroll` and every Deno test in `test_app_js` ran.

**Full suite** (`/tmp` worktree at `897a5cf7407d0b44112d8b9f6962f285680d0ae3`): `Ran 1194 tests in 276.167s, OK (skipped=15)`. A verbose rerun gave `Ran 1194 tests in 272.889s, OK (skipped=15)` and listed the 15 skips. All 15 are real-data skips: 3 `test_child_home_guard` (`PREACHED_GUARD_REAL_SRC` unset), 6 `test_embed_backend` and 2 `test_onnx_pin_repro` (no ONNX/Granite in the temp cache), and 1 each in `test_coverage`, `test_deploy_regex` (infra yaml absent), `test_eval_leak` and `test_shutdown`. **No Deno test skipped.** An earlier full run on the same sha had 1 failure and 1 error, both caused by me. While it ran, I built the Chromium check's synthetic index inside that run's temp `PREACHED_CACHE`. As a result, `cache_guard` flagged the temp cache as changed, and `test_eval_leak` found an index that is normally absent. I reran on a fresh empty temp cache with nothing else running, which gave the clean result above. The final head adds only this report.

**Mutation table** (each mutant applied alone in the `/tmp` worktree, then `tests.test_mobile_ux tests.test_app_js` run, then the file reverted; afterwards `sha256sum -c` passed for all four files against the branch):

| # | Mutant | File | Result | Failing test (first failing check) | `cmp` after revert |
|---|---|---|---|---|---|
| i | `aria-live="polite"` on `#now-playing` | index.html | red | `test_player_is_named_and_quiet` (`'aria-live' unexpectedly found`) | identical |
| ii | announcer set to the sentence on every Play, outside the `catch` | app.js | red | `test_cards_player_and_scroll` (`allowed: cleared at once`) | identical |
| iii | `audio.focus()` after the `is-playing` swap | app.js | red | `test_cards_player_and_scroll` (`held: no focus on audio`) | identical |
| iv | `button.setAttribute("aria-pressed", "true")` in `playClip` | app.js | red | `test_cards_player_and_scroll` (`held: no aria-pressed`) | identical |
| v | old name `"Play " + sermonName + " from " + playLabel` | app.js | red | `test_cards_player_and_scroll` (`spoken label`) | identical |
| vi | `aria-labelledby` removed from `<audio>` | index.html | red | `test_player_is_named_and_quiet` (`None != 'now-playing'`) | identical |
| vii | `min-height: 44px` removed | app.css | red | `test_player_is_named_and_quiet` (`'min-height: 44px' not found`) | identical |
| viii | `#player-announce` moved inside `.player-inner` | index.html | red | `test_player_is_named_and_quiet` (`'player-bar' unexpectedly found`) | identical |
| ix | token guard removed | app.js | red | `test_cards_player_and_scroll` (`stale hold: not announced`) | identical |
| x | `if (announce)` removed from the held write | app.js | red | `test_cards_player_and_scroll` (`TypeError: Cannot set properties of null`) | identical |
| xi | per-Play clear removed | app.js | red | `test_cards_player_and_scroll` (`allowed: cleared at once`) | identical |

11 of 11 red.

**Parity** (`scripts/parity_hash.py` at main, harness `9bbe1a503f36136f`, on the synthetic `tests/test_parity_hash` index: `index_version` `abab…ab`, `model_sha256` `None`, run on `2c89365` and on `897a5cf`). A local script captured each set's records. Of the 225 records in `http`, and of the 225 in `no-church`, exactly 2 differ: probe `/` and probe `/static/app.js`. All other sets have zero differing records.

| Probe | main `2c89365` (= `git show origin/main:app/static/<f> \| sha256sum`) | HEAD (= `sha256sum app/static/<f>`) |
|---|---|---|
| `/` | `ec6bcef68ae1d70514f4e69c937e388b9bfd2665a19ee2f81f299d9999ddd86b` | `0ccef28d3c692acfe72f3702fad469c7fc52e2a55813fe6bb4e391488dc64492` |
| `/static/app.js` | `0e21b3b3e2e072c9ec2d568da0028a56b15d337feb0d3f981e2e27a6556dac62` | `53822e361b5ecf7619006aa43936111f81757ffad8839fe8836b8e7176a6c9db` |

| Set | with `why`, main → HEAD | `--strip why`, main → HEAD |
|---|---|---|
| `http` | `b198c5b3546ef6eb` → `6fe0c9507c26300f` | `87598c3cb97e7a4e` → `d374558790b772b8` |
| `no-church` | `29f0c7e50f011dea` → `13233e0052fbd9b9` | `cc0f371a6b6cdf27` → `6488a1705a3ce1d9` |
| `in-process` | `2c4e3d735333a6b2` (same) | `ca73b0128ad41a55` (same) |
| `in-process-no-health` | `126e6bde69f9049a` (same) | `b60551efd3fe0919` (same) |
| `search+sermon` | `8a7e7554637ecc80` (same) | `f2634f94688508d3` (same) |
| `side` | `3a734e17aff1638d` (same) | `ec626163bcf2eadd` (same) |
| `church` | `0783e6ef1d4a916b` (same) | `604f7b2ce0ee1218` (same) |

The main values equal the old `PINNED`/`PINNED_NO_WHY`. The HEAD values are the new pins, and `tests.test_parity_hash` passes (`Ran 16 tests, OK`). The move is intended. `docs/PARITY.md` real-index rows (`3aef7ca` reviewer box and omarchy `484e682`) are not regenerated here; see §4.

**`/static/app.js` and `/` parity vs PR-C:** on this head `/` = `0ccef28d…dc64492` and `/static/app.js` = `53822e36…76a6c9db`, against main `2c89365` `ec6bcef6…9ddd86b` and `0e21b3b3…6dac62`.

**Doc cite re-pins** (read at HEAD):

| Doc | Before | After | Line at HEAD |
|---|---|---|---|
| `DEMO-SCRIPT.md:28` | `app/static/app.js:217-235` | `app/static/app.js:226-244` | `:226` `function whyLine(why) {` … `:244` `}` |
| `DEMO-SCRIPT.md:28` | rendered at `:312-313` | `:321-322` | `:321` `var why = whyLine(hit.why);` `:322` `if (why) card.appendChild(el("p", "why", why));` |
| `DEMO-SCRIPT.md:42` | `app/static/app.js:338` | `app/static/app.js:347` | `lowHidden: "Low-confidence results hidden.",` |
| `SUBMISSION-DRAFT.md:34` | `app/static/app.js:217-235` and `:312-313` | `:226-244` and `:321-322` | as above |

Unmoved `index.html` cites, still on their text because `index.html:1-95` is byte-identical to main:
- `:63-75` starts at `<summary>What the confidence notes mean</summary>` and ends at the similarity sentence `:75`.
- `:75` is "Similarity is how close …".
- `:78` is the `#hide-low` button.

No other tracked file outside `reports/` cites `app.js`, `index.html` or `app.css` line numbers. `git diff --word-diff=plain origin/main -- docs`, the changed tokens only:

```
[-(`app/static/app.js:217-235`,-]{+(`app/static/app.js:226-244`,+}
[-`:312-313`).-]{+`:321-322`).+}
[-`app/static/app.js:338`).-]{+`app/static/app.js:347`).+}
[-`app/static/app.js:217-235`-]{+`app/static/app.js:226-244`+}
[-`:312-313`,-]{+`:321-322`,+}
```

Only digits changed.

**Headless Chromium (required by the CTO addendum).** `/usr/bin/chromium --headless --no-sandbox`, temp `--user-data-dir`, CDP on `127.0.0.1` only, with `--host-resolver-rules="MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"` so nothing could leave loopback. The server was `app/server.py --bm25-only` on `127.0.0.1:8765` against a synthetic index (`tests/test_side` builders) in the temp dir. The page was `/?q=classiconlytoken`. A Deno script (built-in WebSocket, no new dependency) drove CDP. Each case is a fresh page load and one trusted mouse click at the Play button's centre, and `elementFromPoint` confirmed the click hit the button. Three cases at each of 390×844 (mobile) and 1280×900:
- *unreachable-src*: the archive.org URL doesn't resolve, so `play()` rejects (media error 4). This exercises the held/catch path.
- *local-wav*: the media request is answered by CDP `Fetch.fulfillRequest` with a local 60 s silent WAV.
- *stub-resolve*: `HTMLMediaElement.prototype.play` is replaced to resolve.

| Width / case | Play AX name (visible text) | Focus after Play | `#player-announce` | `#now-playing` | Audio AX name | Audio height | `aria-pressed`/`aria-current` |
|---|---|---|---|---|---|---|---|
| 390 unreachable-src | `Play from 0:00:32, sermon 1` (`Play from 0:00:32`) | the Play button | the held sentence | caption + ". Press play on the bar if the browser held the audio." | "Unable to play media." (Chromium's error-state name) | 54px | null / null |
| 390 local-wav (played, `paused=false`) | same | the Play button | `""` | caption | `Salvation by Faith · 0:00:32 · Read by A. Volunteer (LibriVox volunteer)` (= caption) | 54px | null / null |
| 390 stub-resolve | same | the Play button | `""` | caption | = caption | 54px | null / null |
| 1280 (all three) | same as 390, row for row | the Play button | same as 390 | same | same | 54px | null / null |

Before the first Play, `#player-announce` is empty and has no `[hidden]` ancestor. The audio is out of the AX tree (role `none`) because the bar is still `hidden`. Screenshots `w390-*.png` and `w1280-*.png` (six) stayed in `/tmp/prb.FjLy/shots`, uncommitted. With a playable source and a trusted click, headless Chromium did **not** hold `play()` on this host. The held path was observed through the rejection caused by the unreachable source, which goes through the same `catch`. An earlier attempt, which reused stale click coordinates for a second click, is discarded and not reported as evidence.

**/cache snapshot** (`find /cache -xdev -printf '%p\t%s\t%T@\n' | LC_ALL=C sort`): before 139814 lines, sha256 `d2909d2092c778381ae84725728bd3df1c73e7ccd6ac1797d16d7eb7d566ceb7`; after 139814 lines, sha256 `d2909d2092c778381ae84725728bd3df1c73e7ccd6ac1797d16d7eb7d566ceb7`; `diff` empty. Nothing under `/cache` was opened.

## 4. Open issues, risks, exclusions

- **Not heard on a real screen reader (VoiceOver/TalkBack/NVDA).** The CDP AX names are not a substitute.
- **Chromium names a failed `<audio>` "Unable to play media."**, overriding `aria-labelledby`, when its source errors. That's browser behaviour on a broken source, not on a held one. The announcer still says the held sentence in that case. A real held (autoplay-policy) rejection with a loadable source could not be produced in headless Chromium here.
- **`docs/PARITY.md` not re-baselined.** My run used the synthetic index (`index_version` `abab…`, `model_sha256` `None`), not the page's Wesley indexes, so per the brief the page is unchanged. The `http`/`no-church` rows for `3aef7ca` (reviewer box) and `484e682` (omarchy) will no longer match on this head. The `/` and `/static/app.js` byte hashes move, and the other five sets don't. The reviewer or host operator regenerates those two rows on their index.
- **Host-side write by Chromium:** I launched Chromium with the real `HOME`. Its crash reporter updated `~/.config/chromium/Crash Reports/settings.dat`, in a directory that already existed (created 2026-10-30). Nothing else under `$HOME` changed, and no `Microsoft`/`DeveloperTools` dir was created. I left the file alone because I didn't create it.
- **Temp worktrees:** I made three detached worktrees under `/tmp/prb.FjLy` (mutants, main for parity, full suite) and removed them with `git worktree remove` after a `tempfile.gettempdir()` assertion. In my own temp mutant worktree I ran one `git checkout --detach` to move it to the branch head. That was not in a shared directory, and the main tree `/work/preached` was never touched.
- PR-C (#103) and PR-D cite or edit lines below this PR's additions. Whichever merges second restates parity (CoS note).

## 5. Dependencies added

None. The Chromium check used the host's `/usr/bin/chromium` and Deno's built-in WebSocket; nothing was installed.

## PR BODY

**PR-B: a named and quiet audio player (audit F-02) and Label in Name on Play (audit F-11)**

Base `origin/main` `2c8936583d3939ea5a8e5ae39c2af6eb62d7cbac`. Tested code head `897a5cf7407d0b44112d8b9f6962f285680d0ae3` (the final commit adds only `reports/W5-A11Y-PR-B-F02-F11.md`).

```
$ git diff --stat origin/main...HEAD
 app/static/app.css              |   2 +-
 app/static/app.js               |  13 +-
 app/static/index.html           |   3 +-
 docs/DEMO-SCRIPT.md             |   4 +-
 docs/SUBMISSION-DRAFT.md        |   2 +-
 reports/W5-A11Y-PR-B-F02-F11.md | 254 ++++++++++++++++++++++++++++++++++++++++
 tests/test_mobile_ux.py         |  80 ++++++++++++-
 tests/test_parity_hash.py       |   8 +-
 8 files changed, 349 insertions(+), 17 deletions(-)
```

**What changes**
- `<audio id="player">` is named by `aria-labelledby="now-playing"`, so its name follows the caption. `#now-playing` stays non-live.
- One visually hidden `<p id="player-announce" role="status" aria-live="polite">` sits outside `.wrap` and the player bar. It is cleared on every Play and set only inside the `play()` `catch`, after the token guard, to the constant `"Press play on the bar if the browser held the audio."`. It never carries server text.
- The Play `aria-label` is `"Play from " + playLabel + ", " + sermonName`. Before: visible "Play from 0:01:32", name "Play sermon 41 from 0:01:32". After: name "Play from 0:01:32, sermon 41" (or "Play from 0:01:32, Wandering Thoughts" with no number).
- `.player audio { width: 100%; min-height: 44px; }`, on one line.

**Rulings**
- No focus move at all, on any branch.
- `is-playing` stays visual only: no `aria-pressed`, no `aria-current`.
- The announcer is outside the player bar and in the tree from page load.

**Tests** (all in `tests/test_mobile_ux.py`; `tests/test_app_js.py` unchanged)
- Host `preached-sandbox` (i9-12900K), Python 3.12.16, deno 2.9.8, at `897a5cf7407d0b44112d8b9f6962f285680d0ae3`.
- Focused `tests.test_mobile_ux tests.test_app_js`: `Ran 20 tests in 0.445s, OK`.
- Full suite: `Ran 1194 tests in 276.167s, OK (skipped=15)`. All 15 skips need real data or a real cache. No Deno test skipped, and `RequireDenoTests` passed.

| # | Mutant | File | Failing test | `cmp` |
|---|---|---|---|---|
| i | `aria-live` on `#now-playing` | index.html | `test_player_is_named_and_quiet` | identical |
| ii | announce on every Play | app.js | `test_cards_player_and_scroll` | identical |
| iii | `audio.focus()` | app.js | `test_cards_player_and_scroll` | identical |
| iv | `aria-pressed="true"` | app.js | `test_cards_player_and_scroll` | identical |
| v | old name | app.js | `test_cards_player_and_scroll` | identical |
| vi | no `aria-labelledby` | index.html | `test_player_is_named_and_quiet` | identical |
| vii | no `min-height: 44px` | app.css | `test_player_is_named_and_quiet` | identical |
| viii | announcer inside `.player-inner` | index.html | `test_player_is_named_and_quiet` | identical |
| ix | no token guard | app.js | `test_cards_player_and_scroll` | identical |
| x | no `if (announce)` on held write | app.js | `test_cards_player_and_scroll` | identical |
| xi | no per-Play clear | app.js | `test_cards_player_and_scroll` | identical |

11/11 red. After the run, `sha256sum -c` passed on all four files.

**Parity (intended move)**
- Harness `9bbe1a503f36136f`, synthetic index (`index_version` `abababab…ab`, `model_sha256` `None`), main `2c89365` vs HEAD `897a5cf`, on host `preached-sandbox`.
- Only probes `/` and `/static/app.js` differ, in `http` and `no-church`:
  - `/`: `ec6bcef68ae1d70514f4e69c937e388b9bfd2665a19ee2f81f299d9999ddd86b` → `0ccef28d3c692acfe72f3702fad469c7fc52e2a55813fe6bb4e391488dc64492`
  - `/static/app.js`: `0e21b3b3e2e072c9ec2d568da0028a56b15d337feb0d3f981e2e27a6556dac62` → `53822e361b5ecf7619006aa43936111f81757ffad8839fe8836b8e7176a6c9db`
  - Each equals `git show <rev>:app/static/<file> | sha256sum`.
- `http` `b198c5b3546ef6eb` → `6fe0c9507c26300f` (`--strip why` `87598c3cb97e7a4e` → `d374558790b772b8`).
- `no-church` `29f0c7e50f011dea` → `13233e0052fbd9b9` (`--strip why` `cc0f371a6b6cdf27` → `6488a1705a3ce1d9`).
- `in-process`, `in-process-no-health`, `search+sermon`, `side` and `church` are identical, with and without `why`.
- The `PINNED`/`PINNED_NO_WHY` `http` and `no-church` keys in `tests/test_parity_hash.py` are re-pinned.
- `docs/PARITY.md` is unchanged: this run's `index_version`/`model_sha256` aren't the page's, so the reviewer regenerates the `http`/`no-church` real-index rows.

**Doc cites re-pinned** (line numbers only)

| Cite | Before | After | Text at HEAD |
|---|---|---|---|
| `DEMO-SCRIPT.md:28`, `SUBMISSION-DRAFT.md:34` | `app.js:217-235` | `app.js:226-244` | `function whyLine(why) {` … `}` |
| `DEMO-SCRIPT.md:28`, `SUBMISSION-DRAFT.md:34` | `:312-313` | `:321-322` | `var why = whyLine(hit.why);` / `if (why) card.appendChild(el("p", "why", why));` |
| `DEMO-SCRIPT.md:42` | `app.js:338` | `app.js:347` | `lowHidden: "Low-confidence results hidden.",` |

The `index.html` cites `:63-75`, `:75` and `:78` don't move, because lines 1–95 are byte-identical to main. Word diff:

```
[-(`app/static/app.js:217-235`,-]{+(`app/static/app.js:226-244`,+}
[-`:312-313`).-]{+`:321-322`).+}
[-`app/static/app.js:338`).-]{+`app/static/app.js:347`).+}
[-`app/static/app.js:217-235`-]{+`app/static/app.js:226-244`+}
[-`:312-313`,-]{+`:321-322`,+}
```

Only digits changed.

**Headless Chromium** (`/usr/bin/chromium` 155, `--headless --no-sandbox`, loopback only, temp profile; screenshots not committed)
- Setup: 390×844 and 1280×900, against `app/server.py --bm25-only` on a synthetic index, one trusted click per page load.
- At both widths:
  - The Play AX name is `Play from 0:00:32, sermon 1`, with visible text `Play from 0:00:32` (prefix match).
  - After Play, focus is still on the Play button, the audio is 54px tall, and there is no `aria-pressed` or `aria-current`.
- Allowed Play (local WAV fulfilled over CDP, `paused=false`; and a stubbed resolving `play()`): `#player-announce` is `""`, and the audio's AX name equals the caption.
- Rejected Play (unreachable source): `#player-announce` has the held sentence, and focus stays on Play. Chromium then names the errored audio "Unable to play media.".
- Headless Chromium did not hold a playable source on this host.

**/cache**: listing before and after, 139814 lines each, sha256 `d2909d2092c778381ae84725728bd3df1c73e7ccd6ac1797d16d7eb7d566ceb7` both, no diff.

**DEPLOY cites are untouched**: no file cited in `docs/DEPLOY.md` is edited, and the suite has zero `test_every_cited_file_line_holds_its_string` failures.

Not heard on a real screen reader (VoiceOver/TalkBack/NVDA).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
