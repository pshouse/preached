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

## Round 2 (99-XVC-PR-C-MAIN-REPIN-R2)

- Start head `67abe0d85fb74a73a4b790349ba45ceec6d8dba3` (local == `origin/fix/w5-a11y-side-notes`); status clean. Merged `origin/main` `484e68298b514b8489a359602f4340e7662b7615` (#97 parity harness included) with `git merge`, no rebase.
- Conflicts: none. The merge was clean, no side-pick, no `--ours/--theirs`. All main-side hunks are present.
- `git diff origin/main HEAD -- app tests` before re-pinning showed only round 1's `showSides` (+11) and `SIDE_CHECKS` (+20) edits. SIDE_CHECKS and the mobile UX tests pass.
- Parity (merged harness `scripts/parity_hash.py`, harness hash `9bbe1a503f36136f`, synthetic index, uncommitted record-diff script run on a `git archive` of `origin/main` and on this head): the only differing records are `/static/app.js` in `http` and in `no-church` (225 records each), body sha256 `0e21b3b3e2e072c9ec2d568da0028a56b15d337feb0d3f981e2e27a6556dac62` (= `git show origin/main:app/static/app.js | sha256sum`) to `3a08bf550d5208b3eddecdd2a8a3b5006aab90a899be1c0dd12732d37a00dd9f` (= `git show HEAD:app/static/app.js | sha256sum`). `in-process` (212), `in-process-no-health` (211), `search+sermon` (96), `side` (93) and `church` (22) have 0 differing records; `/` is identical. On main the script reproduces the old pins exactly.
- Re-pinned `PINNED["http"]` `b198c5b3546ef6eb` to `a698343bd83ea865`, `PINNED["no-church"]` `29f0c7e50f011dea` to `153267cefae0f1df`, `PINNED_NO_WHY["http"]` `87598c3cb97e7a4e` to `692ae6d888dc2fb7`, `PINNED_NO_WHY["no-church"]` `cc0f371a6b6cdf27` to `15c9ee63ad285b64`. No other key changed. The move is intended.
- docs/PARITY.md: added a history row naming PR #103 with the old and new values. **Deviation:** the reference table there holds reviewer-box values (real Wesley index + ONNX, main `3aef7ca`). They cannot be recomputed here (the real index is off limits under rule 5), so the table rows and the host gate command were left as they are, and the new row says the reviewer box must re-take `http` and `no-church` on the merged main. I did not invent box values.
- Cites re-read on this head: `docs/DEMO-SCRIPT.md:28` (`app.js:217-235` is `whyLine`, `:312-313` is the `why` line in `renderCard`), `:42` (`app.js:338` is `lowHidden`), `docs/SUBMISSION-DRAFT.md:34` (same cites). All hold, no re-pin. `app/server.py` and DEPLOY.md are untouched.
- Runs: all cache env vars under one `mktemp -d` under `/tmp` (`PREACHED_GUARD_REAL_SRC` unset, `HOME` for children there too).

| Mutant (alone, run, revert) | `tests.test_app_js tests.test_mobile_ux` | `cmp` after revert |
|---|---|---|
| (i) delete new `setText("confidence", ...)` | red (failures=1) | identical |
| (ii) delete new `setText("note", ...)` | red (failures=1) | identical |
| (iii) drop the `showResults` condition | red (failures=1) | identical |
| (iv) `aria-live` on `section.side-col` | red (failures=1) | identical |

## Round 3: CTO review r1 must-fixes MF1 to MF3 (99-XX2-PR103-R1-MF1-MF3), report r2

Superseded on parity: rounds 1 and 2 above predate MF1. Round 1 says #97 is unmerged and `PINNED` does not exist, and round 2's "Deviation" bullet says the reviewer-box rows were left alone. Both are history now; the box rows are re-baselined below (review nit N1).

- Start: `origin/fix/w5-a11y-side-notes` = `3c9b0ebb81e10723c2f58d46093fef4fccd00b31` (matches the review head), checked out in a fresh worktree under `/tmp`, status clean.
- Commits: `b989d70` (MF1 + MF2), then `e891580198269695cea0716612d706c164063da0` (MF3 merge of `origin/main` `2c8936583d3939ea5a8e5ae39c2af6eb62d7cbac`), then this report commit. The final head sha40 is in the hand-off message.
- No `app/` change: `git rev-parse HEAD:app/static/app.js` = `3de946265d9cfd31e42e85fbf35a73cae8af9033` (blob `3de9462`), before and after every mutant.

### MF1 (docs/PARITY.md)

- (a) `docs/PARITY.md:66`, `:67`: `http` `e21a19b25cc1af12` / `5acbc46ef2a6794d`, `no-church` `1601bf8f271e5192` / `eb3d32449ac95d39`.
- (b) `docs/PARITY.md:74`: the provenance sentence, verbatim, directly under the hash table.
- (c) `docs/PARITY.md:82`: the last three sentences of the PR #103 history row are replaced with the brief's text (pre-#103 box values `29e0c0786acacc68` / `b72c4dec54111ca1`, `218d30828042a711` / `f76209cb54d87862`).
- (d) `docs/PARITY.md:115`: `--expect http=e21a19b25cc1af12 --expect no-church=1601bf8f271e5192`.
- (e) Applied in `## PR BODY` below. The old sentence appeared only there.

### MF2 (tests/test_app_js.py SIDE_CHECKS)

- (c) `tests/test_app_js.py:665`: the `noFocusMove(label)` helper runs `eq(nodes.note.focused, false, …)` and `eq(nodes.confidence.focused, false, …)`. It is called after every `showSides` call and the toggle re-render, at `:672`, `:692`, `:703`, `:709`, `:723` and `:731`.
- (b) `:719`–`:735`: `hideLowConfidence = false` (`:719`). The earlier `toggleLowConfidence()` left it on, so this resets it.
  - Two-side `#note` with `classicBm25` + a church side that has results, `abstain: true` and its own `note`. Exact string `"Classic library: John Wesley: <classic note> Your church (sample data): <church note>"` (`:724`–`:727`).
  - Two-side `#confidence` with classic `confidence: { level: "weak", note: null }` + `churchLow`. Exact string `"Classic library: John Wesley: " + MESSAGES.weak + " Your church (sample data): " + MESSAGES.low` (`:732`–`:735`).
- (a) `:737`–`:742`: `showResults` on a classic payload with `note` set and `abstain: true`, after the sides. It asserts:
  - `#note` is the raw note,
  - `#confidence` is `MESSAGES.low`,
  - `nodes.sides.hidden === true`.

Mutation table. Each mutant was applied alone to `app/static/app.js`, then `tests.test_app_js tests.test_mobile_ux` was run, then the file was reverted. After each revert, `cmp` against the pre-mutant bytes was identical. The "old tests" column runs the same mutant against `tests/test_app_js.py` from `3c9b0eb`.

| Mutant | New tests | First failing assertion | Old tests (3c9b0eb) | `cmp` after revert |
|---|---|---|---|---|
| (i) delete `setText("confidence", …)` | **red** | side banner announced in .notices | red | identical |
| (ii) delete `setText("note", …)` | **red** | fallback note announced in .notices | red | identical |
| (iii) drop `&& showResults === true` | **red** | hidden low side adds no banner | red | identical |
| (iv) `aria-live="polite"` on `section.side-col` | **red** | column node has no aria-live | red | identical |
| viii join with `""` (both joins) | **red** | two notes: classic then church, single-space join | survives | identical |
| ix `states = [churchState, classicState]` | **red** | two notes: classic then church, single-space join | survives | identical |
| xi `document.getElementById("confidence").focus()` after the write | **red** | low church side: #confidence not focused | survives | identical |

The two string assertions catch viii and ix independently. With the two-notes assertion deleted, viii and ix still go red, on "two banners: classic then church, single-space join". The MF2(a) classic-view assertions pin `showResults` behaviour; they are not meant to catch these `showSides` mutants.

### MF3 (merge origin/main, #105)

- `git merge --no-ff origin/main` (`2c89365`). There was no rebase and no `--ours`/`--theirs`.
- One conflict, in `docs/PARITY.md`, between the 83121da history paragraph and `## Host gate command`:
  - ours: the PR #103 history row plus the unchanged base "Other hosts" paragraph.
  - theirs: the omarchy block plus the rewritten "Other hosts" paragraph.
- Hand-edited into this order:
  1. the 83121da paragraph (`:80`),
  2. the PR #103 row (`:82`),
  3. the omarchy block (`:84`–`:106`),
  4. main's rewritten "Other hosts" (`:108`).
- The base "Other hosts" paragraph that ours carried unchanged is replaced by main's rewrite. Every other hunk from both sides survives. The commit message lists the hunks.
- Omarchy cells `docs/PARITY.md:98`–`:99`: `http` `69e8cbb13791fdb1` / `dfbfbf9dc21de9c1`, `no-church` `5822f9705a1ae242` / `83261d92460534e0`.
- History sentence `:106`: the pre-#103 omarchy values `7d0e6ba49fe8628c` / `2185fbe08c600a0a` and `85c8322489268a44` / `514aaa45710f9854`, naming #103, tree `ebc058d`+`3c9b0eb` and sandbox merge `2ca2916f`. These values come from the CTO brief; I did not re-take them in this sandbox.
- Main survives: `git diff origin/main HEAD` outside the five PR files is empty. All other merged files are byte-equal to main.

### Results (content head `e891580198269695cea0716612d706c164063da0`, host `preached-sandbox`)

- Focused `tests.test_app_js tests.test_mobile_ux`: `Ran 19 tests, OK`. With `tests.test_parity_hash` added: `Ran 35 tests in 17.913s, OK`.
- Full: `Ran 1193 tests in 260.394s, OK (skipped=15)`, with zero `test_every_cited_file_line_holds_its_string` failures.
  - All 15 skips are data-gated: no real index/ONNX in the temp `PREACHED_CACHE`, `PREACHED_GUARD_REAL_SRC` unset, and no infra yaml.
  - The in-tree `.venv` is a symlink to the scratch venv, per the harness note.
- Env: everything is under one `mktemp -d` (`/tmp/pr103r2.8KHS`): `PREACHED_CACHE`, `PREACHED_ONNX_DIR`, `HF_HOME`/`HF_HUB_CACHE`/`HUGGINGFACE_HUB_CACHE`, `DENO_DIR`, `XDG_CACHE_HOME`, `TORCH_HOME`, `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, `UV_PROJECT_ENVIRONMENT`, `HOME` and `TMPDIR`. Also set: `ORT_DISABLE_TELEMETRY=1`, `HF_HUB_OFFLINE=1`, `PREACHED_REQUIRE_DENO=1`; `PREACHED_GUARD_REAL_SRC` unset. No `Microsoft`/`DeveloperTools` dirs were created.
- `/cache` (`find /cache -xdev -printf '%p\t%s\t%T@\n' | LC_ALL=C sort`): 139814 lines before and after, sha256 `d2909d2092c778381ae84725728bd3df1c73e7ccd6ac1797d16d7eb7d566ceb7` both, diff empty. Nothing under `/cache` was opened.
- Cites: `app/` is unchanged, so `docs/DEMO-SCRIPT.md:28,:42` and `docs/SUBMISSION-DRAFT.md:34` still hold. DEPLOY.md and `tests/test_deploy_alerts.py` are untouched, and the scope includes no server change.

`git diff --stat origin/main...HEAD` (final):

```
 app/static/app.js                  |  11 ++
 docs/PARITY.md                     |  16 ++-
 reports/W5-A11Y-PR-C-SIDE-NOTES.md | 248 +++++++++++++++++++++++++++++++++++++
 tests/test_app_js.py               |  55 ++++++++
 tests/test_parity_hash.py          |   8 +-
 5 files changed, 328 insertions(+), 10 deletions(-)
```

## PR BODY

Side by side (F-03): the low-confidence banner and the BM25-only fallback note are now written into the existing
`#note` and `#confidence` nodes in the `.notices` polite live region, as classic view does. Text is
`heading + ": " + note`, one space between sides; the confidence note only while that side's passages are shown.
Only `showSides` changes. Column paragraphs, `#status`, `resetState`, `setBusy`, `index.html` and CSS are unchanged.

Round 3 (CTO r1 must-fixes):
- MF1: the `docs/PARITY.md` reviewer-box `http`/`no-church` rows are re-baselined, with history kept.
- MF2: new `SIDE_CHECKS` cover the two-side order and join, no focus moves, and classic view after sides.
- MF3: merged `origin/main` `2c8936583d3939ea5a8e5ae39c2af6eb62d7cbac` (#105). The one `docs/PARITY.md` conflict was hand-resolved, and the omarchy `http`/`no-church` cells were moved.
- `app/static/app.js` is unchanged this round (blob `3de9462`).

Branch note: the brief names `fix/w5-a11y-side-notices`; this PR is `fix/w5-a11y-side-notes`.

```
 app/static/app.js                  |  11 ++
 docs/PARITY.md                     |  16 ++-
 reports/W5-A11Y-PR-C-SIDE-NOTES.md | 248 +++++++++++++++++++++++++++++++++++++
 tests/test_app_js.py               |  55 ++++++++
 tests/test_parity_hash.py          |   8 +-
 5 files changed, 328 insertions(+), 10 deletions(-)
```

- Focused (`tests.test_app_js tests.test_mobile_ux tests.test_parity_hash`): `Ran 35 tests in 17.913s, OK`. Run on content head `e891580198269695cea0716612d706c164063da0`, host `preached-sandbox`; only the report changed after it.
- Full: `Ran 1193 tests in 260.394s, OK (skipped=15)`, same sha and host. No `test_every_cited_file_line_holds_its_string` failure.
- Mutants: each was applied alone, run, and reverted, with `cmp` identical every time. viii, ix and xi survived the previous head's tests.

| Mutant | Result |
|---|---|
| (i) delete confidence `setText` | red |
| (ii) delete note `setText` | red |
| (iii) drop `showResults` condition | red |
| (iv) `aria-live` on `section.side-col` | red |
| viii join with `""` | red |
| ix church before classic | red |
| xi focus `#confidence` after write | red |

- Parity (#97 merged; harness `9bbe1a503f36136f`):
  - CI pins (synthetic index): `PINNED["http"]` `b198c5b3546ef6eb` to `a698343bd83ea865`, `PINNED["no-church"]` `29f0c7e50f011dea` to `153267cefae0f1df`, `PINNED_NO_WHY["http"]` `87598c3cb97e7a4e` to `692ae6d888dc2fb7`, `PINNED_NO_WHY["no-church"]` `cc0f371a6b6cdf27` to `15c9ee63ad285b64`.
  - Record level: the only differing records are `/static/app.js` in `http` and `no-church`, body sha256 `0e21b3b3e2e072c9ec2d568da0028a56b15d337feb0d3f981e2e27a6556dac62` (main) to `3a08bf550d5208b3eddecdd2a8a3b5006aab90a899be1c0dd12732d37a00dd9f` (head).
  - The move is intended. docs/PARITY.md has a history row naming PR #103. The reviewer-box `http`/`no-church` rows were re-taken by the CTO review on trial merge `f17e4f5` and are applied above. Box: `http` `e21a19b25cc1af12` / `5acbc46ef2a6794d`, `no-church` `1601bf8f271e5192` / `eb3d32449ac95d39`.
  - Omarchy block: `http` `69e8cbb13791fdb1` / `dfbfbf9dc21de9c1`, `no-church` `5822f9705a1ae242` / `83261d92460534e0`, with the pre-#103 values kept as history.
- `/cache` snapshot: 139814 lines before and after, sha256 `d2909d2092c778381ae84725728bd3df1c73e7ccd6ac1797d16d7eb7d566ceb7` both, diff none.
- DEPLOY cites are untouched (no file cited in docs/DEPLOY.md changes).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
