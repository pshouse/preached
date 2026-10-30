"""The public-domain classic libraries: a committed allow-list.

Only these slugs may be ingested with ``ingest/run.py --library`` and indexed
with ``search/build_library.py``. Each needs a committed provenance file
(``ingest/manifest/<slug>.provenance.json``). Wesley is not on the list: it
has its own pipeline (``ingest/run.py`` without ``--library``,
``search/build_index.py``). Church libraries are never on it: they go through
redaction and review. Remove a slug here to take it out of the product.
"""

from __future__ import annotations

from pathlib import Path

from preached.paths import repo_root

PUBLIC_DOMAIN = ("spurgeon", "edwards")


def provenance_path(slug: str) -> Path:
    """Where the committed provenance file for ``slug`` lives (it may not exist)."""
    if slug not in PUBLIC_DOMAIN:
        raise ValueError(f"{slug!r} is not a public-domain library")
    return repo_root() / "ingest" / "manifest" / f"{slug}.provenance.json"


def is_public_domain(slug: object) -> bool:
    """True only for an allow-listed slug whose provenance file is committed."""
    return isinstance(slug, str) and slug in PUBLIC_DOMAIN and provenance_path(slug).is_file()
