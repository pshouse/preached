# W3-SQLITE-DOC-NIT

CTO #55 nit: the `scan_sqlite_use` docstring (`tests/test_hard_conditions.py`) now says that a
`sqlite3`/`_sqlite3` string and the `<name>.sqlite3` attribute each count as one raw open.

Behaviour was read, not changed. Two details the docstring now states, which go slightly past the nit's sentence:
- The string rule also matches strings starting `sqlite3.` or `_sqlite3.`, not only the exact names.
- Both rules also set `imports`, so each is an import plus one raw open.

Tests: 987 run, OK, 0 skipped (`unittest discover -s tests`, PREACHED_CACHE=/cache). `uv lock --check` passes.
