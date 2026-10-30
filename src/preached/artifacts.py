"""On-disk ONNX artifacts for Granite English R2.

Weights live under ``/cache/models/granite-english-r2-onnx/<revision>/``.
The runtime checks every file named in ``manifest.json`` and refuses a
missing or mismatched sha256. It does not download.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# Hub commit of ibm-granite/granite-embedding-english-r2 that we export.
# Confirmed against the Hub on 2026-10-30; it is the snapshot already in
# the local Hugging Face cache and the one the Wesley index was built from.
GRANITE_HF_ID = "ibm-granite/granite-embedding-english-r2"
GRANITE_REVISION = "47ea694b257b703fee9253d75c2b1f2985180498"
GRANITE_MODEL_KEY = "granite-english-r2"

# Overridable so tests can point at a fixture directory.
ONNX_ROOT_ENV = "PREACHED_ONNX_DIR"
VARIANT_ENV = "PREACHED_ONNX_VARIANT"
THREADS_ENV = "PREACHED_ORT_INTRA_OP_THREADS"

DEFAULT_ONNX_ROOT = Path("/cache/models/granite-english-r2-onnx")
DEFAULT_ORT_THREADS = 4
VARIANTS = ("fp32", "int8")


class ArtifactError(RuntimeError):
    """The ONNX directory is missing or does not match its manifest."""


def onnx_root() -> Path:
    raw = os.environ.get(ONNX_ROOT_ENV)
    if raw:
        return Path(raw)
    return DEFAULT_ONNX_ROOT


def artifact_dir(revision: str | None = None) -> Path:
    return onnx_root() / (revision or GRANITE_REVISION)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(directory: Path | None = None) -> dict:
    folder = directory or artifact_dir()
    path = folder / "manifest.json"
    if not path.is_file():
        raise ArtifactError(f"missing ONNX manifest at {path}")
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"ONNX manifest is not JSON: {path}") from exc
    if manifest.get("revision") != GRANITE_REVISION:
        raise ArtifactError(
            f"ONNX manifest revision {manifest.get('revision')!r} != {GRANITE_REVISION}"
        )
    if manifest.get("hf_id") != GRANITE_HF_ID:
        raise ArtifactError(f"ONNX manifest model {manifest.get('hf_id')!r} != {GRANITE_HF_ID}")
    if manifest.get("pooling") != "cls":
        raise ArtifactError(f"ONNX manifest pooling {manifest.get('pooling')!r} is not cls")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ArtifactError("ONNX manifest has no files")
    return manifest


def verify_manifest(directory: Path | None = None) -> dict:
    """Hash every file the manifest names. Raise ArtifactError on mismatch."""
    folder = directory or artifact_dir()
    manifest = load_manifest(folder)
    for name, info in manifest["files"].items():
        if not isinstance(name, str) or "/" in name or "\\" in name or name.startswith("."):
            raise ArtifactError(f"ONNX manifest has an unsafe file name {name!r}")
        expected = info.get("sha256") if isinstance(info, dict) else None
        if not isinstance(expected, str) or len(expected) != 64:
            raise ArtifactError(f"ONNX manifest sha256 for {name} is missing")
        path = folder / name
        if not path.is_file():
            raise ArtifactError(f"ONNX artifact missing: {name}")
        actual = sha256_file(path)
        if actual != expected:
            raise ArtifactError(f"ONNX sha256 mismatch for {name}")
    return manifest


def resolve_variant(manifest: dict, requested: str | None = None) -> str:
    choice = requested or os.environ.get(VARIANT_ENV) or manifest.get("default_variant")
    if choice not in VARIANTS:
        raise ArtifactError(f"unknown ONNX variant {choice!r}")
    variants = manifest.get("variants") or {}
    filename = variants.get(choice)
    if not isinstance(filename, str) or filename not in manifest["files"]:
        raise ArtifactError(f"ONNX variant {choice} is not in the manifest")
    return choice


def resolve_threads(requested: int | None = None) -> int:
    if requested is not None:
        threads = int(requested)
    else:
        raw = os.environ.get(THREADS_ENV)
        threads = int(raw) if raw else DEFAULT_ORT_THREADS
    if threads < 1:
        raise ArtifactError("ORT intra-op threads must be >= 1")
    return threads
