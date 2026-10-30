"""Export Granite English R2 to ONNX and write a sha256 manifest.

Bench/dev only. This imports torch. The server does not.

The pinned revision is ``preached.artifacts.GRANITE_REVISION``. Export uses
that commit, ``trust_remote_code`` is false, and the process hides CUDA so
the GPU stays with Whisper.

  cd /work/preached/.worktrees/feat/w3-cpu
  uv sync --group bench
  CUDA_VISIBLE_DEVICES="" uv run --group bench python scripts/export_onnx.py

Outputs under ``/cache/models/granite-english-r2-onnx/<revision>/``:

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
import shutil
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.setdefault("HF_HOME", "/cache/huggingface")
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/cache/huggingface/hub")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.artifacts import (  # noqa: E402
    GRANITE_HF_ID,
    GRANITE_REVISION,
    artifact_dir,
    sha256_file,
)
from preached.pooling import HIDDEN_SIZE, MAX_SEQ_LENGTH  # noqa: E402


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
    # reader can still check the other files. The runtime hashes the files
    # named above; manifest.json is not in that list.
    print(json.dumps({name: info["bytes"] for name, info in listed.items()}, indent=2))


def main() -> None:
    import torch
    from huggingface_hub import snapshot_download

    if torch.cuda.is_available():
        raise SystemExit("CUDA is visible; export must run with CUDA_VISIBLE_DEVICES=''")
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
    main()
