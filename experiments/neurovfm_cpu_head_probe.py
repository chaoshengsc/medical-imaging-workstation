"""Run the pinned official NeuroVFM MRI diagnostic head on synthetic CPU features.

Only FusedDense and torch_scatter.segment_csr are replaced with explicit CPU
equivalents. The upstream ClassifyThenAggregate.forward is executed unchanged.
This does not exercise the image encoder, DICOM preprocessor, or real cases.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from neurovfm_static_audit import audit


def segment_csr(src, indptr, reduce):
    """CPU reference for the nonempty one-dimensional segments used by this head."""
    import torch

    if src.ndim != 1 or indptr.ndim != 1 or reduce not in {"max", "sum"}:
        raise ValueError("unsupported segment request")
    boundaries = indptr.tolist()
    if (not boundaries or boundaries[0] != 0 or boundaries[-1] != len(src)
            or any(left >= right for left, right in zip(boundaries, boundaries[1:]))):
        raise ValueError("expected nonempty contiguous segments")
    parts = [src[left:right] for left, right in zip(boundaries, boundaries[1:])]
    return torch.stack([part.max() if reduce == "max" else part.sum() for part in parts])


def _load_official_head(source_root: Path):
    import torch.nn as nn

    root = ModuleType("neurovfm")
    root.__path__ = [str(source_root / "neurovfm")]
    models = ModuleType("neurovfm.models")
    models.__path__ = [str(source_root / "neurovfm/models")]
    sys.modules["neurovfm"] = root
    sys.modules["neurovfm.models"] = models
    for name in ("projector", "mil"):
        path = source_root / "neurovfm/models" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"neurovfm.models.{name}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load pinned official source: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    mil = sys.modules["neurovfm.models.mil"]
    mil.FusedDense = nn.Linear
    mil.torch_scatter = SimpleNamespace(segment_csr=segment_csr)
    return mil.ClassifyThenAggregate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", required=True, type=Path)
    parser.add_argument("--diagnostic", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    contract = audit(args.encoder, args.diagnostic, args.source_root)
    if not contract["all_checks_passed"]:
        raise ValueError("pinned source/checkpoint contract failed")

    import torch

    torch.set_num_threads(4)
    head_class = _load_official_head(args.source_root)
    config = json.loads((args.diagnostic.parent / "config.json").read_text())
    head = head_class(dim=768, **config["params"]).eval()
    weights = torch.load(args.diagnostic, map_location="cpu", weights_only=True, mmap=True)
    head.load_state_dict(weights, strict=True)

    torch.manual_seed(923)
    features = torch.randn(8, 768)
    boundaries = torch.tensor([0, 3, 8], dtype=torch.long)
    with torch.inference_mode():
        output, attention, patch_logits = head(features, cu_seqlens=boundaries, return_logits=True)
        separate = torch.cat([
            head(features[:3], cu_seqlens=torch.tensor([0, 3])),
            head(features[3:], cu_seqlens=torch.tensor([0, 5])),
        ])
    if output.shape != (2, 74) or attention.shape != (8, 74) or patch_logits.shape != (8, 74):
        raise ValueError("unexpected diagnostic-head output shape")
    if not torch.isfinite(output).all():
        raise ValueError("diagnostic-head output is nonfinite")
    attention_error = max(
        (attention[left:right].sum(dim=0) - 1).abs().max().item()
        for left, right in ((0, 3), (3, 8))
    )
    split_error = (output - separate).abs().max().item()
    if attention_error > 1e-5 or split_error > 1e-5:
        raise ValueError("segmented batch output differs from individual series")
    try:
        head.load_state_dict({key: value for key, value in weights.items() if key != "W.bias"}, strict=True)
    except RuntimeError:
        missing_key_rejected = True
    else:
        raise ValueError("strict load accepted a missing key")

    report = {
        "source_commit": contract["source"]["commit"],
        "head_sha256": contract["diagnostic"]["sha256"],
        "torch_version": torch.__version__,
        "threads": torch.get_num_threads(),
        "input": "synthetic Gaussian patch features, lengths 3 and 5; no patient data",
        "official_head_source_executed": True,
        "cpu_substitutions": ["FusedDense -> torch.nn.Linear", "segment_csr -> segmented PyTorch max/sum"],
        "strict_weight_load": True,
        "missing_key_rejected": missing_key_rejected,
        "output_shape": list(output.shape),
        "max_attention_sum_error": attention_error,
        "max_split_output_error": split_error,
        "encoder_or_preprocessor_executed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
