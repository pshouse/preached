#!/bin/bash
# Start the read-only ONNX server. Host, port, and thread count are env vars.
#
#   PREACHED_HOST=127.0.0.1 PREACHED_PORT=8000 scripts/serve.sh
#
# A small CPU box uses one intra-op thread. There is no debug flag and no
# write route. The index is opened mode=ro. Church and YouTube libraries
# are refused here until the server allow-list lands on main.

set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

if [ "$(id -u)" -eq 0 ] && [ "${PREACHED_ALLOW_ROOT:-}" != "1" ]; then
  echo "refusing to serve as root" >&2
  exit 2
fi

LIBRARY=${PREACHED_LIBRARY:-wesley}
case "$LIBRARY" in
  wesley|spurgeon|edwards) ;;
  *)
    echo "refusing library ${LIBRARY}; this deploy allows only wesley, spurgeon, edwards" >&2
    exit 2
    ;;
esac

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

if [ -n "${PREACHED_INDEX:-}" ]; then
  INDEX=$PREACHED_INDEX
elif [ -f "$ROOT/index/${LIBRARY}.sqlite" ]; then
  INDEX=$ROOT/index/${LIBRARY}.sqlite
else
  INDEX=/cache/index/${LIBRARY}.sqlite
fi

case "$INDEX" in
  *cc-speech*|*gaston*|*youtube*|*church*)
    echo "refusing a church or YouTube index" >&2
    exit 2
    ;;
esac
if [ -L "$INDEX" ]; then
  echo "refusing a symlinked index" >&2
  exit 2
fi
if [ "$(basename -- "$INDEX")" != "${LIBRARY}.sqlite" ]; then
  echo "refusing index name; expected ${LIBRARY}.sqlite" >&2
  exit 2
fi
if [ ! -f "$INDEX" ]; then
  echo "missing index for ${LIBRARY}" >&2
  exit 1
fi

# A bundle ships model/<revision>/. A worktree keeps using /cache unless set.
if [ -z "${PREACHED_ONNX_DIR:-}" ] && [ -d "$ROOT/model" ]; then
  PREACHED_ONNX_DIR=$ROOT/model
fi

if [ -n "${PREACHED_PYTHON:-}" ]; then
  PY=$PREACHED_PYTHON
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY=$ROOT/.venv/bin/python
elif command -v uv >/dev/null 2>&1; then
  PY=""
else
  echo "no Python; from the bundle run: uv sync --frozen --no-dev" >&2
  exit 1
fi

# The file is inside the bundle only. Do not change a shared /cache index.
case "$INDEX" in
  "$ROOT"/*)
    chmod a-w "$INDEX" 2>/dev/null || true
    ;;
esac

export PREACHED_EMBED_BACKEND=onnx
export PREACHED_ONNX_VARIANT=fp32
export PREACHED_ORT_INTRA_OP_THREADS=$THREADS
export PREACHED_KILL_FILE=${PREACHED_KILL_FILE:-$ROOT/KILL}
export PREACHED_RATE_LIMIT=${PREACHED_RATE_LIMIT:-60}
export PREACHED_RATE_WINDOW_S=${PREACHED_RATE_WINDOW_S:-60}
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONNOUSERSITE=1
export PYTHONPATH="$ROOT/src:$ROOT"
if [ -n "${PREACHED_ONNX_DIR:-}" ]; then
  export PREACHED_ONNX_DIR
fi

unset PYTHONDEVMODE || true
unset PYTHONASYNCIODEBUG || true
unset SPRITE_TOKEN || true
unset FLY_API_TOKEN || true
unset HF_TOKEN || true
unset HUGGING_FACE_HUB_TOKEN || true

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
  exec "$PY" "${ARGS[@]}"
fi
exec uv run --frozen --no-sync --no-dev --no-default-groups python "${ARGS[@]}"
