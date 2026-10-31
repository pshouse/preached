# W3-DIAG-FIX4: CTO #42 round 4 fixes (docs/w3-retrieval-diag)

| Item | Result |
|---|---|
| MF5 | Merged origin/main (76990e8) in commit `fed4aa8`. The only conflict was `test_every_bypass_form_is_seen`; both blocks kept, #46's 21 "PR #37 r3 nit" cases first, then the 5 S12 cases. No #46 case changed. |
| MF6 | In `scan_sqlite_use`, the `ast.ImportFrom` branch now treats `from <module> import sqlite3 [as q]` as an import and binds the name. Cases added: `from preached.store import sqlite3 as q` and `from preached.library import sqlite3`, each `(True, 1, 0)`. Docstring names both forms. `scan_repo()` still equals `RAW_CONNECTS`/`WRITER_CONNECTS` with no allowlist change; `q.Row` alone scans `(True, 0, 0)`. Commit `7b24dc2`. |
| S12c | `_sqlite3` added beside `sqlite3` in the Import/ImportFrom module checks and the string rule; case `import _sqlite3\n_sqlite3.connect('x')` is `(True, 1, 0)`. Same commit `7b24dc2`. |
| S13 | `reports/W3-DIAG-FIX3.md` S12 row now says five bypass cases and gives the post-merge test count (971). |

Tests: `python -m unittest discover -s tests`: 971 tests, OK (run after the MF6/S12c edits). `uv lock --check` passes; no new deps.
