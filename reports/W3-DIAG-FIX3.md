# W3-DIAG-FIX3: PR #42 CTO r3 (MF4, S12, nit)

Branch `docs/w3-retrieval-diag`. Head SHA: given in the hand-off (the report is committed in that head). Started from `4a90502` (origin/main already merged in). `gh` and `sandbox.sh` are not available here, so "PR #42 open" could not be checked; the branch head matched the precondition. No `src/` change; no numbers, index, `eval/questions.jsonl`, grades or #43 sheet touched.

| item | what was done |
| --- | --- |
| MF4 | `diag.py`, `experiments.py`, `prefixes.py`: `import sqlite3` and a plain `sqlite3.connect(<uri>?mode=ro&immutable=1, uri=True)`; the `store.sqlite3` indirection is gone. The three files are in `RAW_CONNECTS` (count 1 each, comment "scratch eval, reports/: mode=ro&immutable=1 on a static index, never shipped"). |
| MF4, §8 | The sentence "it reaches SQLite through `store.sqlite3` because..." is replaced; the committed-file sha256 table has the three new hashes (diag `6bf041ce…`, experiments `ca606acb…`, prefixes `69d175c8…`). |
| MF4, rerun | On a copy of `wesley.sqlite` (`PREACHED_CACHE` pointing at it, never `/cache/index`): `diag.json` (sha256 `a875192f…2c3e1f`) and `experiments.json` are byte-identical to `/cache/w3-retrieval-diag/`; `experiments.txt` and `prefixes.txt` are byte-identical to `reports/w3-retrieval-diag/results/`. The copy's directory held only `wesley.sqlite` after diag and after prefixes: no `-shm` or `-wal`. (The `/cache/w3-retrieval-diag/*.txt` files differ from a fresh stdout at byte 1; I did not investigate, and `results/` is the committed reference.) |
| S12 | `scan_sqlite_use` counts any attribute named `sqlite3` on any name as an import plus a raw open. Five bypass cases added to `test_every_bypass_form_is_seen`: `store.sqlite3.connect`, `preached.store.sqlite3.connect`, `library.sqlite3.connect`, `s.sqlite3.connect` (aliased `from`) and `ps.sqlite3.connect` (aliased `import`), each `(True, 1, 0)`. After the origin/main merge the suite is 971 tests, OK. |
| S12, existing files | No existing file used `<name>.sqlite3`, so the only `RAW_CONNECTS` changes are the three new entries above. |
| Nit | W3-DIAG-FIX.md S6 row: "LEX 6 (superseded by FIX2: LEX 5)". |
| S10 | Skipped as instructed. |

Tests: `uv run python -m unittest discover -s tests`: 940 tests OK; `uv lock --check` unchanged. gitleaks is not installed, so it was not run.

Diff: see `git diff 4a90502..HEAD`. In short: three scripts (import line, helper body, docstring), `tests/test_hard_conditions.py` (+13: scan rule, three `RAW_CONNECTS` entries, three cases), two report edits.
