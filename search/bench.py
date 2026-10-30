"""Benchmark BM25, each embedding model, and hybrids on the Wesley eval set.

One command:  uv run search/bench.py
Models come from search/models.toml (one table per model, pinned revision).
Each run writes eval/results/YYYY-MM-DD[-N].json and .md and never
overwrites an earlier run. Document vectors are cached in the SQLite index
under a fingerprint of everything that changes them (repo revision, dtype,
document prefix, dim), so a rerun only re-embeds what changed.

Corpus: GPU if present, else CPU. Queries: always CPU at dtype_cpu, the way
one Sprite will run them; the same load measures CPU latency. Metrics are
Recall@5, MRR@10, nDCG@10 on answerable questions, each with a bootstrap 95%
interval, plus a paired bootstrap against the reference row in models.toml.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import platform
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
from preached.metrics import mrr_at, ndcg_at, recall_at  # noqa: E402
from preached.models import EXCLUDED, MODELS, REFERENCE, config_path  # noqa: E402
from preached.paths import CHUNKS_JSONL, INDEX_PATH, chunk_config_path, questions_path, repo_root  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.stats import bootstrap_ci, paired_bootstrap  # noqa: E402
from preached.store import (  # noqa: E402
    chunk_count,
    connect,
    embedding_bytes,
    replace_chunks,
    write_embeddings,
)

MODES = ("dense", "hybrid_rrf", "hybrid_weighted")
# sermon@5 is a looser check: any top-5 chunk from a sermon holding a grade-2 quote.
METRICS = ("recall@5", "mrr@10", "ndcg@10", "sermon@5")


# ---------- environment ----------

def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.check_output(cmd, text=True, timeout=10, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def gpu_used_mib() -> int | None:
    out = _run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    try:
        return int(out.splitlines()[0]) if out else None
    except ValueError:
        return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment() -> dict:
    import numpy
    import sentence_transformers
    import torch
    import transformers

    cpu = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    root = repo_root()
    return {
        "git_commit": _run(["git", "-C", str(root), "rev-parse", "HEAD"]),
        "git_dirty": bool(_run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"])),
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "sentence_transformers": sentence_transformers.__version__,
        "gpu": _run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]),
        "cpu": cpu,
        "torch_threads": torch.get_num_threads(),
        "questions_sha256": sha256(questions_path()),
        "chunks_sha256": sha256(CHUNKS_JSONL),
        "chunk_config": json.loads(chunk_config_path().read_text()),
        "models_toml_sha256": sha256(config_path()),
    }


# ---------- helpers ----------

class VramWatch:
    """Peak GPU memory from before the weights load, so the delta includes the model."""

    def __init__(self) -> None:
        self.baseline = gpu_used_mib() or 0
        self.peak = self.baseline
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
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


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def is_gated(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(t in text for t in ("gated", "401", "403", "access denied", "cannot access", "restricted"))


def ensure_chunks(connection) -> int:
    if not CHUNKS_JSONL.exists():
        raise SystemExit(f"missing {CHUNKS_JSONL}. Run corpus/fetch_wesley.py and corpus/chunk_sermons.py")
    chunks = read_jsonl(CHUNKS_JSONL)
    if chunk_count(connection) != len(chunks):
        replace_chunks(connection, chunks)
    return len(chunks)


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


def score(hits: list, quotes: list[dict]) -> dict:
    texts = [h.text for h in hits]
    best = max(int(q["grade"]) for q in quotes)
    sermons = {q["sermon_id"] for q in quotes if int(q["grade"]) == best}
    return {
        "sermon@5": float(any(h.sermon_id in sermons for h in hits[:5])),
        "recall@5": recall_at(texts, quotes, 5),
        "mrr@10": mrr_at(texts, quotes, 10),
        "ndcg@10": ndcg_at(texts, quotes, 10),
    }


def evaluate(searcher: Searcher, questions: list[dict], modes, encode=None) -> dict:
    """Per-question metrics for answerable items, top-1 score for unanswerable ones."""
    per_query: dict[str, dict] = {m: {} for m in modes}
    negative: dict[str, dict] = {m: {} for m in modes}
    for q in questions:
        vector = encode(q["query"]) if encode else None
        for mode in modes:
            hits = run_mode(searcher, q["query"], vector, mode)
            if q["relevant"]:
                per_query[mode][q["id"]] = score(hits, q["relevant"])
            else:
                negative[mode][q["id"]] = hits[0].score if hits else None
    return {"per_query": per_query, "negative_top1": negative}


def summarize(per_query: dict[str, dict]) -> dict:
    ids = sorted(per_query)
    out = {"n": len(ids)}
    for metric in METRICS:
        out[metric] = bootstrap_ci([per_query[i][metric] for i in ids])
    return out


# ---------- embedding cache ----------

def stored_fingerprint(connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (f"embeddings:{key}",)).fetchone()
    return json.loads(row[0]).get("fingerprint") if row else None


def save_fingerprint(connection, key: str, info: dict) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"embeddings:{key}", json.dumps(info))
    )
    connection.commit()


def embed_corpus(spec, rows, batch_size: int, connection) -> dict:
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    titles = [document_title(r["sermon_title"], r["scripture"]) for r in rows]
    texts = [r["text"] for r in rows]
    with VramWatch() as watch:
        loaded = load_model(spec, device=device, batch_size=batch_size)
        try:
            started = time.perf_counter()
            matrix = encode_documents(loaded, titles, texts)
            elapsed = time.perf_counter() - started
        finally:
            dtype, used_batch = loaded.dtype, loaded.batch_size
            unload(loaded)
    write_embeddings(connection, spec.key, [int(r["rowid"]) for r in rows], matrix)
    stats = {
        "device": device,
        "dtype": dtype,
        "batch_size": used_batch,
        "seconds": round(elapsed, 1),
        "chunks_per_s": round(len(texts) / elapsed, 1) if elapsed else None,
        "vram_baseline_mib": watch.baseline,
        "vram_peak_mib": watch.peak,
        "vram_delta_mib": max(0, watch.peak - watch.baseline),
        "dim": int(matrix.shape[1]),
        "embedded_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    save_fingerprint(connection, spec.key, {"fingerprint": spec.fingerprint(), **stats})
    return stats


def cpu_eval(spec, connection, questions) -> tuple[dict, dict]:
    """Metrics with CPU query vectors, then CPU latency (query embed + search)."""
    loaded = load_model(spec, device="cpu", batch_size=1)
    try:
        searcher = Searcher(connection, model=spec.key)
        result = evaluate(searcher, questions, MODES, encode=lambda q: encode_query(loaded, q))
        for q in questions[:2]:  # warmup
            searcher.hybrid(q["query"], encode_query(loaded, q["query"]), 5)
        timings: dict[str, list[float]] = {m: [] for m in MODES}
        for q in questions:
            for mode in MODES:
                started = time.perf_counter()
                run_mode(searcher, q["query"], encode_query(loaded, q["query"]), mode)
                timings[mode].append((time.perf_counter() - started) * 1000)
        latency = {
            m: {"p50_ms": round(percentile(v, 50), 1), "p95_ms": round(percentile(v, 95), 1), "n": len(v)}
            for m, v in timings.items()
        }
        result["cpu_dtype"] = loaded.dtype
    finally:
        unload(loaded)
    return result, latency


# ---------- output ----------

def output_paths(results_dir: Path, today: str) -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    stem, n = today, 1
    while (results_dir / f"{stem}.json").exists() or (results_dir / f"{stem}.md").exists():
        n += 1
        stem = f"{today}-{n}"
    return results_dir / f"{stem}.json", results_dir / f"{stem}.md"


def fmt_ci(cell: dict) -> str:
    low, high = cell["ci95"]
    return f"{cell['mean']:.3f} [{low:.2f}, {high:.2f}]"


def fmt_diff(cell: dict | None) -> str:
    if not cell:
        return ""
    low, high = cell["ci95"]
    return f"{cell['diff']:+.3f} [{low:+.2f}, {high:+.2f}] ({cell['wins']}/{cell['ties']}/{cell['losses']})"


def markdown(report: dict) -> str:
    ref = report["reference"]
    lines = [
        f"# Retrieval benchmark, {report['started_at']}",
        "",
        f"Questions: {report['n_answerable']} answerable, {report['n_unanswerable']} unanswerable. "
        f"Chunks: {report['chunks']}. Commit `{report['environment']['git_commit']}`"
        + (" (dirty)" if report["environment"]["git_dirty"] else "") + ".",
        f"Libraries: torch {report['environment']['torch']}, transformers {report['environment']['transformers']}, "
        f"sentence-transformers {report['environment']['sentence_transformers']}. "
        f"GPU: {report['environment']['gpu']}. CPU: {report['environment']['cpu']}.",
        "",
        "Cells are the mean with a bootstrap 95% interval over questions. "
        f"Δ is a paired bootstrap of nDCG@10 against `{ref['model']}` `{ref['mode']}` "
        "(wins/ties/losses per question). See docs/research/embeddings.md.",
        "",
        "| model | revision | mode | R@5 | MRR@10 | nDCG@10 | sermon@5 | Δ nDCG@10 vs ref | corpus dtype | chunks/s | CPU p50 / p95 ms | dim |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    bm = report["bm25"]["summary"]
    lines.append(
        f"| BM25 (SQLite FTS5) | | bm25 | {fmt_ci(bm['recall@5'])} | {fmt_ci(bm['mrr@10'])} | "
        f"{fmt_ci(bm['ndcg@10'])} | {fmt_ci(bm['sermon@5'])} | {fmt_diff(report['bm25'].get('vs_reference', {}).get('ndcg@10'))} | | | | |"
    )
    for key, entry in report["models"].items():
        if entry["status"] != "ok":
            lines.append(f"| {key} | `{entry['revision'][:10]}` | {entry['status']} | | | | | | | | | |")
            continue
        embed = entry["embed"]
        for mode in MODES:
            s = entry["summary"][mode]
            lat = entry["cpu_latency"][mode]
            vs = entry["vs_reference"].get(mode, {}).get("ndcg@10")
            lines.append(
                f"| {key} | `{entry['revision'][:10]}` | {mode} | {fmt_ci(s['recall@5'])} | {fmt_ci(s['mrr@10'])} | "
                f"{fmt_ci(s['ndcg@10'])} | {fmt_ci(s['sermon@5'])} | {fmt_diff(vs)} | {embed.get('dtype', '')} | "
                f"{embed.get('chunks_per_s') or ''} | {lat['p50_ms']} / {lat['p95_ms']} | {embed.get('dim', '')} |"
            )
    lines += ["", "Prompts as the model sees them:", ""]
    for key, entry in report["models"].items():
        p = entry.get("prompts")
        if p:
            lines.append(f"- `{key}`: question `{p['question']}`; keyword `{p['keyword']}`; document `{p['document']}`")
    return "\n".join(lines) + "\n"


# ---------- main ----------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    enabled = [k for k, s in MODELS.items() if s.enabled]
    parser.add_argument("--models", nargs="*", default=enabled, choices=sorted(MODELS),
                        help="default: every enabled model in models.toml")
    parser.add_argument("--reembed", action="store_true", help="re-encode the corpus even if the cache matches")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--results-dir", type=Path, default=repo_root() / "eval" / "results")
    parser.add_argument("--note", default="", help="free text stored with the run")
    args = parser.parse_args()

    started = dt.datetime.now().astimezone()
    connection = connect(INDEX_PATH)
    n_chunks = ensure_chunks(connection)
    questions = read_jsonl(questions_path())
    answerable = [q for q in questions if q["relevant"]]
    rows = list(connection.execute("SELECT rowid, sermon_title, scripture, text FROM chunks ORDER BY rowid"))

    models = list(dict.fromkeys(args.models + ([REFERENCE["model"]] if REFERENCE["model"] in MODELS else [])))
    json_path, md_path = output_paths(args.results_dir, started.date().isoformat())
    report = {
        "started_at": started.isoformat(timespec="seconds"),
        "note": args.note,
        "chunks": n_chunks,
        "n_answerable": len(answerable),
        "n_unanswerable": len(questions) - len(answerable),
        "index_path": str(INDEX_PATH),
        "environment": environment(),
        "reference": REFERENCE,
        "excluded_models": EXCLUDED,
        "models": {},
    }
    print(f"chunks={n_chunks} questions={len(questions)} -> {json_path}", flush=True)

    bm = evaluate(Searcher(connection), questions, ("bm25",))
    report["bm25"] = {
        "summary": summarize(bm["per_query"]["bm25"]),
        "per_query": bm["per_query"]["bm25"],
        "negative_top1": bm["negative_top1"]["bm25"],
    }

    for key in models:
        spec = MODELS[key]
        print(f"\n== {key} ({spec.hf_id}@{spec.revision[:10]}) ==", flush=True)
        entry = {**spec.record(), "status": "pending", "prompts": describe_prompts(spec)}
        try:
            have = connection.execute("SELECT count(*) FROM embeddings WHERE model = ?", (key,)).fetchone()[0]
            if args.reembed or have != n_chunks or stored_fingerprint(connection, key) != spec.fingerprint():
                entry["embed"] = embed_corpus(spec, rows, args.batch_size, connection)
                print(f"embedded: {entry['embed']}", flush=True)
            else:
                row = connection.execute("SELECT value FROM meta WHERE key = ?", (f"embeddings:{key}",)).fetchone()
                entry["embed"] = {**json.loads(row[0]), "cached": True}
                print("corpus vectors cached (fingerprint matches)", flush=True)
            result, latency = cpu_eval(spec, connection, questions)
            entry["cpu_dtype"] = result["cpu_dtype"]
            entry["per_query"] = result["per_query"]
            entry["negative_top1"] = result["negative_top1"]
            entry["summary"] = {m: summarize(result["per_query"][m]) for m in MODES}
            entry["cpu_latency"] = latency
            entry["embedding_bytes"] = embedding_bytes(connection, key)
            entry["status"] = "ok"
            for m in MODES:
                s = entry["summary"][m]
                print(f"{m:16s} " + "  ".join(f"{k}={s[k]['mean']:.3f}" for k in METRICS)
                      + f"  cpu p50={latency[m]['p50_ms']} ms", flush=True)
        except Exception as exc:  # one model failing must not lose the others
            entry["status"] = "skipped_gated" if is_gated(exc) else "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            print(f"{entry['status']}: {entry['error']}", flush=True)
        report["models"][key] = entry

    # Paired comparisons against the reference row, on the same questions.
    ref_entry = report["models"].get(REFERENCE["model"], {})
    ref_pq = ref_entry.get("per_query", {}).get(REFERENCE["mode"]) if ref_entry.get("status") == "ok" else None

    def versus(per_query: dict) -> dict:
        ids = sorted(per_query)
        return {
            metric: paired_bootstrap([per_query[i][metric] for i in ids], [ref_pq[i][metric] for i in ids])
            for metric in METRICS
        }

    if ref_pq:
        report["bm25"]["vs_reference"] = versus(report["bm25"]["per_query"])
        for entry in report["models"].values():
            if entry["status"] == "ok":
                entry["vs_reference"] = {m: versus(entry["per_query"][m]) for m in MODES}
    for entry in report["models"].values():
        entry.setdefault("vs_reference", {})

    report["finished_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    json_path.write_text(json.dumps(report, indent=1) + "\n")
    md_path.write_text(markdown(report))
    print(f"\nwrote {json_path}\nwrote {md_path}")


if __name__ == "__main__":
    main()
