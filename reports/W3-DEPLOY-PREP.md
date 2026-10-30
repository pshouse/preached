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

`scripts/build-bundle.sh` writes a directory and a sibling `.tar.gz`: the serve-time source list, `uv.lock`, `requirements-serve.txt` from `uv export --frozen --no-dev --no-default-groups`, the fp32 model, and one index. The manifest is sha256sum format, sorted, and excludes itself, `KILL`, bytecode, and `.venv`. The tar is ustar, owner 0, mtime `2026-10-30 00:00:00` UTC, `gzip -n`. `scripts/serve.sh` binds `PREACHED_HOST` / `PREACHED_PORT` (default `127.0.0.1:8000`), forces ONNX fp32, one thread, offline Hub, and unsets `SPRITE_TOKEN`, `FLY_API_TOKEN`, `HF_TOKEN`, and `HUGGING_FACE_HUB_TOKEN`. It refuses to start as root unless `PREACHED_ALLOW_ROOT=1`.

The allow-list is in those two scripts only. Libraries are `wesley`, `spurgeon`, and `edwards`. The default bundle is Wesley. A symlink, a basename other than `<library>.sqlite`, and a path containing `cc-speech`, `gaston`, `youtube`, or `church` are refused. `app/server.py` still opens whatever library it is given. YouTube tests serve library `sample`. That default was not changed.

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

Sprite update, rollback, and secret rotation are in `docs/DEPLOY.md`. They are human steps. The API is https://api.sprites.dev (OpenAPI at `/openapi.json`). The host is https://preached-blncn.sprites.app. This repo does not call either one.

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

- `app/server.py` still serves any library file when it is started without `scripts/serve.sh`. The allow-list waits on PR #14 must-fix 1 or PR #12. Deploy scripts ship Wesley only. Spurgeon and Edwards are allowed if a person builds a second bundle on purpose. Church libraries, YouTube imports, `cc-speech.sqlite`, and Gaston Community Church are not in the bundle.
- int8 is on disk under `/cache` and is not shipped. The loader still refuses it at runtime.
- Behind a proxy that presents one socket address, the in-app cap is one global bucket. The runbook asks for a host-level limit as well. The process does not trust `X-Forwarded-For`.
- Binding `0.0.0.0` does not add the public name to the Host allowlist. The human sets `PREACHED_HOSTS` to `preached-blncn.sprites.app,127.0.0.1,localhost`.
- Non-root, a read-only mount of the index and model, and TLS are host steps in `docs/DEPLOY.md`. `serve.sh` refuses uid 0 unless `PREACHED_ALLOW_ROOT=1`, and it clears the write bit on an index that lives inside the bundle.
- The exact Sprites CLI flags are not in this repo. The runbook does not invent them. It points at the OpenAPI the admin already uses.
- The application has no secret to rotate. The secret is the Sprite admin credential. Rotation steps are marked human. Tokens are not written into the bundle or the server environment.
- The smoke RSS is higher than the W3-CPU 1-thread figure. The gap is not diagnosed here.
- CSP is unchanged. No new model. No church-member data.

## Dependencies added and why

None. The serve install is the existing lockfile with `--frozen --no-dev --no-default-groups`. Direct runtime packages remain numpy, onnxruntime, and tokenizers.
