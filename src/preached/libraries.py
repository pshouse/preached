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
import os
import re
import stat
import urllib.parse
from pathlib import Path

from preached import paths
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


def manifest_path(slug: str) -> Path:
    """Where the committed manifest for ``slug`` lives (it may not exist)."""
    if slug not in PUBLIC_DOMAIN:
        raise ValueError(f"{slug!r} is not a public-domain library")
    return repo_root() / "ingest" / "manifest" / f"{slug}.jsonl"


def _text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _name(value: object) -> bool:
    return isinstance(value, str) and NAME_RE.fullmatch(value) is not None and ".." not in value


def audio_url(ia_identifier: str, file_name: str) -> str:
    """The archive.org download URL for one file, as the manifests write it."""
    return f"https://archive.org/download/{ia_identifier}/{urllib.parse.quote(file_name)}"


def _archive_url(url: str) -> bool:
    if "\\" in url or not url.isascii() or re.search(r"[\x00-\x20\x7f-\x9f]", url):
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


def check_manifest(slug: str, provenance: dict) -> None:
    """BadProvenance unless the committed manifest and provenance list the same audio.

    Same ids, and per id the same file name, size and md5, with the audio URL
    that provenance derives. Checked whenever a library is used (build, query,
    serve), not only when it is built.
    """
    path = manifest_path(slug)
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise BadProvenance(f"{path}: cannot read manifest ({exc})") from None
    entries = {entry["id"]: entry for entry in provenance["audio_files"]}
    ids = [row.get("id") if isinstance(row, dict) else None for row in rows]
    if len(set(ids)) != len(ids) or set(ids) != set(entries):
        raise BadProvenance(f"{path}: manifest ids differ from {slug}.provenance.json")
    for row in rows:
        entry = entries[row["id"]]
        for key in ("file_name", "size", "md5"):
            if row.get(key) != entry[key]:
                raise BadProvenance(f"{path}: {row['id']} {key} {row.get(key)!r} != provenance {entry[key]!r}")
        if row.get("audio_url") != audio_url(provenance["ia_identifier"], entry["file_name"]):
            raise BadProvenance(f"{path}: {row['id']} audio_url does not match provenance")


def is_public_domain(slug: object) -> bool:
    """True only for an allow-listed slug whose committed provenance checks out
    and agrees with its committed manifest."""
    try:
        check_manifest(slug, load_provenance(slug))
    except BadProvenance:
        return False
    return True


def canonical_index(slug: str, index_dir: Path | None = None) -> Path:
    """The one place a classic library's index may live: INDEX_DIR/<slug>.sqlite."""
    if slug not in PUBLIC_DOMAIN:
        raise ValueError(f"{slug!r} is not a public-domain library")
    return (paths.INDEX_DIR if index_dir is None else Path(index_dir)) / f"{slug}.sqlite"


# SQLite reads these next to a database file: a hot journal or a WAL is
# replayed into what the reader sees, so each is as trusted as the file itself.
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _owner_mode_problem(path: Path, st: os.stat_result, what: str) -> str | None:
    """Owned by root or the server's effective uid, with no group or world write bit."""
    uid = os.geteuid()
    if st.st_uid not in (0, uid):
        return f"{what} {path} is owned by uid {st.st_uid}, not root or this server's uid {uid}"
    if st.st_mode & 0o022:
        return f"{what} {path} is group- or world-writable (mode {stat.S_IMODE(st.st_mode):o})"
    return None


def classic_index_problem(slug: object, path: Path, index_dir: Path | None = None) -> str | None:
    """Why ``path`` may not be treated as the classic library ``slug``, or None.

    The single gate for the classics exemption (no redaction, no review): the
    slug passes ``is_public_domain`` and ``path`` is the canonical
    INDEX_DIR/<slug>.sqlite. Both the given path and the canonical path must
    not be symlinks and must resolve (realpath) to the same file, so a library
    marker in any other file is never trusted. ``index_dir`` defaults to
    ``preached.paths.INDEX_DIR`` read at call time.

    Nobody but root or this server's effective uid may have put the file
    there or changed it: INDEX_DIR, its parent and the file are owned by root
    or the server's euid with no group or world write; INDEX_DIR and the file
    are not symlinks; the file is a regular file with one link (no hardlink
    from elsewhere). Any -wal, -shm or -journal file next to it
    (SIDECAR_SUFFIXES) passes the same file checks, since SQLite reads it.
    """
    if not is_public_domain(slug):
        return f"{slug!r} is not a public-domain library (allowed: {', '.join(PUBLIC_DOMAIN)})"
    canonical = canonical_index(slug, index_dir)
    given = Path(path)
    if os.path.islink(given) or os.path.islink(canonical):
        return f"{given} is a symlink; the {slug} library is served only from {canonical}"
    if os.path.realpath(given) != os.path.realpath(canonical):
        return f"{given} is not {canonical}; the {slug} library is served only from there"
    if not os.path.isfile(canonical):
        return f"missing index {canonical}"
    directory = canonical.parent
    if os.path.islink(directory):
        return f"index directory {directory} is a symlink; the {slug} library is not served through it"
    parent = Path(os.path.abspath(directory)).parent
    try:
        checks = (
            (parent, os.stat(parent), "index parent directory"),
            (directory, os.lstat(directory), "index directory"),
            (canonical, os.lstat(canonical), "index"),
        )
    except OSError as exc:
        return f"cannot check {canonical} ({exc})"
    for target, st, what in checks:
        problem = _owner_mode_problem(target, st, what)
        if problem is not None:
            return problem
    problem = _file_problem(canonical, checks[2][1], slug)
    if problem is not None:
        return problem
    for suffix in SIDECAR_SUFFIXES:
        sidecar = Path(f"{canonical}{suffix}")
        try:
            st = os.lstat(sidecar)
        except FileNotFoundError:
            continue
        except OSError as exc:
            return f"cannot check {sidecar} ({exc})"
        if stat.S_ISLNK(st.st_mode):
            return f"{sidecar} is a symlink; the {slug} library is not served with it"
        problem = _owner_mode_problem(sidecar, st, "index sidecar") or _file_problem(sidecar, st, slug)
        if problem is not None:
            return problem
    return None


def _file_problem(path: Path, st: os.stat_result, slug: str) -> str | None:
    """A regular file with one link (no hardlink from elsewhere)."""
    if not stat.S_ISREG(st.st_mode):
        return f"{path} is not a regular file"
    if st.st_nlink != 1:
        return f"{path} has {st.st_nlink} hard links; the {slug} library is served only from files with one"
    return None
