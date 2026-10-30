"""Query and document strings for an embedder that has no prompt table.

Granite English R2 ships no query or document prefix, so both functions
return the text unchanged. ``is_question`` is still consulted, which is
what the torch path does when the checkpoint has no matching prompt.
Models that rely on a sentence-transformers prompt name stay on the torch
backend; this module only applies the explicit prefix strings.
"""

from __future__ import annotations

from preached.models import ModelSpec, is_question


def prepare_query(spec: ModelSpec, query: str) -> str:
    """Same string the torch path feeds the model.

    ``ModelSpec.query_prefix`` picks the keyword or question string.
    SentenceTransformer prepends a non-empty prompt; so does this.
    """
    prefix = spec.query_prefix(keyword=not is_question(query))
    if prefix:
        return prefix + query
    return query


def prepare_documents(spec: ModelSpec, texts: list[str], titles: list[str] | None = None) -> list[str]:
    if titles is None:
        titles = [""] * len(texts)
    if len(titles) != len(texts):
        raise ValueError("titles and texts must be the same length")
    if spec.document_template:
        return [
            spec.document_template.format(title=title, text=text)
            for title, text in zip(titles, texts)
        ]
    if spec.document_prefix:
        return [spec.document_prefix + text for text in texts]
    return list(texts)
