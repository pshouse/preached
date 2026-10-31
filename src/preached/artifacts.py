"""On-disk ONNX artifacts for Granite English R2.

Weights live under ``/cache/models/granite-english-r2-onnx/<revision>/``.
The runtime loads one variant, fp32. int8 is not a runtime variant: it
missed the quality bar, and a manifest must not point ``fp32`` at another
file. The graph file name and its sha256 are pinned in this module by
variant. ``tokenizer.json`` is pinned by its own digest. A needed file
that is missing or mismatched is refused. The loader does not download.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

# Hub commit of ibm-granite/granite-embedding-english-r2 that we export.
# Confirmed against the Hub on 2026-10-30; it is the snapshot already in
# the local Hugging Face cache and the one the Wesley index was built from.
GRANITE_HF_ID = "ibm-granite/granite-embedding-english-r2"
GRANITE_REVISION = "47ea694b257b703fee9253d75c2b1f2985180498"
GRANITE_MODEL_KEY = "granite-english-r2"

# sha256 of the bytes under /cache, hashed 2026-10-30. The graph pin is
# keyed by variant, not by whatever file name the manifest writes. A
# rewritten manifest cannot aim fp32 at another graph.
FP32_ONNX_SHA256 = "3861025a186e45f0978c66b2ac86ae1c47afb245822e051cc9027edb112d8fa9"
TOKENIZER_SHA256 = "6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30"
# int8 is intentionally absent. The export may still leave model.int8.onnx
# beside the fp32 graph; the server never opens it.
VARIANT_FILES = {"fp32": "model.fp32.onnx"}
VARIANT_SHA256 = {"fp32": FP32_ONNX_SHA256}
PINNED_SHA256 = {"tokenizer.json": TOKENIZER_SHA256}

# Overridable so tests can point at a fixture directory.
ONNX_ROOT_ENV = "PREACHED_ONNX_DIR"
VARIANT_ENV = "PREACHED_ONNX_VARIANT"
THREADS_ENV = "PREACHED_ORT_INTRA_OP_THREADS"

DEFAULT_ONNX_ROOT = Path("/cache/models/granite-english-r2-onnx")
# One intra-op thread. A 1-vCPU Sprite with 4 threads was slower (134 ms
# p50 vs 56 ms). Set PREACHED_ORT_INTRA_OP_THREADS=4 on a larger CPU.
DEFAULT_ORT_THREADS = 1
VARIANTS = tuple(VARIANT_FILES)


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


@dataclass(frozen=True)
class VerifiedArtifacts:
    """Manifest plus the bytes of the files the selected variant needs.

    Callers load the session and the tokenizer from ``files`` so a file
    cannot change between the hash and the open. ``digests`` are the sha256
    hex of those same bytes.
    """

    manifest: dict
    variant: str
    files: dict[str, bytes]
    digests: dict[str, str]


def required_filenames(variant: str) -> list[str]:
    """Hard-coded graph for ``variant``, then the tokenizer and pooling config.

    The manifest does not choose the graph file. ``VARIANT_FILES`` does.
    """
    graph = VARIANT_FILES.get(variant)
    if graph is None:
        raise ArtifactError(f"unknown ONNX variant {variant!r}")
    return [graph, "tokenizer.json", "pooling.json"]


def _read_hashed(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def verify_manifest(
    directory: Path | None = None,
    *,
    variant: str | None = None,
    enforce_pins: bool = True,
) -> VerifiedArtifacts:
    """Check the files this variant needs and return their bytes.

    Files for other graphs are not opened. ``enforce_pins`` (the runtime
    default) also requires the variant's graph and ``tokenizer.json`` to
    match the constants above. Tests of the manifest hash itself pass
    ``enforce_pins=False``. A manifest that points the variant at a
    different file name is refused either way.
    """
    folder = directory or artifact_dir()
    manifest = load_manifest(folder)
    chosen = resolve_variant(manifest, variant)
    verified: dict[str, bytes] = {}
    digests: dict[str, str] = {}
    graph_name = VARIANT_FILES[chosen]
    for name in required_filenames(chosen):
        if not isinstance(name, str) or "/" in name or "\\" in name or name.startswith("."):
            raise ArtifactError(f"ONNX manifest has an unsafe file name {name!r}")
        info = manifest["files"].get(name)
        expected = info.get("sha256") if isinstance(info, dict) else None
        if not isinstance(expected, str) or len(expected) != 64:
            raise ArtifactError(f"ONNX manifest sha256 for {name} is missing")
        path = folder / name
        if not path.is_file():
            raise ArtifactError(f"ONNX artifact missing: {name}")
        data, actual = _read_hashed(path)
        if actual != expected:
            raise ArtifactError(f"ONNX sha256 mismatch for {name}")
        pinned = VARIANT_SHA256[chosen] if name == graph_name else PINNED_SHA256.get(name)
        if enforce_pins and pinned is not None and actual != pinned:
            raise ArtifactError(f"ONNX sha256 for {name} is not the pinned digest")
        verified[name] = data
        digests[name] = actual
    try:
        pooling = json.loads(verified["pooling.json"])
    except json.JSONDecodeError as exc:
        raise ArtifactError("pooling.json is not JSON") from exc
    if not isinstance(pooling, dict) or pooling.get("pooling") != "cls":
        raise ArtifactError(f"pooling.json pooling {pooling.get('pooling')!r} is not cls")
    return VerifiedArtifacts(
        manifest=manifest, variant=chosen, files=verified, digests=digests
    )


def resolve_variant(manifest: dict, requested: str | None = None) -> str:
    choice = requested or os.environ.get(VARIANT_ENV) or manifest.get("default_variant")
    if choice not in VARIANTS:
        raise ArtifactError(f"unknown ONNX variant {choice!r}")
    expected = VARIANT_FILES[choice]
    declared = (manifest.get("variants") or {}).get(choice)
    if declared != expected:
        raise ArtifactError(
            f"ONNX variant {choice} is pinned to {expected}; the manifest names {declared!r}"
        )
    if expected not in manifest.get("files", {}):
        raise ArtifactError(f"ONNX variant {choice} file {expected} is not in the manifest")
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
