"""Check one recovered MR DICOM ZIP as a single 3D model-input series.

Header and SimpleITK geometry checks only. DICOM pixels are read by SimpleITK
from a temporary directory and discarded; there is no model preprocessing or
inference. Ambiguous Study/Series UIDs and unsupported geometry fail closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from zipfile import ZipFile

import numpy as np
import pydicom
import SimpleITK as sitk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dicom_geometry import analyze_series
from study_data import is_supported_classic_image


def validate_headers(headers, expected_series_uid: str, expected_frames: int):
    if len(headers) != expected_frames or not headers:
        raise ValueError("DICOM frame count differs from manifest")
    if any(not is_supported_classic_image(ds) or str(ds.Modality).upper() != "MR" for ds in headers):
        raise ValueError("only classic single-frame MR is supported")
    studies = {str(getattr(ds, "StudyInstanceUID", "")) for ds in headers}
    series = {str(getattr(ds, "SeriesInstanceUID", "")) for ds in headers}
    sops = [str(getattr(ds, "SOPInstanceUID", "")) for ds in headers]
    shapes = {(int(ds.Rows), int(ds.Columns)) for ds in headers}
    if (len(studies) != 1 or "" in studies or series != {expected_series_uid}
            or "" in sops or len(set(sops)) != len(sops) or len(shapes) != 1):
        raise ValueError("ambiguous or incomplete DICOM identity/matrix")
    geometry = analyze_series(headers)
    if not (geometry.inplane_spacing_valid and geometry.uniform_z_geometry_valid
            and geometry.sort_indices is not None):
        raise ValueError("patient-space geometry is not a uniform 3D stack")
    return geometry, tuple(headers[i] for i in geometry.sort_indices), shapes.pop()


def preflight(archive_path: Path, case: dict) -> dict:
    digest = hashlib.sha256()
    with archive_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != case["archive_sha256"]:
        raise ValueError("DICOM archive SHA256 differs from manifest")

    with ZipFile(archive_path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".dcm")]
        if len(names) != len(set(names)) or len({Path(name).name for name in names}) != len(names):
            raise ValueError("duplicate DICOM archive members")
        headers = []
        for name in names:
            with archive.open(name) as source:
                headers.append(pydicom.dcmread(source, stop_before_pixels=True))
        geometry, ordered, (rows, columns) = validate_headers(
            headers, case["series_instance_uid"], case["frames"]
        )

        with tempfile.TemporaryDirectory(prefix="neurovfm-series-") as directory:
            series_path = Path(directory)
            for name in names:
                (series_path / Path(name).name).write_bytes(archive.read(name))
            gdcm_series = sitk.ImageSeriesReader.GetGDCMSeriesIDs(directory)
            if gdcm_series != (case["series_instance_uid"],):
                raise ValueError("SimpleITK series selection differs from manifest")
            file_names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(
                directory, case["series_instance_uid"]
            )
            if len(file_names) != len(ordered):
                raise ValueError("SimpleITK omitted DICOM slices")
            reader = sitk.ImageSeriesReader()
            reader.SetFileNames(file_names)
            image = reader.Execute()
            if image.GetSize() != (columns, rows, len(ordered)):
                raise ValueError("SimpleITK volume dimensions differ from DICOM headers")
            errors = [
                float(np.linalg.norm(
                    np.asarray(image.TransformIndexToPhysicalPoint((0, 0, index)))
                    - np.asarray(ds.ImagePositionPatient, dtype=float)
                ))
                for index, ds in enumerate(ordered)
            ]
            max_error = max(errors)
            if max_error > 1e-3:
                raise ValueError("SimpleITK slice origins differ from DICOM patient space")
            return {
                "case_id": case["patient_id"],
                "archive_sha256": digest.hexdigest(),
                "series_uid": case["series_instance_uid"],
                "dicom_frames": len(ordered),
                "volume_shape_zyx": list(reversed(image.GetSize())),
                "spacing_xyz_mm": list(image.GetSpacing()),
                "max_lps_slice_origin_error_mm": max_error,
                "unique_series_directory_required": True,
                "official_preprocessor_call_shape": "load_study([single_series_directory], modality='mri')",
                "preflight_phase_only": True,
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.cases_root / "manifest.json").read_text())
    reports = [preflight(args.cases_root / case["archive"], case) for case in manifest["cases"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, indent=2) + "\n")
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
