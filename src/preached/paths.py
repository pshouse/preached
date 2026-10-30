"""Locations for code, the committed catalog, and large data under /cache."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# Large data never lives in the git tree. HF_HOME is set in preached.env
# before any Hugging Face import.
CACHE_ROOT = Path(os.environ.get("PREACHED_CACHE", "/cache"))
CORPUS_DIR = CACHE_ROOT / "corpus" / "wesley"
INDEX_DIR = CACHE_ROOT / "index"
INDEX_PATH = INDEX_DIR / "wesley.sqlite"

SERMONS_TEXT = CORPUS_DIR / "sermons.txt"
SERMONS_JSONL = CORPUS_DIR / "sermons.jsonl"
CHUNKS_JSONL = CORPUS_DIR / "chunks.jsonl"
# What the index loads: see index_chunks_jsonl(). W1-C's chunks carry real
# timestamps and audio; the text-only file is the fallback.
# corpus/chunk_sermons.py still writes CHUNKS_JSONL only, so re-chunking never
# overwrites the aligned file, which is why the aligned file records what it
# was built from (ALIGNED_SOURCE_JSON) and is checked before it is used.
ALIGNED_CHUNKS_JSONL = CORPUS_DIR / "chunks_aligned.jsonl"
ALIGNED_SOURCE_JSON = CORPUS_DIR / "chunks_aligned.source.json"
NUMBER_INDEX_HTML = CORPUS_DIR / "ccel_number_index.html"

CCEL_TEXT_URL = "https://www.ccel.org/ccel/w/wesley/sermons/cache/sermons.txt"
CCEL_INDEX_URL = "https://www.ccel.org/ccel/wesley/sermons/sermons.iii.html"
CCEL_PAGE = "https://ccel.org/ccel/wesley/sermons/{href}"


def repo_root() -> Path:
    """Worktree root. Editable installs live under src/, so walk upwards."""
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "AGENTS.md").is_file():
            return candidate
    return Path.cwd()


def catalog_path() -> Path:
    return repo_root() / "corpus" / "catalog.json"


def chunk_config_path() -> Path:
    return repo_root() / "corpus" / "chunk_config.json"


def questions_path() -> Path:
    return repo_root() / "eval" / "questions.jsonl"


class StaleChunks(RuntimeError):
    """chunks_aligned.jsonl was built from other chunks than chunks.jsonl."""


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def chunk_source_record(text_only: Path | None = None, config: Path | None = None) -> dict:
    """What an aligned chunk file depends on: the text-only chunks and the
    chunk config. ``align/wesley.py chunks`` writes this next to its output."""
    return {
        "chunks_jsonl_sha256": file_sha256(text_only or CHUNKS_JSONL),
        "chunk_config_sha256": file_sha256(config or chunk_config_path()),
    }


def _canonical_keys(path: Path) -> list[tuple]:
    keys = []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("text_source") == "asr":
                continue  # church sermons have no text-only counterpart
            keys.append((row.get("chunk_id"), row.get("text")))
    return keys


def check_aligned_source(
    aligned: Path = ALIGNED_CHUNKS_JSONL,
    text_only: Path = CHUNKS_JSONL,
    source: Path | None = None,
    config: Path | None = None,
) -> str:
    """Refuse an aligned chunk file that no longer matches chunks.jsonl.

    Fast path: the hashes recorded by ``align/wesley.py chunks`` equal the
    current chunks.jsonl and chunk_config.json. Otherwise (no record, or a
    re-chunk since) compare the canonical chunk ids and text in order; equal
    content is still safe to load. Returns how it was accepted.
    """
    source = source or aligned.with_name(aligned.stem + ".source.json")
    current = chunk_source_record(text_only, config)
    if source.is_file():
        try:
            recorded = json.loads(source.read_text())
        except ValueError:
            recorded = {}
        if all(recorded.get(key) == value for key, value in current.items()):
            return "hash"
    if not text_only.is_file():
        if source.is_file():
            raise StaleChunks(
                f"{aligned} was built with another chunk config and {text_only} is missing to compare. "
                "Re-run: uv run align/wesley.py chunks"
            )
        return "unverified"
    if _canonical_keys(aligned) == _canonical_keys(text_only):
        return "content"
    raise StaleChunks(
        f"{aligned} does not match {text_only} (chunk ids or text differ, e.g. after re-chunking). "
        "Re-run: uv run align/wesley.py chunks  (or set PREACHED_CHUNKS to the file to load)"
    )


def index_chunks_jsonl(env: dict | None = None) -> Path:
    """The chunk file the index loads, resolved when called (not at import).

    $PREACHED_CHUNKS wins. Else chunks_aligned.jsonl if it exists and still
    matches chunks.jsonl (StaleChunks if not), else chunks.jsonl.
    """
    override = (os.environ if env is None else env).get("PREACHED_CHUNKS")
    if override:
        return Path(override)
    if ALIGNED_CHUNKS_JSONL.exists():
        check_aligned_source(ALIGNED_CHUNKS_JSONL, CHUNKS_JSONL, ALIGNED_SOURCE_JSON)
        return ALIGNED_CHUNKS_JSONL
    return CHUNKS_JSONL
