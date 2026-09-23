"""One-case technical CPU path: verified DICOM -> official preprocessing -> 74 scores.

Research only. CPU operator substitutions have not been numerically compared
against the official GPU kernels; scores are not validated clinical outputs.
No segmentation mask or lesion-level classification is produced.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import resource
import signal
import sys
import tempfile
import time
from types import ModuleType
from zipfile import ZipFile

from neurovfm_static_audit import audit
from neurovfm_cpu_encoder_probe import _build_cpu_class
from neurovfm_cpu_head_probe import _load_official_head
from neurovfm_dicom_input_preflight import preflight


def _load_official_preprocessor(source_root: Path):
    for package, directory in (
        ("neurovfm", source_root / "neurovfm"),
        ("neurovfm.data", source_root / "neurovfm/data"),
        ("neurovfm.pipelines", source_root / "neurovfm/pipelines"),
        ("neurovfm.systems", source_root / "neurovfm/systems"),
    ):
        module = ModuleType(package)
        module.__path__ = [str(directory)]
        sys.modules[package] = module
    paths = (
        ("neurovfm.data.utils", "neurovfm/data/utils.py"),
        ("neurovfm.data.io", "neurovfm/data/io.py"),
        ("neurovfm.data.preprocess", "neurovfm/data/preprocess.py"),
        ("neurovfm.pipelines.preprocessor", "neurovfm/pipelines/preprocessor.py"),
        ("neurovfm.systems.utils", "neurovfm/systems/utils.py"),
    )
    for name, relative in paths:
        path = source_root / relative
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load pinned source: {relative}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return (sys.modules["neurovfm.pipelines.preprocessor"].StudyPreprocessor,
            sys.modules["neurovfm.systems.utils"].NormalizationModule)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-root", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--encoder", required=True, type=Path)
    parser.add_argument("--diagnostic", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--position-wheel", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    signal.alarm(900)
    case = next((item for item in json.loads((args.cases_root / "manifest.json").read_text())["cases"]
                 if item["patient_id"] == args.case_id), None)
    if case is None:
        raise ValueError("case ID absent from recovered public-case manifest")
    archive_path = args.cases_root / case["archive"]
    dicom_report = preflight(archive_path, case)
    contract = audit(args.encoder, args.diagnostic, args.source_root)
    if not contract["all_checks_passed"]:
        raise ValueError("pinned source/checkpoint contract failed")

    import torch

    torch.set_num_threads(4)
    model_class = _build_cpu_class(args.source_root, args.position_wheel)
    encoder_config = json.loads((args.encoder.parent / "config.json").read_text())
    encoder = model_class(**encoder_config["params"]).eval()
    encoder.load_state_dict(torch.load(args.encoder, map_location="cpu", weights_only=True, mmap=True), strict=True)
    head_config = json.loads((args.diagnostic.parent / "config.json").read_text())
    head = _load_official_head(args.source_root)(dim=768, **head_config["params"]).eval()
    head.load_state_dict(torch.load(args.diagnostic, map_location="cpu", weights_only=True, mmap=True), strict=True)
    preprocessor_class, normalization_class = _load_official_preprocessor(args.source_root)
    normalization = normalization_class(custom_stats_list=encoder_config.get("normalization_stats"))

    with tempfile.TemporaryDirectory(prefix="neurovfm-single-series-") as directory:
        series_dir = Path(directory)
        with ZipFile(archive_path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".dcm"):
                    (series_dir / Path(name).name).write_bytes(archive.read(name))
        started = time.monotonic()
        batch = preprocessor_class().load_study([series_dir], modality="mri")
        preprocess_seconds = time.monotonic() - started
        tokens = batch["img"]
        coords = batch["coords"]
        if (batch["mode"] != ["mri"] or tokens.ndim != 2 or tokens.shape[1] != 1024
                or coords.shape != (len(tokens), 3)
                or batch["series_cu_seqlens"].tolist() != [0, len(tokens)]
                or batch["study_cu_seqlens"].tolist() != [0, len(tokens)]
                or not torch.isfinite(tokens).all()):
            raise ValueError("official preprocessor produced an invalid single-series batch")
        normalized = normalization.normalize(tokens.clone(), batch["mode"], batch["path"],
                                             cu_seqlens=batch["series_cu_seqlens"], sizes=batch["size"])
        started = time.monotonic()
        with torch.inference_mode(), torch.autocast("cpu", dtype=torch.bfloat16):
            features = encoder(normalized, coords, cu_seqlens=batch["series_cu_seqlens"],
                               max_seqlen=batch["series_max_len"], use_flash_attn=False)
            scores = head(features, cu_seqlens=batch["study_cu_seqlens"],
                          max_seqlen=batch["study_max_len"])
            values = torch.sigmoid(scores).float().cpu()
        forward_seconds = time.monotonic() - started
    if features.shape != (len(tokens), 768) or values.shape != (1, 74) or not torch.isfinite(values).all():
        raise ValueError("invalid full-chain technical output")
    peak_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        peak_rss_bytes *= 1024
    if peak_rss_bytes > 12 * 1024**3:
        raise ValueError("technical probe exceeded 12 GiB peak RSS")

    result = {
        "status": "technical_research_unvalidated_not_diagnostic",
        "case_id": case["patient_id"],
        "source_commit": contract["source"]["commit"],
        "encoder_sha256": contract["encoder"]["sha256"],
        "diagnostic_sha256": contract["diagnostic"]["sha256"],
        "dicom_input": dicom_report,
        "official_preprocessing": True,
        "preprocessed_volume_size_dhw": batch["size"][0],
        "foreground_tokens": len(tokens),
        "preprocess_seconds": round(preprocess_seconds, 3),
        "cpu_forward_seconds": round(forward_seconds, 3),
        "peak_rss_bytes": peak_rss_bytes,
        "cpu_operator_substitutions_numerically_validated": False,
        "lesion_mask_or_type_produced": False,
        "study_level_uncalibrated_scores": dict(zip(contract["mri_labels"], values[0].tolist(), strict=True)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key != "study_level_uncalibrated_scores"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
