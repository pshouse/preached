#!/bin/bash
# Build a serve-only directory and a matching tar.gz.
#
# The directory holds the server code, the pinned serve lock (uv.lock plus
# requirements-serve.txt from `uv export --no-dev`), the fp32 ONNX files,
# and one read-only index. Church and YouTube indexes are refused.
# Same inputs produce the same MANIFEST.sha256 and the same tar bytes.
#
#   scripts/build-bundle.sh /tmp/preached-bundle
#
# PREACHED_LIBRARY           wesley (default), spurgeon, or edwards
# PREACHED_INDEX             sqlite to copy (default /cache/index/<library>.sqlite)
# PREACHED_ONNX_DIR          model root (default /cache/models/granite-english-r2-onnx)
# PREACHED_BUNDLE_SKIP_PINS  set to 1 only in tests that use stand-in files

set -euo pipefail

SOURCE=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
OUT=${1:-}
if [ -z "$OUT" ] || [ "$#" -gt 1 ]; then
  echo "usage: scripts/build-bundle.sh OUT_DIR" >&2
  exit 2
fi

LIBRARY=${PREACHED_LIBRARY:-wesley}
case "$LIBRARY" in
  wesley|spurgeon|edwards) ;;
  *)
    echo "refusing library ${LIBRARY}; deploy allows only wesley, spurgeon, edwards" >&2
    exit 2
    ;;
esac

INDEX=${PREACHED_INDEX:-/cache/index/${LIBRARY}.sqlite}
ONNX_ROOT=${PREACHED_ONNX_DIR:-/cache/models/granite-english-r2-onnx}

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
base=$(basename -- "$INDEX")
if [ "$base" != "${LIBRARY}.sqlite" ]; then
  echo "refusing index name ${base}; expected ${LIBRARY}.sqlite" >&2
  exit 2
fi
if [ ! -f "$INDEX" ]; then
  echo "missing ${LIBRARY} index" >&2
  exit 1
fi

REVISION=$(sed -n 's/^GRANITE_REVISION = "\([0-9a-f]\{40\}\)".*/\1/p' "$SOURCE/src/preached/artifacts.py")
FP32_SHA=$(sed -n 's/^FP32_ONNX_SHA256 = "\([0-9a-f]\{64\}\)".*/\1/p' "$SOURCE/src/preached/artifacts.py")
TOK_SHA=$(sed -n 's/^TOKENIZER_SHA256 = "\([0-9a-f]\{64\}\)".*/\1/p' "$SOURCE/src/preached/artifacts.py")
if [ -z "$REVISION" ] || [ -z "$FP32_SHA" ] || [ -z "$TOK_SHA" ]; then
  echo "could not read the ONNX pins from artifacts.py" >&2
  exit 1
fi

MODEL_SRC="$ONNX_ROOT/$REVISION"
MODEL_FILES=(manifest.json model.fp32.onnx tokenizer.json pooling.json)
for name in "${MODEL_FILES[@]}"; do
  case "$name" in
    *int8*)
      echo "refusing ${name}" >&2
      exit 2
      ;;
  esac
  if [ ! -f "$MODEL_SRC/$name" ]; then
    echo "missing ONNX file ${name}" >&2
    exit 1
  fi
done

if [ "${PREACHED_BUNDLE_SKIP_PINS:-}" != "1" ]; then
  actual_fp32=$(sha256sum "$MODEL_SRC/model.fp32.onnx" | awk 'NR==1 {print $1}')
  actual_tok=$(sha256sum "$MODEL_SRC/tokenizer.json" | awk 'NR==1 {print $1}')
  if [ "$actual_fp32" != "$FP32_SHA" ] || [ "$actual_tok" != "$TOK_SHA" ]; then
    echo "ONNX sha256 does not match the pin in artifacts.py" >&2
    exit 1
  fi
fi

if [ -e "$OUT" ] && [ -n "$(find "$OUT" -mindepth 1 -print -quit)" ]; then
  echo "output directory is not empty" >&2
  exit 2
fi
mkdir -p "$OUT"

# Serve-time code only. Torch, Whisper, the YouTube importer, and ingest stay out.
CODE_FILES=(
  pyproject.toml
  uv.lock
  README.md
  AGENTS.md
  .python-version
  app/__init__.py
  app/server.py
  app/static/index.html
  app/static/app.js
  app/static/app.css
  app/static/favicon.svg
  src/preached/__init__.py
  src/preached/env.py
  src/preached/abstain.py
  src/preached/artifacts.py
  src/preached/backends.py
  src/preached/fts.py
  src/preached/models.py
  src/preached/onnx_embed.py
  src/preached/paths.py
  src/preached/pooling.py
  src/preached/prefixes.py
  src/preached/rank.py
  src/preached/search.py
  src/preached/store.py
  src/preached/text_tokens.py
  src/preached/youtube/__init__.py
  src/preached/youtube/listing.py
  search/models.toml
  search/abstain.toml
  scripts/serve.sh
)

for rel in "${CODE_FILES[@]}"; do
  if [ ! -f "$SOURCE/$rel" ]; then
    echo "missing source file ${rel}" >&2
    exit 1
  fi
  mkdir -p "$OUT/$(dirname "$rel")"
  cp "$SOURCE/$rel" "$OUT/$rel"
done

mkdir -p "$OUT/model/$REVISION" "$OUT/index"
for name in "${MODEL_FILES[@]}"; do
  cp "$MODEL_SRC/$name" "$OUT/model/$REVISION/$name"
done
# int8 is not a runtime file. Refuse it if a copy step ever adds it.
if [ -e "$OUT/model/$REVISION/model.int8.onnx" ]; then
  echo "refusing to ship model.int8.onnx" >&2
  exit 2
fi
cp "$INDEX" "$OUT/index/${LIBRARY}.sqlite"

# Pinned third-party set for `uv sync --frozen --no-dev`. No extras, no bench group.
uv export --project "$SOURCE" --frozen --no-dev --no-default-groups \
  --no-emit-workspace --no-header --no-annotate --offline \
  -o "$OUT/requirements-serve.txt" >/dev/null

find "$OUT" -type d -exec chmod 0755 {} +
find "$OUT" -type f -exec chmod 0644 {} +
chmod 0755 "$OUT/scripts/serve.sh"
chmod 0444 "$OUT/index/${LIBRARY}.sqlite"
find "$OUT/model" -type f -exec chmod 0444 {} +

python3 "$SOURCE/scripts/bundle_manifest.py" "$OUT" >/dev/null
chmod 0644 "$OUT/MANIFEST.sha256"

TAR="${OUT}.tar.gz"
TZ=UTC tar --format=ustar --sort=name \
  --mtime='2026-10-30 00:00:00' \
  --owner=0 --group=0 --numeric-owner \
  -cf - -C "$OUT" . | gzip -n > "$TAR"

echo "bundle ${OUT}"
echo "library ${LIBRARY}"
echo "manifest $(sha256sum "$OUT/MANIFEST.sha256" | awk '{print $1}')"
echo "tar $(sha256sum "$TAR" | awk '{print $1}')"
