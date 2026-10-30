"""Embedding models allowed for this benchmark, and the ones that are not.

AGENTS.md bars models developed in the PRC and fine-tunes or distillations
of those models. When a base model is unclear, the model is excluded.

Document strings below are the prefixes the model card tells us to use.
Query prompts that SentenceTransformers already ships are preferred at load
time when they match the card, so we do not double-prefix.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    key: str
    hf_id: str
    license: str
    developer: str
    lineage: str
    # SentenceTransformers prompt name for a natural-language question.
    query_prompt: str | None = None
    # Prompt name for a short keyword query. Falls back to query_prompt.
    keyword_prompt: str | None = None
    # Used when the repo has no prompt of that name.
    query_prefix: str = ""
    keyword_prefix: str = ""
    document_prefix: str = ""
    # When set, documents are formatted here and encoded with no extra prompt.
    # EmbeddingGemma's "Document" prompt forces "title: none", so titles are
    # applied by hand. Other models leave this empty and use document_prompt.
    document_template: str = ""
    document_prompt: str | None = None
    trust_remote_code: bool = False
    # "bf16" (EmbeddingGemma 2 card: fp16 overflows), "fp16", or "fp32".
    gpu_dtype: str = "fp16"
    config_kwargs: dict = field(default_factory=dict)
    params: str = ""
    gated: bool = False


# Order is the benchmark order.
MODELS: dict[str, ModelSpec] = {
    "embeddinggemma-2": ModelSpec(
        key="embeddinggemma-2",
        hf_id="google/embeddinggemma-2",
        license="Apache-2.0",
        developer="Google DeepMind",
        lineage=(
            "Gemma 4 text backbone from Google DeepMind (released Oct 2026). "
            "Not a fine-tune of a PRC model. Text-only load is about 270M "
            "of the 740M multimodal checkpoint."
        ),
        query_prompt="QuestionAnswering",
        keyword_prompt="SearchQuery",
        query_prefix="task: question answering | query: ",
        keyword_prefix="task: search result | query: ",
        document_template="title: {title} | text: {text}",
        gpu_dtype="bf16",
        config_kwargs={"vision_config": None, "audio_config": None},
        params="270M text / 740M full",
    ),
    "embeddinggemma-300m": ModelSpec(
        key="embeddinggemma-300m",
        hf_id="google/embeddinggemma-300m",
        license="Gemma license (gated weights)",
        developer="Google DeepMind",
        lineage="EmbeddingGemma (2025), Google. Predecessor of EmbeddingGemma 2.",
        query_prompt="query",
        keyword_prompt="query",
        query_prefix="task: search result | query: ",
        document_prefix="title: none | text: ",
        document_template="title: {title} | text: {text}",
        gpu_dtype="bf16",
        params="300M",
        gated=True,
    ),
    "granite-english-r2": ModelSpec(
        key="granite-english-r2",
        hf_id="ibm-granite/granite-embedding-english-r2",
        license="Apache-2.0",
        developer="IBM Granite Embedding Team",
        lineage=(
            "ModernBERT architecture (Answer.AI, US, and LightOn, France), "
            "trained by IBM. No PRC base model. English R2 (Aug 2025, 149M) "
            "is still the newest English Granite embedder; the May 2026 "
            "multilingual R2 models are a different, multilingual line."
        ),
        gpu_dtype="fp16",
        params="149M",
    ),
    "arctic-embed-l": ModelSpec(
        key="arctic-embed-l",
        hf_id="Snowflake/snowflake-arctic-embed-l",
        license="Apache-2.0",
        developer="Snowflake",
        lineage=(
            "Arctic-Embed 1.0 large, initialized from Microsoft "
            "intfloat/e5-large-unsupervised (BERT-large). The newer "
            "arctic-embed-l-v2.0 and arctic-embed-m-v2.0 are excluded: "
            "v2 large starts from BAAI bge-m3-retromae and v2 medium from "
            "Alibaba gte-multilingual-mlm-base (arXiv:2412.04506, sec. 2.1)."
        ),
        query_prompt="query",
        keyword_prompt="query",
        query_prefix="Represent this sentence for searching relevant passages: ",
        gpu_dtype="fp16",
        params="334M",
    ),
    "nomic-embed-text-v2-moe": ModelSpec(
        key="nomic-embed-text-v2-moe",
        hf_id="nomic-ai/nomic-embed-text-v2-moe",
        license="Apache-2.0",
        developer="Nomic AI (New York)",
        lineage=(
            "Latest Nomic text embedder (Feb 2025). Model tree: "
            "FacebookAI/xlm-roberta-base (Meta) -> nomic-ai/nomic-xlm-2048 -> "
            "nomic-embed-text-v2-moe-unsupervised -> this checkpoint. "
            "nomic-ai/modernbert-embed-base is older (Dec 2024) and was not "
            "substituted. XLM-RoBERTa is not a PRC model."
        ),
        query_prompt="query",
        keyword_prompt="query",
        document_prompt="document",
        query_prefix="search_query: ",
        document_prefix="search_document: ",
        trust_remote_code=True,
        gpu_dtype="fp16",
        params="475M total / 305M active",
    ),
}

EXCLUDED = [
    {
        "hf_id": "Snowflake/snowflake-arctic-embed-l-v2.0",
        "reason": (
            "Arctic-Embed 2.0 large is initialized from bge-m3-retromae "
            "(BAAI, Beijing). AGENTS.md excludes BGE and its fine-tunes. "
            "Source: Arctic-Embed 2.0 paper, arXiv:2412.04506, section 2.1."
        ),
    },
    {
        "hf_id": "Snowflake/snowflake-arctic-embed-m-v2.0",
        "reason": (
            "Arctic-Embed 2.0 medium is initialized from Alibaba "
            "gte-multilingual-mlm-base. AGENTS.md excludes GTE and its "
            "fine-tunes. Same paper, section 2.1."
        ),
    },
]

# Default until the benchmark picks a winner. bench/query can override.
DEFAULT_MODEL = "embeddinggemma-2"

QUESTION_START = (
    "what", "how", "why", "when", "where", "who", "whom", "whose",
    "did", "does", "do", "is", "are", "was", "were", "can", "could",
    "should", "would", "will", "has", "have", "had", "which",
)


def is_question(query: str) -> bool:
    stripped = query.strip().lower()
    if stripped.endswith("?"):
        return True
    first = stripped.split(" ", 1)[0]
    return first in QUESTION_START
