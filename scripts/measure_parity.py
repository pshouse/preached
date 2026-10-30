"""Compare ONNX Granite embeddings to the sentence-transformers fp32 CPU path.

Bench/dev only. Writes nothing into wesley.sqlite. Copies of the index,
with embeddings replaced, go under /cache/index/.

  CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/measure_parity.py

Prints JSON: tokenizer mismatches, and cosine min/mean/p01 for documents
and the 40 eval queries, fp32 and int8 against the torch reference.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.setdefault("HF_HOME", "/cache/huggingface")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.artifacts import GRANITE_HF_ID, GRANITE_REVISION, artifact_dir  # noqa: E402
from preached.corpus import read_jsonl  # noqa: E402
from preached.embed import document_title  # noqa: E402
from preached.models import MODELS  # noqa: E402
from preached.onnx_embed import OnnxEmbedder  # noqa: E402
from preached.paths import INDEX_PATH, questions_path  # noqa: E402
from preached.pooling import MAX_SEQ_LENGTH  # noqa: E402
from preached.store import connect, save_embedding_info, write_embeddings  # noqa: E402
from preached.text_tokens import encode_texts  # noqa: E402
from preached.torch_embed import TorchEmbedder  # noqa: E402

import numpy as np  # noqa: E402


def cosine_stats(reference: np.ndarray, other: np.ndarray) -> dict:
    sims = np.sum(reference.astype(np.float32) * other.astype(np.float32), axis=1)
    ordered = np.sort(sims)
    p01_index = max(0, int(np.ceil(0.01 * len(ordered))) - 1)
    return {
        "n": int(sims.shape[0]),
        "min": float(sims.min()),
        "mean": float(sims.mean()),
        "p01": float(ordered[p01_index]),
        "max": float(sims.max()),
    }


def copy_index(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    src.backup(dst)
    dst.commit()
    src.close()
    dst.close()


def tokenizer_mismatches(snapshot: Path, texts: list[str]) -> dict:
    from tokenizers import Tokenizer
    from transformers import AutoTokenizer

    hf = AutoTokenizer.from_pretrained(snapshot, trust_remote_code=False)
    rust = Tokenizer.from_file(str(artifact_dir() / "tokenizer.json"))
    mismatches = 0
    examples = []
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
        # A single row is not padded, so the rust row is the full sequence.
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
    return {"checked": len(texts), "mismatches": mismatches, "examples": examples}


def encode_rows(embedder, rows, batch_label: str, chunk: int = 128) -> np.ndarray:
    parts = []
    started = time.perf_counter()
    total = len(rows)
    for start in range(0, total, chunk):
        batch = rows[start : start + chunk]
        titles = [document_title(row["sermon_title"], row["scripture"]) for row in batch]
        texts = [row["text"] for row in batch]
        parts.append(embedder.encode_documents(texts, titles))
        done = min(start + chunk, total)
        elapsed = time.perf_counter() - started
        print(
            f"{batch_label} {done}/{total} in {elapsed:.0f}s "
            f"({done / elapsed:.1f} chunks/s)",
            flush=True,
        )
    matrix = parts[0] if len(parts) == 1 else np.concatenate(parts, axis=0)
    elapsed = time.perf_counter() - started
    print(
        f"{batch_label} documents {matrix.shape} in {elapsed:.1f}s "
        f"({total / elapsed:.1f} chunks/s)",
        flush=True,
    )
    return matrix


def store_vectors(source: Path, dest: Path, rowids: list[int], matrix: np.ndarray, info: dict) -> None:
    copy_index(source, dest)
    writable = connect(dest)
    write_embeddings(writable, "granite-english-r2", rowids, matrix)
    save_embedding_info(writable, "granite-english-r2", info)
    writable.close()
    print(f"wrote {dest}", flush=True)


def main() -> None:
    import torch
    from huggingface_hub import snapshot_download

    if torch.cuda.is_available():
        raise SystemExit("CUDA is visible; refuse to measure on the GPU")
    source = INDEX_PATH
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = list(connection.execute("SELECT rowid, sermon_title, scripture, text FROM chunks ORDER BY rowid"))
    connection.close()
    questions = read_jsonl(questions_path())
    queries = [item["query"] for item in questions]
    print(f"chunks={len(rows)} queries={len(queries)}", flush=True)

    snapshot = Path(snapshot_download(GRANITE_HF_ID, revision=GRANITE_REVISION))
    token_report = tokenizer_mismatches(snapshot, [row["text"] for row in rows] + queries)
    print("tokenizer", json.dumps(token_report), flush=True)

    spec = MODELS["granite-english-r2"]
    rowids = [int(row["rowid"]) for row in rows]
    print("loading torch fp32 CPU reference", flush=True)
    torch_embedder = TorchEmbedder.load("granite-english-r2", device="cpu", batch_size=16)
    torch_docs = encode_rows(torch_embedder, rows, "torch")
    torch_queries = torch_embedder.encode_queries(queries)
    torch_embedder.close()
    store_vectors(
        source,
        source.parent / "wesley-torch-cpu.sqlite",
        rowids,
        torch_docs,
        {
            "fingerprint": spec.fingerprint(),
            "backend": "torch",
            "variant": "fp32",
            "device": "cpu",
            "dtype": "fp32",
        },
    )

    report = {"revision": GRANITE_REVISION, "tokenizer": token_report, "variants": {}}
    index_dir = source.parent
    for variant in ("fp32", "int8"):
        print(f"loading onnx {variant}", flush=True)
        embedder = OnnxEmbedder.load(variant=variant, batch_size=16, ort_threads=4)
        docs = encode_rows(embedder, rows, f"onnx-{variant}")
        query_vectors = embedder.encode_queries(queries)
        report["variants"][variant] = {
            "threads": embedder.threads,
            "documents": cosine_stats(torch_docs, docs),
            "queries": cosine_stats(torch_queries, query_vectors),
        }
        dest = index_dir / f"wesley-onnx-{variant}.sqlite"
        store_vectors(
            source,
            dest,
            rowids,
            docs,
            {
                "fingerprint": spec.fingerprint(),
                "backend": "onnx",
                "variant": variant,
                "device": "cpu",
                "dtype": variant,
                "ort_intra_op_threads": embedder.threads,
            },
        )
        print(json.dumps(report["variants"][variant], indent=2), flush=True)

    out = ROOT / "reports" / "w3_parity.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
