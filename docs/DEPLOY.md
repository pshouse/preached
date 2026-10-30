# Deploying Preached

This is the runbook for the lean CPU server: ONNX fp32, one read-only SQLite
index, no torch. Build and the local smoke test stay on this machine. Nothing
in this repo contacts the Sprite or reads a deploy credential.

Steps a person has to do are marked **HUMAN**. The agent does not have Sprite
credentials and must not be given them.

## Hold on church and YouTube libraries

PR #10 (the ONNX runtime) is on `main` (`2ad5550`). The server allow-list
is not. Until PR #14 must-fix 1 or PR #12 lands, `app/server.py` will open
any library file it is pointed at. This branch does not change that default.

This deploy does not. `scripts/build-bundle.sh` and `scripts/serve.sh` allow
only:

| Library | What it is | Ship it? |
| --- | --- | --- |
| `wesley` | John Wesley, public domain. The default. | Yes. This is the bundle. |
| `spurgeon` | Spurgeon, public domain, `/cache/index/spurgeon.sqlite` | Only if a person builds a second bundle on purpose |
| `edwards` | Jonathan Edwards, public domain, `/cache/index/edwards.sqlite` | Only if a person builds a second bundle on purpose |

Do not point the server at a church library, a YouTube import, or
`/cache/index/cc-speech.sqlite`. Gaston Community Church stays unpublished
until the pastor's permission is confirmed. A symlink or a renamed file is
refused when the path contains `cc-speech`, `gaston`, `youtube`, or `church`.

## What the server needs

Python 3.12 (`.python-version`, `requires-python >=3.12,<3.14`). On this
machine that is CPython 3.12.16.

Installed by `uv sync --frozen --no-dev --no-default-groups` (no extras, no `bench` group):
numpy, onnxruntime, tokenizers, and their transitive wheels (flatbuffers,
protobuf, packaging, huggingface-hub, httpx2, and the small libraries those
pull in). Torch, faster-whisper, ctranslate2, yt-dlp, sentence-transformers,
and the NVIDIA CUDA wheels are not installed.

Imported when the process serves a query: the stdlib, numpy, onnxruntime, and
tokenizers. huggingface-hub is installed because tokenizers declares it, and
the serve path does not import it. A test fails if torch, whisper,
faster-whisper, ctranslate2, sentence-transformers, transformers, yt-dlp,
onnx (the export package), onnxscript, Pillow, av, nvidia, or huggingface-hub
show up in `sys.modules` after the serve imports.

ONNX files, revision `47ea694b257b703fee9253d75c2b1f2985180498`:

| File | sha256 |
| --- | --- |
| `model.fp32.onnx` | `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` |
| `tokenizer.json` | `6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30` |

`manifest.json` and `pooling.json` ride along. `model.int8.onnx` is not in
the bundle. The loader checks these digests and refuses a mismatch.

Index: `/cache/index/wesley.sqlite`, opened `mode=ro` with `query_only`.
`/healthz` field `index_version` is the `chunks_sha256` meta value when that
value is 64 hex characters. `model_sha256` is the digest of the fp32 graph
that was loaded. Neither field is a path. A value that is not 64 hex
characters is reported as `null`.

Static files, and only these: `index.html` (the page), `app.js`, `app.css`,
`favicon.svg`. There is no directory listing.

Code the bundle copies is the list in `scripts/build-bundle.sh`. It does not
include `torch_embed.py`, the YouTube importer, ingest, or eval.

## Build the bundle

From this worktree:

```bash
scripts/build-bundle.sh /tmp/preached-bundle
```

That writes `/tmp/preached-bundle/` and `/tmp/preached-bundle.tar.gz`.
`MANIFEST.sha256` lists every file except itself, `<sha256>  <relative path>`,
sorted. The tar is ustar, owner 0, mtime `2026-10-30 00:00:00` UTC, and
`gzip -n`. The same index, model bytes, and source tree produce the same
manifest and the same tar. Check it with:

```bash
cd /tmp/preached-bundle && sha256sum -c MANIFEST.sha256
```

The install recipe, with no new dependencies, is the lockfile subset written
to `requirements-serve.txt`:

```bash
uv sync --frozen --no-dev --no-default-groups
```

`default-groups` is already empty. Do not pass `--extra transcribe`,
`--extra youtube`, or `--group bench`.

## Run it locally

```bash
PREACHED_HOST=127.0.0.1 PREACHED_PORT=8000 scripts/serve.sh
```

From a bundle, the script uses `bundle/.venv/bin/python` when that exists,
opens `bundle/index/<library>.sqlite` read-only, and sets
`PREACHED_ONNX_DIR` to `bundle/model`. One ONNX intra-op thread
(`PREACHED_ORT_THREADS`, default 1). No debug flag. Hugging Face downloads
are off (`HF_HUB_OFFLINE=1`). The process refuses to start as root unless
`PREACHED_ALLOW_ROOT=1`, which is only for a local experiment.

`/healthz` is the health check. A search is
`/api/search?q=...&k=5&mode=hybrid&library=wesley`.

Local smoke, which builds a temp bundle, syncs a fresh venv, and does not
leave the server running:

```bash
scripts/smoke-bundle.sh
```

The numbers from the last run on this machine are in `reports/W3-DEPLOY-PREP.md`.

## Hardening

In the process:

| Control | Behavior |
| --- | --- |
| Read-only index | SQLite `mode=ro` and `query_only`. Bundle copies are mode `0444`. |
| Read-only model | Bundle copies are mode `0444`. The loader does not download. |
| Request size | Path at most 2048 bytes, headers at most 8192, body at most 4096. No chunked bodies. |
| Rate limit | 60 requests per 60 seconds per socket IP in `serve.sh` (the code default is 120, so the unit tests fit). `X-Forwarded-For` is ignored. `429` and `Retry-After`. |
| Timeout | Socket timeout 15 seconds. |
| Headers | CSP, `nosniff`, `no-referrer`, `X-Frame-Options: DENY`, `Server: Preached`. CSP is unchanged. |
| Logs | Access log is IP, method, path, status. The query string is not logged. A failed request logs the exception type, not the message. |
| No listing | `/static/` is an allowlist of three files. |
| Kill switch | `touch KILL` in the bundle root, or `PREACHED_DISABLED=1`. `/healthz` becomes `503` with `{"ok": false, "disabled": true}`. Search returns `{"error": "unavailable"}`. Removing the file turns it back on. The file's contents and path are not sent to the client. |
| Library names | `serve.sh` allows `wesley`, `spurgeon`, `edwards` only. |
| Secrets in the environment | `serve.sh` unsets `SPRITE_TOKEN`, `FLY_API_TOKEN`, `HF_TOKEN`, and `HUGGING_FACE_HUB_TOKEN` if they were exported. |

**HUMAN**, on the host:

- Run the process as its own user, not root.
- The Sprite terminates TLS. The app listens on the Sprite's private port.
  Bind `PREACHED_HOST=0.0.0.0` only there, and set `PREACHED_HOSTS` to the
  public host plus `127.0.0.1,localhost`. The default bind is `127.0.0.1`.
- Keep the bundle directory readable and not writable by the service user
  after `uv sync`. The process does not need a write path. If the host can
  mount the index and `model/` read-only, do that.
- Put the rate limit in front of the app as well if every request arrives
  from one proxy address. This process will then see one IP and the cap
  becomes global, which still protects the small CPU.
- Do not enable directory listings, a debug console, or a shell on the
  public port.
- One ONNX thread is the right default for a 1-vCPU box. `reports/W3-CPU.md`
  measured 4 threads slower on one CPU (134 ms p50 against 56 ms).

## Update the Sprite

**HUMAN.** Use the Sprite admin credential you already have. It is not in
this repo. Do not paste it into a file in the bundle, into `docs/`, or into
a commit. The Sprite is `preached`, https://preached-blncn.sprites.app,
private, admins only. The API is https://api.sprites.dev (OpenAPI at
`/openapi.json`). This runbook does not call it.

1. **HUMAN.** Build `scripts/build-bundle.sh /tmp/preached-bundle` on a
   machine that already has `/cache/index/wesley.sqlite` and the pinned ONNX
   files. Record the manifest sha256 printed by the script.
2. **HUMAN.** Upload `/tmp/preached-bundle.tar.gz` to the Sprite, into a new
   directory named with that manifest sha256, for example
   `/srv/preached/<manifest-sha>/`. Leave the previous directory in place.
3. **HUMAN.** Extract the tar. Confirm `sha256sum -c MANIFEST.sha256` in
   that directory.
4. **HUMAN.** As the service user, not root:
   `uv sync --frozen --no-dev --no-default-groups`.
5. **HUMAN.** Start, with the public host filled in:

   ```bash
   PREACHED_HOST=0.0.0.0 \
   PREACHED_PORT=<the port the Sprite service proxies> \
   PREACHED_HOSTS=<public host>,127.0.0.1,localhost \
   PREACHED_LIBRARY=wesley \
   PREACHED_ORT_THREADS=1 \
   scripts/serve.sh
   ```

   Wire that command as the Sprite service. Do not pass `--library` for a
   church or a YouTube index.
6. **HUMAN.** From the Sprite, `GET /healthz` with a `Host` header in
   `PREACHED_HOSTS`. Expect `ok: true`, `library: wesley`, `dense: true`,
   `backend: onnx`, `model: granite-english-r2`, and `model_sha256` equal to
   the fp32 pin above. `index_version` should match `chunks_sha256` in the
   Wesley index (`198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2`
   as of this branch's `/cache` copy). Then one Wesley search.

## Roll back

**HUMAN.** Point the Sprite service at the previous directory (the previous
manifest sha256) and restart it. Code, model, and index move together
because they live in that directory. Confirm `/healthz` `index_version` and
`model_sha256` match the older manifest. If the new process is wedged,
`touch KILL` in its directory, confirm `/healthz` is 503, then start the old
directory.

There is no database migration. The index file is not rewritten by the server.

## Rotate a secret

The application has no API key, no session secret, and no database password.
The bundle must not contain one. Weights and the Wesley index are public-domain
content plus a published model, not secrets.

The secret is the Sprite admin credential.

1. **HUMAN.** Issue a new Sprite admin credential in the admin console.
2. **HUMAN.** Update the place you store it (your own password store, not
   this repo and not the Sprite's app environment).
3. **HUMAN.** Confirm the old credential is rejected.
4. **HUMAN.** If the old value was typed into a shell on the Sprite, clear
   that shell's history. `serve.sh` drops `SPRITE_TOKEN` and `FLY_API_TOKEN`
   from the server process if they were exported, and that is not a
   substitute for rotating a credential that has leaked.

Do not put a Hugging Face token on the Sprite. The server is offline and the
weights are already in the bundle.
