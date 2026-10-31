# W3-DEPLOY-BENCH-NITS

Branch `chore/w3-deploy-bench-nits`, from origin/main b01c1f0. Precondition: #18 is merged (`origin/feat/w3-deploy-prep` is an ancestor of origin/main; `gh` is not installed here, so checked with git). feat/w3-deploy-prep was not touched.

## What was done
| item | change | test |
| --- | --- | --- |
| #18 S1 | `app/server.py` installs a SIGTERM handler (exit 143) on the line after the `atexit.register`, so the bytecode dir is removed on SIGTERM during start-up imports. `main` still swaps in its own handler for serving. DEPLOY.md updated. | `test_sigterm_during_startup_imports_removes_bytecode_dir` (a shadow `argparse` signals the process mid-import; exit 143, no `preached-pycache-*` left) |
| #18 S2 | DEPLOY.md wording as given by the CTO (added files are in the class of an edited `.py`) | docs |
| #18 S3 | DEPLOY.md: `$TMPDIR` set but unwritable falls back to `/tmp` (next to the SIGKILL note) | docs |
| #18 S4 | `_plant_bytecode` canary is relative (`open('canary', 'w').close()  #`); test 2 canary moved to the bundle dir (its cwd); test 1 also asserts the bundle-dir canary is absent after `_start` | `test_planted_bytecode_does_not_run`, `test_direct_start_ignores_planted_bundle_bytecode` |
| #28 S1 | `reports/BENCH-API-FIX.md` labels the shas: ef4d4eb -> 0c6718a9c792, fc0492a/post-#22 -> 2a42a2118872 | n/a |
| #28 nit: empty `PREACHED_RATE_LIMIT` | unset or blank (either rate-limit var) is lifted to 1000000; a set value is kept | `test_unset_and_empty_rate_limits_are_lifted`, `test_explicit_rate_limit_is_kept` |
| #28 nit: U+2028 | `queries()` splits on `\n` only | `test_u2028_inside_a_query_does_not_split_the_row` |
| #28 nit: stderr path | every bench error after the child starts ends `; see <stderr path>` | `test_http_error_exits_with_status_body_and_stderr_path` |
| #28 nit: env + HTTPError tests | `BenchApiMainTests` runs `main()` against a fake loopback server | the same tests |
| #26 r2 probes | The probe scripts themselves are not in the repo (they live outside it), so I could not edit them. Added `scripts/synthetic_sermon.py`: writes a WAV with a noise burst under each word plus a church-path transcript whose words are those bursts, so the unchanged coverage gate finds no span. Nothing in the product was loosened and no test-only path exists. The probes should build their sermons with it. | `tests/test_synthetic_sermon.py` (clean pair passes; dropping 40 s of words opens a span). Also ran the documented flow by hand on a scratch cache: asr_chunks -> `--ack-review` -> "approved probe-1". |

## How to run the probes
See the docstring of `scripts/synthetic_sermon.py`: set `PREACHED_CACHE` to a scratch dir and `PREACHED_PRIVACY`, generate the pair, run `align/asr_chunks.py ... --audio-dir`, then `import/youtube.py --library church --ack-review <id>`, then serve with `--index`. For the adjacent-chunk probe, pass `--text-file` with the wanted text.

## Results
- Full suite: 680 tests, OK (86 s), run with `PYTHONPATH=<worktree>/src`. Without it, the shared `.venv` (editable install pointing at the main checkout) gives 2 environmental failures that pass on main.
- `uv lock --check`: OK (Resolved 79 packages).
- Head SHA: see the PR / `git rev-parse HEAD` on the branch.

## Open issues
- The probe scripts need a one-line switch to this generator; I could not see them.
- Dependencies added: none.
