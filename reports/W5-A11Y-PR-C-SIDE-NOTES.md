# W5 a11y PR-C: side-by-side notes are announced (F-03), correction round 1

Branch `fix/w5-a11y-side-notes` (the brief names it `fix/w5-a11y-side-notices`; the name was
kept, not renamed, and no second branch exists). Cut from `origin/main`
`3aef7cacf1907fa7ed57a5251b3894dec6618f00`. `origin/main` has since moved to
`b1a2b245b19fb6ee173fd20d491fa7f986ab65ad` (#101, cache-guard tests and reports only; no `app/` or
`tests/test_app_js.py` change). No rebase was needed or done.
Starting head (local and `origin/fix/w5-a11y-side-notes`, matching): `18a72a0dc537c9fd93fbdba9053d082fcb72378b`.
Code commit of this round: `e417bc4b3ac7f7fd092ede89d8b61f66f97cf2a0`. The pushed head sha40 is in the hand-off message.

## 1. What was done

The authoritative brief replaces round 0. `app/static/app.js` and `tests/test_app_js.py` were reset to
`origin/main` bytes and redone:

- `showSides` (only function edited): `#note` = for each side (classic, then church) with a
  `fallbackNote`, `heading + ": " + fallbackNote`, joined with one space, `""` when none. Then `#status`
  unchanged. Then `#confidence` = for each side with a `confidenceNote` and `showResults === true`,
  `heading + ": " + confidenceNote`, joined with one space, `""` when none. Both via `setText`.
- `renderSide`, `resetState`, `setBusy`, `showResults`, `MESSAGES` are byte-identical to main (the
  column paragraphs stay). Round 0's `sideNotes` helper, em-dash wording and `renderSide` edit are gone.
- `tests/test_app_js.py`: edits only in `SIDE_CHECKS`. The `:674` "status is not the banner" assertion is kept.
  `index.html`, `app.css`, `tests/test_mobile_ux.py` are identical to `origin/main` (`git diff origin/main -- FILE` empty).

## 2. How to run it

All variables under one `mktemp -d` (`PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`, `HF_HUB_CACHE`,
`HUGGINGFACE_HUB_CACHE`, `DENO_DIR`, `XDG_CACHE_HOME`, `TORCH_HOME`, `UV_PROJECT_ENVIRONMENT`,
`UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, `HOME`), plus `ORT_DISABLE_TELEMETRY=1`, `HF_HUB_OFFLINE=1`,
`PREACHED_REQUIRE_DENO=1`; `PREACHED_GUARD_REAL_SRC` unset.

    PREACHED_REQUIRE_DENO=1 uv run python -m unittest tests.test_app_js tests.test_mobile_ux
    PREACHED_REQUIRE_DENO=1 HF_HUB_OFFLINE=1 ORT_DISABLE_TELEMETRY=1 uv run python -m unittest discover -s tests

## 3. Results

Host `preached-sandbox`, code commit `e417bc4b3ac7f7fd092ede89d8b61f66f97cf2a0`.

- Focused: `Ran 19 tests in 0.360s, OK` (test_mobile_ux unchanged, skipped=0).
- Full: `Ran 1156 tests in 256.723s, OK (skipped=12)`. Zero `test_every_cited_file_line_holds_its_string` failures.
- Cites re-read on this head: `docs/DEMO-SCRIPT.md:28,:42` and `docs/SUBMISSION-DRAFT.md:34` cite
  `app.js:217-235` (`whyLine` ... `}`), `:312-313` (`whyLine(hit.why)` / `card.appendChild`), `:338` (`lowHidden`).
  All hold; this PR edits only after line 519.
- `/cache` snapshot (`find /cache -xdev -printf '%p\t%s\t%T@\n' | sort`): before 132824 lines,
  sha256 `3ca707d7aba4f2aa682a6497f9e481bad4c8087d9304142444a746ace64bca64`; after 132824 lines, same sha256; diff: none.
  No `Microsoft`/`DeveloperTools` dirs were created.

Mutation proof (each applied alone to `app/static/app.js`, `tests.test_app_js` run, reverted, `cmp` against pre-mutant bytes):

| Mutant | Result | Assertion that failed | revert `cmp` |
|---|---|---|---|
| (i) delete new `setText("confidence", …)` | red | `side banner announced in .notices` | identical |
| (ii) delete new `setText("note", …)` | red | `fallback note announced in .notices` | identical |
| (iii) drop the `showResults === true` condition | red | `hidden low side adds no banner` | identical |
| (iv) `aria-live` on `section.side-col` (and, separately, on `#sides`) | red | `column node has no aria-live` (via `walk()`) | identical |

Parity (#97 not merged; harness from PR #97 head `c2f74e9b40fc0572af4febff5327b87aff95c9bd` in a temporary detached worktree,
removed afterwards, nothing committed). #97's base is `3aef7ca`, so its `app/` tree equals main's. Index: the harness's
synthetic test index (`tests/test_side` builders, fixture encoder), not a real index. The old run reproduces #97's own `PINNED` values.

| Field | Value |
|---|---|
| main | `3aef7cacf1907fa7ed57a5251b3894dec6618f00` |
| machine | `preached-sandbox`, Python 3.14.8 |
| index_version | `abab…ab` (`"ab"*32`, as in `tests/test_parity_hash.py`) |
| model_sha256 | `None` (fixture encoder, no model file) |
| harness hash | `9bbe1a503f36136f` |
| old app.js sha256 (`git show 3aef7ca:app/static/app.js`) | `0e21b3b3e2e072c9ec2d568da0028a56b15d337feb0d3f981e2e27a6556dac62` |
| new app.js sha256 (`HEAD`) | `3a08bf550d5208b3eddecdd2a8a3b5006aab90a899be1c0dd12732d37a00dd9f` |

| Set | Old | New | Records |
|---|---|---|---|
| http | `b198c5b3546ef6eb` | `a698343bd83ea865` | only `/static/app.js` differs (225 records) |
| no-church | `29f0c7e50f011dea` | `153267cefae0f1df` | only `/static/app.js` differs (225 records) |
| in-process | `2c4e3d735333a6b2` | same | identical |
| in-process-no-health | `126e6bde69f9049a` | same | identical |
| search+sermon | `8a7e7554637ecc80` | same | identical |
| side | `3a734e17aff1638d` | same | identical |
| church | `0783e6ef1d4a916b` | same | identical |

The record-level diff (uncommitted script over the harness's stripped record lists) shows the only differing records are
`/static/app.js` in `http` and `no-church`, with body `{"sha256": …}` equal to the two sha256s above. `/` (index.html) is identical.
These values are for the synthetic index; a reviewer-box (Wesley + ONNX) baseline must be recomputed by whoever merges, and
PARITY.md/`PINNED` were not re-pinned (they do not exist on this branch). If PR-B merges first, recompute on the final head.

## 4. Open issues, risks

- #97 is unmerged, so `docs/PARITY.md`, `PINNED` and `PINNED_NO_WHY` are not touched. After #97 merges, the
  `http` and `no-church` keys need a re-pin in whichever of PR-B/PR-C merges second (guaranteed textual conflict, per the brief).
- Visible change: a column's note now also appears at the top, in `.notices`; the column copy stays.
- No browser check (375px/1280px) was run.
- Main moved to `b1a2b24` (no overlap). Rebase after PR-B is for CoS to schedule.

## 5. Dependencies added

None.

## Gap status (round 1)

1 scope: fixed; only `app.js`, `test_app_js.py`, this report differ; `index.html`, `app.css`, `test_mobile_ux.py` empty diff. 2 location: fixed; code only in `showSides`.
3 mechanism: fixed; existing `#note`/`#confidence` via `setText`, no new nodes, aria or focus moves. 4 text/order: fixed (note, status, confidence).
5 confidence only when shown: fixed, mutant (iii). 6 `:674`: fixed, restored. 7 tests: fixed, brief's `SIDE_CHECKS` extensions; round-0 reset and
extra tests removed. 8 mutation: done, table above. 9 parity: done, #97 unmerged branch. 10 cites: hold. 11 rule 5: done. 12 report: this file.
13 commands: as above.

## PR BODY

Side by side (F-03): the low-confidence banner and the BM25-only fallback note are now written into the existing
`#note` and `#confidence` nodes in the `.notices` polite live region, as classic view does. Text is
`heading + ": " + note`, one space between sides; the confidence note only while that side's passages are shown.
Only `showSides` changes. Column paragraphs, `#status`, `resetState`, `setBusy`, `index.html` and CSS are unchanged.

Branch note: the brief names `fix/w5-a11y-side-notices`; this PR is `fix/w5-a11y-side-notes`.

```
 app/static/app.js                  |  11 ++++
 reports/W5-A11Y-PR-C-SIDE-NOTES.md | 127 +++++++++++++++++++++++++++++++++++++
 tests/test_app_js.py               |  20 ++++++
 3 files changed, 158 insertions(+)
```

- Focused: `Ran 19 tests in 0.360s, OK` on `e417bc4b3ac7f7fd092ede89d8b61f66f97cf2a0`, host `preached-sandbox`.
- Full: `Ran 1156 tests in 256.723s, OK (skipped=12)`, same sha and host.
- Mutants (i) delete confidence `setText`, (ii) delete note `setText`, (iii) drop `showResults` condition, (iv) `aria-live` on `section.side-col`: all red, each reverted with `cmp` identical.
- Parity (synthetic index, #97 head `c2f74e9`, #97 unmerged; main `3aef7ca`; harness `9bbe1a503f36136f`; index_version `ab`×32; model_sha256 None): only `/static/app.js` in `http` (`b198c5b3546ef6eb` → `a698343bd83ea865`) and `no-church` (`29f0c7e50f011dea` → `153267cefae0f1df`) moves, `0e21b3b3…ac62` → `3a08bf55…dd9f`; every other set and `/` identical. The move is intended. PARITY.md/PINNED not touched (#97 unmerged).
- `/cache` snapshot: 132824 lines before and after, sha256 `3ca707d7…ca64` both, diff none.
- DEPLOY cites are untouched.
