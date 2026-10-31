"""Export Granite English R2 to ONNX and write a sha256 manifest.

Bench/dev only. This imports torch. The server does not.

The pinned revision is ``preached.artifacts.GRANITE_REVISION``. Export uses
that commit, ``trust_remote_code`` is false, and the process hides CUDA so
the GPU stays with Whisper.

From the repo root (``uv run --group bench`` installs the bench group):

  CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py

The export is byte-reproducible and must write the graph pinned in
``preached.artifacts.FP32_ONNX_SHA256``. Two things move the bytes
(docs/adr/0001-onnx-export-determinism.md):

- torch's ATen CPU dispatch level. The script sets
  ``ATEN_CPU_CAPABILITY=avx2`` before torch is imported and refuses a host
  that is not x86-64 with AVX2.
- The order of transformers' ModernBERT rotary tables, built in
  ``set(config.layer_types)`` order, which follows ``PYTHONHASHSEED``. The
  script re-executes itself under ``PYTHONHASHSEED=1`` and checks the order.

It exits non-zero without a manifest if the graph does not match the pin.

The Hugging Face cache defaults to ``$PREACHED_CACHE/huggingface`` (``/cache``
only when PREACHED_CACHE is unset); an explicit HF_HOME wins.

Outputs under ``$PREACHED_CACHE/models/granite-english-r2-onnx/<revision>/``:

  model.fp32.onnx
  model.int8.onnx
  tokenizer.json
  pooling.json
  manifest.json

Pooling stays outside the graph. The ONNX file returns ``last_hidden_state``.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
# Before torch is imported: the dispatch level changes the exported bytes.
EXPORT_CPU_CAPABILITY = "avx2"
os.environ["ATEN_CPU_CAPABILITY"] = EXPORT_CPU_CAPABILITY


def _default_hf_cache(environ) -> None:
    """Point the HF cache under PREACHED_CACHE (/cache only when it is unset).

    An explicit HF_HOME wins; the hub cache then follows it. This runs at
    import, before the hash-seed restart and before any HF or torch import,
    and the restart passes os.environ on, so the restarted process sees it.
    """
    root = environ.get("PREACHED_CACHE") or "/cache"
    environ.setdefault("HF_HOME", os.path.join(root, "huggingface"))
    environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(environ["HF_HOME"], "hub"))


_default_hf_cache(os.environ)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.artifacts import (  # noqa: E402
    FP32_ONNX_SHA256,
    GRANITE_HF_ID,
    GRANITE_REVISION,
    artifact_dir,
    sha256_file,
)
from preached.pooling import HIDDEN_SIZE, MAX_SEQ_LENGTH  # noqa: E402

# Under this seed (with avx2 dispatch) CPython 3.12 iterates
# set(config.layer_types) sliding first and the export is the pinned graph.
EXPORT_HASHSEED = "1"
PINNED_TRACE_ORDER = ["sliding_attention", "full_attention"]


def _require_avx2(machine: str | None = None, cpuinfo: Path = Path("/proc/cpuinfo")) -> None:
    """The pin is the avx2 export. Refuse a host that cannot run avx2 kernels."""
    machine = machine or platform.machine()
    if machine.lower() not in {"x86_64", "amd64"}:
        raise SystemExit(
            f"export needs an x86-64 host with AVX2 (the pinned graph is the "
            f"ATEN_CPU_CAPABILITY=avx2 export); this host is {machine}"
        )
    try:
        text = cpuinfo.read_text()
    except OSError as exc:
        raise SystemExit(f"export needs an x86-64 host with AVX2; cannot read {cpuinfo}: {exc}") from None
    flags = next((line.split(":", 1)[1].split() for line in text.splitlines() if line.startswith("flags")), [])
    if "avx2" not in flags:
        raise SystemExit("export needs an x86-64 host with AVX2; this CPU does not report avx2")


def _reexec_with_hashseed() -> None:
    """String hashing is fixed at interpreter start, so set it and restart.

    The ambient seed (unset, random, or any other value) never reaches the
    trace. A numeric PYTHONHASHSEED wins over ``-R``, so the variable alone
    says whether the seed is fixed. (``sys.flags.hash_randomization`` reads 1
    under any seed but 0, so testing it would restart forever.)
    """
    if os.environ.get("PYTHONHASHSEED") == EXPORT_HASHSEED:
        return
    os.environ["PYTHONHASHSEED"] = EXPORT_HASHSEED
    script = str(Path(__file__).resolve())
    os.execv(sys.executable, [sys.executable, script, *sys.argv[1:]])


def _check_trace_order(model) -> None:
    # modeling_modernbert.py loops `for layer_type in set(self.config.layer_types)`
    # and calls rotary_emb once per type. Same weights either way; the node
    # names and wiring of the two rotary tables swap, so the bytes differ.
    order = list(set(model.config.layer_types))
    if order != PINNED_TRACE_ORDER:
        raise SystemExit(
            f"rotary trace order {order} != {PINNED_TRACE_ORDER} "
            f"(PYTHONHASHSEED={os.environ.get('PYTHONHASHSEED')!r}); "
            "this export would not match the pinned graph"
        )


def _check_pin(path: Path) -> None:
    actual = sha256_file(path)
    if actual != FP32_ONNX_SHA256:
        raise SystemExit(
            f"exported {path.name} sha256 {actual} is not the pin {FP32_ONNX_SHA256}. "
            "No manifest was written; the runtime will refuse this directory. "
            "Check the bench group matches uv.lock (torch, transformers, onnx)."
        )
    print(f"fp32 sha256 matches the pin {actual}", flush=True)


def _pooling_is_cls(snapshot: Path) -> None:
    pooling = json.loads((snapshot / "1_Pooling" / "config.json").read_text())
    if not pooling.get("pooling_mode_cls_token"):
        raise SystemExit(f"expected CLS pooling, got {pooling}")
    if pooling.get("pooling_mode_mean_tokens") or pooling.get("pooling_mode_max_tokens"):
        raise SystemExit(f"pooling config is not CLS-only: {pooling}")
    sentence = json.loads((snapshot / "sentence_bert_config.json").read_text())
    if int(sentence.get("max_seq_length") or 0) != MAX_SEQ_LENGTH:
        raise SystemExit(f"max_seq_length is {sentence.get('max_seq_length')}, expected {MAX_SEQ_LENGTH}")


def _load_encoder(snapshot: Path):
    import torch
    from transformers import AutoModel

    model = AutoModel.from_pretrained(
        snapshot,
        trust_remote_code=False,
        torch_dtype=torch.float32,
        attn_implementation="eager",
    )
    model.to("cpu")
    model.eval()
    return model


def _export(model, destination: Path) -> None:
    import torch

    class Encoder(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, input_ids, attention_mask):
            output = self.inner(input_ids=input_ids, attention_mask=attention_mask)
            return output.last_hidden_state

    _check_trace_order(model)
    encoder = Encoder(model)
    encoder.eval()
    ids = torch.ones(2, 16, dtype=torch.long)
    mask = torch.ones(2, 16, dtype=torch.long)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Legacy tracer. dynamo=False keeps the graph a plain fp32 encoder.
    torch.onnx.export(
        encoder,
        (ids, mask),
        str(destination),
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "last_hidden_state": {0: "batch", 1: "sequence"},
        },
        opset_version=18,
        do_constant_folding=True,
        dynamo=False,
        external_data=False,
    )


def _torch_hidden(model, ids, mask):
    import torch

    with torch.no_grad():
        output = model(input_ids=ids, attention_mask=mask)
    return output.last_hidden_state.detach().float().numpy()


def _check_export(model, onnx_path: Path) -> None:
    """A few lengths must match torch fp32 before we quantize."""
    import numpy as np
    import onnxruntime as ort
    import torch

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = 1
    session = ort.InferenceSession(
        str(onnx_path), options, providers=["CPUExecutionProvider"]
    )
    output_name = session.get_outputs()[0].name
    for length in (8, 17, 64):
        ids = torch.randint(10, 1000, (2, length))
        attn = torch.ones(2, length, dtype=torch.long)
        attn[0, -3:] = 0
        reference = _torch_hidden(model, ids, attn)
        got = session.run(
            [output_name],
            {"input_ids": ids.numpy(), "attention_mask": attn.numpy()},
        )[0]
        cosine = _cosine_min(reference, got)
        max_abs = float(np.max(np.abs(reference - got)))
        print(f"fp32 check len={length} min_cosine={cosine:.6f} max_abs={max_abs:.3e}", flush=True)
        if cosine < 0.999:
            raise SystemExit(f"ONNX fp32 diverged from torch at length {length}")


def _cosine_min(left, right) -> float:
    import numpy as np

    a = left.reshape(-1, left.shape[-1]).astype("float32")
    b = right.reshape(-1, right.shape[-1]).astype("float32")
    a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    b = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-12)
    return float(np.min(np.sum(a * b, axis=1)))


def _quantize(source: Path, destination: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(
        str(source),
        str(destination),
        weight_type=QuantType.QInt8,
        per_channel=True,
        extra_options={"MatMulConstBOnly": True},
    )


def _write_manifest(folder: Path, files: list[str], default_variant: str) -> None:
    listed = {}
    for name in files:
        path = folder / name
        listed[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest = {
        "hf_id": GRANITE_HF_ID,
        "revision": GRANITE_REVISION,
        "pooling": "cls",
        "normalize": "l2",
        "max_seq_length": MAX_SEQ_LENGTH,
        "hidden_size": HIDDEN_SIZE,
        "trust_remote_code": False,
        "default_variant": default_variant,
        "variants": {"fp32": "model.fp32.onnx", "int8": "model.int8.onnx"},
        "files": listed,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # The manifest hashes itself out. Record it after the write so a later
    # reader can still check the other files. The runtime hashes only the
    # selected variant plus tokenizer.json and pooling.json. int8 may be
    # listed here and still be absent when the server loads fp32.
    # manifest.json is not in the hashed list.
    print(json.dumps({name: info["bytes"] for name, info in listed.items()}, indent=2))


def main() -> None:
    import torch
    from huggingface_hub import snapshot_download

    if torch.cuda.is_available():
        raise SystemExit("CUDA is visible; export must run with CUDA_VISIBLE_DEVICES=''")
    capability = torch.backends.cpu.get_cpu_capability()
    if capability != EXPORT_CPU_CAPABILITY.upper():
        raise SystemExit(f"torch CPU dispatch is {capability}, expected {EXPORT_CPU_CAPABILITY.upper()}")
    snapshot = Path(
        snapshot_download(
            GRANITE_HF_ID,
            revision=GRANITE_REVISION,
            allow_patterns=[
                "config.json",
                "model.safetensors",
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
                "modules.json",
                "sentence_bert_config.json",
                "1_Pooling/config.json",
            ],
        )
    )
    print(f"snapshot {snapshot}", flush=True)
    _pooling_is_cls(snapshot)
    folder = artifact_dir()
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    print("loading fp32 encoder on CPU", flush=True)
    model = _load_encoder(snapshot)
    fp32 = folder / "model.fp32.onnx"
    print(f"exporting {fp32}", flush=True)
    _export(model, fp32)
    _check_pin(fp32)
    _check_export(model, fp32)
    int8 = folder / "model.int8.onnx"
    print(f"quantizing {int8}", flush=True)
    _quantize(fp32, int8)
    shutil.copyfile(snapshot / "tokenizer.json", folder / "tokenizer.json")
    pooling = {
        "pooling": "cls",
        "normalize": "l2",
        "max_seq_length": MAX_SEQ_LENGTH,
        "hidden_size": HIDDEN_SIZE,
        "revision": GRANITE_REVISION,
    }
    (folder / "pooling.json").write_text(json.dumps(pooling, indent=2) + "\n")
    # fp32 is the safe default until the int8 eval says otherwise.
    _write_manifest(
        folder,
        ["model.fp32.onnx", "model.int8.onnx", "tokenizer.json", "pooling.json"],
        default_variant="fp32",
    )
    print(f"wrote {folder}", flush=True)


if __name__ == "__main__":
    _require_avx2()
    _reexec_with_hashseed()
    main()
