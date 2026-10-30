"""End-to-end /api/search latency on the 40 eval questions.

Starts the server, waits until the model is loaded, warms one query, then
times the eval set. Prints JSON: p50_ms, p95_ms, rss_bytes. The percentile
matches search/bench.py (nearest rank, 1-based).

  uv run python scripts/bench_api.py
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "eval" / "questions.jsonl"


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(pct / 100 * len(ordered))
    index = min(len(ordered) - 1, max(0, rank - 1))
    return ordered[index]


def rss_of(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def queries() -> list[str]:
    found = []
    for line in QUESTIONS.read_text().splitlines():
        if line.strip():
            found.append(json.loads(line)["query"])
    if len(found) != 40:
        raise SystemExit(f"expected 40 eval queries, found {len(found)}")
    return found


def main() -> None:
    err_path = Path("/tmp/preached-w2a-bench.stderr")
    cmd = [sys.executable, str(ROOT / "app" / "server.py"), "--port", "0"]
    with err_path.open("w") as err:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=err,
            text=True,
        )
    assert proc.stdout is not None
    port = None
    rss_at_listen = None
    deadline = time.monotonic() + 300
    try:
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                raise SystemExit(f"server exited before listening; see {err_path}")
            if line.startswith("PREACHED_RSS_BYTES "):
                rss_at_listen = int(line.split()[1])
            if line.startswith("PREACHED_LISTENING "):
                port = int(line.rsplit(":", 1)[1])
                break
        if port is None:
            raise SystemExit(f"server did not listen within 300s; see {err_path}")

        health_url = f"http://127.0.0.1:{port}/healthz"
        with urllib.request.urlopen(health_url, timeout=30) as response:
            health = json.loads(response.read())
        if health.get("fallback") or not health.get("dense"):
            raise SystemExit(f"server is not serving dense/hybrid search: {health}")

        def once(query: str) -> float:
            params = urllib.parse.urlencode(
                {"q": query, "k": 10, "mode": "hybrid", "library": "wesley"}
            )
            started = time.perf_counter()
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/search?{params}",
                timeout=120,
            ) as response:
                payload = json.loads(response.read())
            elapsed_ms = (time.perf_counter() - started) * 1000
            if response.status != 200:
                raise SystemExit(f"search failed: {payload}")
            if payload.get("mode") != "hybrid":
                raise SystemExit(f"expected hybrid, got {payload.get('mode')} {payload.get('note')}")
            return elapsed_ms

        once(queries()[0])
        samples = [once(query) for query in queries()]
        summary = {
            "n": len(samples),
            "warmup": "excluded",
            "mode": "hybrid",
            "model": health.get("model"),
            "p50_ms": percentile(samples, 50),
            "p95_ms": percentile(samples, 95),
            "min_ms": min(samples),
            "max_ms": max(samples),
            "rss_bytes_after_model_load": rss_at_listen,
            "rss_bytes_after_queries": rss_of(proc.pid),
            "chunks": health.get("chunks"),
        }
        print(json.dumps(summary, indent=2))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
