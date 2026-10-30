"""Granite English R2 on ONNX Runtime, CPU only.

No torch import. Pooling and L2 normalization run in numpy
(``preached.pooling``). A bad or missing artifact raises ArtifactError
so the server can fall back to BM25.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from preached.artifacts import (
    GRANITE_MODEL_KEY,
    VARIANT_FILES,
    ArtifactError,
    artifact_dir,
    resolve_threads,
    verify_manifest,
)
from preached.models import MODELS, ModelSpec
from preached.pooling import HIDDEN_SIZE, MAX_SEQ_LENGTH, pool_cls
from preached.prefixes import prepare_documents, prepare_query
from preached.text_tokens import encode_texts


class OnnxEmbedder:
    """``encode_queries`` / ``encode_documents`` -> float32, L2-normalized."""

    def __init__(
        self,
        spec: ModelSpec,
        session,
        tokenizer,
        *,
        variant: str,
        max_length: int,
        hidden_size: int,
        batch_size: int,
        threads: int,
    ) -> None:
        self.spec = spec
        self.session = session
        self.tokenizer = tokenizer
        self.variant = variant
        self.max_length = max_length
        self.hidden_size = hidden_size
        self.batch_size = max(1, batch_size)
        self.threads = threads
        self.backend = "onnx"

    @classmethod
    def load(
        cls,
        model_key: str = GRANITE_MODEL_KEY,
        *,
        variant: str | None = None,
        ort_threads: int | None = None,
        batch_size: int = 16,
        directory: Path | None = None,
    ) -> "OnnxEmbedder":
        if model_key != GRANITE_MODEL_KEY:
            raise ArtifactError(f"onnx backend only supports {GRANITE_MODEL_KEY}")
        spec = MODELS[model_key]
        folder = directory or artifact_dir()
        verified = verify_manifest(folder, variant=variant)
        manifest = verified.manifest
        chosen = verified.variant
        # The file name is the code pin, not the manifest's variants map.
        filename = VARIANT_FILES[chosen]
        threads = resolve_threads(ort_threads)
        max_length = int(manifest.get("max_seq_length") or MAX_SEQ_LENGTH)
        hidden_size = int(manifest.get("hidden_size") or HIDDEN_SIZE)
        if max_length != MAX_SEQ_LENGTH or hidden_size != HIDDEN_SIZE:
            raise ArtifactError(
                f"ONNX manifest shape {hidden_size}x{max_length} does not match Granite"
            )

        # Imported here so BM25-only commands and the import guard stay light.
        # The session and the tokenizer are built from the bytes just hashed,
        # not from a second open of the path.
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.log_severity_level = 3
        session = ort.InferenceSession(
            verified.files[filename],
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        input_names = {item.name for item in session.get_inputs()}
        if input_names != {"input_ids", "attention_mask"}:
            raise ArtifactError(f"ONNX inputs {sorted(input_names)} are not input_ids and attention_mask")
        if session.get_providers() != ["CPUExecutionProvider"]:
            # A GPU build of onnxruntime must not pick CUDA. CPUExecutionProvider
            # is requested alone; anything else means the session ignored that.
            raise ArtifactError(f"ONNX session providers {session.get_providers()} are not CPU")
        tokenizer = Tokenizer.from_buffer(verified.files["tokenizer.json"])
        embedder = cls(
            spec,
            session,
            tokenizer,
            variant=chosen,
            max_length=max_length,
            hidden_size=hidden_size,
            batch_size=batch_size,
            threads=threads,
        )
        embedder.output_name = session.get_outputs()[0].name
        return embedder

    def encode_queries(self, queries: list[str]) -> np.ndarray:
        texts = [prepare_query(self.spec, query) for query in queries]
        return self._encode(texts)

    def encode_documents(self, texts: list[str], titles: list[str] | None = None) -> np.ndarray:
        prepared = prepare_documents(self.spec, texts, titles)
        return self._encode(prepared)

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.hidden_size), dtype=np.float32)
        parts = []
        for start in range(0, len(texts), self.batch_size):
            parts.append(self._encode_batch(texts[start : start + self.batch_size]))
        if len(parts) == 1:
            return parts[0]
        return np.concatenate(parts, axis=0)

    def _encode_batch(self, texts: list[str]) -> np.ndarray:
        batch = encode_texts(self.tokenizer, texts, self.max_length)
        hidden = self.session.run(
            [self.output_name],
            {"input_ids": batch.input_ids, "attention_mask": batch.attention_mask},
        )[0]
        pooled = pool_cls(hidden, batch.attention_mask)
        if pooled.shape != (len(texts), self.hidden_size):
            raise RuntimeError(
                f"ONNX embedding shape {pooled.shape} != {(len(texts), self.hidden_size)}"
            )
        return pooled
