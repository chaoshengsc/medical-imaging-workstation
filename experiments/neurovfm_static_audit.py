"""Inspect the two pinned NeuroVFM checkpoints without importing torch or unpickling.

This is a research artifact, not a model loader. It accepts only the restricted
pickle opcode/global set seen in the pinned checkpoints and never reads tensor
payloads. A structural match does not establish numerical or clinical validity.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import pickletools
import zipfile


_MARK = object()
_GLOBALS = {
    "collections OrderedDict",
    "torch._utils _rebuild_tensor_v2",
    "torch BFloat16Storage",
    "torch FloatStorage",
}
_DTYPE_BYTES = {"BFloat16Storage": 2, "FloatStorage": 4}
_ENCODER_SHA256 = "744cf058edf34be85118dd2b5410da6fa50dc0ebad648c73ead86eceb1398fc7"
_DIAGNOSTIC_SHA256 = "e3db6eee69db0d7ef291c1a9ed6de5a9ab4dd417d3fc10b184b43c012329492b"
_SOURCE_COMMIT = "9240021d4ef5c262b21cee5d219c2adf65f4d42f"


def _take_mark(stack: list[object]) -> list[object]:
    for index in range(len(stack) - 1, -1, -1):
        if stack[index] is _MARK:
            values = stack[index + 1 :]
            del stack[index:]
            return values
    raise ValueError("pickle MARK missing")


def parse_tensor_metadata(data: bytes) -> dict[str, dict]:
    """Interpret only the metadata subset of a PyTorch ZIP pickle.

    In particular this function never invokes pickle.load, a GLOBAL, or a
    tensor rebuild function. Unknown opcodes/globals fail closed.
    """
    if len(data) > 1_000_000:
        raise ValueError("checkpoint metadata exceeds 1 MB")
    stack: list[object] = []
    memo: dict[int, object] = {}
    stopped = False
    for opcode, argument, _ in pickletools.genops(data):
        name = opcode.name
        if name == "PROTO":
            if argument != 2:
                raise ValueError("unsupported pickle protocol")
        elif name == "EMPTY_DICT":
            stack.append({})
        elif name == "EMPTY_TUPLE":
            stack.append(())
        elif name == "MARK":
            stack.append(_MARK)
        elif name == "BINUNICODE":
            stack.append(argument)
        elif name in {"BININT", "BININT1", "BININT2"}:
            stack.append(argument)
        elif name == "NEWFALSE":
            stack.append(False)
        elif name == "GLOBAL":
            if argument not in _GLOBALS:
                raise ValueError(f"disallowed pickle GLOBAL: {argument}")
            stack.append(("global", argument))
        elif name in {"BINPUT", "LONG_BINPUT"}:
            if not stack:
                raise ValueError("pickle memo has empty stack")
            memo[argument] = stack[-1]
        elif name == "BINGET":
            stack.append(memo[argument])
        elif name == "TUPLE":
            stack.append(tuple(_take_mark(stack)))
        elif name == "TUPLE1":
            stack.append((stack.pop(),))
        elif name == "TUPLE2":
            right, left = stack.pop(), stack.pop()
            stack.append((left, right))
        elif name == "BINPERSID":
            descriptor = stack.pop()
            if not isinstance(descriptor, tuple) or len(descriptor) != 5:
                raise ValueError("unexpected persistent storage descriptor")
            tag, dtype_global, key, device, length = descriptor
            if tag != "storage" or device != "cpu" or not isinstance(key, str):
                raise ValueError("unexpected storage identity")
            if dtype_global not in {
                ("global", "torch BFloat16Storage"),
                ("global", "torch FloatStorage"),
            } or not isinstance(length, int) or length < 0:
                raise ValueError("unexpected storage type or length")
            stack.append({"storage_key": key, "dtype": dtype_global[1].split()[-1], "length": length})
        elif name == "REDUCE":
            args = stack.pop()
            function = stack.pop()
            if function == ("global", "collections OrderedDict") and args == ():
                stack.append(OrderedDict())
            elif function == ("global", "torch._utils _rebuild_tensor_v2"):
                if not isinstance(args, tuple) or len(args) != 6:
                    raise ValueError("unexpected tensor rebuild arguments")
                storage, offset, shape, stride, requires_grad, hooks = args
                if not isinstance(storage, dict) or not isinstance(offset, int):
                    raise ValueError("unexpected tensor storage or offset")
                if not isinstance(shape, tuple) or not isinstance(stride, tuple):
                    raise ValueError("unexpected tensor shape or stride")
                if any(not isinstance(x, int) or x < 0 for x in shape + stride):
                    raise ValueError("invalid tensor dimensions")
                if requires_grad is not False or not isinstance(hooks, OrderedDict):
                    raise ValueError("unexpected tensor rebuild flags")
                if len(shape) != len(stride):
                    raise ValueError("shape/stride rank mismatch")
                last_index = offset + sum((dim - 1) * step for dim, step in zip(shape, stride))
                if offset < 0 or last_index >= storage["length"]:
                    raise ValueError("tensor view exceeds storage")
                stack.append({**storage, "offset": offset, "shape": list(shape), "stride": list(stride)})
            else:
                raise ValueError("disallowed pickle REDUCE")
        elif name == "SETITEM":
            value, key = stack.pop(), stack.pop()
            mapping = stack[-1]
            if not isinstance(mapping, dict) or key in mapping:
                raise ValueError("invalid or repeated pickle key")
            mapping[key] = value
        elif name == "SETITEMS":
            items = _take_mark(stack)
            mapping = stack[-1]
            if not isinstance(mapping, dict) or len(items) % 2:
                raise ValueError("invalid pickle SETITEMS")
            for key, value in zip(items[::2], items[1::2]):
                if key in mapping:
                    raise ValueError("repeated checkpoint key")
                mapping[key] = value
        elif name == "BUILD":
            state = stack.pop()
            if not isinstance(stack[-1], OrderedDict) or not isinstance(state, dict):
                raise ValueError("unexpected checkpoint BUILD")
            if set(state) != {"_metadata"}:
                raise ValueError("unexpected checkpoint metadata")
        elif name == "STOP":
            stopped = True
            break
        else:
            raise ValueError(f"disallowed pickle opcode: {name}")
    if not stopped or len(stack) != 1 or not isinstance(stack[0], dict):
        raise ValueError("invalid checkpoint top level")
    result = stack[0]
    if not result or any(not isinstance(key, str) or not isinstance(value, dict)
                         or "shape" not in value for key, value in result.items()):
        raise ValueError("checkpoint must contain only named tensors")
    return result


def inspect_checkpoint(path: Path, expected_sha256: str) -> tuple[dict, str]:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    actual_sha256 = sha.hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"checkpoint SHA256 differs from pinned value: {path.name}")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        pickle_names = [name for name in names if name.endswith("/data.pkl")]
        if len(pickle_names) != 1:
            raise ValueError("checkpoint must contain one data.pkl")
        info = archive.getinfo(pickle_names[0])
        if info.file_size > 1_000_000:
            raise ValueError("checkpoint metadata exceeds 1 MB")
        tensors = parse_tensor_metadata(archive.read(pickle_names[0]))
        prefix = pickle_names[0].removesuffix("data.pkl") + "data/"
        for tensor in tensors.values():
            member = prefix + tensor["storage_key"]
            if member not in names:
                raise ValueError(f"missing tensor storage: {member}")
            expected = tensor["length"] * _DTYPE_BYTES[tensor["dtype"]]
            if archive.getinfo(member).file_size != expected:
                raise ValueError(f"storage size mismatch: {member}")
    return tensors, actual_sha256


def _verify_source_manifest(source_root: Path) -> dict:
    manifest = json.loads(Path(__file__).with_name("neurovfm_static_source_manifest.json").read_text())
    if manifest.get("commit") != _SOURCE_COMMIT or manifest.get("repo") != "MLNeurosurg/neurovfm":
        raise ValueError("source revision is not the pinned upstream revision")
    for item in manifest["files"]:
        data = (source_root / item["path"]).read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if digest != item["git_blob"] or len(data) != item["bytes"]:
            raise ValueError(f"source file changed: {item['path']}")
    return {"repository": manifest["repo"], "commit": manifest["commit"], "files_verified": len(manifest["files"])}


def audit(encoder: Path, diagnostic: Path, source_root: Path) -> dict:
    source = _verify_source_manifest(source_root)
    encoder_config = json.loads((encoder.parent / "config.json").read_text())
    diagnostic_config = json.loads((diagnostic.parent / "config.json").read_text())
    labels_path = source_root / "neurovfm/pipelines/resources/mri_label_names.txt"
    labels = [item.strip() for item in labels_path.read_text().splitlines() if item.strip()]
    enc, enc_sha = inspect_checkpoint(encoder, _ENCODER_SHA256)
    dx, dx_sha = inspect_checkpoint(diagnostic, _DIAGNOSTIC_SHA256)
    dim = encoder_config["params"]["embed_dim"]
    depth = encoder_config["params"]["depth"]
    patch = encoder_config["params"]["embed_layer_cf"]["params"]
    position = encoder_config["params"]["pos_emb_cf"]["params"]
    classes = diagnostic_config["params"]["W_out"]
    hidden = diagnostic_config["params"]["hidden_dim"]
    mlp_hidden = diagnostic_config["params"]["mlp_hidden_dims"]
    encoder_expected = {
        "norm.weight": [dim], "norm.bias": [dim],
        "token_embed.proj.weight": [patch["embed_dim"], patch["in_chans"] * patch["patch_d_size"] * patch["patch_hw_size"] ** 2],
        "token_embed.proj.bias": [patch["embed_dim"]],
    }
    for i in range(depth):
        encoder_expected.update({
            f"blocks.{i}.mixer.qkv.weight": [3 * dim, dim],
            f"blocks.{i}.mixer.qkv.bias": [3 * dim],
            f"blocks.{i}.mixer.proj.weight": [dim, dim],
            f"blocks.{i}.norm1.weight": [dim],
            f"blocks.{i}.norm1.bias": [dim],
            f"blocks.{i}.norm2.weight": [dim],
            f"blocks.{i}.norm2.bias": [dim],
            f"blocks.{i}.mlp.fc1.weight": [4 * dim, dim],
            f"blocks.{i}.mlp.fc1.bias": [4 * dim],
            f"blocks.{i}.mlp.fc2.weight": [dim, 4 * dim],
            f"blocks.{i}.mlp.fc2.bias": [dim],
        })
    diagnostic_expected = {
        "output_bias": [classes], "output_scale": [classes],
        "attention_V.weight": [hidden, dim], "attention_V.bias": [hidden],
        "gating_V.weight": [hidden, dim], "gating_V.bias": [hidden],
        "W.weight": [classes, hidden], "W.bias": [classes],
        "norm_attn.weight": [dim], "norm_attn.bias": [dim],
        "norm_mlp.weight": [dim], "norm_mlp.bias": [dim],
    }
    mlp_dimensions = [dim, *mlp_hidden, classes]
    for layer, (input_dim, output_dim) in enumerate(zip(mlp_dimensions[:-1], mlp_dimensions[1:])):
        module_index = layer * 2
        diagnostic_expected[f"mlp.mlp.{module_index}.weight"] = [output_dim, input_dim]
        diagnostic_expected[f"mlp.mlp.{module_index}.bias"] = [output_dim]
    checks = {
        "encoder_sha256_pinned": enc_sha == _ENCODER_SHA256,
        "diagnostic_sha256_pinned": dx_sha == _DIAGNOSTIC_SHA256,
        "encoder_is_vit": encoder_config["which"] == "vit",
        "head_is_classify_then_aggregate": diagnostic_config["which"] == "classify_then_aggregate",
        "embedding_plus_position": patch["embed_dim"] + position["d"] == dim,
        "encoder_exact_keys_and_shapes": {key: value["shape"] for key, value in enc.items()} == encoder_expected,
        "diagnostic_label_count": len(labels) == classes == diagnostic_config["params"]["mlp_out_dim"],
        "diagnostic_labels_unique": len(labels) == len(set(labels)),
        "diagnostic_exact_keys_and_shapes": {key: value["shape"] for key, value in dx.items()} == diagnostic_expected,
    }
    return {
        "method": "restricted_pickle_metadata_only; no torch import, unpickle, or tensor payload read",
        "source": source,
        "encoder": {"sha256": enc_sha, "tensor_count": len(enc), "tensors": enc},
        "diagnostic": {"sha256": dx_sha, "tensor_count": len(dx), "tensors": dx},
        "mri_labels": labels,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", required=True, type=Path)
    parser.add_argument("--diagnostic", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.encoder, args.diagnostic, args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("encoder tensors", result["encoder"]["tensor_count"])
    print("diagnostic tensors", result["diagnostic"]["tensor_count"])
    print("MRI labels", len(result["mri_labels"]))
    for name, passed in result["checks"].items():
        print("PASS" if passed else "FAIL", name)
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
