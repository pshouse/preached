"""End-to-end /api/search latency on every question in eval/questions.jsonl.

Starts the server, waits until the model is loaded, warms one query, then
times the eval set. The query set is read from the eval file (no fixed count);
it must parse cleanly with unique ids and non-empty queries, and the summary
records n_queries and queries_id_sha256 (over [id, query] pairs) so runs can be compared.
Prints JSON: p50_ms, p95_ms, rss_bytes_after_model_load, rss_bytes_after_queries,
rss_peak_bytes (VmHWM), cold_start_s (spawn through healthz and the
warmup query). The percentile matches search/bench.py
(nearest rank, 1-based).

Command for the CPU-only RSS / latency report in reports/BENCH-API-FIX.md
(foreground; the script also blanks CUDA_VISIBLE_DEVICES itself). The child is
a loopback-only bench server, so the script lifts the per-IP rate limits
(PREACHED_RATE_LIMIT, and PREACHED_GLOBAL_RATE_LIMIT where it exists) unless
they are already set in the environment:

  CUDA_VISIBLE_DEVICES="" uv run python scripts/bench_api.py
  CUDA_VISIBLE_DEVICES="" uv run python scripts/bench_api.py --repeats 3 --ort-threads 2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
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


def peak_rss_of(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def queries(path: Path = QUESTIONS) -> list[tuple[str, str]]:
    """Every (id, query) in the eval file, in order. Exits on any unusable line."""
    found: list[tuple[str, str]] = []
    ids: set[str] = set()
    # split("\n"), not splitlines(): U+2028 and friends can sit inside a JSON string.
    for number, line in enumerate(path.read_text().split("\n"), 1):
        if not line.strip():
            continue
        where = f"{path}:{number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{where}: invalid JSON: {exc}")
        if not isinstance(row, dict):
            raise SystemExit(f"{where}: row is not a JSON object")
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id.strip():
            raise SystemExit(f"{where}: missing or non-string id {row_id!r}")
        query = row.get("query")
        if not isinstance(query, str) or not query.strip():
            raise SystemExit(f"{where}: missing or empty query")
        if row_id in ids:
            raise SystemExit(f"{where}: duplicate id {row_id!r}")
        ids.add(row_id)
        found.append((row_id, query))
    if not found:
        raise SystemExit(f"no eval queries in {path}")
    return found


def queries_sha256(found: list[tuple[str, str]]) -> str:
    """Hash of [[id, query], ...] in file order, so ids and boundaries count."""
    blob = json.dumps([[i, q] for i, q in found], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed-backend", choices=("onnx", "torch"), default="onnx")
    parser.add_argument("--onnx-variant", choices=("fp32",), default=None)
    parser.add_argument("--ort-threads", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--index", default=None)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    found = queries()  # validate before the server and model start
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
    env["ORT_DISABLE_TELEMETRY"] = "1"  # the child imports onnxruntime; keep ORT telemetry off
    for name in ("PREACHED_RATE_LIMIT", "PREACHED_GLOBAL_RATE_LIMIT"):
        if not env.get(name, "").strip():  # unset and empty both mean "not chosen"
            env[name] = "1000000"
    err_file = tempfile.NamedTemporaryFile(
        "w", prefix="preached-bench-", suffix=".stderr", delete=False
    )
    err_path = Path(err_file.name)
    started_proc = time.perf_counter()
    with err_file as err:
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
            raise SystemExit(f"server is not serving dense/hybrid search: {health}; see {err_path}")

        def once(query: str) -> float:
            params = urllib.parse.urlencode(
                {"q": query, "k": 10, "mode": "hybrid", "library": "wesley"}
            )
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/search?{params}",
                    timeout=120,
                ) as response:
                    payload = json.loads(response.read())
            except urllib.error.HTTPError as exc:
                body = exc.read().decode(errors="replace")
                raise SystemExit(f"search failed: HTTP {exc.code}: {body}; see {err_path}")
            elapsed_ms = (time.perf_counter() - started) * 1000
            if response.status != 200:
                raise SystemExit(f"search failed: {payload}; see {err_path}")
            if payload.get("mode") != "hybrid":
                raise SystemExit(f"expected hybrid, got {payload.get('mode')} {payload.get('note')}; see {err_path}")
            return elapsed_ms

        once(found[0][1])  # warmup
        cold_start_s = time.perf_counter() - started_proc
        samples = []
        for _ in range(max(1, args.repeats)):
            samples.extend(once(query) for _, query in found)
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
            "rss_peak_bytes": peak_rss_of(proc.pid),
            "n_queries": len(found),
            "queries_id_sha256": queries_sha256(found),
            "chunks": health.get("chunks"),
            "cold_start_note": "process spawn to end of healthz check and one warmup query; eval parse excluded",
            "cold_start_s": round(cold_start_s, 3),
        }
        print(json.dumps(summary, indent=2))
        err_path.unlink(missing_ok=True)  # kept on failure for diagnosis
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
