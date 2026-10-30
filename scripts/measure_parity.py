"""Compare ONNX Granite embeddings to the sentence-transformers fp32 CPU path.

Bench/dev for the torch steps. The ONNX steps need only the runtime venv.
Nothing here writes ``/cache/index/wesley.sqlite``.

Torch document vectors are already in ``/cache/index/wesley-torch-cpu.sqlite``
(the CPU reference encode). This script does not recompute them. It checks
a sample, encodes the 40 eval queries, checks tokenizer ids, and encodes
ONNX in resumable batches.

Checkpoints live in ``/cache/w3-cpu/``. Each ONNX invocation encodes at most
``--max-rows`` new rows and exits, so a killed run resumes from the progress
file.

  # CPU torch venv (sentence-transformers, no CUDA):
  CUDA_VISIBLE_DEVICES="" /cache/venvs/w3-torch-cpu/bin/python scripts/measure_parity.py --step spotcheck
  CUDA_VISIBLE_DEVICES="" /cache/venvs/w3-torch-cpu/bin/python scripts/measure_parity.py --step torch-queries
  CUDA_VISIBLE_DEVICES="" /cache/venvs/w3-torch-cpu/bin/python scripts/measure_parity.py --step tokenizer

  # Runtime venv (onnxruntime, no torch):
  CUDA_VISIBLE_DEVICES="" /cache/venvs/w3-runtime/bin/python scripts/measure_parity.py --step onnx --variant fp32
  CUDA_VISIBLE_DEVICES="" /cache/venvs/w3-runtime/bin/python scripts/measure_parity.py --step onnx --variant int8
  CUDA_VISIBLE_DEVICES="" /cache/venvs/w3-runtime/bin/python scripts/measure_parity.py --step finalize
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.setdefault("HF_HOME", "/cache/huggingface")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from preached.artifacts import GRANITE_HF_ID, GRANITE_REVISION, artifact_dir  # noqa: E402
from preached.corpus import read_jsonl  # noqa: E402
from preached.embed import document_title  # noqa: E402
from preached.models import MODELS  # noqa: E402
from preached.paths import questions_path  # noqa: E402
from preached.pooling import HIDDEN_SIZE, MAX_SEQ_LENGTH  # noqa: E402

# The shipped index. Never open this for writing.
SHIPPED_INDEX = Path("/cache/index/wesley.sqlite")
# CPU fp32 document vectors plus the chunk rows whose hash matches chunks.jsonl.
TORCH_INDEX = Path("/cache/index/wesley-torch-cpu.sqlite")
CACHE = Path("/cache/w3-cpu")
INDEX_DIR = Path("/cache/index")


def _connect(path: Path) -> sqlite3.Connection:
    if path.resolve() == SHIPPED_INDEX.resolve():
        raise SystemExit(f"refusing to open the shipped index {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def load_rows() -> list[sqlite3.Row]:
    connection = sqlite3.connect(f"file:{TORCH_INDEX}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = list(
        connection.execute(
            "SELECT rowid, sermon_title, scripture, text FROM chunks ORDER BY rowid"
        )
    )
    connection.close()
    return rows


def load_torch_docs(rowids: list[int]) -> np.ndarray:
    connection = sqlite3.connect(f"file:{TORCH_INDEX}?mode=ro", uri=True)
    matrix = np.zeros((len(rowids), HIDDEN_SIZE), dtype=np.float32)
    for index, rowid in enumerate(rowids):
        blob, dim = connection.execute(
            "SELECT vector, dim FROM embeddings WHERE model = ? AND rowid = ?",
            ("granite-english-r2", rowid),
        ).fetchone()
        if int(dim) != HIDDEN_SIZE or len(blob) != HIDDEN_SIZE * 4:
            raise SystemExit(f"torch vector at rowid {rowid} is not {HIDDEN_SIZE}-d float32")
        matrix[index] = np.frombuffer(blob, dtype=np.float32)
    connection.close()
    return matrix


def queries() -> list[str]:
    return [item["query"] for item in read_jsonl(questions_path())]


def cosine_stats(reference: np.ndarray, other: np.ndarray) -> dict:
    ref = reference.astype(np.float32)
    got = other.astype(np.float32)
    ref = ref / np.maximum(np.linalg.norm(ref, axis=1, keepdims=True), 1e-12)
    got = got / np.maximum(np.linalg.norm(got, axis=1, keepdims=True), 1e-12)
    sims = np.sum(ref * got, axis=1)
    ordered = np.sort(sims)
    p01_index = max(0, int(np.ceil(0.01 * len(ordered))) - 1)
    return {
        "n": int(sims.shape[0]),
        "min": float(sims.min()),
        "mean": float(sims.mean()),
        "p01": float(ordered[p01_index]),
        "max": float(sims.max()),
    }


def _progress_path(variant: str) -> Path:
    return CACHE / f"onnx-{variant}.progress"


def _npy_path(variant: str) -> Path:
    return CACHE / f"onnx-{variant}.npy"


def _read_progress(variant: str) -> int:
    path = _progress_path(variant)
    if not path.is_file():
        return 0
    return int(path.read_text().strip() or "0")


def _write_progress(variant: str, done: int) -> None:
    path = _progress_path(variant)
    temporary = path.with_suffix(".progress.tmp")
    temporary.write_text(str(done))
    temporary.replace(path)


def step_spotcheck(batch_size: int) -> None:
    """Re-encode a few documents on CPU torch and compare to the stored matrix."""
    import torch

    if torch.cuda.is_available():
        raise SystemExit("CUDA is visible; refuse to measure on the GPU")
    torch.set_num_threads(4)
    rows = load_rows()
    rowids = [int(row["rowid"]) for row in rows]
    stored = load_torch_docs(rowids)
    shipped = sqlite3.connect(f"file:{SHIPPED_INDEX}?mode=ro", uri=True)
    cuda_sample = []
    for rowid in rowids[:8]:
        blob = shipped.execute(
            "SELECT vector FROM embeddings WHERE model = ? AND rowid = ?",
            ("granite-english-r2", rowid),
        ).fetchone()[0]
        cuda_sample.append(np.frombuffer(blob, dtype=np.float32))
    shipped.close()
    cuda = np.stack(cuda_sample)
    same_as_shipped = bool(np.array_equal(stored[:8], cuda))

    from preached.torch_embed import TorchEmbedder

    print("loading torch fp32 CPU for spot check", flush=True)
    embedder = TorchEmbedder.load("granite-english-r2", device="cpu", batch_size=batch_size)
    picks = [0, 1, 15, 16, 100, 1000, 4000, 8000]
    fresh_rows = [rows[i] for i in picks]
    titles = [document_title(row["sermon_title"], row["scripture"]) for row in fresh_rows]
    fresh = embedder.encode_documents([row["text"] for row in fresh_rows], titles)
    # Same batching the original encode used: 16-wide groups from the start.
    head = rows[:32]
    head_titles = [document_title(row["sermon_title"], row["scripture"]) for row in head]
    head_fresh = embedder.encode_documents([row["text"] for row in head], head_titles)
    embedder.close()
    report = {
        "stored_equals_shipped_cuda_first8": same_as_shipped,
        "isolated": cosine_stats(stored[picks], fresh),
        "head32": cosine_stats(stored[:32], head_fresh),
        "stored_norm_mean": float(np.linalg.norm(stored, axis=1).mean()),
        "torch_threads": torch.get_num_threads(),
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "spotcheck.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    if same_as_shipped or report["head32"]["min"] < 0.999:
        raise SystemExit("stored torch-cpu vectors do not match a fresh CPU encode")


def step_torch_queries() -> None:
    import torch

    if torch.cuda.is_available():
        raise SystemExit("CUDA is visible; refuse to measure on the GPU")
    torch.set_num_threads(4)
    from preached.torch_embed import TorchEmbedder

    text = queries()
    if len(text) != 40:
        raise SystemExit(f"expected 40 queries, found {len(text)}")
    out = CACHE / "torch-queries.npy"
    if out.is_file():
        existing = np.load(out)
        if existing.shape[0] == 40:
            print(f"torch queries already at {out}", flush=True)
            return
    print("encoding 40 queries on CPU torch", flush=True)
    embedder = TorchEmbedder.load("granite-english-r2", device="cpu", batch_size=1)
    started = time.perf_counter()
    matrix = embedder.encode_queries(text)
    embedder.close()
    CACHE.mkdir(parents=True, exist_ok=True)
    np.save(out, matrix)
    print(f"torch queries {matrix.shape} in {time.perf_counter() - started:.1f}s", flush=True)


def step_tokenizer() -> None:
    from tokenizers import Tokenizer
    from transformers import AutoTokenizer

    from preached.text_tokens import encode_texts

    rows = load_rows()
    texts = [row["text"] for row in rows] + queries()
    snapshot = Path(f"/cache/huggingface/hub/models--ibm-granite--granite-embedding-english-r2/snapshots/{GRANITE_REVISION}")
    if not snapshot.is_dir():
        from huggingface_hub import snapshot_download

        snapshot = Path(snapshot_download(GRANITE_HF_ID, revision=GRANITE_REVISION))
    hf = AutoTokenizer.from_pretrained(snapshot, trust_remote_code=False)
    rust = Tokenizer.from_file(str(artifact_dir() / "tokenizer.json"))
    mismatches = 0
    examples = []
    started = time.perf_counter()
    for index, text in enumerate(texts):
        hf_out = hf(
            text,
            truncation=True,
            max_length=MAX_SEQ_LENGTH,
            padding=False,
            return_attention_mask=True,
        )
        rust_out = encode_texts(rust, [text], MAX_SEQ_LENGTH)
        ids = rust_out.input_ids[0].tolist()
        mask = rust_out.attention_mask[0].tolist()
        if ids != list(hf_out["input_ids"]) or mask != list(hf_out["attention_mask"]):
            mismatches += 1
            if len(examples) < 8:
                examples.append(
                    {
                        "index": index,
                        "hf_len": len(hf_out["input_ids"]),
                        "rust_len": len(ids),
                        "preview": text[:80],
                    }
                )
        if index and index % 1000 == 0:
            print(f"tokenizer {index}/{len(texts)}", flush=True)
    report = {
        "checked": len(texts),
        "mismatches": mismatches,
        "examples": examples,
        "seconds": round(time.perf_counter() - started, 1),
        "revision": GRANITE_REVISION,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "tokenizer.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    if mismatches:
        raise SystemExit(f"tokenizer mismatches: {mismatches}")


def step_onnx(variant: str, batch_size: int, threads: int, max_rows: int) -> None:
    from preached.onnx_embed import OnnxEmbedder

    rows = load_rows()
    total = len(rows)
    CACHE.mkdir(parents=True, exist_ok=True)
    path = _npy_path(variant)
    if path.is_file() and _read_progress(variant) > 0:
        matrix = np.lib.format.open_memmap(path, mode="r+")
        if matrix.shape != (total, HIDDEN_SIZE):
            raise SystemExit(f"{path} shape {matrix.shape} != {(total, HIDDEN_SIZE)}")
    else:
        matrix = np.lib.format.open_memmap(path, mode="w+", dtype=np.float32, shape=(total, HIDDEN_SIZE))
        _write_progress(variant, 0)
    done = _read_progress(variant)
    if done >= total:
        print(f"onnx {variant} already complete ({done}/{total})", flush=True)
        return
    limit = min(total, done + max(1, max_rows))
    print(f"loading onnx {variant} threads={threads} batch={batch_size} from {done}", flush=True)
    embedder = OnnxEmbedder.load(variant=variant, batch_size=batch_size, ort_threads=threads)
    started = time.perf_counter()
    cursor = done
    while cursor < limit:
        batch = rows[cursor : cursor + batch_size]
        titles = [document_title(row["sermon_title"], row["scripture"]) for row in batch]
        vectors = embedder.encode_documents([row["text"] for row in batch], titles)
        matrix[cursor : cursor + len(batch)] = vectors
        matrix.flush()
        cursor += len(batch)
        _write_progress(variant, cursor)
        elapsed = time.perf_counter() - started
        rate = (cursor - done) / elapsed if elapsed else 0
        print(
            f"onnx-{variant} {cursor}/{total} batch_elapsed={elapsed:.0f}s ({rate:.1f} chunks/s)",
            flush=True,
        )
    if cursor < total:
        print(f"onnx-{variant} paused at {cursor}/{total}; rerun to resume", flush=True)
    else:
        print(f"onnx-{variant} complete", flush=True)


def _copy_index(source: Path, dest: Path) -> None:
    if dest.resolve() == SHIPPED_INDEX.resolve():
        raise SystemExit("refusing to overwrite the shipped index")
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    src.backup(dst)
    dst.commit()
    src.close()
    dst.close()


def step_finalize() -> None:
    from preached.store import connect, save_embedding_info, write_embeddings

    rows = load_rows()
    rowids = [int(row["rowid"]) for row in rows]
    torch_docs = load_torch_docs(rowids)
    torch_queries = np.load(CACHE / "torch-queries.npy")
    spec = MODELS["granite-english-r2"]
    report = {
        "revision": GRANITE_REVISION,
        "hf_id": GRANITE_HF_ID,
        "tokenizer": json.loads((CACHE / "tokenizer.json").read_text()),
        "spotcheck": json.loads((CACHE / "spotcheck.json").read_text()),
        "reference_index": str(TORCH_INDEX),
        "variants": {},
    }
    for variant in ("fp32", "int8"):
        if _read_progress(variant) != len(rows):
            raise SystemExit(f"onnx {variant} is not complete")
        docs = np.load(_npy_path(variant))
        # Queries are encoded here so finalize stays on the runtime venv.
        from preached.onnx_embed import OnnxEmbedder

        embedder = OnnxEmbedder.load(variant=variant, batch_size=16, ort_threads=4)
        query_vectors = embedder.encode_queries(queries())
        stats = {
            "threads": embedder.threads,
            "documents": cosine_stats(torch_docs, docs),
            "queries": cosine_stats(torch_queries, query_vectors),
        }
        report["variants"][variant] = stats
        dest = INDEX_DIR / f"wesley-onnx-{variant}.sqlite"
        print(f"writing {dest}", flush=True)
        _copy_index(TORCH_INDEX, dest)
        writable = connect(dest)
        write_embeddings(writable, "granite-english-r2", rowids, docs)
        save_embedding_info(
            writable,
            "granite-english-r2",
            {
                "fingerprint": spec.fingerprint(),
                "backend": "onnx",
                "variant": variant,
                "device": "cpu",
                "dtype": variant,
                "ort_intra_op_threads": embedder.threads,
            },
        )
        writable.close()
        print(json.dumps(stats, indent=2), flush=True)
        if variant == "fp32" and stats["documents"]["min"] < 0.999:
            raise SystemExit("fp32 ONNX document min cosine is below 0.999")
        if variant == "fp32" and stats["queries"]["min"] < 0.999:
            raise SystemExit("fp32 ONNX query min cosine is below 0.999")
    out = ROOT / "reports" / "w3_parity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    (CACHE / "parity.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {out}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--step",
        required=True,
        choices=("spotcheck", "torch-queries", "tokenizer", "onnx", "finalize"),
    )
    parser.add_argument("--variant", choices=("fp32", "int8"), default="fp32")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--ort-threads", type=int, default=4)
    parser.add_argument(
        "--max-rows",
        type=int,
        default=1024,
        help="ONNX rows to encode this invocation before exiting",
    )
    args = parser.parse_args()
    if args.step == "spotcheck":
        step_spotcheck(args.batch_size)
    elif args.step == "torch-queries":
        step_torch_queries()
    elif args.step == "tokenizer":
        step_tokenizer()
    elif args.step == "onnx":
        step_onnx(args.variant, args.batch_size, args.ort_threads, args.max_rows)
    else:
        step_finalize()


if __name__ == "__main__":
    main()
