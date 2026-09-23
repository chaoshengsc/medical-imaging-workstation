"""Isolated, source-bound KCL VS-Seg T1 worker and file protocol.

Importing this module never imports Torch or MONAI. The CLI is intended to run
in a dedicated CPU environment, outside the Qt process. It writes only a
candidate mask; the product execution/adoption gates remain separate.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tumor_model_admission import (
    KCL_VS_SEG_T1_CODE_COMMIT,
    KCL_VS_SEG_T1_MODEL_ID,
    KCL_VS_SEG_T1_POSTPROCESS_DIGEST,
    KCL_VS_SEG_T1_PREPROCESS_DIGEST,
    KCL_VS_SEG_T1_TASK_VARIANT,
    KCL_VS_SEG_T1_UPSTREAM_REQUIREMENTS_DIGEST,
    KCL_VS_SEG_T1_WEIGHT_DIGEST,
    OFFICIAL_VS_T1_MODEL_SPACE,
    SourceBinding,
)
from vs_seg_t1_adapter import VST1PreparedImage, restore_vs_t1_mask

PROTOCOL_VERSION = 1
ROI_SIZE_XYZ = OFFICIAL_VS_T1_MODEL_SPACE.sliding_window
SW_BATCH_SIZE = 1
SW_OVERLAP = 0.25
SW_MODE = "gaussian"
SW_SIGMA_SCALE = 0.125
TARGET_CHANNEL_INDEX = 1
MODEL_OUTPUT_CHANNELS = 2
INPUT_FILE_NAME = "input.npy"
REQUEST_FILE_NAME = "request.json"
MASK_FILE_NAME = "mask.npy"
RESPONSE_FILE_NAME = "response.json"
WEIGHTS_ZIP_SHA256 = "b83619d9ee475c862a2038eda3ff81282c3c33104e22d714b6b7ab892e53a774"
CHECKPOINT_MEMBER = "UNet2d5_Att_Hard_T1_final/model/best_metric_model.pth"
EXPECTED_STATE_DICT_ENTRIES = 256
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# Fixed KCL files used by the network import path, plus the upstream parameter
# file whose architecture and inference settings this worker implements.
_KCL_SOURCE_FILES = {
    "params/__init__.py": (
        "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "params/networks/__init__.py": (
        "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "params/networks/blocks/__init__.py": (
        "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "params/networks/blocks/attentionblock.py": (
        "e6d938d43e3011798c10ef5678087304e60e4eb8",
        "7a5a73cc500578040a4ab4c80c19cf9e5a7d844594d45789e71bd980e6e3d2aa",
    ),
    "params/networks/blocks/convolutions.py": (
        "1497ef530ee4803ee9315a08b1296e745753eaa1",
        "5840c02d4e743269eac04ba0ba8952586cc83c31c8164d58f44570046d08e5b2",
    ),
    "params/networks/nets/__init__.py": (
        "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "params/networks/nets/unet2d5_spvPA.py": (
        "f656f562974961668745e51cc3cb1f63af93b1e6",
        "b3f0f3cad14c97a825d432fc6a544943a148c16faa8b24b613c68995079f9945",
    ),
    "params/VSparams.py": (
        "859c54842124f8d992a13e32e607f2654c639981",
        "f7b98181bea8821b7d911af1f76e1d709737b0d8e8beb09608e1d37bfa0a3b21",
    ),
}


class VSWorkerProtocolError(ValueError):
    """A staged job or worker reply failed its fixed protocol contract."""

    def __init__(self, failed_gates):
        self.failed_gates = tuple(failed_gates)
        super().__init__("VS-Seg worker protocol rejected: " + ", ".join(self.failed_gates))


@dataclass(frozen=True)
class StagedVSWorkerJob:
    """Parent-side receipt for a staged job; the request bytes are immutable."""

    job_dir: Path
    request_json: bytes

    @property
    def request(self):
        return _strict_json_loads(self.request_json)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path):
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise VSWorkerProtocolError(("file_read",)) from None
    return digest.hexdigest()


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _strict_json_loads(data):
    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise VSWorkerProtocolError(("duplicate_json_key",))
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=reject_duplicate_keys,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              VSWorkerProtocolError(("nonfinite_json_number",))))
    except VSWorkerProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise VSWorkerProtocolError(("invalid_json",)) from None


def _array_sha256(array, dtype):
    canonical = np.ascontiguousarray(np.asarray(array, dtype=dtype))
    return _sha256(canonical.tobytes(order="C"))


def _affine_sha256(affine):
    value = np.asarray(affine, dtype="<f8")
    if value.shape != (4, 4) or not np.all(np.isfinite(value)):
        raise VSWorkerProtocolError(("model_affine",))
    return _sha256(np.ascontiguousarray(value).tobytes(order="C"))


def _binding_sha256(binding):
    if not isinstance(binding, SourceBinding):
        raise VSWorkerProtocolError(("source_binding",))
    payload = {
        "study_instance_uid": binding.study_instance_uid,
        "series_instance_uid": binding.series_instance_uid,
        "source_digest": binding.source_digest,
        "geometry_digest": binding.geometry_digest,
        "ordered_sop_digest": binding.ordered_sop_digest,
    }
    return _sha256(_canonical_json(payload))


def _positive_int_list(value, length):
    return (isinstance(value, list) and len(value) == length
            and all(isinstance(item, int) and not isinstance(item, bool) and item > 0
                    for item in value))


_REQUEST_FIELDS = frozenset({
    "protocol_version", "job_id", "status", "model_id", "model_version",
    "task_variant", "weights_sha256", "upstream_requirements_sha256",
    "preprocess_sha256", "postprocess_sha256", "request_sha256",
    "source_binding_sha256", "dicom_rescale_sha256", "model_affine_sha256",
    "input_file", "input_file_sha256", "input_array_sha256", "input_dtype",
    "input_shape_cxyz", "source_shape_zyx", "input_axes", "model_axis_codes",
    "roi_size_xyz", "sw_batch_size", "sw_overlap", "sw_mode",
    "sw_sigma_scale", "output_channels", "target_channel_index",
    "output_axes", "output_kind", "type_status", "type_scope",
})

_RESPONSE_FIELDS = frozenset({
    "protocol_version", "job_id", "status", "model_id", "model_version",
    "task_variant", "weights_sha256", "upstream_requirements_sha256",
    "preprocess_sha256", "postprocess_sha256", "request_sha256",
    "source_binding_sha256", "dicom_rescale_sha256", "model_affine_sha256",
    "input_file_sha256", "output_file", "output_file_sha256",
    "output_array_sha256", "output_dtype", "output_shape_xyz", "output_axes",
    "output_kind", "target_channel_index", "output_values", "type_status",
    "type_scope",
})


def _validate_request_document(request):
    if not isinstance(request, dict) or set(request) != _REQUEST_FIELDS:
        raise VSWorkerProtocolError(("request_schema",))
    if request["protocol_version"] != PROTOCOL_VERSION:
        raise VSWorkerProtocolError(("protocol_version",))
    if not isinstance(request["job_id"], str) or not _JOB_ID_RE.fullmatch(request["job_id"]):
        raise VSWorkerProtocolError(("job_id",))
    fixed = {
        "status": "queued",
        "model_id": KCL_VS_SEG_T1_MODEL_ID,
        "model_version": KCL_VS_SEG_T1_CODE_COMMIT,
        "task_variant": KCL_VS_SEG_T1_TASK_VARIANT,
        "weights_sha256": KCL_VS_SEG_T1_WEIGHT_DIGEST,
        "upstream_requirements_sha256": KCL_VS_SEG_T1_UPSTREAM_REQUIREMENTS_DIGEST,
        "preprocess_sha256": KCL_VS_SEG_T1_PREPROCESS_DIGEST,
        "postprocess_sha256": KCL_VS_SEG_T1_POSTPROCESS_DIGEST,
        "input_file": INPUT_FILE_NAME,
        "input_dtype": "float32",
        "input_axes": "cxyz",
        "model_axis_codes": "RAS",
        "roi_size_xyz": list(ROI_SIZE_XYZ),
        "sw_batch_size": SW_BATCH_SIZE,
        "sw_overlap": SW_OVERLAP,
        "sw_mode": SW_MODE,
        "sw_sigma_scale": SW_SIGMA_SCALE,
        "output_channels": MODEL_OUTPUT_CHANNELS,
        "target_channel_index": TARGET_CHANNEL_INDEX,
        "output_axes": "xyz",
        "output_kind": "candidate-binary-mask",
        "type_status": "unknown",
        "type_scope": "no-prediction",
    }
    if any(request.get(key) != value for key, value in fixed.items()):
        raise VSWorkerProtocolError(("fixed_model_contract",))
    if (not _positive_int_list(request.get("input_shape_cxyz"), 4)
            or request["input_shape_cxyz"][0] != 1
            or not _positive_int_list(request.get("source_shape_zyx"), 3)):
        raise VSWorkerProtocolError(("input_shape",))
    for field in (
            "request_sha256", "source_binding_sha256", "dicom_rescale_sha256",
            "model_affine_sha256", "input_file_sha256", "input_array_sha256"):
        if not isinstance(request.get(field), str) or not _SHA256_RE.fullmatch(request[field]):
            raise VSWorkerProtocolError((field,))
    return request


def stage_vs_t1_worker_job(prepared, job_dir):
    """Stage one adapter output as non-pickle NPY + minimal JSON provenance.

    The JSON deliberately contains only a digest of source identifiers. It does
    not serialize DICOM tags, patient names, or raw Study/Series UIDs.
    """
    if not isinstance(prepared, VST1PreparedImage):
        raise VSWorkerProtocolError(("prepared_image",))
    image = np.asarray(prepared.image_cxyz)
    if (image.dtype != np.float32 or image.ndim != 4 or image.shape[0] != 1
            or not image.size or not np.all(np.isfinite(image))):
        raise VSWorkerProtocolError(("input_array",))
    if (prepared.model_id != KCL_VS_SEG_T1_MODEL_ID
            or prepared.model_version != KCL_VS_SEG_T1_CODE_COMMIT
            or prepared.model_axis_codes != "RAS"
            or tuple(prepared.spatial_shape_xyz) != tuple(image.shape[1:])):
        raise VSWorkerProtocolError(("prepared_identity",))
    if not _SHA256_RE.fullmatch(prepared.request_digest):
        raise VSWorkerProtocolError(("request_digest",))
    if not _SHA256_RE.fullmatch(prepared.dicom_rescale_digest):
        raise VSWorkerProtocolError(("dicom_rescale_digest",))

    directory = Path(job_dir)
    if directory.exists() or directory.is_symlink():
        raise VSWorkerProtocolError(("job_directory_must_be_new",))
    try:
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError:
        raise VSWorkerProtocolError(("job_directory_create",)) from None

    input_path = directory / INPUT_FILE_NAME
    with input_path.open("xb") as stream:
        np.save(stream, image, allow_pickle=False)
    input_file_digest = _file_sha256(input_path)
    request = {
        "protocol_version": PROTOCOL_VERSION,
        "job_id": __import__("uuid").uuid4().hex,
        "status": "queued",
        "model_id": KCL_VS_SEG_T1_MODEL_ID,
        "model_version": KCL_VS_SEG_T1_CODE_COMMIT,
        "task_variant": KCL_VS_SEG_T1_TASK_VARIANT,
        "weights_sha256": KCL_VS_SEG_T1_WEIGHT_DIGEST,
        "upstream_requirements_sha256": KCL_VS_SEG_T1_UPSTREAM_REQUIREMENTS_DIGEST,
        "preprocess_sha256": KCL_VS_SEG_T1_PREPROCESS_DIGEST,
        "postprocess_sha256": KCL_VS_SEG_T1_POSTPROCESS_DIGEST,
        "request_sha256": prepared.request_digest,
        "source_binding_sha256": _binding_sha256(prepared.source_binding),
        "dicom_rescale_sha256": prepared.dicom_rescale_digest,
        "model_affine_sha256": _affine_sha256(prepared.model_affine_ras),
        "input_file": INPUT_FILE_NAME,
        "input_file_sha256": input_file_digest,
        "input_array_sha256": _array_sha256(image, "<f4"),
        "input_dtype": "float32",
        "input_shape_cxyz": list(image.shape),
        "source_shape_zyx": list(prepared.source_shape_zyx),
        "input_axes": "cxyz",
        "model_axis_codes": "RAS",
        "roi_size_xyz": list(ROI_SIZE_XYZ),
        "sw_batch_size": SW_BATCH_SIZE,
        "sw_overlap": SW_OVERLAP,
        "sw_mode": SW_MODE,
        "sw_sigma_scale": SW_SIGMA_SCALE,
        "output_channels": MODEL_OUTPUT_CHANNELS,
        "target_channel_index": TARGET_CHANNEL_INDEX,
        "output_axes": "xyz",
        "output_kind": "candidate-binary-mask",
        "type_status": "unknown",
        "type_scope": "no-prediction",
    }
    _validate_request_document(request)
    request_bytes = _canonical_json(request)
    with (directory / REQUEST_FILE_NAME).open("xb") as stream:
        stream.write(request_bytes)
    return StagedVSWorkerJob(directory, request_bytes)


def load_staged_worker_input(job_dir):
    """Validate a request and load its float32 input without pickle support."""
    directory = Path(job_dir)
    request_path = directory / REQUEST_FILE_NAME
    input_path = directory / INPUT_FILE_NAME
    if (directory.is_symlink() or not directory.is_dir()
            or request_path.is_symlink() or input_path.is_symlink()):
        raise VSWorkerProtocolError(("symlinked_job_file",))
    try:
        request_bytes = request_path.read_bytes()
    except OSError:
        raise VSWorkerProtocolError(("request_file",)) from None
    if len(request_bytes) > 64 * 1024:
        raise VSWorkerProtocolError(("request_too_large",))
    request = _validate_request_document(_strict_json_loads(request_bytes))
    if _canonical_json(request) != request_bytes:
        raise VSWorkerProtocolError(("noncanonical_request",))
    try:
        if _file_sha256(input_path) != request["input_file_sha256"]:
            raise VSWorkerProtocolError(("input_file_digest",))
        image = np.load(input_path, allow_pickle=False)
    except VSWorkerProtocolError:
        raise
    except (OSError, ValueError, EOFError):
        raise VSWorkerProtocolError(("input_file",)) from None
    if (image.dtype != np.float32 or list(image.shape) != request["input_shape_cxyz"]
            or not np.all(np.isfinite(image))
            or _array_sha256(image, "<f4") != request["input_array_sha256"]):
        raise VSWorkerProtocolError(("input_array_identity",))
    return request, image


def run_sliding_window_inference(inputs, predictor, inferer, *, roi_size=ROI_SIZE_XYZ):
    """Call MONAI's sliding-window API with the pinned KCL inference settings.

    ``roi_size`` is overridable only to test the helper with tiny synthetic
    volumes; the production CLI always uses the author ROI in the request.
    """
    shape = tuple(getattr(inputs, "shape", ()))
    if len(shape) != 5 or shape[0] != 1 or shape[1] != 1:
        raise VSWorkerProtocolError(("batched_input_shape",))
    if (not isinstance(roi_size, (tuple, list)) or len(roi_size) != 3
            or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
                   for value in roi_size)):
        raise VSWorkerProtocolError(("roi_size",))
    try:
        logits = inferer(
            inputs=inputs,
            roi_size=tuple(roi_size),
            sw_batch_size=SW_BATCH_SIZE,
            predictor=predictor,
            overlap=SW_OVERLAP,
            mode=SW_MODE,
            sigma_scale=SW_SIGMA_SCALE,
        )
    except Exception as exc:
        raise VSWorkerProtocolError(("sliding_window_failed", type(exc).__name__)) from None
    output_shape = tuple(getattr(logits, "shape", ()))
    if output_shape != (1, MODEL_OUTPUT_CHANNELS, *shape[2:]):
        raise VSWorkerProtocolError(("logits_shape",))
    values = _as_numpy(logits)
    if not np.all(np.isfinite(values)):
        raise VSWorkerProtocolError(("nonfinite_logits",))
    return logits


def _as_numpy(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def logits_to_binary_candidate(logits):
    """Apply the upstream two-channel argmax; this does not identify tumor type."""
    values = _as_numpy(logits)
    if values.ndim != 5 or values.shape[:2] != (1, MODEL_OUTPUT_CHANNELS):
        raise VSWorkerProtocolError(("logits_shape",))
    if not np.all(np.isfinite(values)):
        raise VSWorkerProtocolError(("nonfinite_logits",))
    mask = np.asarray(np.argmax(values, axis=1)[0] == TARGET_CHANNEL_INDEX,
                      dtype=np.uint8)
    if not np.all((mask == 0) | (mask == 1)):
        raise VSWorkerProtocolError(("binary_mask",))
    return np.ascontiguousarray(mask)


def _response_from_mask(request, mask_xyz):
    _validate_request_document(request)
    mask = np.asarray(mask_xyz)
    expected_shape = tuple(request["input_shape_cxyz"][1:])
    if (mask.dtype != np.uint8 or mask.shape != expected_shape
            or not np.all((mask == 0) | (mask == 1))):
        raise VSWorkerProtocolError(("binary_mask",))
    return {
        "protocol_version": PROTOCOL_VERSION,
        "job_id": request["job_id"],
        "status": "candidate-mask-ready",
        "model_id": request["model_id"],
        "model_version": request["model_version"],
        "task_variant": request["task_variant"],
        "weights_sha256": request["weights_sha256"],
        "upstream_requirements_sha256": request["upstream_requirements_sha256"],
        "preprocess_sha256": request["preprocess_sha256"],
        "postprocess_sha256": request["postprocess_sha256"],
        "request_sha256": request["request_sha256"],
        "source_binding_sha256": request["source_binding_sha256"],
        "dicom_rescale_sha256": request["dicom_rescale_sha256"],
        "model_affine_sha256": request["model_affine_sha256"],
        "input_file_sha256": request["input_file_sha256"],
        "output_file": MASK_FILE_NAME,
        "output_file_sha256": "",
        "output_array_sha256": _array_sha256(mask, "|u1"),
        "output_dtype": "uint8",
        "output_shape_xyz": list(mask.shape),
        "output_axes": "xyz",
        "output_kind": "candidate-binary-mask",
        "target_channel_index": TARGET_CHANNEL_INDEX,
        "output_values": [0, 1],
        "type_status": "unknown",
        "type_scope": "no-prediction",
    }


def write_worker_candidate(job_dir, request, mask_xyz):
    """Write one non-pickle binary candidate and its bound receipt."""
    directory = Path(job_dir)
    response = _response_from_mask(request, mask_xyz)
    mask_path = directory / MASK_FILE_NAME
    response_path = directory / RESPONSE_FILE_NAME
    if mask_path.exists() or response_path.exists() or mask_path.is_symlink() or response_path.is_symlink():
        raise VSWorkerProtocolError(("output_must_be_new",))
    with mask_path.open("xb") as stream:
        np.save(stream, np.asarray(mask_xyz, dtype=np.uint8), allow_pickle=False)
    response["output_file_sha256"] = _file_sha256(mask_path)
    response_bytes = _canonical_json(response)
    with response_path.open("xb") as stream:
        stream.write(response_bytes)
    return response


def verify_worker_candidate(staged, prepared, series):
    """Verify the subprocess echo/output, then restore it to the bound source grid.

    This verifies only the local IPC and coordinate-return contract. It does
    not satisfy ``validate_vs_result`` or product/clinical model admission.
    """
    if not isinstance(staged, StagedVSWorkerJob) or not isinstance(prepared, VST1PreparedImage):
        raise VSWorkerProtocolError(("parent_job_state",))
    directory = staged.job_dir
    request_path = directory / REQUEST_FILE_NAME
    response_path = directory / RESPONSE_FILE_NAME
    mask_path = directory / MASK_FILE_NAME
    if (directory.is_symlink() or not directory.is_dir()
            or any(path.is_symlink() for path in (request_path, response_path, mask_path))):
        raise VSWorkerProtocolError(("symlinked_job_file",))
    try:
        request_bytes = request_path.read_bytes()
        response_bytes = response_path.read_bytes()
    except OSError:
        raise VSWorkerProtocolError(("worker_response_missing",)) from None
    if request_bytes != staged.request_json:
        raise VSWorkerProtocolError(("request_changed",))
    if len(response_bytes) > 64 * 1024:
        raise VSWorkerProtocolError(("response_too_large",))
    response_doc = _strict_json_loads(response_bytes)
    if _canonical_json(response_doc) != response_bytes:
        raise VSWorkerProtocolError(("noncanonical_response",))
    request = _validate_request_document(_strict_json_loads(request_bytes))
    expected = staged.request
    if request != expected:
        raise VSWorkerProtocolError(("issued_request_mismatch",))
    if (request["request_sha256"] != prepared.request_digest
            or request["source_binding_sha256"] != _binding_sha256(prepared.source_binding)
            or request["dicom_rescale_sha256"] != prepared.dicom_rescale_digest
            or request["model_affine_sha256"] != _affine_sha256(prepared.model_affine_ras)
            or request["input_shape_cxyz"] != [1, *prepared.spatial_shape_xyz]
            or request["source_shape_zyx"] != list(prepared.source_shape_zyx)):
        raise VSWorkerProtocolError(("prepared_image_changed",))
    if _file_sha256(directory / INPUT_FILE_NAME) != request["input_file_sha256"]:
        raise VSWorkerProtocolError(("input_file_digest",))
    response = response_doc
    if not isinstance(response, dict) or set(response) != _RESPONSE_FIELDS:
        raise VSWorkerProtocolError(("response_schema",))
    echoes = (
        "protocol_version", "job_id", "model_id", "model_version", "task_variant",
        "weights_sha256", "upstream_requirements_sha256", "preprocess_sha256",
        "postprocess_sha256", "request_sha256", "source_binding_sha256",
        "dicom_rescale_sha256", "model_affine_sha256", "input_file_sha256",
    )
    if any(response.get(field) != request.get(field) for field in echoes):
        raise VSWorkerProtocolError(("response_binding",))
    fixed_response = {
        "status": "candidate-mask-ready",
        "output_file": MASK_FILE_NAME,
        "output_dtype": "uint8",
        "output_shape_xyz": request["input_shape_cxyz"][1:],
        "output_axes": "xyz",
        "output_kind": "candidate-binary-mask",
        "target_channel_index": TARGET_CHANNEL_INDEX,
        "output_values": [0, 1],
        "type_status": "unknown",
        "type_scope": "no-prediction",
    }
    if any(response.get(key) != value for key, value in fixed_response.items()):
        raise VSWorkerProtocolError(("fixed_output_contract",))
    for field in ("output_file_sha256", "output_array_sha256"):
        if not isinstance(response.get(field), str) or not _SHA256_RE.fullmatch(response[field]):
            raise VSWorkerProtocolError((field,))
    try:
        if _file_sha256(mask_path) != response["output_file_sha256"]:
            raise VSWorkerProtocolError(("output_file_digest",))
        mask = np.load(mask_path, allow_pickle=False)
    except VSWorkerProtocolError:
        raise
    except (OSError, ValueError, EOFError):
        raise VSWorkerProtocolError(("output_file",)) from None
    if (mask.dtype != np.uint8 or list(mask.shape) != response["output_shape_xyz"]
            or not np.all((mask == 0) | (mask == 1))
            or _array_sha256(mask, "|u1") != response["output_array_sha256"]):
        raise VSWorkerProtocolError(("output_array_identity",))
    try:
        return restore_vs_t1_mask(mask, prepared, series)
    except ValueError as exc:
        gates = getattr(exc, "failed_gates", ("source_restore",))
        raise VSWorkerProtocolError(gates) from None


def _sha1_git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def verify_kcl_assets(source_root, weights_path):
    """Verify the pinned KCL source and checkpoint bytes; never extracts ZIPs."""
    source_root = Path(source_root)
    weights_path = Path(weights_path)
    if source_root.is_symlink() or not source_root.is_dir() or weights_path.is_symlink():
        raise VSWorkerProtocolError(("runtime_assets_path",))
    for relative, (expected_blob, expected_sha256) in _KCL_SOURCE_FILES.items():
        path = source_root / relative
        if path.is_symlink() or not path.is_file():
            raise VSWorkerProtocolError(("kcl_source_missing",))
        data = path.read_bytes()
        if (_sha1_git_blob(data) != expected_blob
                or _sha256(data) != expected_sha256):
            raise VSWorkerProtocolError(("kcl_source_digest",))
    if not weights_path.is_file():
        raise VSWorkerProtocolError(("weights_zip_digest",))
    try:
        weights_bytes = weights_path.read_bytes()
        if _sha256(weights_bytes) != WEIGHTS_ZIP_SHA256:
            raise VSWorkerProtocolError(("weights_zip_digest",))
        with zipfile.ZipFile(io.BytesIO(weights_bytes)) as archive:
            info = archive.getinfo(CHECKPOINT_MEMBER)
            if info.file_size <= 0 or info.flag_bits & 0x1:
                raise VSWorkerProtocolError(("checkpoint_member",))
            checkpoint = archive.read(info)
    except VSWorkerProtocolError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError):
        raise VSWorkerProtocolError(("checkpoint_archive",)) from None
    if _sha256(checkpoint) != KCL_VS_SEG_T1_WEIGHT_DIGEST:
        raise VSWorkerProtocolError(("checkpoint_digest",))
    return checkpoint


def load_fixed_kcl_model(source_root, weights_path):
    """Load the pinned model in the child process using safe, strict weights."""
    checkpoint = verify_kcl_assets(source_root, weights_path)
    if (sys.version_info[:2] != (3, 10) or np.__version__ != "1.26.4"
            or platform.machine() != "arm64"):
        raise VSWorkerProtocolError(("python_runtime_unverified",))
    if "bool" not in np.__dict__:
        np.bool = bool
    try:
        import monai  # Optional dependency of the isolated CPU worker, not the GUI app.
        import torch  # Optional dependency of the isolated CPU worker, not the GUI app.

        if monai.__version__ != "0.4.0" or torch.__version__.split("+", 1)[0] != "2.5.1":
            raise VSWorkerProtocolError(("torch_monai_runtime_unverified",))
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        sys.path.insert(0, str(Path(source_root).resolve()))
        from monai.networks.layers.factories import Act, Norm
        from params.networks.nets.unet2d5_spvPA import (  # Pinned KCL source bundle, child only.
            UNet2d5_spvPA,
        )

        model = UNet2d5_spvPA(
            dimensions=3,
            in_channels=1,
            out_channels=MODEL_OUTPUT_CHANNELS,
            channels=(16, 32, 48, 64, 80, 96),
            strides=((2, 2, 1), (2, 2, 1), (2, 2, 2), (2, 2, 2), (2, 2, 2)),
            kernel_sizes=((3, 3, 1), (3, 3, 1), (3, 3, 3),
                          (3, 3, 3), (3, 3, 3), (3, 3, 3)),
            sample_kernel_sizes=((3, 3, 1), (3, 3, 1), (3, 3, 3),
                                 (3, 3, 3), (3, 3, 3)),
            num_res_units=2,
            act=Act.PRELU,
            norm=Norm.BATCH,
            dropout=0.1,
            attention_module=True,
        ).cpu()
        state = torch.load(io.BytesIO(checkpoint), map_location="cpu", weights_only=True)
        if not isinstance(state, dict) or len(state) != EXPECTED_STATE_DICT_ENTRIES:
            raise VSWorkerProtocolError(("checkpoint_state_dict",))
        incompatible = model.load_state_dict(state, strict=True)
        if incompatible.missing_keys or incompatible.unexpected_keys:
            raise VSWorkerProtocolError(("strict_state_dict",))
        return model.eval(), torch, monai
    except VSWorkerProtocolError:
        raise
    except Exception as exc:
        raise VSWorkerProtocolError(("model_load_failed", type(exc).__name__)) from None


def _run_cli(job_dir, source_root, weights_path):
    request, image_cxyz = load_staged_worker_input(job_dir)
    model, torch, monai = load_fixed_kcl_model(source_root, weights_path)
    if tuple(ROI_SIZE_XYZ) != tuple(request["roi_size_xyz"]):
        raise VSWorkerProtocolError(("roi_size",))
    inputs = torch.from_numpy(image_cxyz).unsqueeze(0).to(torch.device("cpu"))

    def predictor(patches):
        return model(patches)[0]

    with torch.inference_mode():
        logits = run_sliding_window_inference(
            inputs, predictor, monai.inferers.sliding_window_inference)
    mask_xyz = logits_to_binary_candidate(logits)
    return write_worker_candidate(job_dir, request, mask_xyz)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--kcl-source", required=True, type=Path)
    parser.add_argument("--weights", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        response = _run_cli(args.job_dir, args.kcl_source, args.weights)
    except VSWorkerProtocolError as exc:
        print(json.dumps({"status": "rejected", "failed_gates": exc.failed_gates}),
              file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"status": "worker_error", "error_type": type(exc).__name__}),
              file=sys.stderr)
        return 3
    print(json.dumps({"status": response["status"], "job_id": response["job_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROTOCOL_VERSION", "ROI_SIZE_XYZ", "SW_BATCH_SIZE", "SW_OVERLAP",
    "SW_MODE", "SW_SIGMA_SCALE", "TARGET_CHANNEL_INDEX", "VSWorkerProtocolError",
    "StagedVSWorkerJob", "stage_vs_t1_worker_job", "load_staged_worker_input",
    "run_sliding_window_inference", "logits_to_binary_candidate",
    "write_worker_candidate", "verify_worker_candidate", "verify_kcl_assets",
    "load_fixed_kcl_model", "main",
]
