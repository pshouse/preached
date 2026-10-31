"""Granite English R2 on ONNX Runtime, CPU only.

No torch import. Pooling and L2 normalization run in numpy
(``preached.pooling``). A bad or missing artifact raises ArtifactError
so the server can fall back to BM25.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import mmap
import os
import stat
from pathlib import Path

import numpy as np

from preached.artifacts import (
    GRANITE_MODEL_KEY,
    VARIANT_FILES,
    VARIANT_SHA256,
    ArtifactError,
    artifact_dir,
    resolve_threads,
    verify_manifest,
)
from preached.libraries import _owner_mode_problem
from preached.models import MODELS, ModelSpec
from preached.pooling import HIDDEN_SIZE, MAX_SEQ_LENGTH, pool_cls
from preached.prefixes import prepare_documents, prepare_query
from preached.text_tokens import encode_texts

log = logging.getLogger(__name__)


def _open_hashed_graph(path: Path, expected: str, pinned: str) -> tuple[int, str]:
    """Open ``path`` without following a symlink; check and hash it through that fd.

    Returns the open fd and the sha256 hex of the bytes read through it
    (the digest ``OnnxEmbedder.model_sha256`` reports). The caller hands
    ``/proc/self/fd/N`` to ORT, so ORT reopens the inode that was hashed here. Nobody but root or this euid may
    be able to change that inode or the directory entry pointing at it: the
    directory and the file are owned by root or the euid with no group or
    world write, and the file is a regular file with one link (the
    ``libraries.classic_index_problem`` rules). ``O_NONBLOCK`` keeps a FIFO
    swapped in at the path from hanging the open. A graph that names external data is refused,
    since under ``/proc/self/fd`` a relative location could name another of
    this process's files. The caller closes the fd. Every refusal closes it.
    """
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        raise ArtifactError(f"ONNX directory cannot be opened: {path.parent}") from exc
    try:
        problem = _owner_mode_problem(path.parent, os.fstat(dir_fd), "ONNX directory")
        if problem is not None:
            raise ArtifactError(problem)
        try:
            fd = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=dir_fd,
            )
        except OSError as exc:
            raise ArtifactError(f"ONNX artifact cannot be opened: {path.name}") from exc
    finally:
        os.close(dir_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ArtifactError(f"ONNX artifact is not a regular file: {path.name}")
        problem = _owner_mode_problem(path, st, "ONNX artifact")
        if problem is not None:
            raise ArtifactError(problem)
        if st.st_nlink != 1:
            raise ArtifactError(f"ONNX artifact {path.name} has {st.st_nlink} hard links, not 1")
        if not os.path.exists(f"/proc/self/fd/{fd}"):
            raise ArtifactError("ONNX loading needs /proc/self/fd")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise ArtifactError(f"ONNX sha256 mismatch for {path.name}")
        if actual != pinned:
            raise ArtifactError(f"ONNX sha256 for {path.name} is not the pinned digest")
        if _uses_external_data(fd):
            raise ArtifactError(f"ONNX artifact {path.name} uses external data")
        return fd, actual
    except BaseException:
        os.close(fd)
        raise


# Protobuf fields (onnx.proto) that can hold a TensorProto, by message type.
# Each maps field number -> the message type of that field.
_ONNX_SUBMESSAGES = {
    "model": {7: "graph", 20: "training", 25: "function"},
    "training": {1: "graph", 2: "graph"},
    "function": {7: "node", 11: "attribute"},
    "graph": {1: "node", 5: "tensor", 15: "sparse"},
    "node": {5: "attribute"},
    "attribute": {5: "tensor", 6: "graph", 10: "tensor", 11: "graph", 22: "sparse", 23: "sparse"},
    "sparse": {1: "tensor", 2: "tensor"},
    "tensor": {},
}
_TENSOR_EXTERNAL_DATA = 13
_TENSOR_DATA_LOCATION = 14
_MAX_NESTING = 64


def _varint(buf, pos: int, end: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= end or shift > 63:
            raise ArtifactError("ONNX graph is not a valid protobuf")
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def _scan_external(buf, start: int, end: int, kind: str, depth: int) -> bool:
    """True if any TensorProto under this message names external data."""
    if depth > _MAX_NESTING:
        raise ArtifactError("ONNX graph nests too deeply")
    children = _ONNX_SUBMESSAGES[kind]
    pos = start
    while pos < end:
        key, pos = _varint(buf, pos, end)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos, end)
            if kind == "tensor" and field == _TENSOR_DATA_LOCATION and value != 0:
                return True
        elif wire == 1:
            pos += 8
        elif wire == 5:
            pos += 4
        elif wire == 2:
            length, pos = _varint(buf, pos, end)
            if pos + length > end:
                raise ArtifactError("ONNX graph is not a valid protobuf")
            if kind == "tensor" and field == _TENSOR_EXTERNAL_DATA:
                return True
            child = children.get(field)
            if child is not None and _scan_external(buf, pos, pos + length, child, depth + 1):
                return True
            pos += length
        else:
            raise ArtifactError("ONNX graph is not a valid protobuf")
    if pos != end:
        raise ArtifactError("ONNX graph is not a valid protobuf")
    return False


def _uses_external_data(fd: int) -> bool:
    """Walk the ModelProto on ``fd`` for tensors stored outside the file.

    The walk skips tensor payloads by length, so only field headers are
    read; the mapping is dropped before returning.
    """
    size = os.fstat(fd).st_size
    if size == 0:
        raise ArtifactError("ONNX graph is empty")
    with mmap.mmap(fd, size, access=mmap.ACCESS_READ) as buf:
        return _scan_external(buf, 0, size, "model", 0)


def trim_heap() -> bool:
    """Return freed heap pages to the OS (glibc). False if unavailable."""
    try:
        return bool(ctypes.CDLL("libc.so.6").malloc_trim(0))
    except (OSError, AttributeError):
        return False


class OnnxEmbedder:
    """``encode_queries`` / ``encode_documents`` -> float32, L2-normalized."""

    def __init__(
        self,
        spec: ModelSpec,
        session,
        tokenizer,
        *,
        variant: str,
        max_length: int,
        hidden_size: int,
        batch_size: int,
        threads: int,
    ) -> None:
        self.spec = spec
        self.session = session
        self.tokenizer = tokenizer
        self.variant = variant
        self.max_length = max_length
        self.hidden_size = hidden_size
        self.batch_size = max(1, batch_size)
        self.threads = threads
        self.backend = "onnx"

    @classmethod
    def load(
        cls,
        model_key: str = GRANITE_MODEL_KEY,
        *,
        variant: str | None = None,
        ort_threads: int | None = None,
        batch_size: int = 16,
        directory: Path | None = None,
    ) -> "OnnxEmbedder":
        if model_key != GRANITE_MODEL_KEY:
            raise ArtifactError(f"onnx backend only supports {GRANITE_MODEL_KEY}")
        spec = MODELS[model_key]
        folder = directory or artifact_dir()
        verified = verify_manifest(folder, variant=variant, hash_graph=False)
        manifest = verified.manifest
        chosen = verified.variant
        # The file name is the code pin, not the manifest's variants map.
        filename = VARIANT_FILES[chosen]
        threads = resolve_threads(ort_threads)
        max_length = int(manifest.get("max_seq_length") or MAX_SEQ_LENGTH)
        hidden_size = int(manifest.get("hidden_size") or HIDDEN_SIZE)
        if max_length != MAX_SEQ_LENGTH or hidden_size != HIDDEN_SIZE:
            raise ArtifactError(
                f"ONNX manifest shape {hidden_size}x{max_length} does not match Granite"
            )

        # Imported here so BM25-only commands and the import guard stay light.
        # The tokenizer is built from the bytes just hashed. The graph is
        # hashed through an open fd and ORT loads that same fd, so no second
        # copy of the graph is held in Python.
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.log_severity_level = 3
        # verify_manifest skipped the graph hash; the manifest digest and
        # the pin are checked here, on the fd ORT loads.
        expected = verified.manifest["files"][filename]["sha256"]
        fd, graph_sha = _open_hashed_graph(folder / filename, expected, VARIANT_SHA256[chosen])
        try:
            session = ort.InferenceSession(
                f"/proc/self/fd/{fd}",
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        finally:
            os.close(fd)
            if not trim_heap():
                log.debug("malloc_trim unavailable or freed nothing after ONNX load")
        input_names = {item.name for item in session.get_inputs()}
        if input_names != {"input_ids", "attention_mask"}:
            raise ArtifactError(f"ONNX inputs {sorted(input_names)} are not input_ids and attention_mask")
        if session.get_providers() != ["CPUExecutionProvider"]:
            # A GPU build of onnxruntime must not pick CUDA. CPUExecutionProvider
            # is requested alone; anything else means the session ignored that.
            raise ArtifactError(f"ONNX session providers {session.get_providers()} are not CPU")
        tokenizer = Tokenizer.from_buffer(verified.files["tokenizer.json"])
        embedder = cls(
            spec,
            session,
            tokenizer,
            variant=chosen,
            max_length=max_length,
            hidden_size=hidden_size,
            batch_size=batch_size,
            threads=threads,
        )
        embedder.output_name = session.get_outputs()[0].name
        # Hex digest of the graph bytes hashed on the fd ORT loaded. No path.
        embedder.model_sha256 = graph_sha
        return embedder

    def close(self) -> None:
        """Drop the ONNX Runtime session now, not during interpreter
        finalisation. No call may be in ``encode_*`` when this runs."""
        self.session = None

    def encode_queries(self, queries: list[str]) -> np.ndarray:
        texts = [prepare_query(self.spec, query) for query in queries]
        return self._encode(texts)

    def encode_documents(self, texts: list[str], titles: list[str] | None = None) -> np.ndarray:
        prepared = prepare_documents(self.spec, texts, titles)
        return self._encode(prepared)

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.hidden_size), dtype=np.float32)
        parts = []
        for start in range(0, len(texts), self.batch_size):
            parts.append(self._encode_batch(texts[start : start + self.batch_size]))
        if len(parts) == 1:
            return parts[0]
        return np.concatenate(parts, axis=0)

    def _encode_batch(self, texts: list[str]) -> np.ndarray:
        batch = encode_texts(self.tokenizer, texts, self.max_length)
        hidden = self.session.run(
            [self.output_name],
            {"input_ids": batch.input_ids, "attention_mask": batch.attention_mask},
        )[0]
        pooled = pool_cls(hidden, batch.attention_mask)
        if pooled.shape != (len(texts), self.hidden_size):
            raise RuntimeError(
                f"ONNX embedding shape {pooled.shape} != {(len(texts), self.hidden_size)}"
            )
        return pooled
