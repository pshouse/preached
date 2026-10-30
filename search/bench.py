"""Benchmark BM25, each embedding model, and hybrids on the Wesley eval set.

GPU: embed the corpus (fp16, or bf16 for EmbeddingGemma 2) and record
chunks/s plus the extra VRAM this process used. CPU: embed each eval query
and search, p50/p95. Metrics are Recall@5, MRR@10, nDCG@10 on questions that
have a relevant passage. Unanswerable questions are scored separately so we
can see whether "nothing strong" is distinguishable.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preached import env  # noqa: F401, E402
from preached.corpus import read_jsonl  # noqa: E402
from preached.embed import (  # noqa: E402
    describe_prompts,
    document_title,
    encode_documents,
    encode_query,
    load_model,
    unload,
)
from preached.metrics import mrr_at, ndcg_at, recall_at, summarize  # noqa: E402
from preached.models import EXCLUDED, MODELS  # noqa: E402
from preached.paths import CHUNKS_JSONL, INDEX_PATH, questions_path, repo_root  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.store import (  # noqa: E402
    chunk_count,
    connect,
    embedding_bytes,
    file_bytes,
    replace_chunks,
    write_embeddings,
)


def gpu_used_mib() -> int | None:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=10,
        )
        return int(output.strip().splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class VramWatch:
    def __init__(self) -> None:
        self.baseline = gpu_used_mib() or 0
        self.peak = self.baseline
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            used = gpu_used_mib()
            if used is not None:
                self.peak = max(self.peak, used)
            self._stop.wait(0.25)

    def __enter__(self) -> "VramWatch":
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    @property
    def delta_mib(self) -> int:
        return max(0, self.peak - self.baseline)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(pct / 100 * len(ordered))
    index = min(len(ordered) - 1, max(0, rank - 1))
    return ordered[index]


def is_gated(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(token in text for token in ("gated", "401", "403", "access denied", "cannot access", "restricted"))


def ensure_chunks(connection) -> int:
    if not CHUNKS_JSONL.exists():
        raise SystemExit(f"missing {CHUNKS_JSONL}")
    chunks = read_jsonl(CHUNKS_JSONL)
    if chunk_count(connection) != len(chunks):
        replace_chunks(connection, chunks)
    return len(chunks)


def score_mode(hits_text: list[str], question: dict) -> dict | None:
    quotes = question["relevant"]
    if not quotes:
        return None
    return {
        "recall@5": recall_at(hits_text, quotes, 5),
        "mrr@10": mrr_at(hits_text, quotes, 10),
        "ndcg@10": ndcg_at(hits_text, quotes, 10),
    }


def run_mode(searcher: Searcher, query: str, vector, mode: str) -> list:
    if mode == "bm25":
        return searcher.bm25(query, 10)
    if mode == "dense":
        return searcher.dense(vector, 10)
    if mode == "hybrid_rrf":
        return searcher.hybrid(query, vector, 10, fusion="rrf", rrf_k=60)
    if mode == "hybrid_weighted":
        return searcher.hybrid(query, vector, 10, fusion="weighted", dense_weight=0.5)
    raise RuntimeError(mode)


def embed_corpus(spec, rows, batch_size: int):
    """Load on GPU, encode every chunk, return (loaded, matrix, stats).

    On failure the model is unloaded before the error propagates so the
    next model can use the card.
    """
    titles = [document_title(row["sermon_title"], row["scripture"]) for row in rows]
    texts = [row["text"] for row in rows]
    loaded = load_model(spec, device="cuda" if _cuda() else "cpu", batch_size=batch_size)
    try:
        prompts = describe_prompts(loaded)
        with VramWatch() as watch:
            started = time.perf_counter()
            matrix = encode_documents(loaded, titles, texts)
            elapsed = time.perf_counter() - started
        stats = {
            "device": loaded.device,
            "batch_size": loaded.batch_size,
            "seconds": round(elapsed, 3),
            "chunks_per_s": round(len(texts) / elapsed, 2) if elapsed else None,
            "vram_peak_mib": watch.peak,
            "vram_baseline_mib": watch.baseline,
            "vram_delta_mib": watch.delta_mib,
            "dim": int(matrix.shape[1]),
            "prompts": prompts,
        }
        return loaded, matrix, stats
    except Exception:
        unload(loaded)
        raise


def _cuda() -> bool:
    import torch

    return bool(torch.cuda.is_available())


def measure_cpu_latency(spec, connection, questions: list[dict]) -> dict:
    loaded = load_model(spec, device="cpu", batch_size=1)
    searcher = Searcher(connection, model=spec.key)
    warmup = questions[:2] or questions
    for question in warmup:
        vector = encode_query(loaded, question["query"])
        searcher.hybrid(question["query"], vector, 5, fusion="rrf")
    timings: dict[str, list[float]] = {"dense": [], "hybrid_rrf": [], "hybrid_weighted": []}
    for question in questions:
        for mode in timings:
            started = time.perf_counter()
            vector = encode_query(loaded, question["query"])
            run_mode(searcher, question["query"], vector, mode)
            timings[mode].append((time.perf_counter() - started) * 1000)
    unload(loaded)
    return {
        mode: {"p50_ms": percentile(values, 50), "p95_ms": percentile(values, 95), "n": len(values)}
        for mode, values in timings.items()
    }


def evaluate_with(searcher: Searcher, questions: list[dict], encode) -> dict:
    per_mode: dict[str, list] = {
        "bm25": [],
        "dense": [],
        "hybrid_rrf": [],
        "hybrid_weighted": [],
    }
    negative = {mode: [] for mode in per_mode}
    per_query = []
    for question in questions:
        vector = None if encode is None else encode(question["query"])
        record = {"id": question["id"], "type": question["type"], "modes": {}}
        for mode in per_mode:
            if mode != "bm25" and vector is None:
                continue
            hits = run_mode(searcher, question["query"], vector, mode)
            texts = [hit.text for hit in hits]
            top = hits[0].score if hits else None
            if question["relevant"]:
                metrics = score_mode(texts, question)
                per_mode[mode].append(metrics)
                record["modes"][mode] = metrics
            else:
                negative[mode].append(top)
                record["modes"][mode] = {"top1": top}
        per_query.append(record)
    summary = {mode: summarize(rows) for mode, rows in per_mode.items() if rows}
    return {"summary": summary, "negative_top1": negative, "per_query": per_query}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--reembed", action="store_true")
    parser.add_argument("--skip-latency", action="store_true")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--out", type=Path, default=repo_root() / "reports" / "bench_results.json")
    args = parser.parse_args()

    connection = connect(INDEX_PATH)
    n_chunks = ensure_chunks(connection)
    questions = read_jsonl(questions_path())
    rows = list(connection.execute("SELECT rowid, sermon_title, scripture, text FROM chunks ORDER BY rowid"))
    report = {
        "chunks": n_chunks,
        "questions": len(questions),
        "index_path": str(INDEX_PATH),
        "excluded_models": EXCLUDED,
        "models": {},
    }
    print(f"chunks={n_chunks} questions={len(questions)}", flush=True)

    # BM25 does not depend on a model. Computed once inside the first model
    # that successfully loads, and copied onto the report.
    bm25_summary = None

    for key in args.models:
        spec = MODELS[key]
        print(f"\n== {key} ({spec.hf_id}) ==", flush=True)
        loaded = None
        entry = {
            "hf_id": spec.hf_id,
            "license": spec.license,
            "developer": spec.developer,
            "lineage": spec.lineage,
            "params": spec.params,
            "status": "pending",
        }
        try:
            have = connection.execute(
                "SELECT count(*) FROM embeddings WHERE model = ?", (key,)
            ).fetchone()[0]
            loaded = None
            if args.reembed or have != n_chunks:
                loaded, matrix, stats = embed_corpus(spec, rows, args.batch_size)
                write_embeddings(connection, key, [int(row["rowid"]) for row in rows], matrix)
                entry["embed"] = stats
                print(
                    f"embedded {n_chunks} in {stats['seconds']}s "
                    f"({stats['chunks_per_s']} chunks/s) vram_delta={stats['vram_delta_mib']} MiB "
                    f"batch={stats['batch_size']}",
                    flush=True,
                )
                # Query vectors for metrics, while the model is still loaded.
                searcher = Searcher(connection, model=key)

                def encode(query: str, _loaded=loaded) -> object:
                    return encode_query(_loaded, query)

                metrics = evaluate_with(searcher, questions, encode)
                unload(loaded)
                loaded = None
            else:
                print("embeddings present, skipping GPU encode", flush=True)
                entry["embed"] = {"skipped": True}
                # Metrics still need query vectors. Use CPU if we did not load GPU.
                loaded = load_model(spec, device="cpu", batch_size=1)
                searcher = Searcher(connection, model=key)

                def encode(query: str, _loaded=loaded) -> object:
                    return encode_query(_loaded, query)

                metrics = evaluate_with(searcher, questions, encode)
                unload(loaded)
                loaded = None
            entry["metrics"] = metrics["summary"]
            entry["negative_top1"] = {}
            for mode, scores in metrics["negative_top1"].items():
                present = [score for score in scores if score is not None]
                entry["negative_top1"][mode] = {
                    "n": len(scores),
                    "mean": (sum(present) / len(present)) if present else None,
                    "scores": scores,
                }
            entry["per_query"] = metrics["per_query"]
            entry["embedding_bytes"] = embedding_bytes(connection, key)
            entry["sqlite_bytes"] = file_bytes()
            if not args.skip_latency:
                print("measuring CPU query latency", flush=True)
                entry["cpu_query_latency"] = measure_cpu_latency(spec, connection, questions)
                latency = entry["cpu_query_latency"]["hybrid_rrf"]
                print(f"hybrid cpu p50={latency['p50_ms']:.0f} ms p95={latency['p95_ms']:.0f} ms", flush=True)
            entry["status"] = "ok"
            if bm25_summary is None and "bm25" in metrics["summary"]:
                bm25_summary = metrics["summary"]["bm25"]
            embed_stats = entry.get("embed") or {}
            delta = embed_stats.get("vram_delta_mib")
            # Whisper is using the rest of the 3060. Stay near a 4 GB share.
            if isinstance(delta, int) and delta > 4096 and args.batch_size > 1:
                args.batch_size = max(1, args.batch_size // 2)
                print(
                    f"vram delta {delta} MiB is over 4096; next model batch={args.batch_size}",
                    flush=True,
                )
        except Exception as exc:
            if loaded is not None:
                unload(loaded)
            gc.collect()
            # spec.gated means we expect a gate. Only call it skipped when the
            # error actually looks like an access refusal. A load bug stays an error.
            status = "skipped_gated" if is_gated(exc) else "error"
            entry["status"] = status
            entry["error"] = f"{type(exc).__name__}: {exc}"
            print(f"{status}: {entry['error']}", flush=True)
        report["models"][key] = entry
        report["bm25"] = bm25_summary
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        gc.collect()

    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
