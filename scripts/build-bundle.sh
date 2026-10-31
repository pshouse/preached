#!/bin/bash
# Build a serve-only directory and a matching tar.gz.
#
# The directory holds the server code, the pinned serve lock (uv.lock plus
# requirements-serve.txt from `uv export --no-dev`), the fp32 ONNX files,
# the classics manifests, and one index copied with SQLite's backup API.
# Church and YouTube indexes are refused by app.server.check_servable.
# Same inputs produce the same MANIFEST.sha256 and the same tar bytes.
#
#   scripts/build-bundle.sh /tmp/preached-bundle
#
# PREACHED_LIBRARY           wesley (default), spurgeon, or edwards
# PREACHED_INDEX             sqlite to copy (default /cache/index/<library>.sqlite)
# PREACHED_ONNX_DIR          model root (default /cache/models/granite-english-r2-onnx)
#
# The ONNX files must match the pins in src/preached/artifacts.py. There is
# no switch that skips that check. The tests build from a copy of the source
# whose artifacts.py pins their own small fixture files.

set -euo pipefail

# The import check must not write bytecode into the bundle. Those files are
# not in the manifest and their headers change every run, so the tar would
# not be reproducible. GNU tar would also see them appear mid-build.
export PYTHONDONTWRITEBYTECODE=1

SOURCE=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
OUT=${1:-}
if [ -z "$OUT" ] || [ "$#" -gt 1 ]; then
  echo "usage: scripts/build-bundle.sh OUT_DIR" >&2
  exit 2
fi

LIBRARY=${PREACHED_LIBRARY:-wesley}
INDEX=${PREACHED_INDEX:-/cache/index/${LIBRARY}.sqlite}
ONNX_ROOT=${PREACHED_ONNX_DIR:-/cache/models/granite-english-r2-onnx}

if [ ! -e "$INDEX" ]; then
  echo "missing index ${INDEX}" >&2
  exit 1
fi

if [ -x "$SOURCE/.venv/bin/python" ]; then
  PY=$SOURCE/.venv/bin/python
else
  PY=$(command -v python3)
fi

# The serve gate is check_servable. This script has no library allow-list
# and no path denylist of its own.
PYTHONPATH="$SOURCE/src:$SOURCE" "$PY" - "$LIBRARY" "$INDEX" <<'PY'
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

actual_fp32=$(sha256sum "$MODEL_SRC/model.fp32.onnx" | awk 'NR==1 {print $1}')
actual_tok=$(sha256sum "$MODEL_SRC/tokenizer.json" | awk 'NR==1 {print $1}')
if [ "$actual_fp32" != "$FP32_SHA" ] || [ "$actual_tok" != "$TOK_SHA" ]; then
  echo "ONNX sha256 does not match the pin in artifacts.py" >&2
  exit 1
fi
if [ -e "$OUT" ] && [ -n "$(find "$OUT" -mindepth 1 -print -quit)" ]; then
  echo "output directory is not empty" >&2
  exit 2
fi
mkdir -p "$OUT"

# Serve-time code only, derived from what the server imports (plus the
# fixed non-Python files listed in bundle_files.py). Torch, Whisper, the
# YouTube importer, and ingest stay out. `python -I -B`: no PYTHONPATH, no
# current directory on the path, no bytecode written into the source.
CODE_LIST=$("$PY" -I -B "$SOURCE/scripts/bundle_files.py" list "$SOURCE")
mapfile -t CODE_FILES <<< "$CODE_LIST"
if [ "${#CODE_FILES[@]}" -lt 2 ]; then
  echo "could not list the bundle files" >&2
  exit 1
fi

for rel in "${CODE_FILES[@]}"; do
  if [ ! -f "$SOURCE/$rel" ]; then
    echo "missing source file ${rel}" >&2
    exit 1
  fi
  mkdir -p "$OUT/$(dirname "$rel")"
  cp --reflink=never "$SOURCE/$rel" "$OUT/$rel"
done

mkdir -p "$OUT/model/$REVISION" "$OUT/index"
for name in "${MODEL_FILES[@]}"; do
  cp --reflink=never "$MODEL_SRC/$name" "$OUT/model/$REVISION/$name"
done
# int8 is not a runtime file. Refuse it if a copy step ever adds it, and
# drop it from the shipped manifest even when the source manifest names it.
if [ -e "$OUT/model/$REVISION/model.int8.onnx" ]; then
  echo "refusing to ship model.int8.onnx" >&2
  exit 2
fi
PYTHONPATH="$SOURCE" "$PY" -c 'import sys; from pathlib import Path; from scripts.bundle_manifest import strip_int8_manifest; strip_int8_manifest(Path(sys.argv[1]))' \
  "$OUT/model/$REVISION/manifest.json"

PYTHONPATH="$SOURCE" "$PY" -c 'import sys; from pathlib import Path; from scripts.bundle_manifest import copy_index; copy_index(Path(sys.argv[1]), Path(sys.argv[2]))' \
  "$INDEX" "$OUT/index/${LIBRARY}.sqlite"

# The bundle must import on its own: run from the bundle with `python -I`
# (the source tree is not on the path) and require every app/preached
# module that loads to come from inside the bundle.
(cd "$OUT" && PREACHED_CACHE="$OUT" "$PY" -I -B "$SOURCE/scripts/bundle_files.py" check "$OUT")

# Pinned third-party set for `uv sync --frozen --no-dev`. No extras, no bench group.
uv export --project "$SOURCE" --frozen --no-dev --no-default-groups \
  --no-emit-workspace --no-header --no-annotate --offline \
  -o "$OUT/requirements-serve.txt" >/dev/null

# classic_index_problem requires the bundle root (parent of index/), the
# index directory, and the index file to have no group or world write.
find "$OUT" -depth -type d -name __pycache__ -exec rm -rf {} +
find "$OUT" -type f -name '*.pyc' -delete
find "$OUT" -type d -exec chmod 0755 {} +
find "$OUT" -type f -exec chmod 0644 {} +
chmod 0755 "$OUT/scripts/serve.sh"
chmod 0444 "$OUT/index/${LIBRARY}.sqlite"
find "$OUT/model" -type f -exec chmod 0444 {} +

# The build stamp marks this tree as a bundle (app/bundle.py). It is a
# listed file, so deleting it or editing it fails the manifest check, and a
# tree with no stamp and no .git is refused rather than run as a checkout.
PYTHONPATH="$SOURCE" "$PY" -c 'import sys; from pathlib import Path; from app.bundle import BUILD_STAMP, stamp_text; Path(sys.argv[1], BUILD_STAMP).write_text(stamp_text(sys.argv[2], sys.argv[3]))' \
  "$OUT" "$LIBRARY" "$REVISION"
chmod 0644 "$OUT/PREACHED_BUNDLE"

PYTHONPATH="$SOURCE" "$PY" "$SOURCE/scripts/bundle_manifest.py" "$OUT" >/dev/null
chmod 0644 "$OUT/MANIFEST.sha256"

# Tar a private snapshot. A reflink of a live index or model still changes
# under GNU tar ("file changed as we read it", exit 1) when the source is
# written. The snapshot is a full copy and this script does not touch it.
SNAP=$(mktemp -d)
cleanup() {
  rm -rf "$SNAP"
}
trap cleanup EXIT
cp -a --reflink=never "$OUT/." "$SNAP/"

TAR="${OUT}.tar.gz"
TZ=UTC tar --format=ustar --sort=name \
  --mtime='2026-10-30 00:00:00' \
  --owner=0 --group=0 --numeric-owner \
  -cf - -C "$SNAP" . | gzip -n > "$TAR"
trap - EXIT
rm -rf "$SNAP"

echo "bundle ${OUT}"
echo "library ${LIBRARY}"
echo "manifest $(sha256sum "$OUT/MANIFEST.sha256" | awk '{print $1}')"
echo "tar $(sha256sum "$TAR" | awk '{print $1}')"
