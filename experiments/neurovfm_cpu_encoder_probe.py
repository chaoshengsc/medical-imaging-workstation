"""Isolated CPU encoder probe using pinned NeuroVFM source and synthetic tokens.

The official class bodies are extracted by AST. Only GPU-only fused operators
are supplied with explicit CPU stand-ins; no upstream file or package is edited.
Successful execution is a technical smoke test, not numerical equivalence to
FlashAttention or a patient-level result.
"""

from __future__ import annotations

import argparse
import ast
from functools import partial
import hashlib
import json
import math
from pathlib import Path
import signal
import sys
import warnings

from neurovfm_static_audit import audit
from neurovfm_cpu_head_probe import _load_official_head


_POSITION_WHEEL_SHA256 = "714135704d54f42adc77585d54747e9d42580e03746ca90441e869ba7b3fc324"


def _extract(source: Path, names: set[str], namespace: dict) -> None:
    tree = ast.parse(source.read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    if {node.name for node in selected} != names:
        raise ValueError(f"missing required upstream class/function in {source}")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)


def _build_cpu_class(source_root: Path, wheel: Path):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from einops import rearrange
    from torch.nn.init import trunc_normal_
    from torch.nn.modules.utils import _pair
    from torch.utils.checkpoint import checkpoint
    from torchvision.ops import StochasticDepth

    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != _POSITION_WHEEL_SHA256:
        raise ValueError("positional-encodings wheel SHA256 differs from pinned value")
    sys.path.insert(0, str(wheel))
    from positional_encodings.torch_encodings import PositionalEncoding3D

    class CPUFusedMLP(nn.Module):
        def __init__(self, in_features, hidden_features, checkpoint_lvl=2, return_residual=False):
            super().__init__()
            if return_residual:
                raise ValueError("unsupported residual MLP")
            self.fc1 = nn.Linear(in_features, hidden_features)
            self.fc2 = nn.Linear(hidden_features, in_features)

        def forward(self, x):
            return self.fc2(F.gelu(self.fc1(x), approximate="tanh"))

    def cpu_layer_norm_fn(x, weight, bias, *, residual=None, eps=1e-6,
                          dropout_p=0.0, rowscale=None, prenorm=False,
                          residual_in_fp32=False, is_rms_norm=False):
        if dropout_p != 0 or rowscale is not None or is_rms_norm:
            raise ValueError("CPU probe only supports eval LayerNorm")
        combined = x.float() if residual is None else residual.float() + x.float()
        normalized = F.layer_norm(combined, (x.shape[-1],), weight.float(), bias.float(), eps).to(x.dtype)
        return (normalized, combined) if prenorm else normalized

    namespace = {
        "torch": torch, "nn": nn, "F": F, "math": math, "warnings": warnings,
        "partial": partial, "Dict": dict, "Optional": __import__("typing").Optional,
        "Tuple": __import__("typing").Tuple, "trunc_normal_": trunc_normal_,
        "StochasticDepth": StochasticDepth, "FusedDense": nn.Linear,
        "FusedMLP": CPUFusedMLP, "layer_norm_fn": cpu_layer_norm_fn,
        "RMSNorm": type("UnsupportedRMSNorm", (), {}), "checkpoint": checkpoint,
        "PositionalEncoding3D": PositionalEncoding3D, "rearrange": rearrange,
        "MLP_CHECKPOINT_LVL": 2, "_pair": _pair,
    }
    models = source_root / "neurovfm/models"
    _extract(models / "patch_embed.py", {"PatchEmbed"}, namespace)
    _extract(models / "pos_embed.py", {"PositionalEncoding3DWrapper"}, namespace)
    _extract(models / "vit.py", {
        "pad_packed", "unpad_packed", "SelfAttention", "Block",
        "TransformerEncoder", "VisionTransformer",
    }, namespace)
    return namespace["VisionTransformer"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", required=True, type=Path)
    parser.add_argument("--diagnostic", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--position-wheel", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    signal.alarm(900)
    contract = audit(args.encoder, args.diagnostic, args.source_root)
    if not contract["all_checks_passed"]:
        raise ValueError("pinned source/checkpoint contract failed")

    import torch

    torch.set_num_threads(4)
    model_class = _build_cpu_class(args.source_root, args.position_wheel)
    config = json.loads((args.encoder.parent / "config.json").read_text())
    model = model_class(**config["params"]).eval()
    weights = torch.load(args.encoder, map_location="cpu", weights_only=True, mmap=True)
    model.load_state_dict(weights, strict=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)

    torch.manual_seed(923)
    token_dim = 4 * 16 * 16
    tokens = torch.randn(8, token_dim)
    coords = torch.tensor([[0, 0, 0], [0, 0, 1], [0, 1, 0], [0, 0, 0],
                           [0, 0, 1], [0, 1, 0], [1, 0, 0], [1, 1, 1]], dtype=torch.long)
    boundaries = torch.tensor([0, 3, 8], dtype=torch.int32)
    with torch.inference_mode(), torch.autocast("cpu", dtype=torch.bfloat16):
        features = model(tokens, coords, cu_seqlens=boundaries, max_seqlen=5, use_flash_attn=False)
        first = model(tokens[:3], coords[:3], cu_seqlens=torch.tensor([0, 3], dtype=torch.int32),
                      max_seqlen=3, use_flash_attn=False)
        second = model(tokens[3:], coords[3:], cu_seqlens=torch.tensor([0, 5], dtype=torch.int32),
                       max_seqlen=5, use_flash_attn=False)
    if features.shape != (8, 768) or not torch.isfinite(features).all():
        raise ValueError("invalid encoder synthetic features")
    split_error = (features.float() - torch.cat([first, second]).float()).abs().max().item()
    if split_error > 0.1:
        raise ValueError("packed and individual sequence features differ too much")

    head_config = json.loads((args.diagnostic.parent / "config.json").read_text())
    head = _load_official_head(args.source_root)(dim=768, **head_config["params"]).eval()
    head_weights = torch.load(args.diagnostic, map_location="cpu", weights_only=True, mmap=True)
    head.load_state_dict(head_weights, strict=True)
    with torch.inference_mode():
        study_scores = head(features.float(), cu_seqlens=boundaries.long())
    if study_scores.shape != (2, 74) or not torch.isfinite(study_scores).all():
        raise ValueError("invalid synthetic study-level scores")
    try:
        model.load_state_dict({key: value for key, value in weights.items() if key != "norm.bias"}, strict=True)
    except RuntimeError:
        missing_key_rejected = True
    else:
        raise ValueError("strict encoder load accepted a missing key")

    report = {
        "source_commit": contract["source"]["commit"],
        "encoder_sha256": contract["encoder"]["sha256"],
        "position_wheel_sha256": _POSITION_WHEEL_SHA256,
        "torch_version": torch.__version__,
        "threads": torch.get_num_threads(),
        "input": "synthetic Gaussian voxel-patch tokens, lengths 3 and 5; no patient data",
        "strict_weight_load": True,
        "missing_encoder_key_rejected": missing_key_rejected,
        "cpu_substitutions": ["FusedDense -> Linear", "FusedMLP -> Linear/GELU(tanh)/Linear",
                              "fused residual LayerNorm -> explicit FP32 residual and PyTorch LayerNorm"],
        "output_shape": list(features.shape),
        "study_score_shape": list(study_scores.shape),
        "max_split_feature_error": split_error,
        "official_flashattention_numerical_equivalence_proved": False,
        "real_mri_executed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
