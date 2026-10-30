"""Sentence-transformers embedder. Torch is imported only when this loads.

This is the control path and the GPU benchmark path. The server does not
import this module unless ``--embed-backend torch`` is asked for.
"""

from __future__ import annotations

import numpy as np

from preached.models import MODELS, ModelSpec


class TorchEmbedder:
    def __init__(self, loaded, batch_size: int) -> None:
        self.loaded = loaded
        self.spec: ModelSpec = loaded.spec
        self.batch_size = batch_size
        self.backend = "torch"
        self.variant = loaded.dtype

    @classmethod
    def load(
        cls,
        model_key: str,
        *,
        device: str = "cpu",
        batch_size: int = 8,
    ) -> "TorchEmbedder":
        from preached.embed import load_model

        spec = MODELS[model_key]
        loaded = load_model(spec, device=device, batch_size=batch_size)
        return cls(loaded, batch_size)

    def encode_queries(self, queries: list[str]) -> np.ndarray:
        from preached.embed import encode_query

        if not queries:
            return np.zeros((0, 0), dtype=np.float32)
        rows = [encode_query(self.loaded, query) for query in queries]
        return np.stack(rows, axis=0).astype(np.float32)

    def encode_documents(self, texts: list[str], titles: list[str] | None = None) -> np.ndarray:
        from preached.embed import encode_documents

        if titles is None:
            titles = [""] * len(texts)
        return encode_documents(self.loaded, titles, texts)

    def close(self) -> None:
        from preached.embed import unload

        unload(self.loaded)
