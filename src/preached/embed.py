"""Load one embedding model and encode queries and passages.

Everything model-specific (revision, dtype, prefixes, output size) comes from
search/models.toml through ModelSpec. Prefixes are passed to
SentenceTransformer.encode(prompt=...) so the library handles them the same
way as a named prompt. A document_template that needs the sermon title is
formatted into the text itself. Batch size drops on CUDA OOM.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass

import numpy as np

from preached import env  # noqa: F401  (sets HF_HOME before the heavy imports)
from preached.models import ModelSpec, is_question

# torch and sentence_transformers are imported lazily so BM25-only commands stay light.


@dataclass
class LoadedModel:
    spec: ModelSpec
    model: object
    device: str
    batch_size: int
    dtype: str


def _torch():
    import torch

    return torch


def resolve_dtype(spec: ModelSpec, device: str) -> str:
    """The dtype actually used. bf16 falls back to fp32 when the GPU lacks it."""
    wanted = spec.dtype_cpu if device == "cpu" else spec.dtype_gpu
    if wanted == "bf16" and device != "cpu":
        torch = _torch()
        if not (torch.cuda.is_available() and torch.cuda.is_bf16_supported()):
            return "fp32"
    return wanted


def _torch_dtype(name: str):
    torch = _torch()
    return {"fp32": torch.float32, "bf16": torch.bfloat16, "fp16": torch.float16}[name]


def load_model(spec: ModelSpec, device: str, batch_size: int) -> LoadedModel:
    import torch
    from sentence_transformers import SentenceTransformer

    dtype = resolve_dtype(spec, device)
    kwargs = {
        "device": device,
        "revision": spec.revision,
        "model_kwargs": {"torch_dtype": _torch_dtype(dtype)},
        "trust_remote_code": spec.trust_remote_code,
    }
    if spec.drop_config:
        kwargs["config_kwargs"] = {name: None for name in spec.drop_config}
    model = SentenceTransformer(spec.hf_id, **kwargs)
    model.eval()
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    return LoadedModel(spec=spec, model=model, device=device, batch_size=batch_size, dtype=dtype)


def unload(loaded: LoadedModel) -> None:
    import torch

    del loaded.model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def format_documents(spec: ModelSpec, titles: list[str], texts: list[str]) -> tuple[list[str], str]:
    """Return (texts, prompt). A template wins over a plain prefix."""
    if spec.document_template:
        return [spec.document_template.format(title=t, text=x) for t, x in zip(titles, texts)], ""
    return list(texts), spec.document_prefix


def format_query(spec: ModelSpec, query: str) -> tuple[str, str]:
    return query, spec.query_prefix(keyword=not is_question(query))


def describe_prompts(spec: ModelSpec) -> dict:
    """Literal strings the model sees, for the results file."""
    q, qp = format_query(spec, "What did Wesley say about worry?")
    k, kp = format_query(spec, "Christian perfection")
    d, dp = format_documents(spec, ["Salvation by Faith (Eph 2:8)"], ["By grace are ye saved."])
    return {"question": qp + q, "keyword": kp + k, "document": dp + d[0]}


def _normalize(matrix: np.ndarray, dim: int | None) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if dim is not None and matrix.shape[1] > dim:
        # Matryoshka truncation: keep leading dims, then re-normalize.
        matrix = matrix[:, :dim]
    if not np.isfinite(matrix).all():
        raise RuntimeError("embeddings contain NaN or inf; refusing to index them")
    norms = np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    return (matrix / norms).astype(np.float32)


def _encode(loaded: LoadedModel, texts: list[str], prompt: str, batch_size: int) -> np.ndarray:
    kwargs = {"batch_size": batch_size, "show_progress_bar": False, "convert_to_numpy": True}
    if prompt:
        kwargs["prompt"] = prompt
    matrix = loaded.model.encode(texts, **kwargs)
    return _normalize(matrix, loaded.spec.dim)


def encode_documents(loaded: LoadedModel, titles: list[str], texts: list[str]) -> np.ndarray:
    formatted, prompt = format_documents(loaded.spec, titles, texts)
    batch = loaded.batch_size
    while True:
        try:
            return _encode(loaded, formatted, prompt, batch)
        except RuntimeError as exc:
            message = str(exc).lower()
            oom = "out of memory" in message or ("cuda" in message and "memory" in message)
            if not oom or batch == 1:
                raise
            _torch().cuda.empty_cache()
            batch = max(1, batch // 2)
            loaded.batch_size = batch


def encode_query(loaded: LoadedModel, query: str) -> np.ndarray:
    text, prompt = format_query(loaded.spec, query)
    return _encode(loaded, [text], prompt, batch_size=1)[0]


def document_title(sermon_title: str, scripture: str | None) -> str:
    if scripture:
        return f"{sermon_title} ({scripture})"
    return sermon_title
