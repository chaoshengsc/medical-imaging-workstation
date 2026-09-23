"""Fail-closed KCL VS-Seg T1 image preparation and source-grid restoration.

This module implements only the verified image-space transforms. It does not
load weights, run inference, approve a mask, or enable product execution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np

from tumor_model_admission import (
    KCL_VS_SEG_T1_CODE_COMMIT,
    KCL_VS_SEG_T1_MODEL_ID,
    OFFICIAL_VS_T1_MODEL_SPACE,
    SourceBinding,
    VST1Request,
    qualify_vs_t1_request,
    qualify_vs_t1_source,
    vs_request_digest,
)

_LPS_TO_RAS = np.diag((-1.0, -1.0, 1.0, 1.0))


class VSInputRejected(ValueError):
    """The source or request did not meet the fixed VS-Seg input contract."""

    def __init__(self, failed_gates):
        self.failed_gates = tuple(failed_gates)
        super().__init__("VS-Seg T1 input rejected: " + ", ".join(self.failed_gates))


@dataclass(frozen=True)
class VST1PreparedImage:
    """Image-only model input plus immutable provenance needed for inversion."""

    image_cxyz: np.ndarray
    source_binding: SourceBinding
    request_digest: str
    source_shape_zyx: tuple[int, int, int]
    source_affine_lps: np.ndarray
    source_affine_ras: np.ndarray
    model_affine_ras: np.ndarray
    dicom_rescale_digest: str
    model_axis_to_source_axis: tuple[int, int, int]
    model_axis_flips: tuple[bool, bool, bool]
    normalization_mean: float
    normalization_std: float
    model_id: str = KCL_VS_SEG_T1_MODEL_ID
    model_version: str = KCL_VS_SEG_T1_CODE_COMMIT
    model_axis_codes: str = "RAS"

    @property
    def spatial_shape_xyz(self):
        return tuple(int(value) for value in self.image_cxyz.shape[1:])


@dataclass(frozen=True)
class VST1RestoredMask:
    """Binary candidate mask on the original SeriesVolume z-y-x grid."""

    mask_zyx: np.ndarray
    source_binding: SourceBinding
    affine_lps: np.ndarray
    request_digest: str
    dicom_rescale_digest: str
    model_id: str
    model_version: str
    source_shape_zyx: tuple[int, int, int]


def _io_orientation(affine_ras):
    """Return nibabel-compatible input-axis -> nearest RAS-axis orientation.

    MONAI 0.4's Orientationd delegates orientation discovery to nibabel. This
    reproduces nibabel's polar-decomposition/SVD axis assignment without adding
    nibabel as an application dependency. Oblique orientation is preserved in
    the returned affine; this operation only permutes and flips voxel axes.
    """
    affine = np.asarray(affine_ras, dtype=np.float64)
    if (affine.shape != (4, 4) or not np.all(np.isfinite(affine))
            or not np.allclose(affine[3], (0.0, 0.0, 0.0, 1.0), atol=1e-10)):
        raise ValueError("affine must be a finite homogeneous 4x4 matrix")
    linear = affine[:3, :3]
    zooms = np.sqrt(np.sum(linear * linear, axis=0))
    if np.any(zooms <= np.finfo(np.float64).eps) or abs(np.linalg.det(linear)) <= 1e-12:
        raise ValueError("affine must have three independent spatial axes")
    normalized = linear / zooms
    left, _, right = np.linalg.svd(normalized, full_matrices=False)
    rotation = left @ right
    orientation = np.full((3, 2), np.nan, dtype=np.float64)
    for input_axis in range(3):
        column = rotation[:, input_axis]
        if np.allclose(column, 0.0):
            continue
        output_axis = int(np.argmax(np.abs(column)))
        orientation[input_axis] = (output_axis, np.sign(column[output_axis]))
        rotation[output_axis, :] = 0.0
    axes = orientation[:, 0]
    signs = orientation[:, 1]
    if (not np.all(np.isfinite(orientation))
            or sorted(int(axis) for axis in axes) != [0, 1, 2]
            or not np.all(np.isin(signs, (-1.0, 1.0)))):
        raise ValueError("affine does not resolve to a unique 3D orientation")
    return tuple(int(axis) for axis in axes), tuple(bool(sign < 0) for sign in signs)


def _reorient_to_ras(array_xyz, affine_ras):
    """Apply an exact signed axis permutation and return its matching affine."""
    orientation_axes, orientation_flips = _io_orientation(affine_ras)
    permutation = tuple(int(axis) for axis in np.argsort(orientation_axes))
    model = np.transpose(array_xyz, permutation)
    model_affine = np.asarray(affine_ras, dtype=np.float64).copy()
    source_linear = np.asarray(affine_ras, dtype=np.float64)[:3, :3]
    source_translation = np.asarray(affine_ras, dtype=np.float64)[:3, 3]
    new_linear = np.empty((3, 3), dtype=np.float64)
    new_translation = source_translation.copy()
    model_flips = []
    for model_axis, source_axis in enumerate(permutation):
        flip = orientation_flips[source_axis]
        model_flips.append(flip)
        sign = -1.0 if flip else 1.0
        new_linear[:, model_axis] = source_linear[:, source_axis] * sign
        if flip:
            new_translation += source_linear[:, source_axis] * (array_xyz.shape[source_axis] - 1)
            model = np.flip(model, axis=model_axis)
    model = np.ascontiguousarray(model)
    model_affine[:3, :3] = new_linear
    model_affine[:3, 3] = new_translation
    return model, model_affine, permutation, tuple(model_flips)


def _identity_mr_rescale_digest(series):
    """Accept only MR series whose DICOM modality rescale is identity.

    The fixed KCL conversion imports DICOM through 3D Slicer/ITK before saving
    NIfTI. This workstation's MR ``SeriesVolume`` intentionally retains stored
    pixel values, while non-identity DICOM rescale may alter values in an ITK
    reader. Until that conversion is verified end-to-end for non-identity MR
    transforms, fail closed instead of silently feeding a different volume.
    """
    if getattr(series, "modality", "") != "MR":
        raise VSInputRejected(("source_modality",))
    datasets = tuple(getattr(series, "datasets", ()))
    volume = getattr(series, "volume", None)
    if (not isinstance(volume, np.ndarray) or volume.ndim != 3 or not datasets
            or len(datasets) != int(volume.shape[0])):
        raise VSInputRejected(("dicom_rescale_metadata",))
    transforms = []
    for dataset in datasets:
        try:
            slope_value = getattr(dataset, "RescaleSlope", 1)
            intercept_value = getattr(dataset, "RescaleIntercept", 0)
            if slope_value is None or intercept_value is None:
                raise ValueError("empty rescale value")
            if str(slope_value).strip() == "" or str(intercept_value).strip() == "":
                raise ValueError("empty rescale value")
            slope = float(slope_value)
            intercept = float(intercept_value)
        except (TypeError, ValueError, OverflowError):
            raise VSInputRejected(("dicom_rescale_metadata",)) from None
        if not np.isfinite(slope) or not np.isfinite(intercept):
            raise VSInputRejected(("dicom_rescale_metadata",))
        if slope != 1.0 or intercept != 0.0:
            raise VSInputRejected(("unsupported_mr_rescale",))
        transforms.append((slope, intercept))
    payload = json.dumps(transforms, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def prepare_vs_t1_image(request, series):
    """Build the fixed KCL image-only input after request/source qualification.

    Input: one source-bound, human/source-manifest-confirmed contrast-enhanced
    T1 ``SeriesVolume`` with identity MR rescale metadata. Output: float32
    channel-first ``(1, X, Y, Z)`` in RAS orientation, globally normalized
    including zero background, with no spacing interpolation. Non-identity
    rescale is rejected until matched against the upstream Slicer/ITK reader.
    No label or reference mask is accepted or read.
    """
    decision = qualify_vs_t1_request(request, series)
    if not decision.qualified or decision.source_binding is None:
        raise VSInputRejected(decision.failed_gates or ("request_qualification",))
    if not isinstance(request, VST1Request) or vs_request_digest(request) is None:
        raise VSInputRejected(("request_digest",))
    if series.affine is None or series.volume.ndim != 3 or not series.volume.size:
        raise VSInputRejected(("source_geometry",))
    dicom_rescale_digest = _identity_mr_rescale_digest(series)

    source_lps = np.asarray(series.affine, dtype=np.float64)
    if source_lps.shape != (4, 4) or not np.all(np.isfinite(source_lps)):
        raise VSInputRejected(("source_affine",))
    source_ras = _LPS_TO_RAS @ source_lps
    source_shape_zyx = tuple(int(value) for value in series.volume.shape)
    source_xyz = np.ascontiguousarray(series.volume.transpose(2, 1, 0), dtype=np.float32)
    if not np.all(np.isfinite(source_xyz)):
        raise VSInputRejected(("nonfinite_intensity",))

    oriented, model_affine, permutation, flips = _reorient_to_ras(source_xyz, source_ras)
    # MONAI NormalizeIntensityd defaults: one mean/std per full volume and
    # nonzero=False, so zero-valued background participates in both statistics.
    mean = np.mean(oriented, dtype=np.float32)
    std = np.std(oriented, dtype=np.float32)
    divisor = std if std != 0 else np.float32(1.0)
    normalized = np.ascontiguousarray((oriented - mean) / divisor, dtype=np.float32)
    image_cxyz = normalized[np.newaxis, ...]
    image_cxyz.flags.writeable = False

    immutable_affines = []
    for affine in (source_lps.copy(), source_ras.copy(), model_affine.copy()):
        affine.flags.writeable = False
        immutable_affines.append(affine)
    return VST1PreparedImage(
        image_cxyz=image_cxyz,
        source_binding=decision.source_binding,
        request_digest=vs_request_digest(request),
        source_shape_zyx=source_shape_zyx,
        source_affine_lps=immutable_affines[0],
        source_affine_ras=immutable_affines[1],
        model_affine_ras=immutable_affines[2],
        dicom_rescale_digest=dicom_rescale_digest,
        model_axis_to_source_axis=permutation,
        model_axis_flips=flips,
        normalization_mean=float(mean),
        normalization_std=float(std),
    )


def restore_vs_t1_mask(mask_xyz, prepared, series):
    """Invert model RAS axes to the exact source z-y-x grid; never adopts it."""
    if not isinstance(prepared, VST1PreparedImage):
        raise VSInputRejected(("prepared_image",))
    current_rescale_digest = _identity_mr_rescale_digest(series)
    if current_rescale_digest != prepared.dicom_rescale_digest:
        raise VSInputRejected(("dicom_rescale_source_changed",))
    current = qualify_vs_t1_source(series)
    if (not current.qualified or current.source_binding != prepared.source_binding
            or tuple(series.volume.shape) != prepared.source_shape_zyx
            or not np.array_equal(series.affine, prepared.source_affine_lps)):
        raise VSInputRejected(("source_binding",))
    mask = np.asarray(mask_xyz)
    if mask.ndim != 3 or tuple(mask.shape) != prepared.spatial_shape_xyz:
        raise VSInputRejected(("mask_shape",))
    if mask.dtype.kind not in "biuf":
        raise VSInputRejected(("binary_mask",))
    if not np.all(np.isfinite(mask)) or not np.all(np.isin(np.unique(mask), (0, 1))):
        raise VSInputRejected(("binary_mask",))
    restored_xyz = mask
    for model_axis, flip in enumerate(prepared.model_axis_flips):
        if flip:
            restored_xyz = np.flip(restored_xyz, axis=model_axis)
    inverse_permutation = tuple(int(axis) for axis in np.argsort(
        prepared.model_axis_to_source_axis))
    restored_xyz = np.transpose(restored_xyz, inverse_permutation)
    restored_zyx = np.ascontiguousarray(restored_xyz.transpose(2, 1, 0), dtype=np.uint8)
    if tuple(restored_zyx.shape) != prepared.source_shape_zyx:
        raise VSInputRejected(("restored_shape",))
    restored_zyx.flags.writeable = False
    affine_lps = prepared.source_affine_lps.copy()
    affine_lps.flags.writeable = False
    return VST1RestoredMask(
        mask_zyx=restored_zyx,
        source_binding=prepared.source_binding,
        affine_lps=affine_lps,
        request_digest=prepared.request_digest,
        dicom_rescale_digest=prepared.dicom_rescale_digest,
        model_id=prepared.model_id,
        model_version=prepared.model_version,
        source_shape_zyx=prepared.source_shape_zyx,
    )


__all__ = [
    "OFFICIAL_VS_T1_MODEL_SPACE",
    "VSInputRejected",
    "VST1PreparedImage",
    "VST1RestoredMask",
    "prepare_vs_t1_image",
    "restore_vs_t1_mask",
]
