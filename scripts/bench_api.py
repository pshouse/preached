"""End-to-end /api/search latency on the 40 eval questions.

Starts the server, waits until the model is loaded, warms one query, then
times the eval set. Prints JSON: p50_ms, p95_ms, rss_bytes, cold_start_s.
The percentile matches search/bench.py (nearest rank, 1-based).

  CUDA_VISIBLE_DEVICES="" uv run python scripts/bench_api.py
  CUDA_VISIBLE_DEVICES="" uv run python scripts/bench_api.py --repeats 3 --ort-threads 2
"""

from __future__ import annotations

import argparse
import json
import math
import os
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed-backend", choices=("onnx", "torch"), default="onnx")
    parser.add_argument("--onnx-variant", choices=("fp32", "int8"), default=None)
    parser.add_argument("--ort-threads", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--index", default=None)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    err_path = Path("/tmp/preached-w3-bench.stderr")
    cmd = [
        sys.executable,
        str(ROOT / "app" / "server.py"),
        "--port",
        str(args.port),
        "--embed-backend",
        args.embed_backend,
    ]
    if args.onnx_variant:
        cmd.extend(["--onnx-variant", args.onnx_variant])
    if args.ort_threads is not None:
        cmd.extend(["--ort-threads", str(args.ort_threads)])
    if args.index:
        cmd.extend(["--index", args.index])
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""
    started_proc = time.perf_counter()
    with err_path.open("w") as err:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=err,
            text=True,
            env=env,
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

        found = queries()
        once(found[0])
        cold_start_s = time.perf_counter() - started_proc
        samples = []
        for _ in range(max(1, args.repeats)):
            samples.extend(once(query) for query in found)
        summary = {
            "n": len(samples),
            "repeats": max(1, args.repeats),
            "warmup": "excluded",
            "mode": "hybrid",
            "model": health.get("model"),
            "backend": health.get("backend"),
            "embed_backend_flag": args.embed_backend,
            "onnx_variant": args.onnx_variant,
            "ort_threads": args.ort_threads,
            "p50_ms": percentile(samples, 50),
            "p95_ms": percentile(samples, 95),
            "min_ms": min(samples),
            "max_ms": max(samples),
            "rss_bytes_after_model_load": rss_at_listen,
            "rss_bytes_after_queries": rss_of(proc.pid),
            "chunks": health.get("chunks"),
            "cold_start_s": round(cold_start_s, 3),
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
