"""Select the query embedder. Torch stays behind the torch backend.

``load_embedder`` returns an object with ``encode_queries(list[str])`` and
``encode_documents(list[str], titles=None)``. Both return float32
L2-normalized vectors. The default is ONNX so the server can run without
torch installed.
"""

from __future__ import annotations

import os

BACKENDS = ("onnx", "torch")
DEFAULT_EMBED_BACKEND = "onnx"


def normalize_backend(name: str | None) -> str:
    choice = (name or os.environ.get("PREACHED_EMBED_BACKEND") or DEFAULT_EMBED_BACKEND).strip().lower()
    if choice not in BACKENDS:
        raise ValueError(f"embed backend must be one of {', '.join(BACKENDS)}")
    return choice


def load_embedder(
    model_key: str,
    backend: str | None = None,
    *,
    variant: str | None = None,
    ort_threads: int | None = None,
    device: str = "cpu",
    batch_size: int = 16,
):
    """Load the named backend. Raises if the weights cannot be used.

    The caller (the server) turns that into the BM25 fallback. This function
    does not catch it, and it does not import torch when ``backend`` is onnx.
    eval_only models are refused here; search/bench.py loads them through
    ``preached.embed.load_model`` directly.
    """
    from preached.models import MODELS

    if model_key in MODELS and MODELS[model_key].eval_only:
        raise ValueError(f"model {model_key!r} is eval-only and cannot be loaded for the product")
    choice = normalize_backend(backend)
    if choice == "onnx":
        from preached.onnx_embed import OnnxEmbedder

        return OnnxEmbedder.load(
            model_key,
            variant=variant,
            ort_threads=ort_threads,
            batch_size=batch_size,
        )
    from preached.torch_embed import TorchEmbedder

    return TorchEmbedder.load(model_key, device=device, batch_size=max(1, batch_size))
