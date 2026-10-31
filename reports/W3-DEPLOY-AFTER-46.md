# W3-DEPLOY-AFTER-46

#45 (`docs/w3-deploy-consolidate`) merged with `origin/main` (`96195be`, #46) by a merge commit. #45's Part 1/2/3 layout and its r1 fixes are kept.

## What was done, by item

- **Merge.** One conflict in `docs/DEPLOY.md` (Part 2 "What the server needs"). Resolved to #45's layout. #46's church paragraphs live only in Part 3 ("How the church gate works"), not in Part 2. No "refused at start" wording remains for WAL or writer locks.
- **1. HC1.** Checklist item reads "fixed in #46, pending CTO deploy verification" and stays OPEN. The interim-rule paragraph and the "Refused at start … writer's lock or WAL-mode file" text are removed. The start-time busy file is documented as `INFO church side paused: <reason>` (`app/server.py:1463`), retried after 1 s doubling to 30 s (`CHURCH_RETRY_FIRST_S`/`CHURCH_RETRY_MAX_S`, `:270-271`), returning without a restart.
- **2. Searcher build.** One line, no traceback, `app/server.py:886`, in the gate bullets and in the alert table (row 2).
- **3. New row 3.** `ERROR church side refused: the church file could not be opened (<exc>)`, `app/server.py:1419`, PAGE group.
- **4. Obsolete rule.** Old rule 1 removed; WAL/lock at start are pause lines (`library.py:883-884`, `:895-896`, `:921-922`, `:962`). The "Other lines" WAL row is a pause line. A successful retry's `INFO church side: <slug>, read-only…` is noted as not a restart marker. HD1 (startup `paused` logged before `listening on`) is marked OPEN in Part 3 and on the `listening on` row.
- **5. Line refresh.** Every `file:line` was re-grepped on the merged tree; the grep won where it differed from the map (WAL text is `library.py:883-884`, not `:882-883`; the lines the old map put at 1833…2206 for `request failed:` are 1952, 1957, 2002, 2004, 2064, 2304, 2325). The "grep-verified" sentences name main `96195be`.
- **6. Tests.** `tests/test_deploy_alerts.py`: `WRITER_LOCK_AT_START` is now the pause reason; the start-time lock test asserts `ChurchPaused` and no ERROR log; `SEARCHER_NOT_BUILT` includes `(RuntimeError: boom)` and the test (renamed `…_is_refused_in_one_line`) asserts exactly one line with no traceback. `CITED` is refreshed (S2 pins pass).

## How to run

`uv run --frozen python -m unittest discover -s tests -q`; `uv lock --check`.

## Results

967 tests, OK (`unittest discover`); `uv lock --check` passes.

## Open

HD1 (code fix queued separately); HC1 pending CTO deploy verification. No dependencies added.
