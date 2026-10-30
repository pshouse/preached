"""Batch tokenize with the ``tokenizers`` package, no transformers.

Granite ships a ``tokenizer.json`` whose post-processor adds ``[CLS]`` and
``[SEP]``. Truncation counts those specials toward ``max_length``, and
padding is on the right with the ``[PAD]`` id. The attention mask is 1 on
real tokens and 0 on padding.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TokenBatch:
    input_ids: np.ndarray
    attention_mask: np.ndarray


def encode_texts(tokenizer, texts: list[str], max_length: int) -> TokenBatch:
    """Truncate to ``max_length`` (including specials) and pad the batch."""
    if max_length < 2:
        raise ValueError("max_length must leave room for special tokens")
    if not texts:
        raise ValueError("empty batch")
    pad_id = tokenizer.token_to_id("[PAD]")
    if pad_id is None:
        raise RuntimeError("tokenizer has no [PAD] token")
    tokenizer.no_padding()
    tokenizer.enable_truncation(max_length=max_length)
    tokenizer.enable_padding(pad_id=int(pad_id), pad_token="[PAD]")
    encoded = tokenizer.encode_batch([text if isinstance(text, str) else str(text) for text in texts])
    ids = np.asarray([item.ids for item in encoded], dtype=np.int64)
    mask = np.asarray([item.attention_mask for item in encoded], dtype=np.int64)
    if ids.shape != mask.shape:
        raise RuntimeError("tokenizer ids and mask differ in shape")
    if ids.shape[0] != len(texts) or ids.shape[1] > max_length:
        raise RuntimeError("tokenizer exceeded max_length or dropped a row")
    return TokenBatch(input_ids=ids, attention_mask=mask)
