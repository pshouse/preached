"""Locations for code, the committed catalog, and large data under /cache."""

from __future__ import annotations

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
