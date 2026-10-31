#!/bin/bash
# Build a bundle in a temp dir, install a fresh venv from that bundle, serve
# it with the repo off the path, and print health, p50, and RSS.
#
#   scripts/smoke-bundle.sh
#
# Removes the temp dir and stops the server when it exits.

set -euo pipefail

SOURCE=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
PID=""

cleanup() {
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

"$SOURCE/scripts/build-bundle.sh" "$WORK/bundle"
cd "$WORK/bundle"
uv sync --frozen --no-dev --no-default-groups

if grep -R -l "/work/preached" .venv >/dev/null 2>&1; then
  echo "bundle venv points at the repo" >&2
  exit 1
fi

LOG=$WORK/server.log
env -u PYTHONPATH -u PREACHED_DISABLED \
  PREACHED_HOST=127.0.0.1 \
  PREACHED_PORT=0 \
  PREACHED_LIBRARY=wesley \
  PREACHED_HOSTS=127.0.0.1,localhost \
  PREACHED_ORT_THREADS=1 \
  "$WORK/bundle/scripts/serve.sh" >"$LOG" 2>&1 &
PID=$!

ready=0
for _ in $(seq 1 240); do
  if grep -q '^PREACHED_LISTENING ' "$LOG"; then
    ready=1
    break
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "server exited during startup" >&2
    cat "$LOG" >&2
    exit 1
  fi
  sleep 0.5
done
if [ "$ready" -ne 1 ]; then
  echo "server did not listen in time" >&2
  cat "$LOG" >&2
  exit 1
fi

URL=$(sed -n 's/^PREACHED_LISTENING //p' "$LOG" | head -1)
RSS_START=$(sed -n 's/^PREACHED_RSS_BYTES //p' "$LOG" | head -1)

if grep -E 'libtorch|whisper|ctranslate|libnvidia-cublas|libcudnn' "/proc/$PID/maps"; then
  echo "forbidden library is mapped in the server" >&2
  exit 1
fi
if ! grep -q 'libonnxruntime' "/proc/$PID/maps"; then
  echo "onnxruntime is not mapped" >&2
  exit 1
fi

"$WORK/bundle/.venv/bin/python" - "$URL" "$PID" "$RSS_START" <<'PY'
import json
import sys
import time
import urllib.parse
import urllib.request

base, pid, rss_start = sys.argv[1], sys.argv[2], sys.argv[3]
bad = [entry for entry in sys.path if "/work/preached" in entry]
if bad:
    raise SystemExit("repo on sys.path: " + ",".join(bad))

with urllib.request.urlopen(base + "/healthz", timeout=30) as response:
    health = json.loads(response.read().decode())
blob = json.dumps(health)
for needle in ("/cache", ".sqlite", "KILL", "SPRITE", "TOKEN"):
    if needle in blob:
        raise SystemExit(f"health leaked {needle}: {blob}")
if health.get("ok") is not True or health.get("library") != "wesley":
    raise SystemExit(f"health not ok: {blob}")
if health.get("dense") is not True or health.get("model") != "granite-english-r2":
    raise SystemExit(f"dense model not loaded: {blob}")
if health.get("backend") != "onnx":
    raise SystemExit(f"backend: {blob}")
sha = health.get("model_sha256")
index_version = health.get("index_version")
if not (isinstance(sha, str) and len(sha) == 64 and "/" not in sha):
    raise SystemExit(f"model sha: {sha!r}")
if not (isinstance(index_version, str) and len(index_version) == 64):
    raise SystemExit(f"index version: {index_version!r}")

query = "what did Wesley say about Christian perfection"
params = urllib.parse.urlencode(
    {"q": query, "k": "5", "mode": "hybrid", "library": "wesley"}
)
url = base + "/api/search?" + params
client_ms = []
took_ms = []
first = None
for attempt in range(21):
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode())
    elapsed = (time.perf_counter() - started) * 1000.0
    results = payload.get("results") or []
    if not results:
        raise SystemExit(f"no results: {payload.get('note')}")
    if attempt == 0:
        first = results[0]
        continue
    client_ms.append(elapsed)
    took_ms.append(int(payload["took_ms"]))

def p50(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    mid = count // 2
    if count % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0

rss_after = None
try:
    for line in open(f"/proc/{pid}/status", encoding="utf-8"):
        if line.startswith("VmRSS:"):
            rss_after = int(line.split()[1]) * 1024
except OSError:
    rss_after = None

print(f"health_chunks {health.get('chunks')}")
print(f"index_version {index_version}")
print(f"model_sha256 {sha}")
print(f"backend {health.get('backend')}")
print(f"fallback {health.get('fallback')}")
print(f"first_sermon {first.get('sermon_id')} {first.get('sermon_title')}")
print(f"warmup_dropped 1")
print(f"samples {len(client_ms)}")
print(f"p50_client_ms {p50(client_ms):.1f}")
print(f"p50_took_ms {p50([float(item) for item in took_ms]):.1f}")
print(f"min_client_ms {min(client_ms):.1f}")
print(f"max_client_ms {max(client_ms):.1f}")
print(f"rss_startup_bytes {rss_start}")
print(f"rss_after_bytes {rss_after if rss_after is not None else 'unknown'}")
print(f"client_ms {','.join(f'{item:.1f}' for item in client_ms)}")
print(f"took_ms {','.join(str(item) for item in took_ms)}")
PY

echo "smoke ok"
