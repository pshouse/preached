"""Load one embedding model and encode queries and passages.

GPU inference stays in fp16, except EmbeddingGemma 2, whose card says fp16
overflows and bf16 is required. Query latency is measured with a separate
CPU load (float32). Batch size drops on CUDA OOM.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass

import numpy as np

from preached import env  # noqa: F401  (sets HF_HOME before the heavy imports)
from preached.models import ModelSpec, is_question

# Imported lazily by load_model so BM25-only commands do not import torch.


@dataclass
class LoadedModel:
    spec: ModelSpec
    model: object
    device: str
    batch_size: int
    prompts: dict


def _torch():
    import torch

    return torch


def _dtype(spec: ModelSpec, device: str):
    torch = _torch()
    if device == "cpu":
        # The EmbeddingGemma 2 card says to use float32 on CPU, not bf16/fp16.
        return torch.float32
    if spec.gpu_dtype == "bf16":
        if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
            return torch.bfloat16
        return torch.float32
    if spec.gpu_dtype == "fp16":
        return torch.float16
    return torch.float32


def load_model(spec: ModelSpec, device: str, batch_size: int) -> LoadedModel:
    import torch
    from sentence_transformers import SentenceTransformer

    kwargs = {
        "device": device,
        "model_kwargs": {"torch_dtype": _dtype(spec, device)},
        "trust_remote_code": spec.trust_remote_code,
    }
    if spec.config_kwargs:
        kwargs["config_kwargs"] = dict(spec.config_kwargs)
    try:
        model = SentenceTransformer(spec.hf_id, **kwargs)
    except TypeError:
        # Older SentenceTransformer builds reject config_kwargs.
        kwargs.pop("config_kwargs", None)
        model = SentenceTransformer(spec.hf_id, **kwargs)
    model.eval()
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    prompts = dict(getattr(model, "prompts", {}) or {})
    return LoadedModel(spec=spec, model=model, device=device, batch_size=batch_size, prompts=prompts)


def unload(loaded: LoadedModel) -> None:
    import torch

    del loaded.model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _has_prompt(loaded: LoadedModel, name: str | None) -> bool:
    return bool(name) and name in loaded.prompts


def _prompt_matches(loaded: LoadedModel, name: str | None, expected: str) -> bool:
    """Use a built-in prompt only when it is the prefix the model card specifies."""
    if not _has_prompt(loaded, name):
        return False
    if not expected:
        return True
    actual = str(loaded.prompts[name]).strip()
    wanted = expected.strip()
    return actual.startswith(wanted[:32]) or wanted.startswith(actual[:32])


def format_documents(loaded: LoadedModel, titles: list[str], texts: list[str]) -> tuple[list[str], str | None]:
    spec = loaded.spec
    if spec.document_template:
        formatted = [
            spec.document_template.format(title=title, text=text)
            for title, text in zip(titles, texts)
        ]
        return formatted, None
    if _prompt_matches(loaded, spec.document_prompt, spec.document_prefix):
        return list(texts), spec.document_prompt
    if spec.document_prefix:
        return [spec.document_prefix + text for text in texts], None
    return list(texts), None


def format_query(loaded: LoadedModel, query: str) -> tuple[str, str | None]:
    spec = loaded.spec
    keyword = not is_question(query)
    prompt_name = spec.keyword_prompt if keyword else spec.query_prompt
    prefix = spec.keyword_prefix if keyword and spec.keyword_prefix else spec.query_prefix
    if _prompt_matches(loaded, prompt_name, prefix):
        return query, prompt_name
    if prefix:
        return prefix + query, None
    return query, None


def describe_prompts(loaded: LoadedModel) -> dict:
    question, question_prompt = format_query(loaded, "What did Wesley say about worry?")
    keyword, keyword_prompt = format_query(loaded, "Christian perfection")
    documents, document_prompt = format_documents(loaded, ["Salvation by Faith (Eph 2:8)"], ["By grace are ye saved."])
    return {
        "repo_prompts": {key: value for key, value in loaded.prompts.items()},
        "question_prompt_name": question_prompt,
        "question_example": question[:180],
        "keyword_prompt_name": keyword_prompt,
        "keyword_example": keyword[:180],
        "document_prompt_name": document_prompt,
        "document_example": documents[0][:220],
    }


def _normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if not np.isfinite(matrix).all():
        raise RuntimeError("embeddings contain NaN or inf; refusing to index them")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return (matrix / norms).astype(np.float32)


def _encode(loaded: LoadedModel, texts: list[str], prompt_name: str | None, batch_size: int) -> np.ndarray:
    kwargs = {
        "batch_size": batch_size,
        "normalize_embeddings": True,
        "show_progress_bar": False,
        "convert_to_numpy": True,
    }
    if prompt_name:
        kwargs["prompt_name"] = prompt_name
    matrix = loaded.model.encode(texts, **kwargs)
    return _normalize(matrix)


def encode_documents(loaded: LoadedModel, titles: list[str], texts: list[str]) -> np.ndarray:
    formatted, prompt_name = format_documents(loaded, titles, texts)
    batch = loaded.batch_size
    while True:
        try:
            return _encode(loaded, formatted, prompt_name, batch)
        except RuntimeError as exc:
            message = str(exc).lower()
            oom = "out of memory" in message or "cuda" in message and "memory" in message
            if not oom or batch == 1:
                raise
            _torch().cuda.empty_cache()
            batch = max(1, batch // 2)
            loaded.batch_size = batch


def encode_query(loaded: LoadedModel, query: str) -> np.ndarray:
    text, prompt_name = format_query(loaded, query)
    matrix = _encode(loaded, [text], prompt_name, batch_size=1)
    return matrix[0]


def document_title(sermon_title: str, scripture: str | None) -> str:
    if scripture:
        return f"{sermon_title} ({scripture})"
    return sermon_title
