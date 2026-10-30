# Deploying Preached

This is the runbook for the lean CPU server: ONNX fp32, one read-only SQLite
index, no torch. Build and the local smoke test stay on this machine. Nothing
in this repo contacts the Sprite or reads a deploy credential.

Steps a person has to do are marked **HUMAN**. The agent does not have Sprite
credentials and must not be given them.

The default network is loopback, or a Tailscale address the operator already
uses. Putting this process on the public internet is not a step in this
runbook. It is a separate change. It requires a written threat model, CTO
sign-off, Patrick's approval, and a kill-switch drill, in that order, before
any public name or public bind is added.

## What may be served

`app/server.py` `check_servable` is the only library gate. `scripts/serve.sh`
and `scripts/build-bundle.sh` call it. They do not keep a second allow-list.

| Library | What it is | Ship it? |
| --- | --- | --- |
| `wesley` | John Wesley, public domain. The default. | Yes. This is the bundle. |
| `spurgeon` | Spurgeon, public domain, canonical index only | Only if a person builds a second bundle on purpose |
| `edwards` | Jonathan Edwards, public domain, canonical index only | Only if a person builds a second bundle on purpose |

A church library, a YouTube import, or `/cache/index/cc-speech.sqlite` does
not pass `check_servable`. Gaston Community Church stays unpublished until
the pastor's permission is confirmed. A classic is served only from
`PREACHED_CACHE/index/<slug>.sqlite`, owned by the server uid, with no group
or world write, one hard link, and not a symlink.

A church sermon is not approved on a cue-rule pass. The reviewer must listen
through the whole recording, start to end, before approving a church sermon
(CTO ruling, 2026-10-30, the human-review rule from #19). On the LLM-written
synthetic test set the rules caught 635 of 730 words that should have been
excluded (ASR word recall 0.870), so they miss some. Listening is the real
control. Add an exclude line for every announcement, prayer request, prayer
list, or testimony the rules missed. That rule is the one in the review
file header (`reviewer_must`) and in `reports/W3-PRIV-SKIP.md`.

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

`pooling.json` rides along. The bundled `manifest.json` names fp32 only.
`model.int8.onnx` is not in the bundle and is not named in that manifest.
The loader checks the fp32 and tokenizer digests and refuses a mismatch.

Index: one SQLite file, opened `mode=ro` with `query_only`. The build copies
it with SQLite's backup API and sets `journal_mode=DELETE`, so the bundle
has no `-wal` or `-shm` and the file opens from a directory the process
cannot write. `/healthz` field `index_version` is the `chunks_sha256` meta
value when that value is 64 hex characters. `model_sha256` is the digest of
the fp32 graph that was loaded. Neither field is a path. A value that is not
64 hex characters is reported as `null`.

Static files, and only these: `index.html` (the page), `app.js`, `app.css`,
`favicon.svg`. There is no directory listing.

Code the bundle copies is the list in `scripts/build-bundle.sh`. It includes
`src/preached/libraries.py` and the Spurgeon and Edwards manifests and
provenance files, because the server imports them. It does not include
`torch_embed.py`, the YouTube importer, ingest code, or eval.

## Build the bundle

From this worktree:

```bash
scripts/build-bundle.sh /tmp/preached-bundle
```

That writes `/tmp/preached-bundle/` and `/tmp/preached-bundle.tar.gz`.
`MANIFEST.sha256` lists every file except itself, `<sha256>  <relative path>`,
sorted. The tar is taken from a private copy of the directory (not a reflink
of the live index or model), ustar, owner 0, mtime `2026-10-30 00:00:00` UTC,
and `gzip -n`. The same index, model bytes, and source tree produce the same
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

`PREACHED_BUNDLE_SKIP_PINS` does not skip the ONNX pin check unless the
parent command line looks like the unit tests. A deploy shell that exports
it still checks the pins. That parent check can be faked. The bundle
records the truth in `MANIFEST.sha256` as a comment line,
`# preached-pins-skipped: 0` or `# preached-pins-skipped: 1`
(`sha256sum -c` ignores the comment). The server refuses a bundle whose
manifest says the pins were skipped, unless the server process itself is
the unit tests. `scripts/serve.sh` is not that process.

## Run it locally

```bash
PREACHED_HOST=127.0.0.1 PREACHED_PORT=8000 scripts/serve.sh
```

From a bundle, the script uses `bundle/.venv/bin/python` when that exists,
sets `PREACHED_CACHE` to the bundle root, opens `bundle/index/<library>.sqlite`
read-only, and sets `PREACHED_ONNX_DIR` to `bundle/model`. One ONNX intra-op
thread (`PREACHED_ORT_THREADS`, default 1). No debug flag. Hugging Face
downloads are off (`HF_HUB_OFFLINE=1`).

The server process is started with `env -i` and an allow-list (PATH, HOME,
LANG, LC_ALL, TMPDIR, and the `PREACHED_*` variables the process reads,
plus the offline Hub flags). A token that was exported in the shell is not
in the server's environment. `app/server.py` refuses to run as root. There
is no `PREACHED_ALLOW_ROOT` and no `PREACHED_PYTHON` override.

`/healthz` is the health check. It counts toward the same per-IP rate limit
as search. A search is `/api/search?q=...&k=5&mode=hybrid&library=wesley`.

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
| Read-only index | SQLite `mode=ro` and `query_only`. The bundled file is `journal_mode=DELETE` and mode `0444`. |
| Read-only model | Bundle copies are mode `0444`. The loader does not download. |
| Request size | Path at most 2048 bytes, headers at most 8192, body at most 4096. No chunked bodies. A 405, or any earlier error, that leaves a body unread closes the connection, so those bytes are not parsed as a second request. |
| Header deadline | 15 seconds for the request line and all headers together. A slow byte does not reset the clock. |
| Connections | At most 32 concurrent connections, and at most 4 from one socket IP. Over the cap the accept thread returns 503 and does not start a handler thread. `PREACHED_MAX_CONNECTIONS` and `PREACHED_MAX_CLIENT_CONNECTIONS` override the numbers. |
| Rate limit | 60 requests per 60 seconds per socket IP in `serve.sh` (the code default is 120, so the unit tests fit). `/healthz` uses the same bucket. `X-Forwarded-For` is ignored. A full table of live keys refuses a new IP. `429` and `Retry-After`. |
| Socket timeout | 15 seconds on a read or a write after the headers. |
| Headers | CSP, `nosniff`, `no-referrer`, `X-Frame-Options: DENY`, `Server: Preached`. CSP is unchanged. |
| Logs | Access log is IP, method, path, status. The query string is not logged. Control characters are escaped. A bad request line does not crash the process. A failed request logs the exception type, not the message. |
| No listing | `/static/` is an allowlist of three files. |
| Kill file | Checked on every request. `touch KILL` in the bundle root stops serving without a restart. `/healthz` becomes `503` with `{"ok": false, "disabled": true}`. Search returns `{"error": "unavailable"}`. Removing a regular KILL file turns it back on, again without a restart. A directory, a symlink (dangling or not), or an unreadable parent at that path is treated as killed. The file's contents and path are not sent to the client. |
| `PREACHED_DISABLED` | Read from the process environment on each request. Set it before start. Another shell cannot change a running process's environment, so this is not the without-restart switch. The kill file is. |
| Library gate | `check_servable` only. |
| Server environment | `exec env -i` plus the allow-list in `scripts/serve.sh`. |

**HUMAN**, on the host. The bind stays on loopback or on Tailscale.

- Run the process as its own user, not root. `app/server.py` exits if the
  uid is 0.
- Unpack the bundle as that user, then make sure the service user owns the
  tree and nothing in it is group- or world-writable. `check_servable`
  refuses a bundle whose root, `index/`, or index file is group- or
  world-writable. It does not repair the modes. `scripts/serve.sh` does not
  chmod and does not chown. Modes have to match the table above before
  start. `scripts/serve.sh` has to stay executable or step 5 exits 126:

  ```bash
  chown -R preached:preached /srv/preached/<manifest-sha>
  find /srv/preached/<manifest-sha> -type d -exec chmod 0755 {} +
  find /srv/preached/<manifest-sha> -type f -exec chmod 0644 {} +
  chmod 0755 /srv/preached/<manifest-sha>/scripts/serve.sh
  chmod 0444 /srv/preached/<manifest-sha>/index/*.sqlite
  find /srv/preached/<manifest-sha>/model -type f -exec chmod 0444 {} +
  ```

  `0644` is `u=rw,go=r` and strips the execute bit, so it is not the last
  chmod for `scripts/serve.sh` (mode `0755`). The model files and the index
  stay mode `0444`, which is what the table above says. The owner of the
  tree has to already be the service user. A root-owned tree is not chmod'd
  by the start script.
- Bind `PREACHED_HOST=127.0.0.1`. Leave `PREACHED_HOSTS` at
  `127.0.0.1,localhost` unless the operator is reaching the process through
  an existing tailnet. Then bind the tailscale address (or keep loopback and
  use `tailscale serve` to that loopback port) and add the tailscale
  hostname to `PREACHED_HOSTS`. Do not bind `0.0.0.0`. Do not add a public
  hostname.
- Keep the index and `model/` readable. The process does not need a write
  path. If the host can mount them read-only, do that. A DELETE-mode index
  opens read-only from a directory the process cannot write.
- The in-app rate limit keys on the socket address. `X-Forwarded-For` is
  ignored. A trusted-proxy mode, and a global backstop in front of that, are
  not implemented. Do not put this process behind a public proxy until that
  exists.
- Do not enable directory listings, a debug console, or a shell on the
  listening port.
- One ONNX thread is the right default for a 1-vCPU box. `reports/W3-CPU.md`
  measured 4 threads slower on one CPU (134 ms p50 against 56 ms).

## Going public

Not part of this deploy. Do not add a public DNS name, a public `Host`
entry, or a public bind as part of standing the server up.

Before any of that happens, all of the following have to be done, in order:

1. A written threat model for the public process.
2. CTO sign-off on that threat model.
3. Patrick's approval.
4. A kill-switch drill: `touch KILL`, confirm `/healthz` is 503, remove the
   regular file, confirm `/healthz` is 200 again, without restarting.

Until those are done, the process stays on loopback or Tailscale.

## Update the Sprite

**HUMAN.** Use the Sprite admin credential you already have. It is not in
this repo. Do not paste it into a file in the bundle, into `docs/`, or into
a commit. The Sprite is private and admins only. The API is
https://api.sprites.dev (OpenAPI at `/openapi.json`). This runbook does not
call it and does not publish a public hostname.

1. **HUMAN.** Build `scripts/build-bundle.sh /tmp/preached-bundle` on a
   machine that already has `/cache/index/wesley.sqlite` and the pinned ONNX
   files. Record the manifest sha256 printed by the script.
2. **HUMAN.** Upload `/tmp/preached-bundle.tar.gz` to the Sprite, into a new
   directory named with that manifest sha256, for example
   `/srv/preached/<manifest-sha>/`. Leave the previous directory in place.
3. **HUMAN.** Extract the tar as the service user. Confirm
   `sha256sum -c MANIFEST.sha256` in that directory. Apply the `chown` and
   `chmod` in the hardening section. `PREACHED_CACHE` is the bundle root
   when `serve.sh` sees `index/`.
4. **HUMAN.** As the service user, not root:
   `uv sync --frozen --no-dev --no-default-groups`.
5. **HUMAN.** Start on loopback, or on the tailnet if that is how the
   operator already reaches the box:

   ```bash
   PREACHED_HOST=127.0.0.1 \
   PREACHED_PORT=8000 \
   PREACHED_HOSTS=127.0.0.1,localhost \
   PREACHED_LIBRARY=wesley \
   PREACHED_ORT_THREADS=1 \
   scripts/serve.sh
   ```

   For a tailnet, set `PREACHED_HOST` to the tailscale address and add that
   hostname to `PREACHED_HOSTS`. Wire that command as the service. Do not
   pass a church or a YouTube index.
6. **HUMAN.** From the box, `GET /healthz` with a `Host` header in
   `PREACHED_HOSTS`. Expect `ok: true`, `library: wesley`, `dense: true`,
   `backend: onnx`, `model: granite-english-r2`, and `model_sha256` equal to
   the fp32 pin above. `index_version` should match `chunks_sha256` in the
   Wesley index (`198339132f6861f483ef7d00f616d69081f5b54456ba6cef7301746b43e363b2`
   as of this branch's `/cache` copy). Then one Wesley search.

## Roll back

**HUMAN.** Point the service at the previous directory (the previous
manifest sha256) and restart it. Code, model, and index move together
because they live in that directory. Confirm `/healthz` `index_version` and
`model_sha256` match the older manifest.

To stop the new process without a restart, `touch KILL` in its directory.
The next request sees it. Confirm `/healthz` is 503, then start the old
directory. Removing that regular file resumes the new process, again
without a restart. If `KILL` is a directory, a symlink, or the parent
cannot be read, the process stays stopped until that is fixed. That check
is also on each request.

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
   that shell's history. `serve.sh` starts the server with `env -i`, so a
   token exported in the shell is not copied into the server process. That
   is not a substitute for rotating a credential that has leaked.

Do not put a Hugging Face token on the Sprite. The server is offline and the
weights are already in the bundle.
