"""Embedding model specs, read from search/models.toml.

AGENTS.md bars models developed in the PRC and fine-tunes or distillations
of those models. When a base model is unclear, the model is excluded.
Adding a model is one table in search/models.toml; nothing here changes.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from preached.paths import repo_root

DTYPES = ("fp32", "bf16", "fp16")


@dataclass(frozen=True)
class ModelSpec:
    key: str
    hf_id: str
    revision: str
    license: str = ""
    developer: str = ""
    lineage: str = ""
    lineage_sources: tuple[str, ...] = ()
    params: str = ""
    dtype_gpu: str = "fp32"
    dtype_cpu: str = "fp32"
    dim: int | None = None
    question_prefix: str = ""
    keyword_prefix: str = ""
    document_prefix: str = ""
    document_template: str = ""
    drop_config: tuple[str, ...] = ()
    trust_remote_code: bool = False
    enabled: bool = True
    gated: bool = False
    provenance: str = "clear"

    def query_prefix(self, keyword: bool) -> str:
        if keyword and self.keyword_prefix:
            return self.keyword_prefix
        return self.question_prefix

    def fingerprint(self) -> str:
        """Everything that changes a stored document vector. CPU dtype and
        query prefixes are excluded: they only affect query vectors."""
        parts = {
            "hf_id": self.hf_id,
            "revision": self.revision,
            "dtype_gpu": self.dtype_gpu,
            "dim": self.dim,
            "document_prefix": self.document_prefix,
            "document_template": self.document_template,
            "drop_config": list(self.drop_config),
        }
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]

    def record(self) -> dict:
        data = asdict(self)
        data["lineage_sources"] = list(self.lineage_sources)
        data["drop_config"] = list(self.drop_config)
        return data


def config_path() -> Path:
    return repo_root() / "search" / "models.toml"


def load_config(path: Path | None = None) -> dict:
    raw = tomllib.loads((path or config_path()).read_text())
    models: dict[str, ModelSpec] = {}
    for key, entry in raw.get("models", {}).items():
        entry = dict(entry)
        for name in ("lineage_sources", "drop_config"):
            entry[name] = tuple(entry.get(name, ()))
        spec = ModelSpec(key=key, **entry)
        for dtype in (spec.dtype_gpu, spec.dtype_cpu):
            if dtype not in DTYPES:
                raise ValueError(f"{key}: dtype {dtype!r} is not one of {DTYPES}")
        if not spec.revision:
            raise ValueError(f"{key}: pin a revision (commit hash) in models.toml")
        if spec.provenance != "clear" and not spec.provenance.startswith("unclear:"):
            raise ValueError(f"{key}: provenance must be 'clear' or 'unclear: <reason>'")
        models[key] = spec
    default = raw.get("default")
    if default not in models:
        raise ValueError(f"default model {default!r} is not in models.toml")
    if models[default].provenance != "clear":
        raise ValueError(f"default model {default!r} has unresolved provenance")
    return {
        "models": models,
        "default": default,
        "reference": raw.get("reference", {"model": default, "mode": "hybrid_rrf"}),
        "excluded": list(raw.get("excluded", [])),
    }


_CONFIG = load_config()
MODELS: dict[str, ModelSpec] = _CONFIG["models"]
DEFAULT_MODEL: str = _CONFIG["default"]
REFERENCE: dict = _CONFIG["reference"]
EXCLUDED: list[dict] = _CONFIG["excluded"]

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
