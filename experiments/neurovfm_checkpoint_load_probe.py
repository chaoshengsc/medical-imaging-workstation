"""CPU-only, weights-only load probe for the two pinned NeuroVFM state dicts.

This is not model construction or inference. Run it in an isolated Python
environment where importing torch is known to work; no package is installed.
The static auditor verifies the pinned file hashes before torch.load is called.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from neurovfm_static_audit import audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", required=True, type=Path)
    parser.add_argument("--diagnostic", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    contract = audit(args.encoder, args.diagnostic, args.source_root)
    if not contract["all_checks_passed"]:
        raise ValueError("pinned checkpoint/source contract failed before torch load")

    import torch

    torch.set_num_threads(4)
    report = {
        "method": "torch.load(map_location='cpu', weights_only=True, mmap=True); no model or forward",
        "torch_version": torch.__version__,
        "threads": torch.get_num_threads(),
        "source_commit": contract["source"]["commit"],
        "checkpoints": {},
    }
    for role, path in (("encoder", args.encoder), ("diagnostic", args.diagnostic)):
        started = time.monotonic()
        state = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
        expected = contract[role]["tensors"]
        if not isinstance(state, dict) or set(state) != set(expected):
            raise ValueError(f"{role}: loaded keys differ from static audit")
        for name, tensor in state.items():
            meta = expected[name]
            dtype = torch.bfloat16 if meta["dtype"] == "BFloat16Storage" else torch.float32
            if (not isinstance(tensor, torch.Tensor) or tensor.device.type != "cpu"
                    or tensor.dtype != dtype or list(tensor.shape) != meta["shape"]):
                raise ValueError(f"{role}: loaded tensor metadata differs: {name}")
        report["checkpoints"][role] = {
            "sha256": contract[role]["sha256"],
            "tensor_count": len(state),
            "element_count": sum(item.numel() for item in state.values()),
            "dtype_counts": {
                "bfloat16": sum(item.dtype == torch.bfloat16 for item in state.values()),
                "float32": sum(item.dtype == torch.float32 for item in state.values()),
            },
            "load_and_verify_seconds": round(time.monotonic() - started, 3),
        }
        del state
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
