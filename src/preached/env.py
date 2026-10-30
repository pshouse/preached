"""Set cache env vars before Hugging Face or SentenceTransformer import."""

from __future__ import annotations

import os

os.environ.setdefault("HF_HOME", "/cache/huggingface")
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/cache/huggingface/hub")
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", "/cache/huggingface/sentence-transformers")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# The 3060 is shared with Whisper. Stay quiet about TF32 and avoid extra allocs.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
