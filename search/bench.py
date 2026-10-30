"""Benchmark BM25, each embedding model, and hybrids on the Wesley eval set.

One command:  uv run --group bench search/bench.py
(The bench group adds Pillow and torchvision, which EmbeddingGemma 2 needs to load.)
Models come from search/models.toml (one table per model, pinned revision).
Each run writes eval/results/YYYY-MM-DD[-N].json and .md and never
overwrites an earlier run. Document vectors are cached in the SQLite index
under a fingerprint of everything that changes them (repo revision, dtype,
document prefix, dim), so a rerun only re-embeds what changed.

Corpus: GPU if present, else CPU. Queries: always CPU at dtype_cpu, the way
one Sprite will run them; the same load measures CPU latency. Metrics are
Recall@5, MRR@10, nDCG@10 on answerable questions, each with a bootstrap 95%
interval, plus a paired bootstrap against the reference row in models.toml.

--dedupe scores the list GET /api/search returns instead of the raw ranker:
api_search (src/preached/search.py), which takes the top SEARCH_POOL (100) and
runs dedupe_adjacent down to 10. hybrid_weighted is not an API mode; it gets
the same pool and de-dup. Those runs write eval/results/YYYY-MM-DD-dedupe[-N]
.json and .md, so they never overwrite or mix with raw-ranker runs.

--abstain evaluates the "nothing found" rule (src/preached/abstain.py) on the
API path, hybrid, k=10, per model: in-sample (floor fitted on all 40
questions) and leave-one-out (floor refitted without the held-out question).
An abstained answerable question counts as a miss for R@5 and MRR@10. It
writes eval/results/YYYY-MM-DD-abstain[-N].json and .md. Add
--write-calibration to store the in-sample floors in search/abstain.toml.
Corpus vectors must already be embedded (run the plain bench first).

Every run also reports each metric per question group (the ``group`` field
in eval/questions.jsonl: plain, names-topic, title-keyword,
scripture-keyword, unanswerable) next to the overall numbers. See the
"Title leakage" section of docs/research/embeddings.md.
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
from preached import abstain  # noqa: E402
from preached.metrics import mrr_at, ndcg_at, recall_at  # noqa: E402
from preached.models import EXCLUDED, MODELS, REFERENCE, config_path  # noqa: E402
from preached.paths import INDEX_PATH, StaleChunks, chunk_config_path, index_chunks_jsonl, questions_path, repo_root  # noqa: E402
from preached.search import SEARCH_POOL, Searcher, api_search, dedupe_adjacent  # noqa: E402
from preached.stats import bootstrap_ci, paired_bootstrap  # noqa: E402
from preached.store import (  # noqa: E402
    connect,
    embedding_bytes,
    save_embedding_info,
    stored_fingerprint,
    sync_chunks,
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
        "chunks_sha256": sha256(index_chunks_jsonl()),
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
    try:
        chunks_path = index_chunks_jsonl()
    except StaleChunks as exc:
        raise SystemExit(f"error: {exc}") from exc
    if not chunks_path.exists():
        raise SystemExit(f"missing {chunks_path}. Run corpus/fetch_wesley.py and corpus/chunk_sermons.py")
    return sync_chunks(connection, chunks_path)


API_MODE = {"bm25": "bm25", "dense": "dense", "hybrid_rrf": "hybrid"}


def run_mode(searcher: Searcher, query: str, vector, mode: str, dedupe: bool = False) -> list:
    if dedupe:
        # The shipped path. hybrid_weighted is not an API mode; give it the same pool and de-dup.
        if mode in API_MODE:
            return api_search(searcher, query, vector, API_MODE[mode], 10)
        if mode == "hybrid_weighted":
            pool = searcher.hybrid(query, vector, SEARCH_POOL, fusion="weighted", dense_weight=0.5)
            return dedupe_adjacent(pool, 10)
        raise RuntimeError(mode)
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
        "top10": [h.chunk_id for h in hits[:10]],
    }


def evaluate(searcher: Searcher, questions: list[dict], modes, encode=None, dedupe: bool = False) -> dict:
    """Per-question metrics for answerable items, top-1 score for unanswerable ones."""
    per_query: dict[str, dict] = {m: {} for m in modes}
    negative: dict[str, dict] = {m: {} for m in modes}
    for q in questions:
        vector = encode(q["query"]) if encode else None
        for mode in modes:
            hits = run_mode(searcher, q["query"], vector, mode, dedupe)
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


def question_groups(questions: list[dict]) -> dict[str, list[str]]:
    """Question ids per ``group``, in first-seen order. Ungrouped items go to "ungrouped"."""
    groups: dict[str, list[str]] = {}
    for q in questions:
        groups.setdefault(q.get("group", "ungrouped"), []).append(q["id"])
    return groups


def by_group(per_query: dict[str, dict], groups: dict[str, list[str]]) -> dict[str, dict]:
    """``summarize`` on each group's answerable questions (groups with none are skipped)."""
    out = {}
    for name, ids in groups.items():
        subset = {i: per_query[i] for i in ids if i in per_query}
        if subset:
            out[name] = summarize(subset)
    return out


# ---------- embedding cache ----------

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
    save_embedding_info(connection, spec.key, {"fingerprint": spec.fingerprint(), **stats})
    return stats


def cpu_eval(spec, connection, questions, dedupe: bool = False) -> tuple[dict, dict]:
    """Metrics with CPU query vectors, then CPU latency (query embed + search)."""
    loaded = load_model(spec, device="cpu", batch_size=1)
    try:
        searcher = Searcher(connection, model=spec.key)
        result = evaluate(searcher, questions, MODES, encode=lambda q: encode_query(loaded, q), dedupe=dedupe)
        for q in questions[:2]:  # warmup
            searcher.hybrid(q["query"], encode_query(loaded, q["query"]), 5)
        timings: dict[str, list[float]] = {m: [] for m in MODES}
        for q in questions:
            for mode in MODES:
                started = time.perf_counter()
                run_mode(searcher, q["query"], encode_query(loaded, q["query"]), mode, dedupe)
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

def output_paths(results_dir: Path, today: str, tag: str = "") -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    base = f"{today}-{tag}" if tag else today
    stem, n = base, 1
    while (results_dir / f"{stem}.json").exists() or (results_dir / f"{stem}.md").exists():
        n += 1
        stem = f"{base}-{n}"
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
        *(["Scored list: the API path (`--dedupe`): top 100, `dedupe_adjacent`, top 10, "
           "as `GET /api/search` returns it.", ""] if report.get("dedupe") else []),
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
            flag = "" if entry.get("provenance", "clear") == "clear" else " ⚠ lineage unclear"
            lines.append(
                f"| {key}{flag} | `{entry['revision'][:10]}` | {mode} | {fmt_ci(s['recall@5'])} | {fmt_ci(s['mrr@10'])} | "
                f"{fmt_ci(s['ndcg@10'])} | {fmt_ci(s['sermon@5'])} | {fmt_diff(vs)} | {embed.get('dtype', '')} | "
                f"{embed.get('chunks_per_s') or ''} | {lat['p50_ms']} / {lat['p95_ms']} | {embed.get('dim', '')} |"
            )
    groups = report.get("groups")
    if groups:
        names = [g for g in groups if g in report["bm25"].get("by_group", {})]
        lines += ["", "Per question group (mean nDCG@10 / R@5 / MRR@10; n answerable in the header). "
                  "Group definitions: eval/README.md.", "",
                  "| model | mode | " + " | ".join(f"{g} (n={report['bm25']['by_group'][g]['n']})" for g in names)
                  + " | overall |",
                  "| --- | --- | " + " | ".join("---" for _ in names) + " | --- |"]

        def group_cells(summary: dict, grouped: dict) -> str:
            cells = [grouped.get(g) for g in names] + [summary]
            return " | ".join(f"{c['ndcg@10']['mean']:.3f} / {c['recall@5']['mean']:.3f} / {c['mrr@10']['mean']:.3f}"
                              if c else "" for c in cells)

        lines.append(f"| BM25 | bm25 | {group_cells(bm, report['bm25']['by_group'])} |")
        for key, entry in report["models"].items():
            if entry["status"] == "ok":
                for mode in MODES:
                    lines.append(f"| {key} | {mode} | {group_cells(entry['summary'][mode], entry['by_group'][mode])} |")
        lines += ["", "Paired Δ nDCG@10 against the reference, per group (95% CI, wins/ties/losses):", "",
                  "| model | mode | " + " | ".join(names) + " |", "| --- | --- | " + " | ".join("---" for _ in names) + " |"]
        rows = [("BM25", "bm25", report["bm25"])] + [
            (k, m, {"vs_reference_by_group": {g: v.get(m, {}) for g, v in e.get("vs_reference_by_group", {}).items()}})
            for k, e in report["models"].items() if e["status"] == "ok" for m in MODES]
        for key, mode, entry in rows:
            vs = entry.get("vs_reference_by_group", {})
            lines.append(f"| {key} | {mode} | " + " | ".join(fmt_diff(vs.get(g, {}).get("ndcg@10")) for g in names) + " |")
    lines += ["", "Prompts as the model sees them:", ""]
    for key, entry in report["models"].items():
        p = entry.get("prompts")
        if p:
            lines.append(f"- `{key}`: question `{p['question']}`; keyword `{p['keyword']}`; document `{p['document']}`")
    return "\n".join(lines) + "\n"


# ---------- abstain ----------

# Unlabelled probes, reported next to the eval but never used to fit. The
# first four are the page's example chips; the rest are questions a visitor
# might try. No ground truth: read their levels as a demo check only.
PROBES = (
    "What did Wesley say about worry?",
    "How can I know that I am a child of God?",
    "What did Wesley say about money?",
    "Romans 8:16",
    "What did Wesley say about drinking gin?",
    "What did Wesley say about slavery?",
    "What did Wesley say about electricity?",
    "Is it okay for Christians to play video games?",
    "What did Wesley say about dinosaurs?",
    "What did Wesley think about the internet?",
    "Did Wesley support the American Revolution?",
    "What did Wesley teach about climate change and the environment?",
)


def abstain_rows(spec, connection, questions) -> tuple[list[dict], list[dict]]:
    """Per-question signals and metrics on the API path (hybrid, k=10)."""
    loaded = load_model(spec, device="cpu", batch_size=1)
    try:
        searcher = Searcher(connection, model=spec.key)
        rows = []
        for q in questions:
            vector = encode_query(loaded, q["query"])
            hits, conf = abstain.search_with_confidence(searcher, q["query"], vector, "hybrid", 10, None)
            row = {"id": q["id"], "group": q.get("group", "ungrouped"), "answerable": bool(q["relevant"]),
                   **conf.as_dict()["signals"]}
            if q["relevant"]:
                texts = [h.text for h in hits]
                row["recall@5"] = recall_at(texts, q["relevant"], 5)
                row["mrr@10"] = mrr_at(texts, q["relevant"], 10)
            rows.append(row)
        probes = []
        for text in PROBES:
            vector = encode_query(loaded, text)
            hits, conf = abstain.search_with_confidence(searcher, text, vector, "hybrid", 10, None)
            probes.append({"query": text, **conf.as_dict()["signals"], "top": hits[0].chunk_id if hits else None})
    finally:
        unload(loaded)
    return rows, probes


def _signals(row: dict) -> "abstain.Signals":
    return abstain.Signals(bm25_hits=row["bm25_hits"], dense_top=row["dense_top"], agreement=row["agreement"])


def abstain_summary(rows: list[dict], levels: list[str]) -> dict:
    """Abstention precision/recall on unanswerable, false abstains, and
    R@5 / MRR@10 with abstained answerable questions scored 0."""
    neg = [lv for r, lv in zip(rows, levels) if not r["answerable"]]
    pos = [(r, lv) for r, lv in zip(rows, levels) if r["answerable"]]
    abstained = sum(lv == "none" for lv in levels)
    true_abstain = sum(lv == "none" for lv in neg)
    flagged_neg = sum(lv in ("none", "weak") for lv in neg)
    n_pos = len(pos)

    def mean(values):
        return round(sum(values) / len(values), 4) if values else None

    return {
        "n_answerable": n_pos,
        "n_unanswerable": len(neg),
        "abstained": abstained,
        "abstain_precision": round(true_abstain / abstained, 4) if abstained else None,
        "abstain_recall": round(true_abstain / len(neg), 4) if neg else None,
        "flagged_recall": round(flagged_neg / len(neg), 4) if neg else None,
        "false_abstain_rate": round(sum(lv == "none" for _, lv in pos) / n_pos, 4) if n_pos else None,
        "weak_rate_answerable": round(sum(lv == "weak" for _, lv in pos) / n_pos, 4) if n_pos else None,
        "recall@5": mean([r["recall@5"] for r, _ in pos]),
        "recall@5_abstain": mean([0.0 if lv == "none" else r["recall@5"] for r, lv in pos]),
        "mrr@10": mean([r["mrr@10"] for r, _ in pos]),
        "mrr@10_abstain": mean([0.0 if lv == "none" else r["mrr@10"] for r, lv in pos]),
        "levels": {lv: levels.count(lv) for lv in ("strong", "weak", "none", "unrated")},
    }


def abstain_eval(rows: list[dict]) -> dict:
    pairs = [(_signals(r), r["answerable"]) for r in rows]
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(row.get("group", "ungrouped"), []).append(index)
    floor = abstain.fit_floor(pairs)
    in_sample = [abstain.decide(s, floor).level for s, _ in pairs]
    loo_levels, loo_floors = [], []
    for index, (signals, _) in enumerate(pairs):
        held_floor = abstain.fit_floor(pairs[:index] + pairs[index + 1:])
        loo_floors.append(held_floor)
        loo_levels.append(abstain.decide(signals, held_floor).level)
    uncalibrated = [abstain.decide(s, None).level for s, _ in pairs]
    for row, a, b, c, f in zip(rows, in_sample, loo_levels, uncalibrated, loo_floors):
        row["level_in_sample"], row["level_loo"], row["level_uncalibrated"], row["loo_floor"] = a, b, c, f
    def per_group(levels: list[str]) -> dict:
        return {g: abstain_summary([rows[i] for i in ids], [levels[i] for i in ids]) for g, ids in groups.items()}

    return {
        "floor": floor,
        "in_sample_by_group": per_group(in_sample),
        "leave_one_out_by_group": per_group(loo_levels),
        "in_sample": abstain_summary(rows, in_sample),
        "leave_one_out": abstain_summary(rows, loo_levels),
        "uncalibrated": abstain_summary(rows, uncalibrated),
        "loo_floor_range": [min(f for f in loo_floors if f is not None), max(f for f in loo_floors if f is not None)]
        if any(f is not None for f in loo_floors) else None,
    }


def abstain_markdown(report: dict) -> str:
    lines = [
        f"# Abstain rule, {report['started_at']}",
        "",
        "API path (hybrid RRF, top 100, `dedupe_adjacent`, k=10). Rule: `src/preached/abstain.py`. "
        f"Questions: {report['n_answerable']} answerable, {report['n_unanswerable']} unanswerable "
        "(LLM-written labels, pending human review). Commit "
        f"`{report['environment']['git_commit']}`" + (" (dirty)" if report["environment"]["git_dirty"] else "") + ".",
        "",
        "Headline is leave-one-out (LOO): each question is judged with a floor fitted on the other 39. "
        "An abstained answerable question counts as a miss.",
        "",
        "| model | eval | floor | abstain precision | abstain recall | flagged (weak or none) recall | "
        "false abstain | weak on answerable | R@5 → with abstain | MRR@10 → with abstain |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    def cell(value):
        return "n/a" if value is None else f"{value:.3f}"

    for key, entry in report["models"].items():
        if entry.get("status") != "ok":
            lines.append(f"| {key} | {entry.get('status')} | | | | | | | | |")
            continue
        ev = entry["abstain"]
        for name, label in (("leave_one_out", "**LOO**"), ("in_sample", "in-sample"), ("uncalibrated", "no floor")):
            s = ev[name]
            floor = {"leave_one_out": "refit per fold (range " + (
                f"{ev['loo_floor_range'][0]:.4f}–{ev['loo_floor_range'][1]:.4f}" if ev["loo_floor_range"] else "n/a") + ")",
                "in_sample": cell(ev["floor"]) if ev["floor"] is not None else "n/a",
                "uncalibrated": "none"}[name]
            lines.append(
                f"| {key} | {label} | {floor} | {cell(s['abstain_precision'])} | {cell(s['abstain_recall'])} | "
                f"{cell(s['flagged_recall'])} | {cell(s['false_abstain_rate'])} | {cell(s['weak_rate_answerable'])} | "
                f"{cell(s['recall@5'])} → {cell(s['recall@5_abstain'])} | {cell(s['mrr@10'])} → {cell(s['mrr@10_abstain'])} |"
            )
    lines += ["", "Per group, leave-one-out (in-sample in parentheses). Answerable groups: share abstained "
              "(false abstain) and share weak. Unanswerable: share abstained and share flagged weak or none.", "",
              "| model | group | n | abstained | weak or flagged | R@5 → with abstain |", "| --- | --- | --- | --- | --- | --- |"]
    for key, entry in report["models"].items():
        if entry.get("status") != "ok":
            continue
        ev = entry["abstain"]
        for group, s in ev["leave_one_out_by_group"].items():
            i = ev["in_sample_by_group"][group]
            if s["n_answerable"]:
                lines.append(f"| {key} | {group} | {s['n_answerable']} | {cell(s['false_abstain_rate'])} "
                             f"({cell(i['false_abstain_rate'])}) | {cell(s['weak_rate_answerable'])} "
                             f"({cell(i['weak_rate_answerable'])}) | {cell(s['recall@5'])} → {cell(s['recall@5_abstain'])} |")
            else:
                lines.append(f"| {key} | {group} | {s['n_unanswerable']} | {cell(s['abstain_recall'])} "
                             f"({cell(i['abstain_recall'])}) | {cell(s['flagged_recall'])} ({cell(i['flagged_recall'])}) | |")
    lines += ["", "Per question (signals and levels; `agree` = a shown passage is in both BM25's and dense's top 100):", ""]
    for key, entry in report["models"].items():
        if entry.get("status") != "ok":
            continue
        lines += [f"## {key}", "", "| id | group | answerable | BM25 hits | dense top | agree | R@5 | in-sample | LOO | no floor |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in sorted(entry["rows"], key=lambda r: (r["answerable"], r["dense_top"] or 0)):
            lines.append(
                f"| {r['id']} | {r.get('group', '')} | {'yes' if r['answerable'] else 'no'} | {r['bm25_hits']} | {r['dense_top']:.4f} | "
                f"{'yes' if r['agreement'] else 'no'} | {r.get('recall@5', '')} | {r['level_in_sample']} | "
                f"{r['level_loo']} | {r['level_uncalibrated']} |"
            )
        lines += ["", "Unlabelled probes (not used to fit; no ground truth), level with the in-sample floor:", "",
                  "| query | BM25 hits | dense top | agree | level |", "| --- | --- | --- | --- | --- |"]
        for p in entry["probes"]:
            lines.append(f"| {p['query']} | {p['bm25_hits']} | {p['dense_top']:.4f} | "
                         f"{'yes' if p['agreement'] else 'no'} | {p['level']} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def run_abstain(args, connection, questions, started) -> None:
    answerable = [q for q in questions if q["relevant"]]
    json_path, md_path = output_paths(args.results_dir, started.date().isoformat(), "abstain")
    report = {
        "started_at": started.isoformat(timespec="seconds"),
        "note": args.note,
        "mode": "hybrid_rrf (API path, dedupe, k=10)",
        "n_answerable": len(answerable),
        "n_unanswerable": len(questions) - len(answerable),
        "groups": question_groups(questions),
        "index_path": str(INDEX_PATH),
        "environment": environment(),
        "rule": abstain.__doc__,
        "models": {},
    }
    print(f"abstain eval, questions={len(questions)} -> {json_path}", flush=True)
    calibrations = {k: v for k, v in abstain.load_calibrations().items() if isinstance(v, dict)}
    for key in args.models:
        spec = MODELS[key]
        entry = {"hf_id": spec.hf_id, "revision": spec.revision, "fingerprint": spec.fingerprint(),
                 "query_fingerprint": abstain.query_fingerprint(spec), "status": "pending"}
        try:
            if stored_fingerprint(connection, key) != spec.fingerprint():
                raise RuntimeError(f"stored vectors for {key} are missing or stale; run: uv run --group bench "
                                   f"search/bench.py --models {key}")
            rows, probes = abstain_rows(spec, connection, questions)
            entry["rows"] = rows
            entry["abstain"] = abstain_eval(rows)
            floor = entry["abstain"]["floor"]
            for p in probes:
                p["level"] = abstain.decide(_signals(p), floor).level
            entry["probes"] = probes
            entry["status"] = "ok"
            for name in ("leave_one_out", "in_sample"):
                s = entry["abstain"][name]
                print(f"{key} {name}: floor={floor} precision={s['abstain_precision']} recall={s['abstain_recall']} "
                      f"false_abstain={s['false_abstain_rate']} weak={s['weak_rate_answerable']} "
                      f"R@5 {s['recall@5']}->{s['recall@5_abstain']} MRR {s['mrr@10']}->{s['mrr@10_abstain']}", flush=True)
            if floor is not None:
                calibrations[key] = {
                    "dense_floor": floor,
                    "fingerprint": spec.fingerprint(),
                    "query_fingerprint": abstain.query_fingerprint(spec),
                    # abstain_rows embeds queries with torch on CPU at dtype_cpu.
                    "backend": "torch",
                    "variant": spec.dtype_cpu,
                    "fitted_on": f"eval/questions.jsonl sha256 {sha256(questions_path())[:16]}, "
                                 f"{len(answerable)} answerable + {len(questions) - len(answerable)} unanswerable",
                    "results": str(json_path.relative_to(repo_root())) if json_path.is_relative_to(repo_root())
                    else json_path.name,
                }
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            print(f"{key}: {entry['error']}", flush=True)
        report["models"][key] = entry
    report["finished_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    json_path.write_text(json.dumps(report, indent=1) + "\n")
    md_path.write_text(abstain_markdown(report))
    print(f"wrote {json_path}\nwrote {md_path}")
    if args.write_calibration:
        path = abstain.calibration_path()
        path.write_text(abstain.calibration_toml(calibrations))
        print(f"wrote {path}")


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
    parser.add_argument("--dedupe", action="store_true",
                        help="score the API path: top SEARCH_POOL, then dedupe_adjacent to 10")
    parser.add_argument("--abstain", action="store_true",
                        help="evaluate the nothing-found rule per model (in-sample and leave-one-out)")
    parser.add_argument("--write-calibration", action="store_true",
                        help="with --abstain: store the fitted floors in search/abstain.toml")
    args = parser.parse_args()
    if args.write_calibration and not args.abstain:
        parser.error("--write-calibration needs --abstain")

    started = dt.datetime.now().astimezone()
    connection = connect(INDEX_PATH)
    n_chunks = ensure_chunks(connection)
    questions = read_jsonl(questions_path())
    if args.abstain:
        run_abstain(args, connection, questions, started)
        return
    answerable = [q for q in questions if q["relevant"]]
    rows = list(connection.execute("SELECT rowid, sermon_title, scripture, text FROM chunks ORDER BY rowid"))

    models = list(dict.fromkeys(args.models + ([REFERENCE["model"]] if REFERENCE["model"] in MODELS else [])))
    json_path, md_path = output_paths(args.results_dir, started.date().isoformat(), "dedupe" if args.dedupe else "")
    report = {
        "started_at": started.isoformat(timespec="seconds"),
        "note": args.note,
        "dedupe": args.dedupe,
        "chunks": n_chunks,
        "n_answerable": len(answerable),
        "n_unanswerable": len(questions) - len(answerable),
        "groups": question_groups(questions),
        "index_path": str(INDEX_PATH),
        "environment": environment(),
        "reference": REFERENCE,
        "excluded_models": EXCLUDED,
        "models": {},
    }
    print(f"chunks={n_chunks} questions={len(questions)} dedupe={args.dedupe} -> {json_path}", flush=True)

    bm = evaluate(Searcher(connection), questions, ("bm25",), dedupe=args.dedupe)
    report["bm25"] = {
        "summary": summarize(bm["per_query"]["bm25"]),
        "by_group": by_group(bm["per_query"]["bm25"], report["groups"]),
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
            result, latency = cpu_eval(spec, connection, questions, args.dedupe)
            entry["cpu_dtype"] = result["cpu_dtype"]
            entry["per_query"] = result["per_query"]
            entry["negative_top1"] = result["negative_top1"]
            entry["summary"] = {m: summarize(result["per_query"][m]) for m in MODES}
            entry["by_group"] = {m: by_group(result["per_query"][m], report["groups"]) for m in MODES}
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

    def versus(per_query: dict, only: list[str] | None = None) -> dict:
        ids = sorted(i for i in per_query if only is None or i in only)
        return {
            metric: paired_bootstrap([per_query[i][metric] for i in ids], [ref_pq[i][metric] for i in ids])
            for metric in METRICS
        }

    def versus_by_group(per_query: dict) -> dict:
        return {g: versus(per_query, ids) for g, ids in report["groups"].items() if any(i in per_query for i in ids)}

    if ref_pq:
        report["bm25"]["vs_reference"] = versus(report["bm25"]["per_query"])
        report["bm25"]["vs_reference_by_group"] = versus_by_group(report["bm25"]["per_query"])
        for entry in report["models"].values():
            if entry["status"] == "ok":
                entry["vs_reference"] = {m: versus(entry["per_query"][m]) for m in MODES}
                by_mode = {m: versus_by_group(entry["per_query"][m]) for m in MODES}
                entry["vs_reference_by_group"] = {g: {m: by_mode[m][g] for m in MODES} for g in by_mode[MODES[0]]}
    for entry in report["models"].values():
        entry.setdefault("vs_reference", {})

    report["finished_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    json_path.write_text(json.dumps(report, indent=1) + "\n")
    md_path.write_text(markdown(report))
    print(f"\nwrote {json_path}\nwrote {md_path}")


if __name__ == "__main__":
    main()
