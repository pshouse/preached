# Deploying Preached

This is the runbook for the lean CPU server: ONNX fp32, one read-only SQLite
index, no torch. Read it end to end before a deploy. Part 1 is the one
ordered runbook. Part 2 is reference for the steps. Part 3 covers the church
side, which is not deployed. Part 4 covers going public, which is not part of
this deploy either.

Nothing in this repo contacts the Sprite or reads a deploy credential. Steps
a person has to do are marked **HUMAN**. The agent does not have Sprite
credentials and must not be given them.

What this deploy is, and is not:

- **Wesley only.** The bundle serves one public-domain classic library
  (`wesley`). See "What may be served".
- **Loopback or Tailscale only.** The bind is `127.0.0.1`, or a Tailscale
  address the operator already uses. Do not bind `0.0.0.0` and do not add a
  public hostname. Going public is a separate change with its own gate
  (Part 4).
- **No church side.** It stays off until every item in "Church deploy hard
  conditions" (Part 3) is met. Today every item is OPEN.

## Part 1: The runbook

Do these in order. Each step says what to check before you go on.

### 1. Build the bundle

**HUMAN**, on a machine that already has `/cache/index/wesley.sqlite` and the
pinned ONNX files (Part 2, "What the server needs"). From a clean checkout:

```bash
scripts/build-bundle.sh /tmp/preached-bundle
```

Pass the output directory without a trailing slash. The script writes
`/tmp/preached-bundle/` and `/tmp/preached-bundle.tar.gz`, and prints the
manifest sha256 and the `input ...` lines (Part 2, "Reproducing a bundle
hash"). Record the manifest sha256 and the `input` lines.

How to read the result:

- **Exit 0** is a success, including when the output shows
  `tar exited 1 (file changed as we read it?); attempt N of 3` lines before
  it. If `/tmp/preached-bundle.tar.gz` exists, the build succeeded: the
  script removes any `.tar.gz` (and leftover `.tar.gz.partial.<pid>` files)
  from an earlier build before it checks anything, so a failed build leaves
  no `.tar.gz`.
- **`tar failed (tar 1, gzip 0); no archive written`**: the tar flake
  outlasted three attempts. Rerun once. If that fails the same way, report
  it and build off-box.
- **Any other non-zero exit is a real error. Investigate it.** That covers
  another tar or gzip status in the `tar failed (...)` line,
  `tar.gz does not match MANIFEST.sha256; no archive written`, and a refused
  input.

Why the tar flake happens: GNU tar sometimes exits 1 ("file changed as we
read it") even though the tar is taken from a private copy of the
directory. The likely cause is the Grok Bot box's snapshot daemon, which
creates and deletes `*.box-store-snap-*` files next to the index and model
files while tar reads them. In the r2 measurement 8 of 10 real Wesley builds
hit it, and one retry recovered each. The script makes up to three tar
attempts on exit 1, checks each archive against `MANIFEST.sha256`, and only
then renames it into place.

### 2. Check the bundle

```bash
cd /tmp/preached-bundle && sha256sum -c MANIFEST.sha256
```

Every line must say `OK`.

### 3. Upload and extract

1. **HUMAN.** Upload `/tmp/preached-bundle.tar.gz` to the Sprite, into a new
   directory named with the manifest sha256, for example
   `/srv/preached/<manifest-sha>/`. Leave the previous directory in place:
   it is the roll back.
2. **HUMAN.** Extract the tar as the service user, under `umask 022`. The
   tar has no top-level directory (entries start `./`), so extract into the
   new directory with `-C`:

   ```bash
   umask 022; tar -xzf preached-bundle.tar.gz -C /srv/preached/<manifest-sha>
   ```
3. **HUMAN.** In that directory, run `sha256sum -c MANIFEST.sha256` again.

### 4. Set owner and modes

**HUMAN**, on the host. Run the process as its own user, not root
(`app/server.py` exits if the uid is 0). The service user must own the tree,
and nothing in it may be group- or world-writable. `check_servable` refuses a
bundle whose root, `index/`, or index file is group- or world-writable. It
does not repair modes, and `scripts/serve.sh` does not chmod or chown.

```bash
chown -R preached:preached /srv/preached/<manifest-sha>
find /srv/preached/<manifest-sha> -type d -exec chmod 0755 {} +
find /srv/preached/<manifest-sha> -type f -exec chmod 0644 {} +
chmod 0755 /srv/preached/<manifest-sha>/scripts/serve.sh
chmod 0444 /srv/preached/<manifest-sha>/index/*.sqlite
find /srv/preached/<manifest-sha>/model -type f -exec chmod 0444 {} +
```

`0644` strips the execute bit, so the `serve.sh` line has to come after it.
Without it, step 6 exits 126. The model files and the index end at `0444`.

The ONNX loader also checks `model/<revision>/` (the revision pinned in
`src/preached/artifacts.py`): that directory and every file in it must be
owned by root or the service uid, the directory `0755` or stricter, the
files `0444`/`0644` or stricter. It checks only that directory, not `model/`
above it (files are pinned by hash), but keep `model/` at `0755` too. The
loader's refusal does not stop the server: it logs the reason and the server
serves BM25 only, with `/healthz` `dense: false`. Step 7 catches this.

A real cause is copying `model/` with `cp -r` or `rsync -r` from a checkout
made under `umask 002`, which makes new directories `0775`. Copy with
`cp -a` or `rsync -a` from a tree whose directories are already `0755`, or
run the `chmod` lines above afterwards. (A tar from `scripts/build-bundle.sh`
stores `0755`/`0444`. Extraction under `umask 002`, `000`, or `022` all gave
`755`/`755`/`444`, so the tar itself does not cause this.)

Check before you go on: `find /srv/preached/<manifest-sha>/model ! -type l -perm /022`
prints nothing.

Keep the index and `model/` readable. The process needs no write path. If
the host can mount them read-only, do that: a DELETE-mode index opens
read-only from a directory the process cannot write.

### 5. Create the venv

**HUMAN.** As the service user, not root, in the bundle directory:

```bash
uv sync --frozen --no-dev --no-default-groups
```

That installs the lockfile subset also written to `requirements-serve.txt`.
`default-groups` is already empty. Do not pass `--extra transcribe`,
`--extra youtube`, or `--group bench`. `.venv/` is a trust boundary: keep it
owned by the service user, not group- or world-writable, and recreate it (do
not patch it) on every update (Part 2, "`.venv` is a trust boundary").

### 6. Start the service

**HUMAN.** Start on loopback, or on the tailnet if that is how the operator
already reaches the box:

```bash
PREACHED_HOST=127.0.0.1 \
PREACHED_PORT=8000 \
PREACHED_HOSTS=127.0.0.1,localhost \
PREACHED_LIBRARY=wesley \
PREACHED_ORT_THREADS=1 \
scripts/serve.sh
```

- For a tailnet, bind the tailscale address (or keep loopback and use
  `tailscale serve` to that loopback port) and add the tailscale hostname to
  `PREACHED_HOSTS`. Otherwise leave `PREACHED_HOSTS` at `127.0.0.1,localhost`.
- Do not pass `--church-library`, `--church-index`, `PREACHED_CHURCH_SIDE`,
  or a YouTube index. `serve.sh` passes none of them.
- Leave `PREACHED_TRUSTED_PROXIES` empty unless a proxy that appends
  `X-Forwarded-For` is the only thing that can reach the port (Part 2,
  "Notes for the host").
- Never start the service with `python -m app.server` (Part 2, "What a
  direct start does and does not guarantee").

Wire that command as the systemd service. Unit settings:

- `User=` the service user, `WorkingDirectory=` the bundle root,
  `ExecStart=` `scripts/serve.sh`, and the `PREACHED_*` values above as
  `Environment=` lines. `serve.sh` starts the server with `env -i` and its
  allow-list, so nothing else from the unit's environment reaches it.
- `TimeoutStopSec=30` (for example). It has to be above `DRAIN_TIMEOUT_S`
  (10 s, `app/server.py:244`) and `REQUEST_TIMEOUT_S` (15 s,
  `app/server.py:238`). The systemd default is 90 s. When it runs out,
  systemd sends SIGKILL and reports the stop as failed (result `timeout`),
  not as a clean exit.
- `SuccessExitStatus=143`, only if the unit may be stopped in the first
  moments of a start. A SIGTERM then can arrive before `app/server.py`
  installs its handler. With the bundle's `.venv`, `serve.sh` `exec`s Python
  directly and the unit ends by signal (systemd already counts a SIGTERM
  death as clean, so it needs no entry). Only the `uv run` path reports exit
  status 143.
- A stuck stop: if a handler thread is still running 10 s after SIGTERM,
  the server logs
  `ERROR <n> handler thread(s) still running after 10s; index left open`,
  leaves the classic index, the church index (when one is open) and the
  ONNX session open, waits for that thread, and exits 1
  (`app/server.py:3368-3386`; the church connection is closed only on the
  clean path at `:3382`; that path logs `INFO stopped cleanly` at `:3384`;
  alert table, "deploy alerts"). A second SIGTERM or Ctrl-C does not force an exit.
  `TimeoutStopSec=` (or a SIGKILL by hand) ends it.
- Logs go to stderr, so under systemd to journald. Set journald's limits
  (Part 2, "Notes for the host").

### 7. Go-live checks

**HUMAN**, from the box. `GET /healthz` with a `Host` header in
`PREACHED_HOSTS`. Expect:

- `ok: true`, `library: wesley`
- `dense: true`, `backend: onnx`, `model: granite-english-r2`
- `model_sha256` equal to the fp32 pin
  (`3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9`)
- `index_version` equal to the bundled index's `chunks_sha256` meta value.
  Read it in the bundle root:

  ```bash
  .venv/bin/python -c "import sqlite3;print(sqlite3.connect('file:index/wesley.sqlite?mode=ro',uri=True).execute(\"select value from meta where key='chunks_sha256'\").fetchone()[0])"
  ```

  The build's `input index-file` and `input index-bundled` lines are sha256
  digests of the SQLite file itself. They are not this value and `/healthz`
  does not report them.
- `"church": null` (it is null whether or not a church side is open, so it
  proves nothing about the church; step 6 is what keeps it off)

`dense: false`, or `model_sha256` null or not the pin, is a **failed
go-live** even though `ok` is true and search answers: the server fell back
to BM25 only. Stop it, fix the `model/` owner and modes (step 4), and start
again.

Then run one Wesley search:
`/api/search?q=...&k=5&mode=hybrid&library=wesley`.

Then the kill-file check, without a restart: `touch KILL` in the bundle
root, confirm `/healthz` is `503` with `{"ok": false, "disabled": true}`,
remove the file, confirm `/healthz` is `200` again.

### 8. Roll back

**HUMAN.** Point the service at the previous directory (the previous
manifest sha256) and restart it. Code, model, and index move together
because they live in that directory. Confirm `/healthz` `index_version` and
`model_sha256` match the older manifest. There is no database migration; the
server never rewrites the index.

To stop the new process at once, without a restart, `touch KILL` in its
directory. The next request sees it. Confirm `/healthz` is `503`, then start
the old directory. Removing that regular file resumes the new process, again
without a restart. If `KILL` is a directory, a symlink, or its parent cannot
be read, the process stays stopped until that is fixed.

### 9. Rotate a secret

The application has no API key, no session secret, and no database
password, and the bundle must not contain one. The weights and the Wesley
index are public-domain content plus a published model, not secrets. The
one secret is the Sprite admin credential. It is not in this repo. Do not
paste it into a file in the bundle, into `docs/`, or into a commit. The
Sprite is private and admins only. Its API is https://api.sprites.dev
(OpenAPI at `/openapi.json`); this runbook does not call it.

1. **HUMAN.** Issue a new Sprite admin credential in the admin console.
2. **HUMAN.** Update the place you store it (your own password store, not
   this repo and not the Sprite's app environment).
3. **HUMAN.** Confirm the old credential is rejected.
4. **HUMAN.** If the old value was typed into a shell on the Sprite, clear
   that shell's history. `serve.sh` starts the server with `env -i`, so a
   token exported in the shell is not in the server process. That is not a
   substitute for rotating a credential that has leaked.

Do not put a Hugging Face token on the Sprite. The server is offline
(`HF_HUB_OFFLINE=1`) and the weights are in the bundle.

### Local smoke test

On the build machine, before step 3 if you want it:

```bash
scripts/smoke-bundle.sh
```

It builds a temp bundle, syncs a fresh venv, and does not leave the server
running. The numbers from the last run are in `reports/W3-DEPLOY-PREP.md`.

Run the test suite on the build machine before step 3 as well:

```bash
PREACHED_REQUIRE_DENO=1 \
HF_HUB_OFFLINE=1 \
PREACHED_CACHE=$(mktemp -d) \
PREACHED_ONNX_DIR=$(mktemp -d) \
HF_HOME=$(mktemp -d) \
DENO_DIR=$(mktemp -d) \
XDG_CACHE_HOME=$(mktemp -d) \
UV_CACHE_DIR=$(mktemp -d) \
uv run python -m unittest discover -s tests
```

Only the host verify-merge gate runs the suite against the real `/cache`;
when a test needs real data, use a read-only copy or a read-only bind mount.

`PREACHED_REQUIRE_DENO=1` turns a missing `deno` from a skip into a failure
for the deno-backed tests that honor it (the set grows as more
tests adopt it). Without it, a machine with no `deno` would skip the
withheld-card scan, the touch-only blur check and the code-point cap check,
and the suite would still pass.

To run a checkout or a bundle by hand on loopback:
`PREACHED_HOST=127.0.0.1 PREACHED_PORT=8000 scripts/serve.sh`.

## Part 2: Reference

### What may be served

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

### What the server needs

Python 3.12 (`.python-version`, `requires-python >=3.12,<3.14`). On the
build machine that is CPython 3.12.16.

Installed by `uv sync --frozen --no-dev --no-default-groups` (no extras, no
`bench` group): numpy, onnxruntime, tokenizers, and their transitive wheels
(flatbuffers, protobuf, packaging, huggingface-hub, httpx2, and the small
libraries those pull in). Torch, faster-whisper, ctranslate2, yt-dlp,
sentence-transformers, and the NVIDIA CUDA wheels are not installed.

Imported when the process serves a query: the stdlib, numpy, onnxruntime,
and tokenizers. huggingface-hub is installed because tokenizers declares it;
the serve path does not import it. A test fails if torch, whisper,
faster-whisper, ctranslate2, sentence-transformers, transformers, yt-dlp,
onnx (the export package), onnxscript, Pillow, av, nvidia, or huggingface-hub
show up in `sys.modules` after the serve imports.

ONNX files, revision `47ea694b257b703fee9253d75c2b1f2985180498`:

| File | sha256 |
| --- | --- |
| `model.fp32.onnx` | `3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9` |
| `tokenizer.json` | `6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30` |

`pooling.json` rides along. The bundled `manifest.json` names fp32 only;
`model.int8.onnx` is neither in the bundle nor in that manifest. The loader
checks the fp32 and tokenizer digests and refuses a mismatch. The build
always checks the ONNX files against the pins in `src/preached/artifacts.py`;
no switch skips it. (The unit tests build from a copy of the source whose
`artifacts.py` pins small fixture files.)

Index: one SQLite file, opened `mode=ro` with `query_only`. The build copies
it with SQLite's backup API and sets `journal_mode=DELETE`, so the bundle
has no `-wal` or `-shm` and the file opens from a directory the process
cannot write. Serving the WAL-mode `/cache` index straight from a checkout
on a read-only mount is unsupported; use `copy_index` (it copies the index
with the SQLite backup API and switches the copy to rollback-journal
(`DELETE`) mode, so it can be served from a read-only directory; the source
is opened read-only and is not checkpointed) for that. Never use
`immutable=1` (it gives silent stale reads and missed reloads). `/healthz`
`index_version` is the `chunks_sha256` meta value and `model_sha256` is the
digest of the fp32 graph that was loaded; each is `null` unless it is 64
hex characters. Neither is a path.

Static files, and only these: `index.html` (the page), `app.js`, `app.css`,
`favicon.svg`. There is no directory listing.

One ONNX intra-op thread (`PREACHED_ORT_THREADS`, default 1) is right for a
1-vCPU box: `reports/W3-CPU.md` measured 4 threads slower on one CPU
(134 ms p50 against 56 ms).

### What the bundle holds

`MANIFEST.sha256` lists every file except itself, `<sha256>  <relative path>`,
sorted. The tar is taken from a private copy of the directory (not a reflink
of the live index or model): ustar, owner 0, mtime `2026-10-30 00:00:00` UTC,
`gzip -n`. The same index, model bytes, and source tree give the same
manifest and the same tar.

The bundled code is derived, not hand-listed: `scripts/bundle_files.py list`
imports the serve entry points and ships every `app`/`preached` module they
load, the data directories inside those packages (`preached/privacy_data`),
and a short list of non-Python files (including `pyproject.toml`, `uv.lock`,
and the Spurgeon and Edwards manifests and provenance files, which the
server imports). It does not ship `torch_embed.py`, the YouTube importer,
ingest code, or eval. After the copy, the build re-imports the server from
the bundle with `python -I` and fails unless every loaded `app`/`preached`
module comes from inside the bundle.

The build also fails if any shipped module uses `importlib` or `__import__`:
an import by string is invisible to that scan, so serve code may not use one.
Known limit: this is a text check for accidental lazy imports, not a
security boundary.
`getattr(builtins, "__imp" + "ort__")`, `exec("import x")`, `runpy`, or
`sys.modules` lookups all pass it; a module loaded that way at request time
is not in the bundle and fails with `ModuleNotFoundError` when it runs, not
at build time. Code review is the control for serve code.

The build writes a stamp, `PREACHED_BUNDLE` (format line, library, model
revision), and lists it in `MANIFEST.sha256`.

### The start-up bundle check

The tree is classified explicitly (`app/bundle.py`):

- **bundle**: `PREACHED_BUNDLE` exists. Every check below applies.
- **checkout**: no stamp, a `.git` entry at the root, and none of
  `MANIFEST.sha256`, `index/`, `model/`, `requirements-serve.txt`. Nothing
  is hashed.
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

`scripts/serve.sh` runs this check as
`python -I -B app/bundle.py ROOT INDEX` before anything imports bundle code.
`app/bundle.py` uses the standard library only. Its preflight (which imports
`app.server`) runs with `PYTHONPYCACHEPREFIX` set to a fresh empty
directory, so in-tree bytecode is never read, in a checkout as well. That
directory is removed before the server starts, or on a failed preflight.
`app/server.py` repeats the check in `main` for any other launcher. Hashing
the bundle (index plus fp32 model) adds a few seconds to start, and
`serve.sh` hashes it twice (the stdlib check, then `main`).

A refusal prints `error: ...` and exits 1.

While serving, a bundle's index is frozen. If the open index changes after
start (chunks, vectors, any commit from another connection, or a status read
that fails), every request gets `503` until the process is restarted. It is
not reloaded. A checkout still reloads in place.

### What `serve.sh` sets

From a bundle, the script uses `bundle/.venv/bin/python` when that exists,
sets `PREACHED_CACHE` to the bundle root, opens
`bundle/index/<library>.sqlite` read-only, and sets `PREACHED_ONNX_DIR` to
`bundle/model`. No debug flag. Hugging Face downloads are off
(`HF_HUB_OFFLINE=1`). The kill file is `PREACHED_KILL_FILE`, default
`<bundle root>/KILL`.

The server process is started with `env -i` and an allow-list (PATH, HOME,
LANG, LC_ALL, TMPDIR, the `PREACHED_*` variables the process reads, and the
offline Hub flags). `PREACHED_CHURCH_SIDE` is not on it. A token exported in
the shell is not in the server's environment. `app/server.py` refuses to run
as root. There is no `PREACHED_ALLOW_ROOT` and no `PREACHED_PYTHON` override.

### Privacy: ONNX Runtime telemetry is off

The official onnxruntime Linux wheels from 1.29 on ship Microsoft 1DS
telemetry, on by default. It creates a persistent device ID and an event
database (`deviceid`, `onnxruntime.db`) under
`$XDG_CACHE_HOME/Microsoft/DeveloperTools/.onnxruntime/` and uploads events
to Microsoft's OneCollector endpoint (see ORT's `docs/Privacy.md`).

Preached turns it off two ways. `scripts/serve.sh` sets and passes
`ORT_DISABLE_TELEMETRY=1`, and `src/preached/onnx_embed.py` sets it with
`os.environ.setdefault` before it imports onnxruntime, then calls
`onnxruntime.disable_telemetry_events()` when that exists. A direct start
(not recommended, see below) is covered by the code alone.

To verify on the host: after the service has loaded the model, check that
`find "$XDG_CACHE_HOME" "$HOME/.cache" -path '*Microsoft/DeveloperTools*'`
prints nothing, and that
`tr '\0' '\n' < /proc/<server pid>/environ | grep ORT_DISABLE_TELEMETRY`
shows `ORT_DISABLE_TELEMETRY=1`. `tests/test_ort_telemetry_off.py` checks the
first part against a scratch cache.

### What a direct start does and does not guarantee

A direct start is `python app/server.py`, `python -B app/server.py`, or
`uv run app/server.py`, run without `serve.sh`. Use `serve.sh`.

It does guarantee:

- No cached bytecode for the server's own `.py` modules is read from the
  tree, and none is written to it. The first lines of `app/server.py`,
  before any `app` or `preached` import, set `sys.dont_write_bytecode` and
  point `sys.pycache_prefix` at a new private empty directory
  (`tempfile.mkdtemp`). `app/__init__.py`, `app/bundle.py` and every
  `preached` module are compiled from their source files. A planted
  `__pycache__` (for example one that makes `bundle_problem` return None) is
  not read; `main` then finds it and refuses to start. The directory is
  removed at exit. When `app/server.py` runs as a script, SIGTERM is blocked
  from before the directory is made until its atexit hook and handler are
  installed, so a SIGTERM at any point removes it. Importing the module
  installs no handler.
- `main` runs the whole bundle check (`bundle_problem`, then the model
  directory check) before it opens the index or binds the port.
- The stop behaviour in "Stop and exit codes" below.

It does not guarantee:

- That the check runs before bundle code. `app.bundle` and `preached.*` are
  imported, from their `.py` files, before `main` hashes those files. An
  edited `.py` in the tree runs first and is only refused afterwards. Files
  added to the tree (a sourceless `.pyc`, a `sitecustomize` under
  `serve.sh`'s `PYTHONPATH`, an extension module) are in the same class:
  refused by the check, but only after they have run. `serve.sh` runs only
  `app/bundle.py` itself before the check.
- Anything about a planted extension module. Python prefers
  `bundle.cpython-312-x86_64-linux-gnu.so` (or any extension suffix) over
  `bundle.py` in the same directory, and it is loaded before the check.
  `serve.sh` runs `app/bundle.py` by path with `-I`, so its check refuses
  that unlisted file before anything imports it.
- Anything for `python -m app.server`. `runpy` imports `app` and
  `app.server` through the normal import system before the first line of
  `app/server.py` runs, so their in-tree bytecode can be read. Do not start
  the server that way.
- Anything about `.venv` or the interpreter (next section).
- A clean exit on SIGKILL. The private bytecode directory (empty, mode
  0700) is left in `$TMPDIR`.
- That `$TMPDIR` is used. If it is set but not writable, `mkdtemp` falls
  back to `/tmp` (same mode 0700, random name, removed at exit).

### Stop and exit codes

- **SIGTERM while serving** is a requested stop, in order: no new
  connections, wait for the handler threads (a search in progress finishes;
  an idle keep-alive connection is closed), close the index (and the church
  index, when one is open), release the ONNX session. The server logs
  `INFO stopping` first. The process exits 0 with no traceback and the
  bytecode directory removed.
- **A stuck handler**: if a handler thread is still running 10 s after the
  stop (`DRAIN_TIMEOUT_S`), the server logs
  `ERROR <n> handler thread(s) still running after 10s; index left open`,
  flushes the suppressed refusal counts, leaves both indexes and the ONNX
  session open, waits for that thread, and exits 1. A second Ctrl-C or
  SIGTERM does not force an exit: the stop is already under way and the
  signal is ignored. Send SIGKILL, or let `TimeoutStopSec=` do it (step 6).
- **SIGTERM after the handler is installed and before serving** exits 0 and
  serves nothing in the cases tested: during the imports, in `main`'s
  start-up checks, and during an `onnxruntime` import that turns it into
  `ImportError` (the server records the request and does not serve the BM25
  fallback).
- **SIGTERM in the first moments of start**, before the first lines of
  `app/server.py` install the handler, kills the process by the signal
  (systemd: step 6, `SuccessExitStatus=143`).
- **Ctrl-C (SIGINT)** while serving stops the same way and exits 0. During
  `main`'s start-up checks it exits 130 with no traceback; during the module
  imports before `main` it prints a traceback and dies by SIGINT.
- **A refusal** (`error: ...`) exits 1.

Tests: `tests/test_shutdown.py` and `tests/test_deploy.py`. The shutdown
test runs 16 clients searching (bm25 and hybrid), an idle server, and an
idle keep-alive connection. The loaded test is probabilistic: on CI's small
bm25 index (3 runs, no hybrid) it misses the old crash about half the time,
so the deterministic in-flight test (a search held open across SIGTERM) is
the CI gate. The gate for a change to the drain is the real-index loaded
run, `PREACHED_SHUTDOWN_RUNS=30 python -m unittest tests.test_shutdown`,
with `/cache` present (bm25 and hybrid). That run does not need deno; the
pre-deploy full-suite command in "Local smoke test" does.

### `.venv` is a trust boundary

`.venv/` is outside the manifest. Nothing in it is hashed: the interpreter,
the third-party packages, and any `sitecustomize.py` or `.pth` file in its
`site-packages` run before, and with the same rights as, the manifest check.
Whoever can write `.venv/` can run code in the server. Create it with
`uv sync --frozen --no-dev --no-default-groups` as the service user, keep it
owned by that user and not group- or world-writable, and recreate it (do not
patch it) on every update. The manifest check proves the bundle's own files;
it says nothing about `.venv/`.

### Reproducing a bundle hash

The tar bytes depend on the source tree, the bundled index copy, the model
files, and the versions of the tools that write them. `build-bundle.sh`
prints each as an `input ...` line after the `tar` line:

- `input source`: the git commit of the source tree, with `dirty` if
  `git status --porcelain` is not empty. A dirty build is not reproducible
  from the repo.
- `input index-file` and `input index-bundled`: sha256 of the index named by
  `PREACHED_INDEX` and of the copy in the bundle. The index is not in git;
  it lives in `/cache`. The bundled copy (SQLite backup API) is what the tar
  holds.
- `input model-revision`: the ONNX revision. The files are pinned by sha256
  in `src/preached/artifacts.py`.
- `input python` (with the SQLite library version), `input uv` (it writes
  `requirements-serve.txt`), `input tar`, `input gzip`.

Two builds with the same `input` lines give the same tar. Someone without
the build machine's `/cache` cannot rebuild the same tar: they need an index
file with the same `index-bundled` sha256 and the pinned model files. The
W3-DEPLOY-PREP report records the inputs of each published hash.

### Hardening

In the process:

| Control | Behavior |
| --- | --- |
| Read-only index | SQLite `mode=ro` and `query_only`. The bundled file is `journal_mode=DELETE` and mode `0444`. |
| Read-only model | Bundle copies are mode `0444`. The loader does not download. |
| Control characters | A NUL or any other control character in the request line (apart from its CRLF ending), or in a header value (HTAB is allowed, RFC 9110 5.5), is a `400` and the connection is closed. The line is not logged. |
| Request size | Path at most 2048 bytes, headers at most 8192, body at most 4096. No chunked bodies. A 405, or any earlier error, that leaves a body unread closes the connection, so those bytes are not parsed as a second request. |
| Header deadline | 15 seconds for the request line and all headers together. A slow byte does not reset the clock. |
| Connections | At most 32 concurrent connections, and at most 4 from one socket IP (a trusted proxy is exempt from the per-IP cap). Over the cap the accept thread returns 503 with `Retry-After: 1` and does not start a handler thread. When that request's `Accept` names `text/html` with a nonzero weight, the body is a static HTML page with a meta refresh of the same 1 second, and no byte of the request is copied into the page. Any other request still gets `{"error":"unavailable"}`: `Accept: application/json`, `text/html;q=0` (q=0 means not acceptable), and the wildcards `*/*` and `text/*`, which are not taken as `text/html` (pinned in `tests/test_html_503.py`). The accept thread reads only the request bytes already buffered when it accepts, and never waits for more, so a silent connection cannot hold it. A request whose headers have not all arrived by then (sent late, or split across packets) gets the JSON body, even from a browser; the browser shows it until reloaded. A connection counts until its last response is flushed, so the per-IP cap of N includes a closing response still being written: a peer at its cap that reconnects the instant it has read a `Connection: close` response can get that 503, and should retry after 1 second. There is no grace period, which would let a closing connection and its replacement both count as one. A peer already at its cap may take its own oldest idle keep-alive once that socket has been quiet for 1 second, and the new connection uses that slot. A request that arrives on the idle socket at the moment of the hand-over is dropped. Busy sockets, sockets still receiving headers, and a reserved `/healthz` connection are not taken, and a new connection during that quiet second is still refused. Clients sharing a NAT or an IPv6 /64 are one peer and can close each other's idle keep-alives, which is intended. `PREACHED_MAX_CONNECTIONS` and `PREACHED_MAX_CLIENT_CONNECTIONS` override the numbers. |
| Slot fairness | When all 32 are taken, a new connection takes the slot of the longest-idle connection (waiting between requests) of the peer holding the most, if that peer holds at least two more than the newcomer. A connection whose request line has arrived and whose headers are still coming is taken only when no such peer has an idle one left. A request being handled is never closed. Once 8 or fewer slots are free, a connection waiting for its next request gets 2 seconds, not 15 (`PREACHED_SCARCE_IDLE_S`). At most 4 searches (and, separately, 4 `/healthz` requests) in flight per client key (`PREACHED_MAX_CLIENT_REQUESTS`); over that is `503`, `Retry-After: 1`, and the connection closes. A request counts until its response is written, so a client at its cap that sends the next request the instant it has read a response can get that 503. An IPv6 peer is counted by its /64. |
| `/healthz` reserve | When nothing can be closed, one more connection is admitted (`PREACHED_HEALTH_RESERVED_CONNECTIONS`, default 1, 0 turns it off). It serves one `/healthz` and closes (`Connection: close`). Any other path on it is `503`. While it is held, the next newcomer gets the accept-time `503`. |
| Client key | The socket peer, or its /64 for IPv6 (IPv4-mapped IPv6 is folded to IPv4). A Tailscale address (`fd7a:115c:a1e0::/48`, where every node shares one /64) is keyed per address. Trust is by the listed network only, never widened to the proxy's /64. `X-Forwarded-For` is read only when the peer is in `PREACHED_TRUSTED_PROXIES` (comma-separated addresses or networks, default empty). Then the key is the right-most hop that is not a trusted proxy. Hops to its left are never read. A forwarded IPv6 hop is keyed by its /64 too. A hop that does not parse keys on the nearest trusted address. A malformed `PREACHED_TRUSTED_PROXIES` entry stops the server. `Forwarded` (RFC 7239) is ignored. |
| Rate limit | 60 requests per 60 seconds per client key in `serve.sh` (the code default is 120, so the unit tests fit). Behind that, a global backstop of 600 per 60 seconds across all clients in `serve.sh` (code default 1200, `PREACHED_GLOBAL_RATE_LIMIT`). A client over its own cap does not spend the backstop, and a request the backstop refuses gives its hit back to the client's own bucket. A full table of live keys refuses a new key. `429` and `Retry-After`. |
| `/healthz` bucket | Its own per-client bucket (60 per 60 seconds, `PREACHED_HEALTH_RATE_LIMIT`) and its own global backstop (600, `PREACHED_HEALTH_GLOBAL_RATE_LIMIT`). Health checks never spend the search budget, and a search flood does not starve them. The connection caps above still apply, before the path is known. |
| Socket timeout | 15 seconds on a read or a write after the headers (`REQUEST_TIMEOUT_S`). |
| Headers | CSP, `nosniff`, `no-referrer`, `X-Frame-Options: DENY`, `Server: Preached`. CSP is unchanged. |
| Logs | Access log is `peer key method path status`: the socket peer, then the client key (the forwarded client behind a trusted proxy, the peer otherwise, a /64 for IPv6). The query string is not logged. Control characters are escaped in both addresses and the path. Refusals are logged as `refused <class> ... suppressed=N` warnings, at most one line per class per second, where N counts the lines dropped since the last one. Classes: `over-cap` (accept-time 503), `evict` (`holder->newcomer`), `busy` (per-key in-flight 503, or a non-`/healthz` request on the reserve), and `429-client`, `429-global`, `429-health`, `429-health-global`. Counts still suppressed at shutdown are logged as `refused <class> flush suppressed=N`. A bad request line does not crash the process. A failed request logs the exception type, not the message. |
| No listing | `/static/` is an allowlist of three files. |
| Kill file | Checked on every request. `touch KILL` in the bundle root stops serving without a restart. `/healthz` becomes `503` with `{"ok": false, "disabled": true}`. Search returns `{"error": "unavailable"}`. Removing a regular KILL file turns it back on, again without a restart. A directory, a symlink (dangling or not), or an unreadable parent at that path is treated as killed. The file's contents and path are not sent to the client. |
| `PREACHED_DISABLED` | Read from the process environment on each request. Set it before start. Another shell cannot change a running process's environment, so this is not the without-restart switch. The kill file is. |
| Library gate | `check_servable` only. |
| Server environment | `exec env -i` plus the allow-list in `scripts/serve.sh`. |

API clients (Hark, parallel callers) must honour `Retry-After` on a `503`
(wait that long, then retry; do not retry at once) and on a `429`. Users
behind one IP, such as a shared office, school or NAT, share that IP's caps
(4 connections, 4 requests in flight, and the rate limit), unless the IP is
a trusted proxy that forwards `X-Forwarded-For`, which keys them separately.

### Notes for the host

- **Trusted proxy.** The in-app limits key on the socket address.
  `X-Forwarded-For` is ignored unless the peer is listed in
  `PREACHED_TRUSTED_PROXIES` (empty by default). With `tailscale serve` in
  front, the peer is loopback: list `127.0.0.1` only if that proxy is the
  only thing that can reach the port, and check that it appends
  `X-Forwarded-For`. Otherwise leave it empty; every proxied client then
  shares one bucket, which fails closed. Any local process on the Sprite
  that can connect from `127.0.0.1` is then the trusted proxy and can choose
  its own key.
- **Log volume.** The server writes one access line per request, and
  refusal lines at most once per class per second, to stderr. Under
  systemd that goes to journald, which rate-limits each service
  (`RateLimitIntervalSec=`, `RateLimitBurst=` in `journald.conf`, or
  `LogRateLimitIntervalSec=`/`LogRateLimitBurst=` in the unit). Over the
  limit it drops lines and logs one "Suppressed N messages" line, so a
  flood can cost access lines, and alert lines with them. Rotation and the
  disk cap are `SystemMaxUse=`, `SystemMaxFileSize=` and `MaxRetentionSec=`.
  The lines hold real client IPs behind a proxy, so the retention period is
  a go-public decision (Part 4, item 5), not a default to leave in place.
- Do not enable directory listings, a debug console, or a shell on the
  listening port.

## Part 3: The church side (not deployed)

**Do not deploy a church side.** It stays off until every hard condition
below is met. These holds stand whatever the code allows. The bundle does
not ship a church file and `serve.sh` passes no church option, so a deploy
by Part 1 has no church side.

### Church deploy hard conditions

Every item is **OPEN**. None is met.

- [ ] **OPEN: Pastor permission.** Gaston Community Church's pastor has
  given permission. Until then Gaston sermons are not used or published.
- [ ] **OPEN: CTO church-deploy approval.** The CTO approves this church
  deploy, in writing.
- [ ] **OPEN: Patrick's approval** of the church deploy, in writing.
- [ ] **OPEN: Operator-chosen unguessable slug.** The church slug
  (`--church-library`, or the file's stem) is chosen by the operator and is
  hard to guess. It is not the church's public name: the slug is what a
  client asks for in `library=`.
- [ ] **OPEN: Infra Ops alerts on the exact strings.** The rules in the
  alert tables below (drafted by Infra Ops, every rule `enabled: false`) are
  enabled after the church deploy is approved, matching the exact strings,
  including `church side refused: the church file could not be opened` and
  `church side paused:`.
- [ ] **OPEN: The writer-lock fix: fixed in #46, pending CTO deploy
  verification.** A church file that is busy at start (a writer's lock, or
  WAL mode while `--ack-review` runs) is no longer a refusal. The server logs
  `INFO church side paused: <reason>` (`app/server.py:1532`), retries the open
  after 1 s, doubling to 30 s (`CHURCH_RETRY_FIRST_S`, `CHURCH_RETRY_MAX_S`,
  `app/server.py:285-286`), and the side comes back with no restart.
- [ ] **OPEN: Church-on integration test: added in #46, pending CTO
  verification.** One test, with a church side open, under #29's caps,
  covering: health buckets, refusal-log flush, SIGTERM, and the stuck path
  (`tests/test_church_harden.py`, commit `b9833d8`).

A church side is not started until every condition above is met, including
the CTO's sign-off on each and Patrick's written approval.

Met, for the record (these are not church conditions that stay open):

- [x] **MET: HD1, the startup `paused` line logged before `listening on`**
  (fixed in #48 at `76990e8`; see the "Other lines" table).
- [x] **MET: #27 S1 and #33 should-fixes 1-2** (CTO #37 r3).
- [x] **MET: the #39 tar/bundle gate** (CTO #39 r2).

Approval rule for every church sermon: it is not approved on a cue-rule
pass. The reviewer must listen through the whole recording, start to end,
before approving a church sermon (CTO ruling, 2026-10-30, the human-review
rule from #19). On the LLM-written synthetic test set the rules caught 635
of 730 words that should have been excluded (ASR word recall 0.870), so
they miss some. Listening is the real control. Add an exclude line for
every announcement, prayer request, prayer list, or testimony the rules
missed. That rule is the one in the review file header (`reviewer_must`)
and in `reports/W3-PRIV-SKIP.md`.

### How the church gate works

`--church-library <slug>` or `--church-index <file>` adds a second,
read-only column of approved church sermons. `app/server.py` opens it only
when every condition below holds, from a checkout or a bundle. Otherwise
the classic side serves exactly as with no church named.

1. **Deploy switch.** `PREACHED_CHURCH_SIDE=enabled` (exactly that value)
   is in the server's environment. It is not on `serve.sh`'s allow-list, so
   a `serve.sh` start never has it. Without it the church file is not
   opened.
2. **Privacy config.** `PREACHED_PRIVACY` names the library's privacy TOML
   (`privacy.example.toml`). Approval must run under the same config as the
   import.
3. **Permissions and owner.** The church name is not a symlink. The real
   file and the directory that really holds it are owned by the serving uid
   (or root), and neither is group- or world-writable. So is every
   directory above it up to `/`, on the path given and on the real path;
   the one exception is a root-owned sticky directory (like `/tmp`) whose
   next component is owned by the serving uid or root. The file SQLite
   opened must be the inode that was checked. The file has one hard link
   and is not a classic. Its `-wal`/`-shm`/`-journal` names, when present,
   are plain files with one link. These are checked at start and before
   every church search.
4. **DELETE journal mode.** `--ack-review` leaves the file in DELETE mode,
   so the read-only open creates no `-wal` or `-shm`. If `--ack-review`
   prints `warning: the church file is still in wal journal mode`, close the
   other reader and run it again. A file in WAL mode, or locked by a writer,
   is a pause (below), at start as well as while serving. The church
   connection never waits for a lock (`busy_timeout` 0), so a writer never
   stalls the server.
5. **Publish gate.** Only approved sermons are served: the review file's
   sha256 was approved, `status = 'ok'`, and ASR coverage was checked with
   no open gap. A human listened through each recording first (above).

What happens, and what is logged:

- **Refused at start.** Any other failed condition at start logs one
  `ERROR church side refused: <why>` line (`app/server.py:3002`, `:3009`,
  `:3020`, `:1444`, `:1449`). The church side stays off until restart.
  When the church searcher cannot be built, the line is
  `ERROR church side refused: its searcher could not be built (<Type>: <why>)`
  (`app/server.py:922`): one line, no traceback.
- **Paused at start.** A church file that is busy at start (a writer's
  lock, `src/preached/library.py:895-896`, `:921-922`; or WAL mode,
  `:883-884`, reason `<file> is in WAL journal mode`; or the start's own
  `church_file_problem` check pausing, `:915`, with the text of `:962` or
  `:468`; or the searcher build finding the lock, `app/server.py:919`) is
  not a refusal. The
  server logs `INFO church side paused: <reason>` (`app/server.py:1532`),
  and retries the open on a later church request after 1 s, doubling to 30 s
  (`CHURCH_RETRY_FIRST_S`, `CHURCH_RETRY_MAX_S`). The side returns without a
  restart. A retry runs the whole start again (`open_church`, the searcher
  build, the install; the `start` closure at `app/server.py:1814`). A failed
  retry logs one `ERROR church side refused: <why>` line, the same line a
  start would log: `app/server.py:3002`, `:3009` or `:3020` (an ordinary
  refusal), `:922` (the searcher could not be built), `:1444` or `:1449`
  (the install). Only an unexpected exception logs
  `ERROR church side refused: the church file could not be opened (<exc>)`
  (`app/server.py:1482`). Either way the retries end and the pause is
  cleared (`_church_paused = False`, `app/server.py:1490`) with no
  `resumed` line. `INFO church side pause ended: refused`
  (`app/server.py:1489`) follows any refusal of a retry while paused
  (rows 1-3), not only `:1482`; the refusal line precedes it. Not an
  alert. The side is off until restart. A file that is busy again
  on a retry (`ChurchPaused`, also from the searcher build, `app/server.py:919`)
  keeps the pause and doubles the wait, with no new `paused` line. A
  successful retry logs
  `INFO church side: <slug>, read-only, through the publish gate`
  mid-process, so that line is **not** a restart marker. A pause found at
  start is held and logged by `log_startup_pause` (`app/server.py:1540`,
  called at `:2934`) after `INFO listening on` (HD1, MET, fixed in #48).
- **Dropped while serving.** A problem found before a church search (owner,
  mode, inode, link count, sidecars, shape) logs
  `ERROR church side dropped: <why>` once. The side stays off until
  restart.
- **Paused while serving.** A writer's lock or a WAL-mode file seen after
  the side is open skips the church side for that request only. Nothing is dropped.
  `INFO church side paused: <why>` is logged once when the pause starts,
  and `INFO church side resumed` once, after the next church search
  completes. With no church searches, no `resumed` line comes.
- **Search failed.** Any other exception in a church search logs
  `ERROR church search failed; that side is empty` with a traceback; that
  request's church column is empty and the side stays open.

A paused, dropped, or refused church side, and a server with no church
side, all look the same to a client: `/api/side` returns the church column
with `"present": false`, and `/healthz` says `"church": null` in every
case. Neither endpoint reports "paused".

Known gaps, accepted for now:

- The checks run by name. A same-uid process can still race them (#33).
- A file edited or corrupted in place, without a new inode, can still be
  served from SQLite's page cache until the next read misses it.
- `/healthz` says nothing about the church side (above).

### Alert rules (Infra Ops)

The rules live outside the repo, kept by Infra Ops, at
`/workspace/infra-ops/preached/alerts/church-alerts.yaml` on the ops box.
They are not readable from this repo. **Every church rule stays DISABLED
until the church deploy is approved** (hard conditions above).

Log format: `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")`
(`app/server.py:3189`). Each line is the level name, one space, the
message. Patterns are anchored to the start of the line. A
`logging.exception` call adds a traceback on the following lines.

Infra Ops' yaml is `church-alerts.yaml`, sha256
`42dd7e7c762a575a3333c676d6560b545dd0443da67c9cef4243df1487794d24`: 25 rules,
every one `enabled: false`. It supersedes the 21-rule file
`c1841274aed5d778b9fa3b9b417a456c53a38555fb9403cb072deba68b676f0e` (pinned to
main `76990e8`, drafted at `0f2b553`). The line numbers below are this
tree: the merged tree this file ships in (main plus the listen backlog change), in `app/server.py`. Each `app/server.py` cite was read off that file. D2b is
drafted. `INFO stopped cleanly` is `deploy-stopped-cleanly`. All rules stay
disabled until Infra Ops enables them after deploy approval.

| # | Severity | Rule id | Line starts with | Emitted at | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | PAGE | `church-refused` | `ERROR church side refused:` | `app/server.py:1444`, `:1449`, `:3002`, `:3009`, `:3020` | Any refusal, at start or on a retry of a paused start, one line. Start-time lock and WAL are no longer refusals (row 5). |
| 2 | PAGE | `church-refused` | `ERROR church side refused: its searcher could not be built` | `app/server.py:922` | `ERROR church side refused: its searcher could not be built (<Type>: <why>)`, one line, no traceback. At start or on a retry of a paused start. |
| 3 | PAGE | `church-refused` | `ERROR church side refused: the church file could not be opened` | `app/server.py:1482` | `ERROR church side refused: the church file could not be opened (<exc>)`, only for an unexpected exception on a retry of a paused start (an ordinary failed retry logs a row 1 or row 2 line). In the paging group with rows 1-2. Any failed retry ends the retries and clears the pause with no `resumed` line. |
| 4 | PAGE | `church-dropped` | `ERROR church side dropped:` | `app/server.py:1521` | Off until restart: the same effect as a refusal (the church side stays off until restart), so it pages with rows 1-3. Final severity (CTO). |
| 5 | INFO, then PAGE | `church-paused` -> `church-paused-stuck` / `church-paused-unverified` | `INFO church side paused:` | `app/server.py:1532`, `:1540` | Opens a 15-minute window. Start-time busy file, or a lock or WAL seen while serving. The side retries (1 s doubling to 30 s) and returns without a restart. Closed by `INFO church side resumed` (`app/server.py:1599`), which is logged only after the next church search completes, and also by a refused or dropped line or the restart marker. It pages (`church-paused-stuck`) only on a second `GET /api/side 200` logged after the window, at least 30 s (`confirm_after`) after the first; with no church search, no `resumed` line comes and the rule raises the info notice `church-paused-unverified`, not a page. See the note below. A pause found at start is held and logged after `listening on` (`:1540`, a `%s` of the held text; a grep for `church side paused` in the source misses it). A page for a start-time pause can therefore come late. `church-paused-stuck` PAGE (with the 30 s confirm), `church-paused-unverified` INFO (CTO final). |
| 6 | TICKET | `church-search-failed` | `ERROR church search failed; that side is empty` | `app/server.py:1602` | At most one ticket per hour. Traceback follows. Final severity TICKET (CTO). |

Rule numbers moved with #46: the old rule 1 (a writer's lock at start is a
page) is obsolete, and the old rule 2 is split into rows 1-3 above. The old
rows 3-5 are now 4-6.

On row 5: Infra Ops' prepared rule (`church-alerts.yaml`, state machine
`church-paused`, CTO-approved) is passive. It does not probe.

- `INFO church side paused:` opens the pause and a 15-minute window.
- The pause is cleared by `INFO church side resumed`, by an
  `ERROR church side refused:` or `ERROR church side dropped:` line, and by
  the restart marker `INFO listening on http://`. A cleared pause raises
  nothing.
- Candidates are access lines matching `^INFO \S+ \S+ GET /api/side 200$` <!-- regex: side-access -->
  logged after the 15-minute window while the side is still paused. Lines
  inside the window are not candidates.
- It raises the page `church-paused-stuck` only on a second candidate
  logged at least `confirm_after: 30s` after the first candidate. One
  candidate alone never pages: a paused start retries only when its wait
  is over, so one request can land inside the wait and never try the file.
  30 s is the longest wait (`CHURCH_RETRY_MAX_S`), so a request 30 s after
  the first has had a retry.
- With no church traffic to confirm it, it raises the info notice
  `church-paused-unverified`. That is not a page: with no church search,
  nothing shows whether the lock is gone.

A revert (paging on the first candidate again) is the one `confirm_after`
value in the yaml; nothing else in the rule changes.

`/api/side` has no paused state: a paused side gives `"present": false`, the
same as a dropped or refused one. A `GET /api/side?q=...` is itself a church
search, so it ends the pause (and logs `resumed`) if the lock is gone. The
rule quotes only what CTO stated; the yaml is not in this repo.

Optional manual check, not part of the rule: after 15 minutes, one
`GET /api/side?q=<word>&library=wesley` probe. `"present": true` means
resumed; `"present": false` with no `dropped` line since the `paused` line
means still paused.

#### Church silent degradation (ticket)

Rule drafted, disabled (Infra Ops, `church-alerts.yaml`; enabled after deploy
approval). Final severity TICKET (CTO).

The church searcher can fail to load its vectors and the side then serves
BM25 only, with no refusal. Both lines carry a traceback
(`logging.exception`):

| # | Severity | Rule id | Line starts with | Emitted at | Notes |
| --- | --- | --- | --- | --- | --- |
| 7 | TICKET | `church-vectors-mismatch-bm25` | `ERROR church vectors do not match search/models.toml; that side is BM25 only` | `app/server.py:896` | The church file's stored vectors do not match the configured model. Traceback follows. Rule drafted, disabled. |
| 8 | TICKET | `church-vectors-unavailable-bm25` | `ERROR church vectors unavailable; that side is BM25 only` | `app/server.py:901` | The church vectors could not be loaded. Traceback follows. Rule drafted, disabled. |

#### Deploy alerts

These are lines from the Wesley deploy, not the church side. D1-D7, D2b and
`deploy-index-stamp-unreadable` are drafted and disabled (Infra Ops,
`church-alerts.yaml`); Infra Ops enables them after deploy approval. D2
fires only at startup: a reload does not emit it. D1, D2 and D2b page once
per transition, deduped to at most 1 per hour. D2b is PAGE, disabled until
deploy approval. D7 (`deploy-abstain-calibration-unusable`) is TICKET, at
most 1 per hour. `deploy-index-stamp-unreadable` is TICKET, at most 1 per
rolling hour (the cap survives restarts). `INFO stopped cleanly` is
`deploy-stopped-cleanly` (INFO; the other-lines table). D1 or D2 at start
is a failed go-live (step 7). Severities are the CTO's final rulings.

| # | Severity | Rule id | Line starts with | Emitted at | Notes |
| --- | --- | --- | --- | --- | --- |
| D1 | PAGE | `deploy-stored-vectors-mismatch-bm25` | `ERROR stored vectors do not match search/models.toml; serving BM25 only` | startup `app/server.py:863` (text `:296`); reload `:1169` via `:1201` | Startup (`logging.exception`) carries a traceback. A reload logs the same line once per transition, when the note changes, with no traceback. Pages once per transition, deduped to at most 1 per hour. Dense search is off. Rule drafted, disabled. |
| D2 | PAGE | `deploy-embedding-unavailable-bm25` | `ERROR embedding model unavailable; serving BM25 only` | startup only, `app/server.py:872` (text `:297`); missing graph `:868` | Fires only at startup, in two forms. A load failure logs it with a traceback (`:872`). A missing ONNX graph or manifest (the export never ran) logs it with `logging.error`, no traceback (`:868`), and the next line is `ERROR ONNX GRAPH NOT BUILT…` (row below). The regex `^ERROR embedding model unavailable; serving BM25 only$` matches both. A reload does not emit this line (that path is D2b). Pages once per transition, deduped to at most 1 per hour. Dense search is off. Rule drafted, disabled. |
| D2 detail | none (not an alert; D2 already pages) | none | `ERROR ONNX GRAPH NOT BUILT. Hybrid search is OFF; results are BM25 only.` | `app/server.py:869` (text `:300`) | Follows the missing-graph D2 line. The rest of the line is the missing path and the export command (`uv run --group bench python scripts/export_onnx.py`). No traceback. `/healthz` then reports `"search_mode": "bm25"` and `"search_mode_reason": "onnx_graph_not_built"` (`:1348-1349`, codes `:306-312`). The other reasons are `model_unavailable` (D2 with a traceback), `stale_vectors` (D1), `index_unreadable` (D2b), and `bm25_only` (`--bm25-only`). With dense search loaded it is `"hybrid"` and `null`. The reason is a code, never a path. |
| D2b | PAGE | `deploy-index-status-unreadable-bm25` | `ERROR index status unreadable after reload; serving BM25 only` | `app/server.py:1169` via `:1244` (text `:302`) | Regex `^ERROR index status unreadable after reload; serving BM25 only$`. Reload only, and only when dense search was loaded. Once per transition, no traceback. Pages once per transition, deduped to at most 1 per hour. Rule drafted, disabled until deploy approval. |
| D3 | PAGE | `deploy-refusing-after-reload` | `ERROR refusing to serve after reload:` | `app/server.py:1152` | A checkout reloaded an index it will not serve. Rule drafted, disabled. |
| D4 | PAGE | `deploy-refusing-frozen-bundle` | `ERROR refusing to serve:` | `app/server.py:1235` | The frozen bundle index changed after start; every request is `503`. Rule drafted, disabled. |
| D5 | PAGE | `deploy-stuck-stop` | `ERROR <n> handler thread(s) still running after 10s; index left open` | `app/server.py:3372` | The stuck stop (the 10 s `DRAIN_TIMEOUT_S` line, logged after `stopping` at `:3367`); exit 1. It does not log `stopped cleanly`. Rule drafted, disabled. |
| D6 | TICKET (server types), INFO (client types) | `deploy-request-failed-server` (TICKET, at most 1 per rolling hour), `deploy-request-failed-client` (INFO) | `ERROR request failed:` | `app/server.py:2031`, `:2036`, `:2081`, `:2083`, `:2143`, `:2383`, `:2404` | The line carries the exception type only. Ordinary clients produce it: a slow header, a keep-alive left idle past 15 s (`REQUEST_TIMEOUT_S`) and a reset give `TimeoutError` and `ConnectionResetError`. The client-caused types `TimeoutError`, `ConnectionResetError`, `BrokenPipeError` and `ConnectionAbortedError` go to the INFO rule; every other type goes to the TICKET rule. Rules drafted, disabled. |
| D7 | TICKET | `deploy-abstain-calibration-unusable` | `ERROR abstain calibration unusable; abstain floor disabled` | `app/server.py:1808` | At most 1 per hour. Traceback follows. The server serves with no abstain floor. Rule drafted, disabled. |
| stamp | TICKET | `deploy-index-stamp-unreadable` | `ERROR could not read the index stamp` | `app/server.py:1121` | Regex `^ERROR could not read the index stamp$`. At most 1 per rolling hour; the cap survives restarts. `enabled: false`. Traceback once per outage, then DEBUG. With dense search loaded, a stamp failure also fires the D2b page (D4 in a frozen bundle): one page for impact, one ticket for cause. Under `--bm25-only` this is the only alert. Recovery is silent (`/healthz` `"dense": true` only). Open suggestion for the CTO: log `INFO dense search restored` when dense search comes back. That line is not logged today. Rule drafted, disabled. |

Observability holds from W3-OBS-GAPS, MET in #51 (`8cd3104`, merged as `87c0395`):

- [x] **MET: a BM25 fallback during a reload is logged.** The reload
  BM25-fallback hard condition applies to any deploy that can reach the
  reload paths (a checkout deploy and the church site). A frozen bundle
  still refuses first at `app/server.py:1235` (D4) and does not fall back.
  On a checkout, stored vectors that no longer match log D1 once per
  transition (`:1169` via `:1201`). An unreadable index status, when dense
  search was loaded, logs D2b once per transition (`:1169` via `:1244`).
  A server that never loaded weights stays quiet on that path: startup
  already logged why, and D2 (`:872`) fires only at startup. D1 and D2 at
  startup still carry a traceback (`:863`, `:872`), except D2's
  missing-graph form (`:868`), which has none. The failed stamp read
  logs `ERROR could not read the index stamp` with a traceback once per
  outage (`:1121`), then DEBUG while the outage lasts. With dense search
  loaded, that also fires the D2b page (D4 in a frozen bundle); under
  `--bm25-only` the stamp line is the only alert. Recovery is silent
  (`/healthz` `"dense": true` only). D2b itself has no traceback.
- [x] **MET: a clean stop logs `INFO stopped cleanly`**
  (`app/server.py:3384`). It is the last line of the clean path, after the
  church connection closes (`:3382`). The stuck path logs D5 (`:3372`) and
  exits 1, and does not log this line. The INFO rule is
  `deploy-stopped-cleanly`, drafted and disabled (other lines table).

Other lines this runbook names, all read off this tree. The Rule id column is the INFO rule Infra Ops drafted (disabled), where there is one:

| Line | Rule id | Emitted at | Where it shows |
| --- | --- | --- | --- |
| `INFO church side: <slug>, read-only, through the publish gate` | `church-opened` (INFO) | `app/server.py:3027` | Church side opened, at start or on a successful retry. Not a restart marker. |
| `INFO church side paused: <file> is in WAL journal mode` | `church-paused` (INFO) | `app/server.py:1532` (direct) or `:1540` (held at start, logged after `listening on`), text from `src/preached/library.py:883-884` (start) or `:962` (the check, before a search, or at start through `:915`) | Pause line, WAL form. |
| `INFO church side paused: the church file is locked by a writer (...)` | `church-paused` (INFO) | `app/server.py:1532` or `:1540`, text from `src/preached/library.py:895-896`, `:921-922` (start), `:468` (the check, before a search, or at start through `:915`), `app/server.py:919` (searcher build, at start or on a retry) or `app/server.py:1607` (search) | Pause line, lock form. |
| `warning: the church file is still in wal journal mode (...)` | | `src/preached/youtube/pipeline.py:333`, text from `src/preached/youtube/library.py:157` | `--ack-review` output (step 4 of the gate). |
| `INFO listening on http://<host>:<port>` | `process-restart` (INFO) | `app/server.py:2930` | Server up. Infra Ops' restart marker. A start-time `paused` line is logged after it, by `log_startup_pause` called at `:2934` (HD1, MET, fixed in #48). |
| `INFO stopping` | `deploy-stopping` (INFO) | `app/server.py:3367` | Start of every stop. |
| `INFO stopped cleanly` | `deploy-stopped-cleanly` (INFO) | `app/server.py:3384` | Last line of a clean stop. The stuck path (D5) does not log it. Rule drafted, disabled. |
| `ERROR <n> handler thread(s) still running after 10s; index left open` | `deploy-stuck-stop` (PAGE) | `app/server.py:3372` | The stuck path; exit 1 (also D5 above). |
| `WARNING refused <class> <detail> suppressed=N` | `deploy-refusal-warning` (INFO) | `app/server.py:506` | Rate-limited refusal lines. |
| `WARNING refused <class> flush suppressed=N` | `deploy-refusal-flush` (INFO) | `app/server.py:518` | Counts flushed at stop. |
| `tar exited 1 (file changed as we read it?); attempt N of 3` | `build-tar-flake-retry` (INFO, build stream only) | `scripts/build-bundle.sh:239` | Build machine, the tar flake. Not an alert. |
| `tar failed (tar 1, gzip 0); no archive written` | `build-tar-flake-exhausted` (INFO, build stream only) | `scripts/build-bundle.sh:243` | Build machine, the tar flake after three attempts: rerun once. Not an alert. |
| `tar.gz does not match MANIFEST.sha256; no archive written` | | `scripts/build-bundle.sh:247` | Build machine: a real error. |

Code nit, OPEN (a later code change, not in this PR): an idle keep-alive
timeout should not log at ERROR. Today it is `ERROR request failed:
TimeoutError`, which D6 routes to INFO by type.

`tests/test_deploy_alerts.py` pins the start-time lock pause (no log line,
`ChurchPaused`), the row-6 line and its traceback, the one-line
searcher-build refusal, the log format, and that this file quotes each of
them. It also checks that the string in every `file:line` this file cites
(the alert rows, the "Other lines" table, the gate and unit bullets and the
MET observability bullets) sits on that line of that file, and that this file cites
it in the same row or paragraph. A change that moves a cited line, or edits
its text in place, fails it until this file is refreshed.

## Going public (Part 4, not part of this deploy)

Do not add a public DNS name, a public `Host` entry, or a public bind as
part of standing the server up. Until every item below is done, the
process stays on loopback or Tailscale.

Public exposure goes only through Tailscale (`tailscale serve` or
`tailscale funnel` to the loopback port), with
`PREACHED_TRUSTED_PROXIES=127.0.0.1`. The process never binds a public
interface. Eviction and the per-peer connection cap matter only for a
direct bind: behind the proxy every connection comes from `127.0.0.1`,
which is exempt from the per-peer cap and holds all the slots.

### Threat model (DRAFT, not final)

Status: draft from W3-EXPOSURE-HARDEN. It is not signed off and does not
authorise a public bind. Nothing here changes the gate order below.

#### Assets

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

#### Attackers

- Anonymous internet clients: floods, many source addresses, slow senders,
  idle keep-alive holders.
- Clients that forge `X-Forwarded-For` to get fresh rate buckets or to frame
  another address.
- HTTP parser abuse: request smuggling, control characters, oversize
  headers, bodies on GET-only routes.
- A local user, or anything that can write the bundle, `.venv/`, or the
  index on the host. Out of scope for the in-app gates; covered by
  ownership and modes (see "`.venv` is a trust boundary").
- Anyone holding the Sprite admin credential. Out of scope for the app;
  covered by rotation.

#### Entry points

- The listening socket: `GET`/`HEAD` on `/`, `/static/<allowlisted>`,
  `/api/search`, `/api/side`, `/api/sermon/<id>`, `/healthz`. Every other
  method is `405`; no route reads a body.
- Request headers that change behaviour: `Host` (allowlist),
  `Content-Length` and `Transfer-Encoding` (refused unless plain),
  `X-Forwarded-For` (only from a trusted proxy).
- Process environment, set by `scripts/serve.sh` through `env -i`.
- The kill file at `PREACHED_KILL_FILE`.
- The bundle on disk, checked once at start.

#### Controls in place

The Hardening table in Part 2: Host allowlist, size limits, framing and
control-character refusal, header deadline, connection caps and slot
fairness, trusted-proxy keying, per-client and global rate limits, the
separate `/healthz` bucket, the kill file, the frozen bundle index, the
manifest gate, root refusal, and the scrubbed environment.

#### Known gaps

- Thread per connection. Caps and eviction bound it, but a distributed
  flood of real requests up to the global backstop still costs CPU, and
  32 busy searches fill every slot (busy requests are never closed).
- The connection caps run before the path is known. One connection over
  the cap is reserved for `/healthz`, but one client can hold it for up to
  the scarce header deadline (2 s) and reconnect, so the reserve is a best
  effort, not a guarantee.
- The 32-address lockout on a direct bind. Eviction needs a peer holding at
  least two more connections than the newcomer. 32 addresses that each
  hold one connection and reconnect about 4 times a second without sending
  a request leave no victim, so legitimate newcomers got 65 of 65 `503`s
  in the CTO's run. PR #18 behaves the same. Behind Tailscale this does not
  apply (one peer), but the 32 slots are then the shared limit.
- Any local process on the Sprite counts as the trusted proxy when
  `PREACHED_TRUSTED_PROXIES=127.0.0.1`, and can forge `X-Forwarded-For` to
  pick any key (a fresh bucket, or someone else's).
- With `PREACHED_TRUSTED_PROXIES` left empty behind `tailscale serve`, the
  log and the limits key on the socket peer, not the client: every proxied
  request is logged and limited as `127.0.0.1`, so all clients share one
  bucket (fails closed).
- No TLS in the process. TLS has to come from the proxy or Tailscale.
- A garbage `X-Forwarded-For` hop written by a trusted proxy keys on that
  proxy, so those clients share one bucket.

### Remaining go-public gate items

The go-public gate. All of these, in this order. None is done.

1. **Threat model.** Written and final. The draft is above; it is not final.
2. **RSS fix (#26) go-live checks on the Sprite.** RSS with dense search on
   is now 721 MiB; what is left is proving the dense path is the one
   serving: `/healthz` shows `dense: true`, `fallback: false`, and
   `model_sha256` equal to the fp32 pin, and `model/` is not
   group- or world-writable (`find model ! -type l -perm /022` prints
   nothing). A
   bundle unpacked under `umask 002` silently serves BM25 only.
3. **Stale-bytecode drill (#18) on the Sprite.** Plant a `__pycache__` that
   would change `bundle_problem`, start through `scripts/serve.sh`, confirm
   the start is refused, remove it. Never start with `python -m app.server`.
4. **Audit logging (PR #29 review M2) accepted.** The log names the client
   key, and refusals and evictions are logged. In code on main since PR #29
   was merged; the item closes when the CTO accepts it.
5. **OPEN: Access-log retention.** The log stores the real client IP behind the
   proxy, with path and time. Set a retention period and journald limits
   (`SystemMaxUse=`, `MaxRetentionSec=`, `RateLimitIntervalSec=` and
   `RateLimitBurst=`) on the Sprite. The period is an open decision for
   Patrick.
6. **OPEN: Least-privilege, scoped credentials.** The Sprite credential can do
   only what operating this service needs. The Tailscale node is a tagged
   node whose ACL allows only `serve`/`funnel` to the server's port. Any
   auth key has an expiry and is rotated, and is referred to only by its
   1Password path, never pasted into the repo, a report or the Sprite's app
   environment. Serve (tailnet only) or funnel (public) is an open decision
   for Patrick.
7. **Fuzzing of untrusted input.** Nothing fuzzes the HTTP request parser
   (request line, headers, framing) or `client_key`/`X-Forwarded-For`
   parsing yet.
8. **OPEN: Dependency and secret scanning in CI.** The repo has no CI (no
   `.github/`). Which CI to add is an open decision for Patrick.
9. **End-to-end test through a real `tailscale serve` or `tailscale funnel`**
   in front of the process, with `PREACHED_TRUSTED_PROXIES=127.0.0.1`: it
   appends `X-Forwarded-For`, the key in the log is the client, and
   per-client 429s land on the client, not the proxy (the per-peer cap and
   eviction then never apply; they matter only for a direct bind).
10. **Per-/64 IPv6 keying (PR #29 review M4) accepted**, with Tailscale
    addresses (`fd7a:115c:a1e0::/48`) keyed per address. In code on main
    since PR #29 was merged; the item closes when the CTO accepts it.
11. **DEPLOY.md read end to end** by the CTO (this consolidation is for
    that read-through). It gates any deploy and the exposure sign-off.
12. **CTO sign-off** on the threat model.
13. **Patrick's approval.**
14. **A kill-switch drill on the Sprite:** `touch KILL`, confirm `/healthz` is
    503, remove the regular file, confirm `/healthz` is 200 again, without
    restarting.

## Release notes

### W3 deploy prep (PR #18)

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
- From a bundle: the start-up checks in Part 2 (build stamp, manifest, no
  bytecode, own index, own `model/`, onnx only).

### W3 exposure hardening (PR #29)

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
  logged as rate-limited `refused ...` warnings. (Before this, every
  proxied request was logged as `127.0.0.1`.)
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
