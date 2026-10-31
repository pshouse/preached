#!/bin/bash
# Start the read-only ONNX server. Host, port, and thread count are env vars.
#
#   PREACHED_HOST=127.0.0.1 PREACHED_PORT=8000 scripts/serve.sh
#
# A small CPU box uses one intra-op thread. There is no debug flag and no
# write route. The index is opened mode=ro. The only library gate is
# app.server.check_servable. This script does not change modes: a group- or
# world-writable tree is refused by that gate. The preflight and the server
# both run under `env -i` and the allow-list below.

set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

if [ "$(id -u)" -eq 0 ]; then
  echo "refusing to serve as root" >&2
  exit 2
fi

LIBRARY=${PREACHED_LIBRARY:-wesley}
HOST=${PREACHED_HOST:-127.0.0.1}
PORT=${PREACHED_PORT:-8000}
HOSTS=${PREACHED_HOSTS:-127.0.0.1,localhost}
THREADS=${PREACHED_ORT_THREADS:-1}

case "$PORT" in
  ''|*[!0-9]*)
    echo "PREACHED_PORT must be an integer" >&2
    exit 2
    ;;
esac
if [ "$PORT" -gt 65535 ]; then
  echo "PREACHED_PORT is out of range" >&2
  exit 2
fi
case "$THREADS" in
  ''|*[!0-9]*)
    echo "PREACHED_ORT_THREADS must be a positive integer" >&2
    exit 2
    ;;
esac
if [ "$THREADS" -lt 1 ]; then
  echo "PREACHED_ORT_THREADS must be >= 1" >&2
  exit 2
fi

# A bundle ships index/<library>.sqlite. That tree is the cache root so
# classic_index_problem's canonical path is the file in the bundle.
# A worktree has no index/ and keeps PREACHED_CACHE (default /cache).
if [ -d "$ROOT/index" ]; then
  PREACHED_CACHE=$ROOT
fi
PREACHED_CACHE=${PREACHED_CACHE:-/cache}

if [ -n "${PREACHED_INDEX:-}" ]; then
  INDEX=$PREACHED_INDEX
elif [ -f "$ROOT/index/${LIBRARY}.sqlite" ]; then
  INDEX=$ROOT/index/${LIBRARY}.sqlite
else
  INDEX=${PREACHED_CACHE}/index/${LIBRARY}.sqlite
fi

if [ ! -e "$INDEX" ]; then
  echo "missing index for ${LIBRARY}" >&2
  exit 1
fi

# A bundle ships model/<revision>/. A worktree keeps using /cache unless set.
if [ -z "${PREACHED_ONNX_DIR:-}" ] && [ -d "$ROOT/model" ]; then
  PREACHED_ONNX_DIR=$ROOT/model
fi

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY=$ROOT/.venv/bin/python
elif command -v uv >/dev/null 2>&1; then
  PY=""
else
  echo "no Python; from the bundle run: uv sync --frozen --no-dev" >&2
  exit 1
fi

# Modes are not changed here. check_servable refuses a group- or
# world-writable bundle root, index directory, or index file. Repairing
# them would hide that, follow a PREACHED_INDEX symlink, and fail when the
# tree is owned by root.

PREACHED_EMBED_BACKEND=onnx
PREACHED_ONNX_VARIANT=fp32
PREACHED_ORT_INTRA_OP_THREADS=$THREADS
PREACHED_KILL_FILE=${PREACHED_KILL_FILE:-$ROOT/KILL}
PREACHED_RATE_LIMIT=${PREACHED_RATE_LIMIT:-60}
PREACHED_RATE_WINDOW_S=${PREACHED_RATE_WINDOW_S:-60}
HF_HUB_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
TRANSFORMERS_OFFLINE=1
TOKENIZERS_PARALLELISM=false
PYTHONDONTWRITEBYTECODE=1
PYTHONUNBUFFERED=1
PYTHONNOUSERSITE=1
PYTHONPATH="$ROOT/src:$ROOT"
HOME=${HOME:-/tmp}
LANG=${LANG:-C.UTF-8}
LC_ALL=${LC_ALL:-$LANG}
TMPDIR=${TMPDIR:-/tmp}

# The preflight and the server see only this list. Tokens and cloud
# credentials in the shell are not passed through. Names, not values, are
# the contract.
ENV_ARGS=("PATH=${PATH}" "HOME=${HOME}" "LANG=${LANG}" "LC_ALL=${LC_ALL}" "TMPDIR=${TMPDIR}")
pass() {
  local name=$1
  if [ -n "${!name+x}" ]; then
    ENV_ARGS+=("${name}=${!name}")
  fi
}
pass PREACHED_CACHE
pass PREACHED_EMBED_BACKEND
pass PREACHED_ONNX_VARIANT
pass PREACHED_ONNX_DIR
pass PREACHED_ORT_INTRA_OP_THREADS
pass PREACHED_KILL_FILE
pass PREACHED_RATE_LIMIT
pass PREACHED_RATE_WINDOW_S
pass PREACHED_DISABLED
pass PREACHED_HEADER_DEADLINE_S
pass PREACHED_MAX_CONNECTIONS
pass PREACHED_MAX_CLIENT_CONNECTIONS
pass HF_HUB_OFFLINE
pass HF_HUB_DISABLE_TELEMETRY
pass TRANSFORMERS_OFFLINE
pass TOKENIZERS_PARALLELISM
pass PYTHONDONTWRITEBYTECODE
pass PYTHONUNBUFFERED
pass PYTHONNOUSERSITE
pass PYTHONPATH
pass TZ

# Bytecode in the tree is never loaded: an old __pycache__ can match a
# source file's size and mtime (every release tar has the same mtime) and
# run in place of the hashed source. The preflight imports app (and
# app.server itself) before app/server.py can set its own prefix, so it
# runs with a fresh empty PYTHONPYCACHEPREFIX. That directory is removed
# before the exec below. The server is started as a script, so its first
# lines set a private prefix of their own and remove it at exit.
# app/bundle.py also refuses a bundle with any __pycache__ or *.pyc
# outside .venv.
PYCACHE=$(mktemp -d "${TMPDIR}/preached-pycache.XXXXXX")
trap 'rm -rf -- "$PYCACHE"' EXIT
if [ -n "$PY" ]; then
  CHECK=(env -i "${ENV_ARGS[@]}" "PYTHONPYCACHEPREFIX=${PYCACHE}" "$PY")
else
  CHECK=(env -i "${ENV_ARGS[@]}" "PYTHONPYCACHEPREFIX=${PYCACHE}" uv run --project "$ROOT" --frozen --no-sync --no-dev --no-default-groups python)
fi
# Bundle or checkout, the manifest, no bytecode, the bundle's own model
# directory. Stdlib only, run as a script with -I -B, so it runs before any
# bundle module is imported and nothing else is on the path.
"${CHECK[@]}" -I -B "$ROOT/app/bundle.py" "$ROOT" "$INDEX"

"${CHECK[@]}" - "$LIBRARY" "$INDEX" <<'PY'
import sqlite3
import sys
from pathlib import Path

from app.server import check_servable
from preached.store import open_readonly

library = sys.argv[1]
index = Path(sys.argv[2])
try:
    connection = open_readonly(index, check_same_thread=False)
except Exception as exc:
    raise SystemExit(f"error: cannot open {index} ({type(exc).__name__})") from exc
try:
    check_servable(connection, library, index)
except SystemExit:
    raise
except sqlite3.DatabaseError as exc:
    raise SystemExit(f"error: {index} is not a SQLite index ({type(exc).__name__})") from exc
finally:
    connection.close()
PY

rm -rf -- "$PYCACHE"
trap - EXIT

ARGS=(
  app/server.py
  --host "$HOST"
  --port "$PORT"
  --hosts "$HOSTS"
  --library "$LIBRARY"
  --index "$INDEX"
  --embed-backend onnx
  --onnx-variant fp32
  --ort-threads "$THREADS"
)

if [ -n "$PY" ]; then
  exec env -i "${ENV_ARGS[@]}" "$PY" "${ARGS[@]}"
fi
exec env -i "${ENV_ARGS[@]}" uv run --frozen --no-sync --no-dev --no-default-groups python "${ARGS[@]}"
