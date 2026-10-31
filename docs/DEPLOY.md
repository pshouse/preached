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

## The church gate (not for any current deploy)

**Do not deploy a church side.** It stays off until the pastor's permission
is confirmed and the CTO approves a church deploy. These holds stand
whatever the code allows. The gate below is a HARD CONDITION before any
church deploy (CTO ruling on PR #37 r1, should-fix 4). It is not something
to set up now.

`--church-library <slug>` or `--church-index <file>` adds a second, read-only
column of approved church sermons. `scripts/serve.sh` passes neither, and
the bundle does not ship a church file. `app/server.py` opens the church
side only when every condition below holds. Otherwise it logs one
`ERROR church side refused: <why>` line and serves the classic side exactly
as with no church named, from a checkout or a bundle. A problem found while
serving logs `ERROR church side dropped: <why>` once instead, and the church
side stays off until restart. A pause logs `INFO church side paused: <why>`
when it starts and `INFO church side resumed` when church results come back.

The church slug (`--church-library`, or the file's stem) is chosen by the
operator and hard to guess. It is not the church's public name: the slug is
what a client asks for in `library=`.

1. **Deploy switch.** `PREACHED_CHURCH_SIDE=enabled` (exactly that value)
   is in the server's environment. It is not on `serve.sh`'s allow-list, so
   a `serve.sh` start never has it. Without it the church file is not opened.
2. **Privacy config.** `PREACHED_PRIVACY` names the library's privacy TOML
   (`privacy.example.toml`). Approval must run under the same config as the
   import.
3. **Permissions and owner.** The church name is not a symlink. The real
   file and the directory that really holds it are owned by the serving uid
   (or root), and neither is group- or world-writable. So is every
   directory above it up to `/`, on the path given and on the real path;
   the one exception is a root-owned sticky directory (like `/tmp`) whose
   next component is owned by the serving uid or root. The file SQLite
   opened must be the inode that was checked. The file has one
   hard link and is not a classic. Its `-wal`/`-shm`/`-journal` names, when
   present, are plain files with one link. These are checked at start and
   before every church search. Any failure drops the church side until
   restart.
4. **DELETE journal mode.** `--ack-review` leaves the file in DELETE mode,
   so the read-only open creates no `-wal` or `-shm`. A WAL-mode church file
   is refused at start. While `--ack-review` is writing (the file is briefly
   in WAL mode, or holds its write lock), each church search is skipped for
   that request, and the side is not dropped. The church connection never
   waits for a lock (`busy_timeout` 0), so a writer never stalls the
   server. If `--ack-review` prints
   `warning: the church file is still in wal journal mode`, close the other
   reader and run it again.
5. **Publish gate.** Only approved sermons are served: the review file's
   sha256 was approved, `status = 'ok'`, and ASR coverage was checked with
   no open gap. A human listened through each recording first (above).

Known gaps, accepted for now:
- The checks run by name. A same-uid process can still race them (#33).
- A file edited or corrupted in place, without a new inode, can still be
  served from SQLite's page cache until the next read misses it.
- `/healthz` says `"church": null` whether or not a church side is open.

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
manifest and the same tar. GNU tar sometimes exits 1 ("file changed as we
read it") even on that private copy. The likely cause is the Grok Bot box's
snapshot daemon, which creates and deletes `*.box-store-snap-*` files next to
the index and model files while tar reads them (8 of 10 real Wesley builds
hit it in the r2 measurement; one retry recovered each). The script makes up
to three tar attempts on exit 1, checks each archive against
`MANIFEST.sha256`, and only then renames it into place. A line `attempt N of 3`
followed by exit 0 is a success. If it prints `tar failed (tar 1, gzip 0)`,
rerun once; if that fails the same way, report and build off-box. Any other
non-zero exit is a real error: investigate it. That covers another tar or gzip
status, `tar.gz does not match MANIFEST.sha256`, and a refused input.
The script removes any `.tar.gz` (and leftover
`.tar.gz.partial.<pid>` files) from an earlier build before it checks
anything, so a failed build exits non-zero and leaves no `.tar.gz`. If
`/tmp/preached-bundle.tar.gz` exists, the build succeeded. Pass the output
directory without a trailing slash. Check it with:

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

The build always checks the ONNX files against the pins in
`src/preached/artifacts.py`. There is no switch that skips that check. The
unit tests build from a copy of the source whose `artifacts.py` pins small
fixture files.

The bundled code is derived, not hand-listed: `scripts/bundle_files.py list`
imports the serve entry points and ships every `app`/`preached` module they
load, the data directories inside those packages (`preached/privacy_data`),
and a short list of non-Python files. After the copy, the build re-imports
the server from the bundle with `python -I` and fails unless every loaded
`app`/`preached` module comes from inside the bundle.

The build also fails if any shipped module uses `importlib` or
`__import__`. An import by string is invisible to the import scan above, so
it is not allowed in serve code at all.

Known limit: this is a text check for accidental lazy imports, not a
security boundary. It is easy to get around: `getattr(builtins, "__imp" +
"ort__")`, `exec("import x")`, `runpy`, or `sys.modules` lookups all pass it.
A module loaded that way at request time is not in the bundle list and
fails with `ModuleNotFoundError` when it runs, not at build time. Code
review is the control for serve code.

The build writes a stamp, `PREACHED_BUNDLE` (format line, library, model
revision), and lists it in `MANIFEST.sha256`. The tree is classified
explicitly (`app/bundle.py`):

- **bundle**: `PREACHED_BUNDLE` exists. Every check below applies.
- **checkout**: no stamp, a `.git` entry at the root, and none of
  `MANIFEST.sha256`, `index/`, `model/`, `requirements-serve.txt`. Nothing is
  hashed.
- anything else is refused at start. A bundle with its stamp (or every
  marker) deleted does not fall back to checkout mode.

From a bundle the server refuses to start unless all of these hold:

- `MANIFEST.sha256` exists, every line is `<sha256>  <relative path>`,
  sorted, with no comments, blank lines or repeats, and it lists
  `PREACHED_BUNDLE`.
- every listed file is a regular file with that sha256.
- no other file is in the tree. Only `.venv/` and the kill file `KILL` are
  allowed beside it. Any `__pycache__/` or `*.pyc` is refused: every release
  tar has the same mtime, so a leftover `.pyc` whose source size matches
  would otherwise be loaded in place of the hashed source.
- the index (`PREACHED_INDEX` or the default) resolves to a listed file
  under the bundle's own `index/`. An index outside the bundle is refused.
- `PREACHED_ONNX_DIR` is unset or is the bundle's own `model/`. Another
  directory (an older revision, or an empty one that drops search to BM25)
  is refused. The embed backend must be `onnx`; torch is not shipped.

`scripts/serve.sh` is the supported launcher. It runs this check as
`python -I -B app/bundle.py ROOT INDEX` before anything imports bundle code.
`app/bundle.py` uses the standard library only. Its preflight (which
imports `app.server`) runs with `PYTHONPYCACHEPREFIX` set to a fresh empty
directory, so in-tree bytecode is never read, in a checkout as well. That
directory is removed before the server starts, or on a failed preflight.

`app/server.py` repeats the check in `main` for any other launcher.

### What a direct start does and does not guarantee

A direct start is `python app/server.py`, `python -B app/server.py`, or
`uv run app/server.py`, run without `serve.sh`.

It does guarantee:

- no cached bytecode for the server's own `.py` modules is read from the tree,
  and none is written to it. Files added to the tree (a sourceless `.pyc`, a
  `sitecustomize` under `serve.sh`'s `PYTHONPATH`, an extension module) are in
  the same class as an edited `.py`: refused by the check, but only after they
  have run on a direct start. The first lines of
  `app/server.py`, before any `app` or `preached` import, set
  `sys.dont_write_bytecode` and point `sys.pycache_prefix` at a new private
  empty directory (`tempfile.mkdtemp`). `app/__init__.py`, `app/bundle.py`
  and every `preached` module are compiled from their source files. A
  planted `__pycache__` (for example one that makes `bundle_problem` return
  None) is not read; `main` then finds it and refuses to start. The
  directory is removed at exit. When `app/server.py` runs as a script,
  SIGTERM is blocked from before the directory is made until its atexit
  hook and handler are installed, so a SIGTERM at any point removes it.
  Importing the module installs no handler.
- **Stop and exit codes.** SIGTERM is a requested stop. While serving it
  stops in order: no new connections, wait for the handler threads (a
  search in progress finishes; an idle keep-alive connection is closed),
  close the index, release the ONNX session. The process then exits 0 with
  no traceback and the bytecode directory removed. `tests/test_shutdown.py`
  proves this with 16 clients searching (bm25 and hybrid), on an idle
  server, and with an idle keep-alive connection open. The loaded test is
  probabilistic: on CI's small bm25 index (3 runs, no hybrid) it misses the
  old crash about half the time, so the deterministic in-flight test
  (a search held open across SIGTERM) is the CI gate. The gate for a
  change to the drain is the real-index loaded run,
  `PREACHED_SHUTDOWN_RUNS=30 python -m unittest tests.test_shutdown`
  with `/cache` present (bm25 and hybrid). A SIGTERM after the
  handler is installed and before serving exits 0 and serves nothing in the
  cases tested: during the imports, in `main`'s start-up checks, and during
  an `onnxruntime` import that turns it into `ImportError` (the server
  records the request and does not serve the BM25 fallback). Same file and
  `tests/test_deploy.py`.
  Not covered: a SIGTERM in the first moments of start, before the first
  lines of `app/server.py` install the handler, kills the process by the
  signal. What systemd sees depends on how `serve.sh` started it: with the
  project `.venv` it `exec`s Python directly and the unit ends by signal
  (`SIGTERM`, not an exit status); only the `uv run` path reports exit
  status 143. Add `SuccessExitStatus=143` if a unit
  may be stopped that early (SIGTERM needs no entry: systemd already counts
  a SIGTERM death as a clean stop). If a handler thread is still running 10 s after
  the stop (`DRAIN_TIMEOUT_S`), the index is left open, the process waits
  for that thread and exits 1.
  Ctrl-C (SIGINT) while serving stops the same way and exits 0. A second
  Ctrl-C (or a second SIGTERM) does not force an exit while a handler is
  stuck: the stop is already under way and the signal is ignored. Send
  SIGKILL, or set `TimeoutStopSec=` in the unit: when it runs out systemd
  sends SIGKILL to the unit, and the stop is then reported as failed
  (result `timeout`), not as a clean exit. The default is 90 s, which is
  long next to the 10 s `DRAIN_TIMEOUT_S`. During
  `main`'s start-up checks it exits 130 with no traceback; during the
  module imports before `main` it prints a traceback and dies by SIGINT.
  A refusal (`error: ...`) exits 1.
- `main` runs the whole bundle check (`bundle_problem`, then the model
  directory check) before it opens the index or binds the port.

It does not guarantee:

- that the check runs before bundle code. `app.bundle` and `preached.*`
  are imported, from their `.py` files, before `main` hashes those files.
  An edited `.py` in the tree runs first and is only refused afterwards.
  `serve.sh` runs only `app/bundle.py` itself before the check.
- anything about a planted extension module. Python prefers
  `bundle.cpython-312-x86_64-linux-gnu.so` (or any extension suffix) over
  `bundle.py` in the same directory, and it is loaded before the check.
  `serve.sh` runs `app/bundle.py` by path with `-I`, so its check refuses
  that unlisted file before anything imports it.
- anything for `python -m app.server`. `runpy` imports `app` and
  `app.server` through the normal import system before the first line of
  `app/server.py` runs, so their in-tree bytecode can be read. Do not start
  the server that way.
- anything about `.venv` or the interpreter (next section).
- a clean exit on SIGKILL. The private bytecode directory (empty, mode
  0700) is left in `$TMPDIR`.
- that `$TMPDIR` is used. If it is set but not writable, `mkdtemp` falls back
  to `/tmp` (same mode 0700, random name, removed at exit).

While serving, a bundle's index is frozen. If the open index changes after
start (chunks, vectors, any commit from another connection, or a status
read that fails), every request gets `503` until the process is restarted.
It is not reloaded. A checkout still reloads in place.

Hashing the bundle (index plus fp32 model) adds a few seconds to start, and
`serve.sh` hashes it twice (the stdlib check, then `main`).

### Reproducing a bundle hash

The tar bytes depend on the source tree, the bundled index copy, the model
files, and the versions of the tools that write them. `build-bundle.sh`
prints every one of these as `input ...` lines after the `tar` line:

- `input source`: the git commit of the source tree, with `dirty` if
  `git status --porcelain` is not empty. A dirty build is not reproducible
  from the repo.
- `input index-file` and `input index-bundled`: sha256 of the index named
  by `PREACHED_INDEX` and of the copy in the bundle. The index is not in
  git; it lives in `/cache`. The bundled copy (SQLite backup API) is what
  the tar holds.
- `input model-revision`: the ONNX revision. The files are pinned by sha256
  in `src/preached/artifacts.py`.
- `input python` (with the SQLite library version), `input uv` (it writes
  `requirements-serve.txt`), `input tar`, `input gzip`.

Two builds with the same `input` lines give the same tar. Someone without
this machine's `/cache` cannot rebuild the same tar: they need an index
file with the same `index-bundled` sha256 and the pinned model files. The
W3-DEPLOY-PREP report records the inputs of each published hash.

### `.venv` is a trust boundary

`.venv/` is outside the manifest. Nothing in it is hashed: the interpreter,
the third-party packages, and any `sitecustomize.py` or `.pth` file in its
`site-packages` run before, and with the same rights as, the manifest check.
Whoever can write `.venv/` can run code in the server. Create it with
`uv sync --frozen --no-dev --no-default-groups` as the service user, keep it
owned by that user and not group- or world-writable, and recreate it (do not
patch it) on every update. The manifest check proves the bundle's own files;
it says nothing about `.venv/`.

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

`/healthz` is the health check. It has its own rate buckets and its own
in-flight table, and one connection over the cap is reserved for it (see
Hardening). A search is `/api/search?q=...&k=5&mode=hybrid&library=wesley`.

API clients (Hark, parallel callers) must honour `Retry-After` on a `503`
(wait that long, then retry; do not retry at once) and on a `429`. Users
behind one IP, such as a shared office, school or NAT, share that IP's caps
(4 connections, 4 requests in flight, and the rate limit), unless the IP is
a trusted proxy that forwards `X-Forwarded-For`, which keys them separately.

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
| Control characters | A NUL or any other control character in the request line (apart from its CRLF ending), or in a header value (HTAB is allowed, RFC 9110 5.5), is a `400` and the connection is closed. The line is not logged. |
| Request size | Path at most 2048 bytes, headers at most 8192, body at most 4096. No chunked bodies. A 405, or any earlier error, that leaves a body unread closes the connection, so those bytes are not parsed as a second request. |
| Header deadline | 15 seconds for the request line and all headers together. A slow byte does not reset the clock. |
| Connections | At most 32 concurrent connections, and at most 4 from one socket IP (a trusted proxy is exempt from the per-IP cap). Over the cap the accept thread returns 503 with `Retry-After: 1` and does not start a handler thread. A connection counts until its last response is flushed, so the per-IP cap of N includes a closing response still being written: a peer at its cap that reconnects the instant it has read a `Connection: close` response can get that 503, and should retry after 1 second. There is no grace period, which would let a closing connection and its replacement both count as one. `PREACHED_MAX_CONNECTIONS` and `PREACHED_MAX_CLIENT_CONNECTIONS` override the numbers. |
| Slot fairness | When all 32 are taken, a new connection takes the slot of the longest-idle connection (waiting between requests) of the peer holding the most, if that peer holds at least two more than the newcomer. A connection whose request line has arrived and whose headers are still coming is taken only when no such peer has an idle one left. A request being handled is never closed. Once 8 or fewer slots are free, a connection waiting for its next request gets 2 seconds, not 15 (`PREACHED_SCARCE_IDLE_S`). At most 4 searches (and, separately, 4 `/healthz` requests) in flight per client key (`PREACHED_MAX_CLIENT_REQUESTS`); over that is `503`, `Retry-After: 1`, and the connection closes. A request counts until its response is written, so a client at its cap that sends the next request the instant it has read a response can get that 503. An IPv6 peer is counted by its /64. |
| `/healthz` reserve | When nothing can be closed, one more connection is admitted (`PREACHED_HEALTH_RESERVED_CONNECTIONS`, default 1, 0 turns it off). It serves one `/healthz` and closes (`Connection: close`). Any other path on it is `503`. While it is held, the next newcomer gets the accept-time `503`. |
| Client key | The socket peer, or its /64 for IPv6 (IPv4-mapped IPv6 is folded to IPv4). A Tailscale address (`fd7a:115c:a1e0::/48`, where every node shares one /64) is keyed per address. Trust is by the listed network only, never widened to the proxy's /64. `X-Forwarded-For` is read only when the peer is in `PREACHED_TRUSTED_PROXIES` (comma-separated addresses or networks, default empty). Then the key is the right-most hop that is not a trusted proxy. Hops to its left are never read. A forwarded IPv6 hop is keyed by its /64 too. A hop that does not parse keys on the nearest trusted address. A malformed `PREACHED_TRUSTED_PROXIES` entry stops the server. `Forwarded` (RFC 7239) is ignored. |
| Rate limit | 60 requests per 60 seconds per client key in `serve.sh` (the code default is 120, so the unit tests fit). Behind that, a global backstop of 600 per 60 seconds across all clients in `serve.sh` (code default 1200, `PREACHED_GLOBAL_RATE_LIMIT`). A client over its own cap does not spend the backstop, and a request the backstop refuses gives its hit back to the client's own bucket. A full table of live keys refuses a new key. `429` and `Retry-After`. |
| `/healthz` bucket | Its own per-client bucket (60 per 60 seconds, `PREACHED_HEALTH_RATE_LIMIT`) and its own global backstop (600, `PREACHED_HEALTH_GLOBAL_RATE_LIMIT`). Health checks never spend the search budget, and a search flood does not starve them. The connection caps above still apply, before the path is known. |
| Socket timeout | 15 seconds on a read or a write after the headers. |
| Headers | CSP, `nosniff`, `no-referrer`, `X-Frame-Options: DENY`, `Server: Preached`. CSP is unchanged. |
| Logs | Access log is `peer key method path status`: the socket peer, then the client key (the forwarded client behind a trusted proxy, the peer otherwise, a /64 for IPv6). The query string is not logged. Control characters are escaped in both addresses and the path. Refusals are logged as `refused <class> ... suppressed=N` warnings, at most one line per class per second, where N counts the lines dropped since the last one. Classes: `over-cap` (accept-time 503), `evict` (`holder->newcomer`), `busy` (per-key in-flight 503, or a non-`/healthz` request on the reserve), and `429-client`, `429-global`, `429-health`, `429-health-global`. Counts still suppressed at shutdown are logged as `refused <class> flush suppressed=N`. A bad request line does not crash the process. A failed request logs the exception type, not the message. |
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
- The `model/<revision>/` directory (the revision pinned in
  `src/preached/artifacts.py`) and every file in it must be owned by root or
  the service uid, and the directory must be `0755` or stricter (no group or
  world write); files must be `0444`/`0644` or stricter. The loader checks
  that one directory, not `model/` above it (files are pinned by hash, so a
  loose `model/` does not let a file be swapped, but keep it `0755` anyway).
  `check_servable` does not look at any of this; the ONNX loader does, and it
  does not stop the server. If it refuses, the reason is logged and the
  server serves BM25 only, with `/healthz` `dense: false`. The pre-cutover
  check is `/healthz` showing `dense: true`. A real cause is `model/`
  copied with `cp -r` or `rsync -r` from a checkout made under
  `umask 002`: `cp -r` makes new directories `0775` under that umask. Copy
  with `cp -a` or `rsync -a` from a tree whose directories are already `0755`,
  which keeps the source modes, or run the `chmod` lines above
  afterward.
  (A tar from `scripts/build-bundle.sh` stores `0755`/`0444`, and extraction
  under `umask 002`, `000`, or `022` all gave `755`/`755`/`444`, so the
  tar itself does not cause this.) Run the `chmod` lines above and check
  step 6.
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
  ignored unless the peer is listed in `PREACHED_TRUSTED_PROXIES`, which is
  empty by default. With `tailscale serve` in front, the peer is loopback;
  list `127.0.0.1` only if that proxy is the only thing that can reach the
  port, and check that it appends `X-Forwarded-For`. Otherwise leave it
  empty: every proxied client then shares one bucket, which fails closed.
  Any local process on the Sprite that can connect to the port from
  `127.0.0.1` is then the trusted proxy and can choose its own key.
- Access-log volume. The server writes one access line per request, and
  refusal lines at most once per class per second, to stderr. Under
  systemd that goes to journald. journald rate-limits each service
  (`RateLimitIntervalSec=`, `RateLimitBurst=` in `journald.conf`, or
  `LogRateLimitIntervalSec=`/`LogRateLimitBurst=` in the unit). Over the
  limit it drops lines and logs one "Suppressed N messages" line, so a
  flood can cost access lines. Rotation and the cap on disk use are
  `SystemMaxUse=`, `SystemMaxFileSize=` and `MaxRetentionSec=`. The lines
  hold real client IPs behind the proxy, so the retention period is a
  go-public decision (gate item 5), not a default to leave in place.
- Do not enable directory listings, a debug console, or a shell on the
  listening port.
- One ONNX thread is the right default for a 1-vCPU box. `reports/W3-CPU.md`
  measured 4 threads slower on one CPU (134 ms p50 against 56 ms).

## Going public

Not part of this deploy. Do not add a public DNS name, a public `Host`
entry, or a public bind as part of standing the server up.

Public exposure goes only through Tailscale (`tailscale serve` or
`tailscale funnel` to the loopback port), with
`PREACHED_TRUSTED_PROXIES=127.0.0.1`. The process never binds a public
interface. Eviction and the per-peer connection cap matter only for a
direct bind: behind the proxy every connection comes from `127.0.0.1`,
which is exempt from the per-peer cap and holds all the slots.

Before any of that happens, all of the following have to be done, in order:

1. A written threat model for the public process. A draft is below; it is
   not final.
2. Go-live checks for the RSS fix (#26) on the Sprite. RSS with dense
   search on is now 721 MiB; what is left is proving the dense path is the
   one serving. `/healthz` shows `dense: true`, `fallback: false`, and
   `model_sha256` equal to the fp32 pin. `model/` and every file in it are
   not group- or world-writable (`find model ! -type l -perm /022` prints
   nothing). A bundle unpacked under `umask 002` silently serves BM25 only.
3. Stale-bytecode drill for the bytecode fix (#18) on the Sprite: plant a
   `__pycache__` that would change `bundle_problem`, start through
   `scripts/serve.sh`, confirm the start is refused, remove it. The service
   never starts with `python -m app.server` (see "What a direct start does
   and does not guarantee").
4. Audit logging (PR #29 review M2): the log names the client key, and
   refusals and evictions are logged. In code on `feat/w3-exposure`; done
   when the CTO accepts it.
5. Access-log retention. The log stores the real client IP behind the
   proxy, with path and time. Set a retention period and journald limits
   (`SystemMaxUse=`, `MaxRetentionSec=`, `RateLimitIntervalSec=` and
   `RateLimitBurst=`) on the Sprite. The period is an open decision for
   Patrick.
6. Least-privilege, scoped credentials. The Sprite credential can do only
   what operating this service needs. The Tailscale node is a tagged node
   whose ACL allows only `serve`/`funnel` to the server's port. Any auth key
   has an expiry and is rotated; it is referred to only
   by its 1Password path, never pasted into the repo, a report or the
   Sprite's app environment. Serve (tailnet only) or funnel (public) is an
   open decision for Patrick.
7. Fuzzing of untrusted input. Nothing fuzzes the HTTP request parser
   (request line, headers, framing) or `client_key`/`X-Forwarded-For`
   parsing yet.
8. Dependency and secret scanning in CI. The repo has no CI (no
   `.github/`). Which CI to add is an open decision for Patrick.
9. An end-to-end test through a real `tailscale serve` or `tailscale funnel`
   in front of the process: it appends `X-Forwarded-For`, the key in the log
   is the client, and per-client 429s land on the client, not the proxy.
   Still open.
10. Per-/64 IPv6 keying (PR #29 review M4), with Tailscale addresses
    (`fd7a:115c:a1e0::/48`) keyed per address. In code on
    `feat/w3-exposure`; done when the CTO accepts it.
11. CTO sign-off on that threat model.
12. Patrick's approval.
13. A kill-switch drill: `touch KILL`, confirm `/healthz` is 503, remove the
    regular file, confirm `/healthz` is 200 again, without restarting.

Until those are done, the process stays on loopback or Tailscale.

## Threat model (DRAFT, not final)

Status: draft from W3-EXPOSURE-HARDEN. It is not signed off and does not
authorise a public bind. Nothing here changes the "Going public" order.

### Assets

- Availability of search and `/healthz` on a one-vCPU Sprite (CPU, the
  32 connection slots, memory for the ONNX model).
- Integrity of what is served: the bundle (code, `MANIFEST.sha256`, build
  stamp), the frozen index, and the pinned fp32 model.
- The rule that only public-domain classic libraries are served. Church
  libraries, YouTube imports, `cc-speech.sqlite` and Gaston Community
  Church stay unpublished (`check_servable`).
- The Sprite admin credential and any token in the operator's shell. The
  app holds no secret of its own.
- Searchers' queries. The access log drops the query string; no query is
  stored. The client IP (the real one behind a trusted proxy), the path and
  the time are stored, for as long as the log is kept.

### Attackers

- Anonymous internet clients: floods, many source addresses, slow senders,
  idle keep-alive holders.
- Clients that forge `X-Forwarded-For` to get fresh rate buckets or to frame
  another address.
- HTTP parser abuse: request smuggling, control characters, oversize
  headers, bodies on GET-only routes.
- A local user, or anything that can write the bundle, `.venv/`, or the
  index on the host. Out of scope for the in-app gates; covered by
  ownership and modes (see `.venv` is a trust boundary).
- Anyone holding the Sprite admin credential. Out of scope for the app;
  covered by rotation.

### Entry points

- The listening socket: `GET`/`HEAD` on `/`, `/static/<allowlisted>`,
  `/api/search`, `/api/side`, `/api/sermon/<id>`, `/healthz`. Every other
  method is `405`; no route reads a body.
- Request headers that change behaviour: `Host` (allowlist), `Content-Length`
  and `Transfer-Encoding` (refused unless plain), `X-Forwarded-For` (only
  from a trusted proxy).
- Process environment, set by `scripts/serve.sh` through `env -i`.
- The kill file at `PREACHED_KILL_FILE`.
- The bundle on disk, checked once at start.

### Controls in place

The Hardening table above: Host allowlist, size limits, framing and
control-character refusal, header deadline, connection caps and slot
fairness, trusted-proxy keying, per-client and global rate limits, the
separate `/healthz` bucket, the kill file, the frozen bundle index, the
manifest gate, root refusal, and the scrubbed environment.

### Known gaps

- Thread per connection. Caps and eviction bound it, but a distributed
  flood of real requests up to the global backstop still costs CPU, and
  32 busy searches fill every slot (busy requests are never closed).
- The connection caps run before the path is known. One connection over
  the cap is reserved for `/healthz`, but one client can hold it for up to
  the scarce header deadline (2 s) and reconnect, so the reserve is a
  best effort, not a guarantee.
- The 32-address lockout on a direct bind. Eviction needs a peer holding at
  least two more connections than the newcomer. 32 addresses that each
  hold one connection and reconnect about 4 times a second without sending
  a request leave no victim, so legitimate newcomers got 65 of 65 `503`s
  in the CTO's run. PR #18 behaves the same. Behind Tailscale this does not
  apply (one peer), but the 32 slots are then the shared limit.
- Any local process on the Sprite counts as the trusted proxy when
  `PREACHED_TRUSTED_PROXIES=127.0.0.1`, and can forge `X-Forwarded-For` to
  pick any key (a fresh bucket, or someone else's).
- The audit log records the socket peer, not the client, until M2 (above)
  is accepted. Before `feat/w3-exposure` round 1, every proxied request was
  logged as `127.0.0.1`.
- No TLS in the process. TLS has to come from the proxy or Tailscale.
- A garbage `X-Forwarded-For` hop written by a trusted proxy keys on that
  proxy, so those clients share one bucket.

### Remaining go-public gate items

Not done, and required, in this order:

1. RSS fix (#26) go-live checks on the Sprite: `/healthz` `dense: true`,
   `fallback: false`, `model_sha256` equal to the pin, and `model/` not
   group- or world-writable. (RSS is now 721 MiB.)
2. Stale-bytecode drill (#18) on the Sprite; never `python -m app.server`.
3. Audit logging (M2) accepted.
4. Access-log retention and journald limits set. Retention period: open,
   Patrick decides.
5. Scoped credentials: least-privilege Sprite credential, tagged Tailscale
   node whose ACL allows only serve/funnel to the port, auth keys with
   expiry and rotation, referred to by 1Password path only. Serve or
   funnel: open, Patrick decides.
6. Fuzzing for the HTTP parser and `client_key`/`X-Forwarded-For` parsing.
7. Dependency and secret scanning in CI (there is no CI yet). Which CI:
   open, Patrick decides.
8. An end-to-end test through a real `tailscale serve` or `tailscale funnel`.
   Open.
9. Per-/64 IPv6 keying (M4), Tailscale `/48` per address, accepted.
10. CTO sign-off on this threat model, once it is final.
11. Patrick's approval.
12. A kill-switch drill on the Sprite: `touch KILL`, confirm `/healthz` is
    503, remove the regular file, confirm `/healthz` is 200 again, without
    restarting.

Public exposure goes only through Tailscale with
`PREACHED_TRUSTED_PROXIES=127.0.0.1`. Eviction matters only for a direct
bind.

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
3. **HUMAN.** Extract the tar as the service user under `umask 022`. Confirm
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
   `dense: false` (or `model_sha256` null or not the pin) is a failed
   go-live even though `ok` is true and search still answers: the server
   fell back to BM25-only. Stop it, fix the `model/` owner and modes per the
   hardening section, and start again.

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

## Release notes (W3 deploy prep, PR #18)

Behaviour changes for anyone already running `app/server.py`:

- **Rate limit on by default.** `app/server.py` now limits each socket IP to
  **120 requests per 60 seconds** (`DEFAULT_RATE_LIMIT`,
  `DEFAULT_RATE_WINDOW_S`), even when started directly. Before this there
  was no limit. `scripts/serve.sh` sets 60 per 60 seconds. Override with
  `PREACHED_RATE_LIMIT` and `PREACHED_RATE_WINDOW_S`. Over the limit is
  `429` with `Retry-After`. (`/healthz` shared this bucket in PR #18; see
  the exposure-hardening notes below.)
- **New `/healthz` fields.** `disabled` (false while serving),
  `index_version` (the index's `chunks_sha256`, 64 hex, or null) and
  `model_sha256` (sha256 of the loaded ONNX graph, or null). No paths. With
  the kill switch on, `/healthz` is `503` with `{"ok": false, "disabled":
  true}`. A refused index, or a bundle's index changed after start, is `503`.
- A control character or NUL in the request line or a header value is a
  `400` and closes the connection.
- From a bundle: the start-up checks above (build stamp, manifest, no
  bytecode, own index, own `model/`, onnx only).

## Release notes (W3 exposure hardening)

- `/healthz` has its own per-client bucket (60 per 60 seconds) and global
  backstop (600). It no longer counts toward the search limit.
- Search has a global backstop: 1200 per 60 seconds in code, 600 in
  `serve.sh`.
- `PREACHED_TRUSTED_PROXIES` (default empty) turns on `X-Forwarded-For`
  keying for listed peers only.
- A full server closes an idle connection of the peer holding the most to
  admit a new client. Keep-alive idle time drops to 2 seconds when 8 or
  fewer slots are free. At most 4 requests in flight per client key.
  Both per-client caps count a response until it is written (a closing
  connection until it is flushed). A client at its cap that reconnects
  or sends again in that instant gets `503` with `Retry-After: 1`.
- New variables, all passed by `serve.sh`: `PREACHED_TRUSTED_PROXIES`,
  `PREACHED_GLOBAL_RATE_LIMIT`, `PREACHED_HEALTH_RATE_LIMIT`,
  `PREACHED_HEALTH_GLOBAL_RATE_LIMIT`, `PREACHED_MAX_CLIENT_REQUESTS`,
  `PREACHED_SCARCE_IDLE_S`, `PREACHED_HEALTH_RESERVED_CONNECTIONS`.
- The access log line is now `peer key method path status` (one more
  field). Log parsers that split on spaces need updating. Refusals are
  logged as rate-limited `refused ...` warnings.
- IPv6 clients are keyed by /64: addresses in one /64 share a rate bucket,
  in-flight slots and the per-peer connection cap. Tailscale addresses
  (`fd7a:115c:a1e0::/48`) are keyed per address, because the tailnet puts
  every node in one /64.
- A connection's slot is freed before its last (`Connection: close`)
  response is sent, so a client that reads it and reconnects at once is
  not refused for its own old slot.
- One connection over the cap is reserved for a single `/healthz`.
- A connection still receiving its headers is evicted only after every
  idle one of the same peer.
- Search, side, sermon, page and static responses are unchanged byte for
  byte (Date, `took_ms` and Content-Length masked).
