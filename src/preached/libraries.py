"""The public-domain classic libraries: a committed allow-list.

Only these slugs may be ingested with ``ingest/run.py --library``, indexed
with ``search/build_library.py`` and served by ``app/server.py``. Each needs a
committed provenance file (``ingest/manifest/<slug>.provenance.json``) that
passes ``load_provenance``. Wesley is not on the list: it has its own pipeline
(``ingest/run.py`` without ``--library``, ``search/build_index.py``). Church
libraries are never on it: they go through redaction and review. Remove a slug
here to take it out of the product.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from preached.paths import repo_root

PUBLIC_DOMAIN = ("spurgeon", "edwards")

# Same shapes as ingest/manifest.py (FILE_NAME_RE, the md5 check).
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}")
MD5_RE = re.compile(r"[0-9a-f]{32}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class BadProvenance(ValueError):
    """A provenance file that is missing, unreadable or incomplete."""


def provenance_path(slug: str) -> Path:
    """Where the committed provenance file for ``slug`` lives (it may not exist)."""
    if slug not in PUBLIC_DOMAIN:
        raise ValueError(f"{slug!r} is not a public-domain library")
    return repo_root() / "ingest" / "manifest" / f"{slug}.provenance.json"


def _text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _name(value: object) -> bool:
    return isinstance(value, str) and NAME_RE.fullmatch(value) is not None and ".." not in value


def audio_url(ia_identifier: str, file_name: str) -> str:
    """The archive.org download URL for one file, as the manifests write it."""
    return f"https://archive.org/download/{ia_identifier}/{urllib.parse.quote(file_name)}"


def _archive_url(url: str) -> bool:
    if "\\" in url or re.search(r"[\x00-\x20\x7f-\x9f]", url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https" and parts.hostname == "archive.org" and port is None
        and not parts.username and not parts.password
    )


def load_provenance(slug: object) -> dict:
    """The provenance for an allow-listed slug, checked; else BadProvenance.

    Checks: the file parses; its ``slug`` matches; a licence (``licenseurl``
    and ``license_note``); a text edition note; the archive.org identifier;
    and a non-empty ``audio_files`` list where every entry has a safe file
    name, size, md5 and sha256 and builds a valid https archive.org URL.
    """
    if not isinstance(slug, str) or slug not in PUBLIC_DOMAIN:
        raise BadProvenance(f"{slug!r} is not a public-domain library")
    path = provenance_path(slug)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BadProvenance(f"{path}: cannot read provenance ({exc})") from None
    if not isinstance(data, dict):
        raise BadProvenance(f"{path}: not a JSON object")
    if data.get("slug") != slug:
        raise BadProvenance(f"{path}: slug {data.get('slug')!r} != {slug!r}")
    if not _text(data.get("licenseurl")) or not _text(data.get("license_note")):
        raise BadProvenance(f"{path}: licence missing")
    edition = data.get("text_edition")
    if not isinstance(edition, dict) or not _text(edition.get("note")):
        raise BadProvenance(f"{path}: text edition missing")
    ident = data.get("ia_identifier")
    if not _name(ident) or data.get("ia_url") != f"https://archive.org/details/{ident}":
        raise BadProvenance(f"{path}: bad archive.org identifier or ia_url")
    files = data.get("audio_files")
    if not isinstance(files, list) or not files:
        raise BadProvenance(f"{path}: audio_files is empty")
    for entry in files:
        ok = (
            isinstance(entry, dict)
            and _name(entry.get("id"))
            and _name(entry.get("file_name"))
            and isinstance(entry.get("size"), int) and not isinstance(entry["size"], bool) and entry["size"] > 0
            and isinstance(entry.get("md5"), str) and MD5_RE.fullmatch(entry["md5"])
            and isinstance(entry.get("sha256"), str) and SHA256_RE.fullmatch(entry["sha256"])
            and _archive_url(audio_url(ident, entry["file_name"]))
        )
        if not ok:
            raise BadProvenance(f"{path}: bad audio_files entry {entry!r}")
    return data


def is_public_domain(slug: object) -> bool:
    """True only for an allow-listed slug whose committed provenance checks out."""
    try:
        load_provenance(slug)
    except BadProvenance:
        return False
    return True
