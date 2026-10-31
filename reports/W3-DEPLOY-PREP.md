# W3-DEPLOY-PREP: package the lean CPU server

Branch `feat/w3-deploy-prep`. PR #10 merged to `main` as `2ad5550` while this work was in progress. That merge commit has the same tree as `origin/feat/w3-cpu` at `0fee69c`. This branch was fast-forwarded onto `origin/main` before the commits below. Nothing here contacted the Sprite or read a deploy credential.

CPU for the smoke: 12th Gen Intel Core i9-12900K, 24 logical CPUs. One ONNX intra-op thread. The GPU was not used.

## What was done

Serve-time footprint, recorded in `docs/DEPLOY.md`:

- Python 3.12 (this machine: CPython 3.12.16). `requires-python` is `>=3.12,<3.14`.
- `uv sync --frozen --no-dev --no-default-groups` installs 21 packages. The smoke venv listed anyio 4.15.1, click 8.5.0, filelock 4.2.4, flatbuffers 25.12.19, fsspec 2026.9.0, h11 0.16.0, hf-xet 1.8.0, httpcore2 2.16.0, httpx2 2.16.0, huggingface-hub 2.4.0, idna 3.20, numpy 2.5.4, onnxruntime 1.31.1, packaging 26.3, preached 0.1.0, protobuf 7.36.2, pyyaml 6.0.3, tokenizers 0.23.3, tqdm 4.70.1, truststore 0.10.5, typing-extensions 4.16.0.
- A query imports the stdlib, numpy, onnxruntime, and tokenizers. huggingface-hub is installed because tokenizers depends on it. The serve path does not import it. `tests/test_deploy.py` fails if torch, torchvision, torchaudio, whisper, faster-whisper, ctranslate2, sentence-transformers, transformers, yt-dlp, onnx, onnxscript, Pillow, av, nvidia, or huggingface-hub appear in `sys.modules` after the serve imports.
- ONNX revision `47ea694b257b703fee9253d75c2b1f2985180498`. `model.fp32.onnx` sha256 `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`. `tokenizer.json` sha256 `6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30`. `manifest.json` and `pooling.json` are copied with them. `model.int8.onnx` is not copied.
- Index: `/cache/index/wesley.sqlite`, 8,383 chunks, `chunks_sha256` `198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2`. Opened `mode=ro` with `query_only`.
- Static allowlist unchanged: `app.js`, `app.css`, `favicon.svg`, plus the page `index.html`.

`/healthz` still returns the old keys. It also returns `disabled`, `index_version` (the `chunks_sha256` meta value when that value is 64 lowercase hex), and `model_sha256` (the digest of the fp32 graph just verified). A value that is not 64 hex characters is `null`. BM25 fallback leaves `model_sha256` null. The kill switch (`PREACHED_DISABLED` in `1,true,yes,on`, or a kill file) returns HTTP 503 and `{"ok": false, "disabled": true}` with no other fields.

In-app limits added in stdlib: headers over 8,192 bytes get 431; 120 requests per 60 seconds per socket IP in code, 60 per 60 seconds when started by `scripts/serve.sh`. `X-Forwarded-For` is ignored. A full table of 4,096 active keys refuses a new IP. Access logs are IP, method, path, status. The query string is stripped. A failed request logs the exception type.

`scripts/build-bundle.sh` writes a directory and a sibling `.tar.gz`: the serve-time source list, `uv.lock`, `requirements-serve.txt` from `uv export --frozen --no-dev --no-default-groups`, the fp32 model, and one index. The manifest is sha256sum format, sorted, and excludes itself, `KILL`, bytecode, and `.venv`. The tar is ustar, owner 0, mtime `2026-10-30 00:00:00` UTC, `gzip -n`. `scripts/serve.sh` binds `PREACHED_HOST` / `PREACHED_PORT` (default `127.0.0.1:8000`), forces ONNX fp32, one thread, and offline Hub. The first cut unset four token names and allowed root when `PREACHED_ALLOW_ROOT=1`. The fix-up below replaces that with `exec env -i` and an unconditional root refusal.

The first cut kept a script allow-list and a path denylist (`cc-speech`, `gaston`, `youtube`, `church`), and `app/server.py` opened whatever library it was given. YouTube tests in `tests/test_server.py` still build a library named `sample` inside the test harness. The fix-up deletes the script lists and calls `check_servable`.

`docs/DEPLOY.md` is the runbook. Human steps are marked **HUMAN**: upload, extract, `uv sync` as the service user, the public `Host` list, rollback by switching directories, and rotation of the Sprite admin credential. The app has no API key.

## How to run

From `/work/preached/.worktrees/feat/w3-deploy-prep`:

```bash
uv run python -m unittest discover -s tests
scripts/build-bundle.sh /tmp/preached-bundle
cd /tmp/preached-bundle && sha256sum -c MANIFEST.sha256
uv sync --frozen --no-dev --no-default-groups
PREACHED_HOST=127.0.0.1 PREACHED_PORT=8000 scripts/serve.sh
scripts/smoke-bundle.sh
```

`scripts/smoke-bundle.sh` builds into a temp directory, syncs a fresh venv there, checks that `/work/preached` is not on that venv's path, starts `serve.sh` with a scrubbed environment, hits `/healthz` and 21 hybrid searches, prints p50 and RSS, then deletes the temp directory and stops the server.

Sprite update, rollback, and secret rotation are in `docs/DEPLOY.md`. They are human steps. The admin API is https://api.sprites.dev (OpenAPI at `/openapi.json`). The fix-up runbook does not publish a public app hostname. This repo does not call the API.

## Results and numbers

`uv run python -m unittest discover -s tests` on this tree: **301 tests, 21.514s, OK**. Thirteen of those are in `tests/test_deploy.py` (health identity, rate limit, kill switch, header cap, log hygiene, import guard, bundle refusal, reproducible tar, `serve.sh` refusing library `sample`).

Smoke, this machine, 1 ORT thread, bundle venv only. Query `what did Wesley say about Christian perfection`, `k=5`, `mode=hybrid`, `library=wesley`. The first of 21 calls is dropped. p50 is the mean of the two middle values of the remaining 20.

| measurement | value |
| --- | --- |
| health chunks | 8,383 |
| index_version | `198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2` |
| model_sha256 | `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` |
| backend / fallback | onnx / false |
| first hit | `wesley-040` Christian Perfection |
| p50 client | 65.1 ms (sorted neighbors 65.0 and 65.2) |
| p50 `took_ms` | 62.5 ms (sorted neighbors 62 and 63) |
| client min / max | 59.9 ms / 88.5 ms |
| RSS at listen, after model load | 1,582,137,344 bytes (1,508.8 MiB) |
| RSS after the 21 queries | 1,636,610,048 bytes (1,560.8 MiB) |
| manifest sha256 (of `MANIFEST.sha256`) | `2de49fa3ec8f77042185bbf501d07ba1219fb242d4d761d2f5f3b9462a8da498` |
| tar.gz sha256 | `f9da3aae7598d2d7903413f2bf5b44fdc03b4ad22b2142f04953043d855aca79` |
| uv sync | 21 packages in 59 ms |

Client samples, ms: 88.5, 61.8, 74.4, 60.7, 69.4, 65.6, 68.4, 62.2, 62.8, 63.0, 60.1, 64.1, 60.9, 74.0, 71.0, 68.1, 65.9, 65.2, 65.0, 59.9.

`took_ms`: 85, 59, 73, 59, 67, 64, 66, 61, 61, 60, 58, 63, 60, 71, 68, 66, 63, 62, 62, 59.

RSS is VmRSS. The startup figure is printed by the server after the model is loaded and before `serve_forever`. The later figure is `/proc/<pid>/status` after the queries. `reports/W3-CPU.md` recorded a different harness: ONNX fp32 API hybrid, 1 thread pinned to CPU 0, p50 56.5 ms, RSS after load 992,342,016 bytes (946.2 MiB). These two runs are not the same measurement. The smoke also confirmed `libonnxruntime` mapped in the server and did not find libtorch, whisper, ctranslate2, libcublas, or libcudnn.

`uv sync` in `/tmp` warned that hardlinks failed and copied the wheels instead. The install finished. `UV_LINK_MODE=copy` silences that warning when the cache and `/tmp` are different filesystems.

The manifest and tar hashes are from that smoke. `scripts/build-bundle.sh` is not a file inside the bundle, so sending `uv export` stdout to `/dev/null` does not change them. `docs/DEPLOY.md` and this report are not in the bundle either. The temp directory was removed and the server process was gone after the smoke.

## Open issues, risks, and exclusions

- The first cut left library checks in the scripts only. The fix-up puts `check_servable` in `app/server.py` as well. Church libraries, YouTube imports, `cc-speech.sqlite`, and Gaston Community Church stay unpublished.
- int8 is on disk under `/cache` and is not shipped. The bundled manifest no longer names it. The loader still refuses it at runtime.
- Trusted-proxy `X-Forwarded-For` keying, plus a global backstop in front of the per-IP cap, is not in this PR. It is required before anything goes public. The process ignores `X-Forwarded-For`.
- The first cut told the operator to bind `0.0.0.0` and add a public Host. The fix-up runbook keeps loopback or an existing Tailscale address. A public bind is a separate gated step.
- Non-root, a read-only mount of the index and model, and TLS are host steps in `docs/DEPLOY.md`. `app/server.py` and `serve.sh` refuse uid 0. There is no `PREACHED_ALLOW_ROOT`. `serve.sh` clears the write bit on a bundle index.
- The exact Sprites CLI flags are not in this repo. The runbook does not invent them. It points at the OpenAPI the admin already uses.
- The application has no secret to rotate. The secret is the Sprite admin credential. Rotation steps are marked human. Tokens are not written into the bundle or the server environment.
- The smoke RSS is higher than the W3-CPU 1-thread figure. The gap is not diagnosed here.
- CSP is unchanged. No new model. No church-member data.

## Dependencies added and why

None. The serve install is the existing lockfile with `--frozen --no-dev --no-default-groups`. Direct runtime packages remain numpy, onnxruntime, and tokenizers.

## Fix-up: CTO review of PR #18 (11-W3-DEPLOY-FIX)

Merged `origin/main` (`c95d872`, includes #10 and #14) into `feat/w3-deploy-prep` as `c9e8182`. Merge commit only. The three conflict hunks in `app/server.py` kept both the deploy-prep rate limit and kill file and main's `servable` gate. The paragraphs above are the first cut. Where they disagree with this section, this section is the current behaviour. The smoke latency and RSS figures above were not re-run.

| Item | Commit | Tests and checks |
| --- | --- | --- |
| Secrets: `exec env -i` and an allow-list. `FAKE_TOKEN`, `AWS_SECRET_ACCESS_KEY`, `SPRITE_TOKEN`, and `HF_TOKEN` are absent from the server environment (names only). | `55761d7` | `test_serve_sh_drops_secret_names`, `test_server_refuses_root` (the script contains the literal `env -i`) |
| Tar "file changed as we read it": tar a private `cp --reflink=never` snapshot, not the live tree. | `56ffbf7` | `test_bundle_is_reproducible_and_serve_only`. Real `scripts/build-bundle.sh /tmp/preached-bundle-real` exited 0. |
| Bundled index: SQLite backup API and `journal_mode=DELETE`. Opens `mode=ro` from a non-writable directory. | `56ffbf7` | Same test (no `-wal`, mode `0444`, `journal` `delete`, count 1 from a `0555` directory). Real bundle: 8,383 chunks, journal `delete`, `chunks_sha256` `198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2`, opened `mode=ro` after `chmod 0555` on the bundle root and `index/`. |
| Bundle after #14: `PREACHED_CACHE` is the bundle root, `libraries.py` and the Spurgeon and Edwards manifests ship, build-time import check, script allow/deny lists deleted, `check_servable` is the gate. Unpack as the service user with no group or world write. | `56ffbf7`, `55761d7`, `4219bff` | `test_bundle_is_reproducible_and_serve_only`, `test_refuses_church_and_youtube_libraries`, `test_refuses_a_renamed_church_path_and_a_symlink`, `test_serve_sh_refuses_a_sample_library` |
| Slow-send: global cap 32, per-client cap 4, one 15 s header deadline. Over the cap the accept thread returns 503 and starts no handler thread. | `36a095f` | `test_header_deadline_is_not_per_read`, `test_connection_caps_reject_without_a_handler_slot` |
| `docs/DEPLOY.md` stays on loopback or Tailscale. Going public needs a written threat model, CTO sign-off, Patrick's approval, and a kill-switch drill, in that order. | `4219bff` | Runbook review. The doc does not give `0.0.0.0` or a public Host as the default. |
| Kill switch fails closed on a directory, a symlink, or an unreadable parent. Removing a regular file resumes serving on the next request. `PREACHED_DISABLED` is process environment, so it is not the without-restart switch. | `36a095f`, `4219bff` | `test_kill_switch_fails_closed_on_surprises`, `test_kill_file_stops_search_without_leaking_the_path` |
| Bad request lines do not crash the process. Control characters in the log are escaped. | `36a095f` | `test_bad_request_line_does_not_crash_and_controls_are_escaped`, `test_access_log_drops_the_query` |
| No `PREACHED_ALLOW_ROOT` and no `PREACHED_PYTHON`. `app/server.py` refuses uid 0. | `36a095f`, `55761d7` | `test_server_refuses_root` |
| Bundled manifest drops int8. `PREACHED_BUNDLE_SKIP_PINS=1` is honoured only when the parent command line is the unit tests. | `56ffbf7` | `test_int8_is_removed_from_the_bundled_manifest`, `test_skip_pins_is_ignored_outside_the_tests` |
| Rate limiter: a full table refuses a new client and keeps live keys. `/healthz` shares the bucket. | `36a095f` | `test_full_table_refuses_a_new_client`, `test_healthz_uses_the_same_bucket`, `test_rate_table_drops_idle_keys` |

Real bundle, this machine, Wesley index and the pinned fp32 ONNX files. `sha256sum -c MANIFEST.sha256` matched every file. `gzip -t` passed. Manifest sha256 (of `MANIFEST.sha256`) `4dd28a7957691fe3bd5d9834d73c0859371624c8c62db946baf138c2b1dde5da`. Tar sha256 `c403ea0fbea39cbf87e558b9fd8fa7c9a6c503c80e9e0cc3a08ec573eccef5e5`. These replace the first-cut manifest and tar hashes for the current tree. The p50 and RSS table above is still the first-cut smoke.

`uv run python -m unittest discover -s tests`: **380 tests, 25.924s, OK**.

`uv lock --check`: clean (79 packages resolved). No lockfile change. No new dependencies. No LLM.

Code head: `781e9b4`. This report is the commit after it. `git log -1` on `feat/w3-deploy-prep` is the branch head.

Open, and required before anything goes public: trusted-proxy `X-Forwarded-For` keying plus a global backstop. Not in this PR. `test_per_ip_limit_ignores_forwarded_for` still checks that the header is ignored.

## Fix-up: CTO round 2 of PR #18 (11-W3-DEPLOY-FIX2)

Reviewed head `75cabe24f65317e06c7b636b1e0473e1661154f2`. No merge was required. No rebase, no force-push. The paragraphs above are the first cut and the round-1 fix-up. Where they disagree with this section, this section is the current behaviour. In particular, `serve.sh` does not clear the write bit on a bundle index.

| Item | Commit | Tests and checks |
| --- | --- | --- |
| Must: delete the `serve.sh` mode repair (old lines 82–88). A world-writable bundle is refused by `check_servable`, not chmod'd back to 755/755/444. The script does not follow a `PREACHED_INDEX` symlink and does not fail on a root-owned tree. `docs/DEPLOY.md` no longer says the start script repeats the chmod. | `ee15140` | `test_world_writable_bundle_is_refused_not_repaired` (modes stay 0777/0777/0666, stderr says writable). `test_deploy_doc_modes_and_the_review_rule` (the script contains no `chmod`). |
| Must: the unpack recipe must not be `chmod u=rw,go=r` on every file. That is 0644, so step 5 ran `serve.sh` and exited 126, and the model stayed 0644 while the table says 0444. Directories `0755`, `scripts/serve.sh` `0755`, index and model files `0444`. | `ee15140` | `test_deploy_doc_modes_and_the_review_rule` |
| Must: the #19 human-review rule. The reviewer listens through the whole recording, start to end, before approving a church sermon. ASR word recall on the synthetic set is 0.870 (635/730). | `ee15140` | `test_deploy_doc_modes_and_the_review_rule` (`whole recording`, `0.870`) |
| Should: `bundle_manifest.copy_index` opens the source with `mode=ro`, so the backup cannot write the live index. | `ee15140` | `test_copy_index_opens_the_source_read_only` (source left at 0444, copy is DELETE mode, one chunk) |
| Should: after a 405, or any earlier error, an unread body closes the connection. A POST body is not parsed as a second request. Same bug on main; fixed in `app/server.py`. | `ee15140` | `test_unread_body_is_not_parsed_as_a_request` (raw socket: POST with a body to a GET-only path; also 421 and 413. One status line, `Connection: close`, then EOF) |
| Should: `serve.sh`'s preflight runs under the same `env -i` allow-list as the server. | `ee15140` | `test_preflight_uses_the_scrubbed_environment` (names only: `FAKE_TOKEN`, `AWS_SECRET_ACCESS_KEY`, `SPRITE_TOKEN`, `SPRITES_TOKEN`, `OP_SERVICE_ACCOUNT_TOKEN`, `HF_TOKEN` absent; `PATH`, `HOME`, `PREACHED_CACHE`, `PYTHONPATH` present) |
| Should: the env-absence test names `SPRITES_TOKEN` and `OP_SERVICE_ACCOUNT_TOKEN`. Names only. | `ee15140` | `test_serve_sh_drops_secret_names` |
| Should: `PREACHED_BUNDLE_SKIP_PINS` can be faked by the parent command line. `MANIFEST.sha256` records `# preached-pins-skipped: 0` or `: 1` (`sha256sum -c` ignores the comment). The server refuses `: 1` unless that process itself is the unit tests. `serve.sh` is not. | `ee15140` | `test_skipped_pins_are_recorded_and_refused_outside_the_tests` (bash `-c` whose argv contains `unittest` still builds, the manifest says `: 1`, in-process `check_servable` allows it, `python -c` and `serve.sh` refuse). `test_skip_pins_is_ignored_outside_the_tests` still fails the build when the parent is not the tests. |

`uv run python -m unittest discover -s tests`: **386 tests, 27.304s, OK**. That is the round-1 380 plus the six tests named above.

`uv lock --check`: clean (79 packages resolved). No lockfile change. No new dependencies. No LLM.

Round-2 code head: `ee15140c3cedf05b46f03238936461a1f5714d17`. This section is the commit after it. `git rev-parse HEAD` on `feat/w3-deploy-prep` is the branch head.

Open, unchanged: trusted-proxy `X-Forwarded-For` keying plus a global backstop, before anything is public. Not in this PR.

## Fix-up: CTO round 3 of PR #18 (21-W3-DEPLOY-FIX3) and the main merge

Reviewed head `df81912048289940e7bd60c82aec0dfbea63f441`. First, `origin/main` at `e465ad0` (#10, #14, #12, #17, #19) was merged with a merge commit. No rebase, no force-push. Where this section disagrees with the sections above, this section describes the current behaviour. In particular, `PREACHED_BUNDLE_SKIP_PINS` and the `# preached-pins-skipped` line no longer exist.

| Item | Commit | Tests and checks |
| --- | --- | --- |
| Merge `origin/main` `e465ad0`. Conflicts were in `app/server.py` only: `/healthz` keeps `index_version`, `model_sha256` and `disabled` from this branch plus main's gated `chunks` count and `pending_review`. `check_servable` takes main's `church_gate` signature and keeps the writability check. Right after the merge, 3 bundle tests failed with `ModuleNotFoundError: preached.audio_policy` (must-fix 3). | `8593ac6` | 557 tests, 3 failures, all fixed in `6bae550` |
| Must 1: the pins-skipped marker failed open. **Preferred fix done.** The skip switch is gone from `build-bundle.sh`, `bundle_manifest.py` and the server, and so are `_server_process_is_unit_tests` (the argv0 check) and `pins_skip_problem`. The build always checks the ONNX files against `artifacts.py`. The tests build from a copy of the source whose `artifacts.py` pins small fixture files, so they need no marker. When the server runs from a bundle it checks the bundle once at start and refuses to start on any of these: a missing `MANIFEST.sha256`; a manifest that does not parse (any comment, blank line, case variant, single space, unsorted or repeated line, missing final newline, non-UTF-8 bytes, or a `..` path); a listed file whose sha256 differs; an unlisted file (only `.venv/`, `__pycache__`, `*.pyc` and `KILL` are allowed); or an index that does not resolve to a listed file under the bundle's own `index/` (`PREACHED_INDEX` outside the bundle). | `6bae550` | `test_build_checks_the_real_pins_with_no_switch`: stand-ins fail the build with the unittest process as the direct parent, with and without the old variable, and the old names appear nowhere in the scripts or server. `test_bundle_serves_only_with_its_own_manifest`: a fixture bundle reaches `PREACHED_LISTENING` through `serve.sh`; with no MANIFEST, or with `PREACHED_INDEX` outside the bundle, `serve.sh` exits non-zero. `test_manifest_variants_are_refused`: 11 manifest edits, a tampered file, an extra `sitecustomize.py`, and a symlinked index. `test_bundle_is_reproducible_and_serve_only` (no `#` line in the manifest) |
| Must 2: HTTP desync. Before any route runs: any `Transfer-Encoding`, even an empty one, gets 501. A repeated `Content-Length` gets 400, and so does a signed, comma-list, hex or empty one. So do a header name that is not a token (`Content-Length : 0`), a header line the parser could not take, and an obs-fold continuation. Every one of these closes the connection, so trailing bytes are never parsed as a request. `_has_unread_body` treats all of these as an unread body. | `235f501` | `FramingTests.test_ambiguous_framing_is_refused_and_closed`: raw socket, 15 cases × GET/POST/BREW, each with a smuggled `GET /healthz` after the headers. Every case gets exactly one status line, `Connection: close`, and EOF. Against the pre-fix server, 24 sub-cases fail. `FramingTests.test_plain_zero_length_keeps_the_connection` is the control: clean `Content-Length: 0` does pipeline, giving two 200s. |
| Must 3: the bundle was missing `audio_policy.py`, `privacy.py` and `privacy_data/`. `CODE_FILES` is now derived by `scripts/bundle_files.py list`: it imports the serve entry points (`app.server`, `preached.backends`, `preached.onnx_embed`, `preached.artifacts`, `preached.libraries`) and ships every `app`/`preached` module they load, the data directories inside those packages, and a short fixed list of non-Python files. An `app`/`preached` import anywhere in that code (including lazy imports inside functions) must name a loaded module or `BUILD_ONLY` (`torch_embed`, `embed`), or the build fails. The import check now runs `bundle_files.py check` from the bundle directory with `python -I -B` and fails unless every loaded `app`/`preached` module's `__file__` is inside the bundle. | `6bae550` | `test_bundle_is_reproducible_and_serve_only` (ships `audio_policy.py`, `privacy.py`, `privacy_data/lexicon.txt.gz`; not `asr.py`, `embed.py`, `torch_embed.py`, `transcribe.py`). `test_bundle_import_check_uses_the_bundle_only`: after `audio_policy.py` is deleted from a built bundle, the check fails even with `PYTHONPATH` pointing at the source tree. |

Real bundle, end to end, on this machine: `scripts/smoke-bundle.sh`. It used `/cache/index/wesley.sqlite` and the pinned fp32 ONNX files, so the real pin check passed. A fresh `uv sync --frozen --no-dev --no-default-groups` in the bundle did not trip the unlisted-file check. Health: 8,383 chunks, `backend onnx`, `fallback False`, `index_version 198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2`, `model_sha256 3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`. Search over 20 samples (1 warmup dropped): p50 client 57.7 ms, p50 took 56.0 ms. RSS 1.59 GB at start and 1.65 GB after. Manifest sha256 `7e6ab4fdd0b2a0246daa2f1d4ae607109d156444a749daedde07a4a6fb35fd23`, tar sha256 `2c68a72e502f556961fb93ec1362ba0508c6e0edb24be9d1558257412d95509a`.

`uv run python -m unittest discover -s tests`: **561 tests, 49.9s, OK**. That is the 557 after the merge, with 2 tests replaced and 4 added.

`uv lock --check`: clean (79 packages resolved). No lockfile change. No new dependencies. No LLM.

Notes and limits:

- "Running from a bundle" means the code root has `MANIFEST.sha256`, `index/`, `model/` or `requirements-serve.txt`. A tree with all four removed looks like a checkout and skips the manifest gate. `check_servable`, the writability check and the runtime ONNX pin check still apply to it. Someone who can rewrite the bundle's own `app/server.py` is outside this gate's threat model.
- The manifest gate runs once at start, before the index opens. It does not run on each reload. Reloads still require the same `(st_dev, st_ino)` and re-run `check_servable`.
- `PREACHED_ONNX_DIR` outside the bundle is not refused by this gate. The loader still refuses any graph or tokenizer that does not match the pins in the bundle's `artifacts.py`.
- Out of scope, as briefed: `X-Forwarded-For` keying, slot fairness, the `/healthz` bucket, and RSS.

The round-3 code head is `6bae550`, and this section is the commit after it. `git rev-parse HEAD` on `feat/w3-deploy-prep` is the branch head.

## Fix-up: CTO round 4 of PR #18 (21-W3-DEPLOY-FIX4) and the main merge

Reviewed head `f47601f7f0a3112be981c7af0702e382f1b2dbf9`. First, `origin/main` at `9e5c054` (#16, #21) was merged with a merge commit. No rebase, no force-push. Where this section disagrees with the sections above, this section describes the current behaviour. In particular, `__pycache__` and `*.pyc` are no longer allowed in a bundle, and "running from a bundle" now means the build stamp `PREACHED_BUNDLE` exists.

The bundle checks moved to a new stdlib-only module, `app/bundle.py` (`layout`, `is_bundle`, `bundle_problem`, `onnx_dir_problem`). `app.server` re-exports the names, so existing callers still work.

| Item | Commit | Tests and checks |
| --- | --- | --- |
| Merge `origin/main` `9e5c054`. Conflicts were in `app/server.py` only. All three were "both added": the rate limiter and kill file vs main's church stubs in `App.__init__`; `index_version`/`model_sha256` vs `church` in `/healthz`; `bundle_problem` vs `prepare_church` in `main`. Both sides were kept. | `8c09c1e` | 591 tests OK right after the merge |
| **N1, must: stale bytecode.** Both fixes done. (a) `serve.sh` sets `PYTHONPYCACHEPREFIX=$(mktemp -d ...)` and passes it through `env -i`, so in-tree bytecode is never read, in a checkout as well. (b) `bundle_problem` no longer allows `__pycache__` or `*.pyc`: either one refuses the bundle. (c) Ordering: `serve.sh` now runs `python -I -B app/bundle.py ROOT INDEX` before the preflight. That is a stdlib-only script, so the manifest and bytecode check runs before any bundle module is imported. `main` repeats it for other launchers. | `efa867b` | `test_planted_bytecode_does_not_run`: compiles a same-size edit of `src/preached/paths.py` (a canary that creates a file) into `__pycache__`, then restores the source with its size and mtime. Control: a plain `import preached.paths` with the bundle on the path **does** run the canary. With `PYTHONPYCACHEPREFIX` it does not. `bundle_problem` names the bytecode; `serve.sh` exits non-zero with "bytecode" and the canary never appears. A loose `paths.pyc` is refused too. `test_serve_sh_sets_a_fresh_pycache_prefix`: the prefix is set and passed; the `app/bundle.py` call comes before the `app.server` import; `app/bundle.py` imports only stdlib modules. Mutation check: with the `__pycache__` refusal disabled, the test fails. |
| Should 1: explicit bundle vs checkout. The build writes `PREACHED_BUNDLE` (`preached-bundle 1`, library, model revision) before the manifest, so the stamp is listed. **bundle** = stamp exists, and it must be listed and match. **checkout** = no stamp, `.git` exists, and none of `MANIFEST.sha256`/`index`/`model`/`requirements-serve.txt`. Anything else is refused. | `efa867b` | `test_bundle_needs_its_listed_stamp`: stamp deleted → "no build stamp" (direct, and through `serve.sh`). Stamp, manifest, model and requirements deleted, index moved out → "not a git checkout" (direct, and through `serve.sh`). `.git` added to a bundle with the stamp deleted → refused. Stamp removed from the manifest → "is not in". Stamp edited → "does not match". The existing assertion that the real checkout (`ROOT`, which has `.git`) returns None still passes. |
| Should 2: in a bundle, `PREACHED_ONNX_DIR` must be unset or resolve to `ROOT/model`, otherwise start is refused. `main` sets it to `ROOT/model` when unset. The embed backend must be `onnx` (torch and `preached.embed` are not shipped). | `efa867b` | `test_bundle_refuses_another_onnx_dir`: unit cases (unset, own dir, a copied "rollback" dir, a checkout pointing anywhere). Through `serve.sh`, the other dir is refused and the bundle's own `model/` reaches `PREACHED_LISTENING`. |
| Should 3: a bundle's index is frozen. `App(frozen=True)` (set by `main` when serving a bundle) refuses with 503 until restart if the index stamp or `PRAGMA data_version` changes, or a status read fails. That refusal is sticky and survives `_refuse_unless_servable`. A checkout still reloads in place. The index's `(st_dev, st_ino)` is now captured **before** `bundle_problem` hashes it. | `efa867b` | `FrozenIndexTests.test_bundle_refuses_an_index_change_until_restart`: 200, then a write from another connection, then 503 on `/healthz`, search, and `/healthz` again (the body says only "index unavailable"). `test_checkout_reloads_an_index_change` is the control: the new row is searchable. `test_identity_is_taken_before_the_hash`: a `bundle_problem` stand-in swaps the file during the "hash", and `main` exits with "replaced" before serving. Mutation check: with the identity read moved back after the hash, the test fails. |
| Should 4: RFC 9110 §5.5. A request line containing any byte 0x00–0x1f or 0x7f (apart from its CRLF ending) gets 400 before parsing, and is closed and not logged. A header value containing NUL, CR, LF, 0x01–0x08, 0x0b–0x1f or 0x7f gets 400 and is closed. HTAB and obs-text are allowed. | `efa867b` | `ControlCharacterTests.test_controls_are_refused_and_closed`: 11 raw-socket cases (NUL/SOH/VT/DEL/bare CR in a value, NUL in Host; NUL/TAB/bare CR in the target, NUL in the method, ESC in the version), each followed by a smuggled request. Each gets exactly one 400 and EOF. `test_tab_and_obs_text_in_a_value_are_allowed` is the control (200). `test_bad_request_line_does_not_crash_and_controls_are_escaped` now expects a 400 for `\x01` in the target, and neither the byte nor the target appears in the log. Mutation check: with both checks reverted, 8 sub-cases fail. |
| Should 5: `scripts/bundle_files.py list` fails the build if any shipped module imports `importlib`, or names `importlib`, `__import__`, `x.__import__` or the string `"__import__"`. Current shipped code has none. The lazy `preached.embed` import is only reachable through the torch backend, and a bundle now refuses that backend (should 2). | `efa867b` | `test_build_fails_on_import_by_string`: `import importlib`, `from importlib import ...`, `__import__('preached.embed')` and `builtins.__import__` appended to the shipped `rank.py` each fail `list` with "imports by string" and the file name, and `build-bundle.sh` fails too. |
| Should 6: DEPLOY has a new subsection, "`.venv` is a trust boundary". `.venv/` is outside the manifest; `sitecustomize.py`/`.pth` files and packages in it run before the check; create it with `uv sync --frozen` as the service user, never group- or world-writable, and recreate it on every update. | `1ddd2d6` | `test_deploy_doc_modes_and_the_review_rule` asserts the heading |
| Should 7–8: DEPLOY "Release notes": the new `/healthz` fields (`disabled`, `index_version`, `model_sha256`, and the 503 cases), and the behaviour change of **120 requests per 60 s per socket IP** by default in `app/server.py` (60 per 60 s in `serve.sh`; `PREACHED_RATE_LIMIT`/`PREACHED_RATE_WINDOW_S`). Main had no limit. DEPLOY's bundle section and the `server.py` module docstring describe the stamp, the bytecode refusal, the stdlib pre-check, the frozen index and the control-character rule. | `1ddd2d6`, `57198dd` | the same doc test asserts the 120/60 text and the three field names in the release notes |

Changed existing tests: `test_world_writable_bundle_is_refused_not_repaired` hand-builds an unstamped tree, so `app/bundle.py` now refuses it before the writability check. It still asserts a refusal and unchanged modes. The control-character log test is described in the Should 4 row.

### Numbers

- `uv run python -m unittest discover -s tests`: **601 tests, 65.4 s, OK**. That is the 591 after the merge plus 10 new tests (2 of them are controls).
- `uv lock --check`: clean (79 packages resolved). No lockfile change. No new dependencies. No LLM.
- Bundle build and verify, with the real `/cache/index/wesley.sqlite` and the pinned fp32 ONNX files: two builds gave the same manifest sha256 `17692c19701e87927555e5531362cbed6320d4b57b7be88a6deb0c9add6fd80c` and the same tar sha256 `a4880c6f697f5914c895885dafd0b3632f9bb7ff56e87ecaaf940694509db2ce`. `sha256sum -c MANIFEST.sha256` OK. No `__pycache__` or `*.pyc` in the tree. The stamp reads `preached-bundle 1` / `library wesley` / `model-revision 47ea694b257b703fee9253d75c2b1f2985180498`.
- Serve smoke, `scripts/smoke-bundle.sh` (fresh `uv sync --frozen --no-dev --no-default-groups` in the bundle, then `serve.sh`, so both bundle checks and the frozen App ran): 8,383 chunks, `backend onnx`, `fallback False`, `index_version 198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2`, `model_sha256 3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`. Search over 20 samples (1 warmup dropped): p50 client 56.4 ms, p50 took 55.0 ms. RSS 1.56 GB at start and 1.61 GB after. `smoke ok`.

### Notes and limits

- `serve.sh` hashes the bundle twice (the stdlib pre-check, then `main`). That adds a few seconds to start. It is kept so that a server started without `serve.sh` is still checked.
- The pre-check is itself bundle code (`app/bundle.py`, run as a script with `-I -B`, so no bytecode of its own is read). Whoever can rewrite it, `serve.sh`, or `.venv/` is outside this gate's threat model. DEPLOY now says so for `.venv/`.
- `PYTHONPYCACHEPREFIX` creates one empty temp directory per start. Bytecode writing stays off (`PYTHONDONTWRITEBYTECODE=1`), so it stays empty. `serve.sh` `exec`s the server and cannot remove it.
- The frozen-index check runs on each request (stamp plus `PRAGMA data_version`), as the reload check did before. A same-inode in-place edit made by another process without SQLite (raw bytes) is not caught until the next `check_servable` or restart. The file is mode `0444` in the bundle.
- `__file__`-relative data read lazily at serve time (`search/models.toml`, `search/abstain.toml`, the classics manifests, `preached/privacy_data/`) is in `STATIC_FILES` or the derived data directories. That list is still kept by hand. `bundle_files.py check` loads the Spurgeon and Edwards manifests from the bundle, and a missing TOML fails the serve smoke.

The round-4 code head is `57198dd`, and this section is the commit after it. `git rev-parse HEAD` on `feat/w3-deploy-prep` is the branch head.
