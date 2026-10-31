# W3-DEPLOY-REGEX-PIN

New file `tests/test_deploy_regex.py` pins every backticked `^...$` regex in `docs/DEPLOY.md` to a real emitted log line. `docs/DEPLOY.md` and `tests/test_deploy_alerts.py` are untouched (PRs #69 and #72 are re-pinning cites there).

## How it works
- The parser reads every backticked `^...$` in DEPLOY.md. Table rows are named by their first cell. Prose is named by `DEPLOY.md:<line>`.
- It fails if nothing is found. `test_the_parser_finds_patterns` also requires the D2b and stamp rows. Each pattern checked is printed to stderr and used as the subTest name.
- The line format is not retyped. `main()` is run with `logging.basicConfig` patched to capture its `format=` and then abort. That format goes into a `logging.Formatter`, and each record is rendered with `formatMessage`. That is the one line an alert sees, without a traceback.
- The producer is chosen by row name, not by regex text. A mutated regex therefore fails on the fullmatch assertion, not on a missing producer. An unknown pattern fails with "no producer", never a silent skip.

## Patterns found (3)
| Name | Regex | Line produced by | Real or format-only |
| --- | --- | --- | --- |
| D2b (table) | `^ERROR index status unreadable after reload; serving BM25 only$` | The `test_obs_gaps` fixture (real `App`, real index, dense side loaded) with `app.server.index_stamp` raising `OperationalError`. The real `App.search`, `_refresh_if_stale` and `_serve_keyword_only` run. | Real |
| stamp (table) | `^ERROR could not read the index stamp$` | Same drive. The real `App._capture_stamp` logs it. | Real |
| DEPLOY.md:822 (prose, not in an alert table) | `^INFO \S+ \S+ GET /api/side 200$` | The real handler class from `make_handler`, built with `object.__new__` (no socket), then the real `log_request(200)`. | Real |

No pattern needed the format-only fallback. All three fullmatch their real line: `'ERROR index status unreadable after reload; serving BM25 only'`, `'ERROR could not read the index stamp'`, `'INFO 203.0.113.9 203.0.113.9 GET /api/side 200'`. **No findings.** Nothing in DEPLOY.md was changed.

## Mutant proof (DEPLOY.md edited temporarily, then reverted with `git checkout`)
- D2b: `reload` changed to `relaod` in the regex. FAIL: `D2b: '^ERROR index status unreadable after relaod; serving BM25 only$' does not fullmatch real line(s) ['ERROR index status unreadable after reload; serving BM25 only']`
- stamp: `stamp` changed to `stamq`. FAIL: `stamp: '^ERROR could not read the index stamq$' does not fullmatch real line(s) ['ERROR could not read the index stamp']`
- My first D2b mutant attempt did not apply (wrong sed), so the run was OK. I redid it correctly and it fails as shown above.
- `git status` confirms DEPLOY.md is reverted.

## Full suite
`PREACHED_REQUIRE_DENO=1 PREACHED_CACHE=/cache uv run python -m unittest discover -s tests`: **Ran 1007 tests, OK, 0 failures, 0 errors.** `uv lock --check`: OK (no new deps).

Note: the new test builds the `test_obs_gaps` fixture by instantiating its TestCase and calling `setUp`. It imports the module rather than the class, so discovery does not run those tests twice.
