"""Set cache env vars before Hugging Face or SentenceTransformer import.

Everything large lives under PREACHED_CACHE (default /cache, the sandbox mount).
"""

from __future__ import annotations

import os

_CACHE = os.environ.get("PREACHED_CACHE", "/cache")
os.environ.setdefault("HF_HOME", f"{_CACHE}/huggingface")
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", f"{_CACHE}/huggingface/hub")
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", f"{_CACHE}/huggingface/sentence-transformers")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# The 3060 is shared with Whisper. Avoid extra allocations.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
