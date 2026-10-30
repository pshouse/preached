"""CLS pooling and L2 normalization for Granite English R2.

The sentence-transformers snapshot pools with the CLS token
(``1_Pooling/config.json``: ``pooling_mode_cls_token`` true, mean/max off)
and then L2-normalizes. CLS is the first token whose attention mask is 1,
which is index 0 when the batch is right-padded. This matches
``sentence_transformers`` pooling mode ``"cls"``.
"""

from __future__ import annotations

import numpy as np

# ibm-granite/granite-embedding-english-r2 @ 47ea694b257b703fee9253d75c2b1f2985180498
POOLING_MODE = "cls"
MAX_SEQ_LENGTH = 8192
HIDDEN_SIZE = 768


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 norm. Refuses NaN or inf, same as the torch encode path."""
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2:
        raise ValueError("expected a vector or a batch of vectors")
    if not np.isfinite(matrix).all():
        raise RuntimeError("embeddings contain NaN or inf; refusing to index them")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return (matrix / norms).astype(np.float32)


def pool_cls(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Pool each row to its first real token and L2-normalize.

    ``token_embeddings`` is ``(batch, seq, hidden)``. ``attention_mask`` is
    ``(batch, seq)`` with 1 on tokens to keep. An all-pad row falls back to
    position 0, which is what ``argmax`` returns.
    """
    hidden = np.asarray(token_embeddings)
    mask = np.asarray(attention_mask)
    if hidden.ndim != 3:
        raise ValueError("token embeddings must be (batch, seq, hidden)")
    if mask.shape[:2] != hidden.shape[:2]:
        raise ValueError("attention mask does not match token embeddings")
    first = np.argmax(mask, axis=1)
    batch = np.arange(hidden.shape[0])
    pooled = hidden[batch, first]
    return l2_normalize(pooled)
