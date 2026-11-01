# W5 a11y PR-C: side-by-side notes are announced (F-03)

Branch `fix/w5-a11y-side-notes`, from `origin/main` `3aef7cacf1907fa7ed57a5251b3894dec6618f00`.
Code commit `e0c2d4b7eb8138ac1d55cfe8c861f519e5bc1d6e`. The pushed head sha40 is in the hand-off message,
because this report is in that commit.

## Cause

In classic view, `showResults` writes the fallback note to `#note` and the
confidence banner to `#confidence`. Both sit in `<div class="notices" aria-live="polite">`
(index.html:58-61), so a screen reader hears the low-confidence warning. In side by
side, `renderSide` appended the same notes to each column as plain `<p class="note">`
(main app.js:440, 442), outside any live region. `showSides` never wrote `#note`/`#confidence`,
so the warning was not announced in the demo's main view.

## Change (app/static/app.js only)

- `renderSide` no longer draws the notes in the column.
- New `sideNotes(states, key)` builds the text for each live node. Each side's note is
  prefixed with its column heading, for example
  `Your church (sample data) — Low confidence: …`, so it stays clear which side a
  note belongs to. When both sides have one, the two notes are joined in one node.
- `showSides` calls `setText("note", …)` and `setText("confidence", …)` with that text.
  These are the same nodes and the same `.notices` live region that classic uses.
- Same rule as classic: a side's confidence note is shown only while that side's
  passages are shown. When "Hide low-confidence results" hides the low side, its
  banner hides too. The column status already says "Low-confidence results hidden."
  This is a small visible change. Before, the column kept its banner while its
  passages were hidden.
- Reset and new search: `showSides`, `runSearch` and `showFailure` all start with
  `resetState`, which already does `setText("note", "")` / `setText("confidence", "")`.
  So no stale warning is left behind.
- Classic path (`showResults`) is untouched. `index.html` and `app.css` are unchanged:
  the nodes and styles already exist.
- The audio/player code (PR-B) is untouched. `resetState` is unchanged, so this PR does not
  touch that part of PR-D's code. `showSides` gains two lines.

DEPLOY cites: `docs/DEPLOY.md` names `app.js` only in a file list (line 371, no line
cite). `tests/test_deploy_alerts.py` has no pin on `app.js` or `test_app_js.py`. Nothing
needed re-pinning. The suite shows 0 `test_every_cited_file_line_holds_its_string` failures.

## Tests (tests/test_app_js.py, `SIDE_CHECKS`)

- The fake DOM now has a `.notices` node (`aria-live="polite"`) whose children are
  `#note` and `#confidence`, as in index.html. index.html's own containment is still
  checked by `test_mobile_ux.test_confidence_banner_is_announced`.
- As ruled, the old `:674` assertion ("status is not the banner") is replaced with:
  the banner node is inside `.notices` and not hidden. The new checks also cover:
  - the text is `Your church (sample data) — <MESSAGES.low>`;
  - the unrated classic side adds nothing;
  - the column does not repeat the note;
  - the banner hides with the low side's passages and comes back with them;
  - `resetState()` hides and empties it;
  - a weak classic side with a fallback note puts both notes in `.notices`, each named
    (`#note` and `#confidence` not hidden);
  - a later search (church missing) drops the stale banner and note.

Red, with `origin/main`'s app.js put in place temporarily and HEAD's restored afterwards:

```
FAIL: test_side_by_side_rendering
Error: side banner not hidden: got true, want false
Ran 10 tests ... FAILED (failures=1)
```

Green at HEAD: `tests.test_app_js` + `tests.test_mobile_ux`: 19 tests OK.

## Parity

`docs/PARITY.md` is not on `origin/main`: #97 has not landed. So PARITY.md is **not** touched.

I took the harness from PR #97's branch without checking it out:
`git show origin/chore/w5-parity-harness:scripts/parity_hash.py` and `eval/parity/requests.json`.
I put them into `git archive` copies of `origin/main` and of HEAD under `/tmp/prc_parity/`.
A driver in a separate dir ran it. The sandbox has no Wesley index or ONNX model outside `/cache`,
and `/cache` must not be read. So the driver ran it the way `tests/test_parity_hash.py` does:
synthetic `build_library(classic_rows())` index in a temp dir, fixture loader, `chunks_sha256 = "ab"*32`.
The driver also captured every record per set, which gave the record-level diff.
The `/` and `/static/app.js` bytes come from the tree, not from the index, so the probe records do not
depend on which index is used. Harness hash `9bbe1a503f36136f`.
The main run reproduces #97's `PINNED` synthetic hashes exactly.

| Set | main | head | records changed |
|---|---|---|---|
| http | `b198c5b3546ef6eb` | `e487e72f580466aa` | 1 of 225: `/static/app.js` |
| no-church | `29f0c7e50f011dea` | `b23edff07cf3930e` | 1 of 225: `/static/app.js` |
| in-process | `2c4e3d735333a6b2` | `2c4e3d735333a6b2` | 0 of 212 |
| in-process-no-health | `126e6bde69f9049a` | `126e6bde69f9049a` | 0 of 211 |
| search+sermon | `8a7e7554637ecc80` | `8a7e7554637ecc80` | 0 of 96 |
| side | `3a734e17aff1638d` | `3a734e17aff1638d` | 0 of 93 |
| church | `0783e6ef1d4a916b` | `0783e6ef1d4a916b` | 0 of 22 |

The one changed record (#12 in both `http` and `no-church`), `/static/app.js` body sha256:
`0e21b3b3e2e072c9ec2d568da0028a56b15d337feb0d3f981e2e27a6556dac62` →
`5b4ce261052a436666bb554797f204ec7aa820436e0ec7721c67aef4a789fedc`. This equals
`git show HEAD:app/static/app.js | sha256sum`. Main's value equals `git show origin/main:app/static/app.js | sha256sum`.
The probe `/` did not change, because this PR does not edit `index.html`. Its sha256 is
`ec6bcef68ae1d70514f4e69c937e388b9bfd2665a19ee2f81f299d9999ddd86b` at both trees.
The real-index (Wesley + ONNX) http/no-church refs were not computed here. They will move by the same one record.

## Full suite

Machine `preached-sandbox` (24 CPUs, Python 3.12.16, deno 2.9.8), tree `e0c2d4b` (the report adds no code).
All of these were fresh dirs under one `mktemp -d /tmp/prc.XXXXXX`: `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`,
`DENO_DIR`, `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `TORCH_HOME`, `UV_PYTHON_INSTALL_DIR`, `UV_PROJECT_ENVIRONMENT`.
Also set: `ORT_DISABLE_TELEMETRY=1`, `PREACHED_REQUIRE_DENO=1`, `HF_HUB_OFFLINE=1`, and `PREACHED_GUARD_REAL_SRC` unset.

```
uv run python -m unittest discover -s tests
Ran 1156 tests in 258.140s
OK (skipped=12)
```

## /cache

`find /cache -printf '%p %s %T@\n' | sort` before and after all runs: 132824 lines each, `diff` empty,
both listings sha256 `d967c6be6aac584c56b5dce991fa76b76ee359c6e1722a1cd81ddbdf86077006`. Nothing under
`/cache` was opened.

## Stat

```
$ git diff --stat origin/main..HEAD
 app/static/app.js                  |  21 ++++-
 reports/W5-A11Y-PR-C-SIDE-NOTES.md | 157 +++++++++++++++++++++++++++++++++++++
 tests/test_app_js.py               |  36 ++++++++-
 3 files changed, 210 insertions(+), 4 deletions(-)
```

## PR BODY

**F-03 (Medium): side-by-side fallback and confidence notes are now announced.**

Before this change, side by side drew each column's notes as plain `<p>`, outside any live region, so the
low-confidence warning was not announced in the demo's main view. Now `showSides` writes them to
`#note` / `#confidence` inside `.notices` (`aria-live="polite"`), the same nodes classic uses. Each note is
prefixed with its column heading (`Your church (sample data) — Low confidence: …`), so it stays clear which
side it belongs to. As in classic, a side's banner hides when its low-confidence passages are hidden.
`resetState` clears both nodes on reset and on each new search. Classic view, `index.html`, `app.css` and
the audio code are unchanged.

- Tests: the `test_app_js.py:674` assertion is replaced, as ruled, with "the banner node is inside `.notices`
  and not hidden". New checks cover the side naming, both sides at once, the fallback note, hide/show,
  reset, and a stale note after a new search. Red on main's app.js (`side banner not hidden`), green at head.
- Parity (#97 harness from its branch, synthetic index; PARITY.md is not on main, so it is not touched):
  only record `/static/app.js` changes in `http` and `no-church`. The new sha256 `5b4ce261…fedc` equals
  `git show HEAD:app/static/app.js | sha256sum`. `/` is unchanged, and every other set has the same hash.
- Full suite (temp caches): 1156 tests OK, 12 skipped. `/cache` listing unchanged.

```
 app/static/app.js                  |  21 ++++-
 reports/W5-A11Y-PR-C-SIDE-NOTES.md | 157 +++++++++++++++++++++++++++++++++++++
 tests/test_app_js.py               |  36 ++++++++-
 3 files changed, 210 insertions(+), 4 deletions(-)
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)
