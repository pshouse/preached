# W5-A11Y-PR-A-503-PAGE

One shared constant 503 page for an over-cap navigation (F-01) and a disabled browser `GET /` or `HEAD /` (F-06). Branch `fix/w5-a11y-503-page` from `origin/main` `3aef7cacf1907fa7ed57a5251b3894dec6618f00`.

## What was done

`_BUSY_PAGE` in `app/server.py` is the only HTML body for both cases. It has a viewport (`width=device-width, initial-scale=1`), an `<h1>` ("Preached is busy"), the sentence "Preached is busy. This page will try again in a moment.", and `<meta http-equiv="refresh" content="5">`. It is built from constants. No request byte, script, or external URL is in it.

`Retry-After` on the accept-thread 503 stays `1`. The refresh is no longer that header. The coupling comment at `app/server.py:2915`–`2917` says so. `docs/DEPLOY.md:628` no longer says "a meta refresh of the same 1 second". `tests/test_html_503.py` no longer requires `content="{retry-after}"`; it requires a refresh of 5 (and at least 5) and that the refresh is not the `Retry-After` value. The negative checks stay: the query, the peer, `{"error"`, `<script`, `http://`, and `https://` stay out of the body. A second query returns the same bytes.

F-06: a disabled `GET /` or `HEAD /` whose `Accept` names `text/html` with a nonzero weight gets that same page. `/healthz` stays `{"ok": false, "disabled": true}`. `/api/*` and every other path, including `/static/app.js` and a non-HTML `Accept` on `/`, stay `{"error": "unavailable"}`. `q=0`, `*/*`, and `text/*` stay JSON. The kill-switch JSON assertion at `tests/test_deploy.py:229` is unchanged and green. `tests/test_exposure.py` was not edited; the JSON 503 assertions at `:577`, `:1190`, and `:1330` are the same lines.

The new helpers sit after `app/server.py:3445`, the last cited line. The disabled branch and the page constant keep the same line counts as before, so no `file:line` pin moved. Read after the edit, still holding their strings: `:2398` and `:2419` (`request failed`), `:2989` (`listening on`), `:2993` (`log_startup_pause`), `:3061` and `:3068` (`church side refused`), `:3248` (`basicConfig`), `:3426` (`stopping`), `:3427` (`stuck = server.drain()`), `:3431` (handler threads), `:3441` (`church_connection.close()`), `:3443` (`stopped cleanly`), `:3445` (`raise SystemExit(1)`). `tests/test_deploy_alerts.py` `test_every_cited_file_line_holds_its_string` and `test_the_runbook_cites_exactly_the_pinned_lines` passed. The sentence at `docs/DEPLOY.md:842`–`843` is already tree-relative ("this tree's `app/server.py`") and was left as written. The sha `76990e8` in that paragraph is the old alerts yaml, not the line-number tree.

## How to run it

Full suite, scratch caches only. `PREACHED_GUARD_REAL_SRC` stays unset.

```
S=$(mktemp -d /tmp/w5-a11y-503-suite.XXXXXX)
for v in PREACHED_CACHE PREACHED_ONNX_DIR HF_HOME DENO_DIR XDG_CACHE_HOME UV_CACHE_DIR TORCH_HOME UV_PYTHON_INSTALL_DIR; do
  mkdir -p "$S/$v"
done
cd /work/preached
PREACHED_REQUIRE_DENO=1 \
PREACHED_CACHE="$S/PREACHED_CACHE" \
PREACHED_ONNX_DIR="$S/PREACHED_ONNX_DIR" \
HF_HOME="$S/HF_HOME" \
DENO_DIR="$S/DENO_DIR" \
XDG_CACHE_HOME="$S/XDG_CACHE_HOME" \
UV_CACHE_DIR="$S/UV_CACHE_DIR" \
TORCH_HOME="$S/TORCH_HOME" \
UV_PYTHON_INSTALL_DIR="$S/UV_PYTHON_INSTALL_DIR" \
ORT_DISABLE_TELEMETRY=1 \
HF_HUB_OFFLINE=1 \
.venv/bin/python -m unittest discover -s tests
```

Focused: `.venv/bin/python -m unittest tests.test_html_503 tests.test_deploy.RateAndKillTests tests.test_deploy_alerts.RunbookTests`

## Results

Machine `preached-sandbox`, 24 cores, Linux 7.2.8-9-omarchy, Python 3.12.16. Suite base `/tmp/w5-a11y-503-suite.JU7J9E` (under `tempfile.gettempdir()`). **Ran 1161 tests in 275.783s, OK (skipped=12), exit 0.** Elapsed 276.21s. Zero failures, so zero `test_every_cited_file_line_holds_its_string` failures. The 12 skips were not named (the run was not verbose).

`/cache` listing `find /cache -printf '%p %s %T@\n' | sort`: **132824 lines before and after, identical.** Nothing under `/cache` was opened with sqlite or ORT. `PREACHED_GUARD_REAL_SRC` was unset.

`scripts/parity_hash.py` is not on `origin/main`. Normal-mode responses (browser `Accept`, not over cap, not disabled), body sha256, base and head identical:

| Path | Status | Type | Bytes | sha256 |
| --- | --- | --- | --- | --- |
| `/` | 200 | `text/html; charset=utf-8` | 5521 | `ec6bcef68ae1d70514f4e69c937e388b9bfd2665a19ee2f81f299d9999ddd86b` |
| `/static/app.js` | 200 | `text/javascript; charset=utf-8` | 25013 | `0e21b3b3e2e072c9ec2d568da0028a56b15d337feb0d3f981e2e27a6556dac62` |
| `/static/app.css` | 200 | `text/css; charset=utf-8` | 7668 | `06c9cb2d35c91df4d013ba4996118a989b6eaedbaa3cbbafd03bcef16f727525` |
| `/static/favicon.svg` | 200 | `image/svg+xml` | 321 | `6469c5e748d3a2937019ac4d9ab49b7b94e1a3faad9f1a824510c63164983613` |

Headless Chromium was already installed (155.0.8059.84, ChromeDriver the same build). Nothing was installed. Phone emulation 390×844, device pixel ratio 3, a mobile user agent, against a loopback server with one connection held and `max_connections_per_client=1`. The harness waits up to 2s for the request bytes, the same wait as `tests/test_html_503.py`, because the production accept thread does not wait and would answer JSON if the headers had not arrived yet. The body is still `_BUSY_PAGE`.

| Page | clientWidth | innerWidth | viewport | refresh |
| --- | --- | --- | --- | --- |
| Data URL with no viewport meta | 980 | 980 | none | none |
| `GET /?q=secretquery` over cap | 390 | 390 | `width=device-width, initial-scale=1` | `5` |

The busy document's heading was "Preached is busy", the paragraph was the sentence, `document.scripts.length` was 0, and there were no links. The query was not in the text.

## Open issues

`docs/DEMO-SCRIPT.md` still describes the old "Unavailable. Retrying." page. It is outside this PR's scope.

A 5 second meta refresh still reloads on its own. The ruling allowed that (5 seconds or more, or a Try again link). The sentence says the page will try again, so the refresh is the option used here. The user cannot pause it.

A navigation whose headers have not arrived when the accept thread reads still gets the JSON 503. That behavior is unchanged.

## Dependencies

None.

## PR BODY

Shared constant 503 page for an over-cap navigation and a disabled browser `GET /` or `HEAD /`.

The page has a viewport (`width=device-width, initial-scale=1`), an `<h1>`, the sentence "Preached is busy. This page will try again in a moment.", and a meta refresh of 5 seconds. It is constant: no request bytes, no script, no external URL. `Retry-After` stays `1` for the accept-thread response. The refresh is no longer that header. The coupling comment at `app/server.py:2915`–`2917`, the Connections sentence at `docs/DEPLOY.md:628`, and the `content="{retry-after}"` assertion in `tests/test_html_503.py` are updated. The negative assertions in that file stay.

A disabled `GET /` or `HEAD /` with a browser `Accept` gets the same page. `/healthz` stays `{"ok": false, "disabled": true}`. `/api/*` stays JSON, including when the `Accept` is a browser's. `tests/test_deploy.py:229` is unchanged and green. `tests/test_exposure.py:577`, `:1190`, and `:1330` were not edited.

No `docs/DEPLOY.md` `file:line` pin moved. Helpers were added after the last cited line (`app/server.py:3445`). The pins around the edit were read and still hold their strings. `test_every_cited_file_line_holds_its_string` passed. The line-number sentence at `docs/DEPLOY.md:842`–`843` is already tree-relative and was left as written.

`scripts/parity_hash.py` is not on `origin/main` (`3aef7ca`). Normal-mode bodies for `/`, `/static/app.js`, `/static/app.css`, and `/static/favicon.svg` are byte-identical on base and head (sha256 in the report table).

Headless Chromium 155.0.8059.84 was already installed. At phone emulation 390×844, a page with no viewport meta laid out at 980 CSS pixels. The over-cap page laid out at 390, with the heading, the sentence, refresh `5`, and no script. The harness waited for the request bytes so the browser received the HTML page.

Suite on `preached-sandbox` (24 cores, Python 3.12.16), scratch dirs for `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME`, and `UV_PYTHON_INSTALL_DIR`, `ORT_DISABLE_TELEMETRY=1`, `PREACHED_GUARD_REAL_SRC` unset: **Ran 1161 tests in 275.783s, OK (skipped=12)**. `/cache` listing (paths, sizes, mtimes), 132824 lines, identical before and after.

```
git diff --stat origin/main..HEAD
 app/server.py                    |  67 +++++++++++++++++++------
 docs/DEPLOY.md                   |   4 +-
 reports/W5-A11Y-PR-A-503-PAGE.md | 103 +++++++++++++++++++++++++++++++++++++++
 tests/test_deploy.py             |  65 +++++++++++++++++++++++-
 tests/test_html_503.py           |  60 +++++++++++++++++++++--
 5 files changed, 276 insertions(+), 23 deletions(-)
```

No new dependencies.
