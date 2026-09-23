"""Synthetic contract tests for KCL VS-Seg T1 preprocessing and inversion."""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
from pydicom.uid import MRImageStorage, generate_uid

from study_data import SeriesVolume
from tumor_model_admission import (
    KCL_VS_SEG_T1_MODEL_ID,
    KCL_VS_SEG_T1_TASK_VARIANT,
    OFFICIAL_VS_T1_MODEL_SPACE,
    MRISequenceEvidence,
    SequenceEvidenceState,
    VST1Request,
    admit_vs_t1_execution,
    dicom_fields_sequence_evidence,
    qualify_vs_t1_source,
    vs_request_digest,
)
from vs_seg_t1_adapter import (
    VSInputRejected,
    prepare_vs_t1_image,
    restore_vs_t1_mask,
)


def _orientations():
    rz, ry = np.deg2rad(23.0), np.deg2rad(-17.0)
    rotate_z = np.array([
        [np.cos(rz), -np.sin(rz), 0.0],
        [np.sin(rz), np.cos(rz), 0.0],
        [0.0, 0.0, 1.0],
    ])
    rotate_y = np.array([
        [np.cos(ry), 0.0, np.sin(ry)],
        [0.0, 1.0, 0.0],
        [-np.sin(ry), 0.0, np.cos(ry)],
    ])
    return {
        "axial_lps": np.eye(3),
        "axial_reversed": np.diag((-1.0, -1.0, 1.0)),
        "coronal": np.column_stack(([1.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                                     [0.0, -1.0, 0.0])),
        "sagittal": np.column_stack(([0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
                                      [1.0, 0.0, 0.0])),
        "oblique": rotate_z @ rotate_y,
    }


def _series(directions, *, changed_pixel=False, constant=False, rescale_by_slice=None):
    z_count, rows, columns = 5, 7, 9
    study_uid, series_uid = generate_uid(), generate_uid()
    normal = np.cross(directions[:, 0], directions[:, 1])
    origin = np.array((31.0, -18.0, 4.0))
    frames = []
    for z in range(z_count):
        pixels = (np.full((rows, columns), 5, dtype=np.int16) if constant else
                  np.arange(rows * columns, dtype=np.int16).reshape(rows, columns)
                  + z * 100)
        if z == 2 and changed_pixel:
            pixels = pixels.copy()
            pixels[1, 3] += 1
        frames.append(SimpleNamespace(
            SOPClassUID=MRImageStorage,
            Modality="MR",
            StudyInstanceUID=study_uid,
            SeriesInstanceUID=series_uid,
            SOPInstanceUID=generate_uid(),
            InstanceNumber=z + 1,
            ImageOrientationPatient=tuple((*directions[:, 0], *directions[:, 1])),
            ImagePositionPatient=tuple(origin + normal * z * 1.8),
            PixelSpacing=(0.9, 0.7),
            Rows=rows,
            Columns=columns,
            RescaleSlope=(1.0 if rescale_by_slice is None
                          else rescale_by_slice[z][0]),
            RescaleIntercept=(0.0 if rescale_by_slice is None
                              else rescale_by_slice[z][1]),
            pixel_array=pixels,
        ))
    return SeriesVolume.from_datasets(frames)


def _request(series):
    source = qualify_vs_t1_source(series)
    if not source.qualified:
        raise AssertionError(source.failed_gates)
    evidence = MRISequenceEvidence(
        state=SequenceEvidenceState.CONFIRMED,
        sequence="contrast-enhanced-t1-weighted",
        basis="human-reviewed-record",
        record_digest="a" * 64,
        source_binding=source.source_binding,
    )
    return VST1Request(
        task_variant=KCL_VS_SEG_T1_TASK_VARIANT,
        model_id=KCL_VS_SEG_T1_MODEL_ID,
        source_binding=source.source_binding,
        sequence_evidence=evidence,
        model_space=OFFICIAL_VS_T1_MODEL_SPACE,
    )


def _source_xyz_from_model_index(model_index, prepared, source_shape_zyx):
    source_shape_xyz = (source_shape_zyx[2], source_shape_zyx[1], source_shape_zyx[0])
    source_index = np.empty(3, dtype=np.float64)
    for model_axis, source_axis in enumerate(prepared.model_axis_to_source_axis):
        index = model_index[model_axis]
        source_index[source_axis] = (
            source_shape_xyz[source_axis] - 1 - index
            if prepared.model_axis_flips[model_axis] else index
        )
    return source_index


class VSSegT1AdapterTests(unittest.TestCase):
    def test_image_only_ras_preprocessing_and_exact_mask_inverse(self):
        for name, directions in _orientations().items():
            with self.subTest(orientation=name):
                series = _series(directions)
                request = _request(series)
                prepared = prepare_vs_t1_image(request, series)
                execution = admit_vs_t1_execution(request, series)
                self.assertFalse(execution.admitted)
                self.assertIn("engineering_runtime_not_ready", execution.failed_gates)

                self.assertEqual(prepared.image_cxyz.dtype, np.float32)
                self.assertEqual(prepared.image_cxyz.ndim, 4)
                self.assertEqual(prepared.image_cxyz.shape[0], 1)
                self.assertTrue(np.isfinite(prepared.image_cxyz).all())
                self.assertAlmostEqual(float(prepared.image_cxyz.mean()), 0.0, places=5)
                if prepared.normalization_std:
                    self.assertAlmostEqual(float(prepared.image_cxyz.std()), 1.0, places=5)
                self.assertEqual(prepared.model_axis_codes, "RAS")
                self.assertEqual(prepared.request_digest, vs_request_digest(request))
                self.assertTrue(prepared.request_digest)
                source_xyz = series.volume.transpose(2, 1, 0)
                divisor = prepared.normalization_std or 1.0
                for model_index in np.ndindex(prepared.spatial_shape_xyz):
                    source_index = _source_xyz_from_model_index(
                        model_index, prepared, prepared.source_shape_zyx).astype(int)
                    expected_value = (
                        np.float32(source_xyz[tuple(source_index)])
                        - np.float32(prepared.normalization_mean)
                    ) / np.float32(divisor)
                    self.assertAlmostEqual(
                        float(prepared.image_cxyz[(0, *model_index)]),
                        float(expected_value), places=5)

                source_mask_zyx = np.zeros(series.volume.shape, dtype=np.uint8)
                source_mask_zyx[1:4, 2:6, 3:8] = 1
                source_mask_zyx[2, 5, 7] = 0
                source_mask_xyz = source_mask_zyx.transpose(2, 1, 0)
                model_mask = np.transpose(source_mask_xyz,
                                          prepared.model_axis_to_source_axis)
                for axis, flip in enumerate(prepared.model_axis_flips):
                    if flip:
                        model_mask = np.flip(model_mask, axis=axis)
                restored = restore_vs_t1_mask(model_mask, prepared, series)
                np.testing.assert_array_equal(restored.mask_zyx, source_mask_zyx)
                self.assertEqual(restored.source_binding, prepared.source_binding)
                self.assertEqual(restored.model_id, KCL_VS_SEG_T1_MODEL_ID)
                self.assertEqual(restored.source_shape_zyx, series.volume.shape)
                np.testing.assert_array_equal(restored.affine_lps, series.affine)

                for model_index in (
                        np.zeros(3),
                        np.asarray(prepared.spatial_shape_xyz, dtype=float) - 1,
                        np.array((2.0, 3.0, 1.0))):
                    source_index = _source_xyz_from_model_index(
                        model_index, prepared, prepared.source_shape_zyx)
                    source_world = prepared.source_affine_ras @ np.r_[source_index, 1.0]
                    model_world = prepared.model_affine_ras @ np.r_[model_index, 1.0]
                    np.testing.assert_allclose(model_world, source_world, atol=1e-8)

    def test_normalization_includes_zero_background_and_constant_series_is_finite(self):
        series = _series(_orientations()["axial_lps"])
        prepared = prepare_vs_t1_image(_request(series), series)
        source_xyz = series.volume.transpose(2, 1, 0)
        ras_affine = np.diag((-1.0, -1.0, 1.0, 1.0)) @ series.affine
        from vs_seg_t1_adapter import _reorient_to_ras

        oriented, _, _, _ = _reorient_to_ras(source_xyz, ras_affine)
        self.assertAlmostEqual(prepared.normalization_mean, float(oriented.mean()), places=4)
        self.assertAlmostEqual(prepared.normalization_std, float(oriented.std()), places=4)
        self.assertFalse(np.allclose(prepared.image_cxyz[0][oriented == 0], 0.0))

        constant = _series(_orientations()["oblique"], constant=True)
        constant_prepared = prepare_vs_t1_image(_request(constant), constant)
        self.assertEqual(constant_prepared.normalization_std, 0.0)
        self.assertTrue(np.isfinite(constant_prepared.image_cxyz).all())
        self.assertEqual(float(np.max(np.abs(constant_prepared.image_cxyz))), 0.0)

    def test_unknown_sequence_evidence_and_stale_source_are_rejected(self):
        series = _series(_orientations()["axial_lps"])
        request = _request(series)
        unknown = replace(request, sequence_evidence=dicom_fields_sequence_evidence(
            request.source_binding, series_description="T1 post")
        )
        with self.assertRaises(VSInputRejected) as caught:
            prepare_vs_t1_image(unknown, series)
        self.assertIn("sequence_evidence", caught.exception.failed_gates)

        prepared = prepare_vs_t1_image(request, series)
        changed = _series_with_same_identity_changed_pixels(series)
        with self.assertRaises(VSInputRejected) as caught:
            restore_vs_t1_mask(np.zeros(prepared.spatial_shape_xyz), prepared, changed)
        self.assertIn("source_binding", caught.exception.failed_gates)

    def test_nonidentity_or_invalid_mr_rescale_is_rejected(self):
        for transforms in (
                [(1.0, 0.0)] * 4 + [(2.0, 0.0)],
                [(1.0, 0.0)] * 4 + [(1.0, -12.0)],
                [(1.0, 0.0)] * 4 + [(float("nan"), 0.0)],
                [(1.0, 0.0)] * 4 + [(1.0, float("inf"))]):
            with self.subTest(last_transform=transforms[-1]):
                series = _series(_orientations()["axial_lps"],
                                 rescale_by_slice=transforms)
                with self.assertRaises(VSInputRejected) as caught:
                    prepare_vs_t1_image(_request(series), series)
                self.assertIn("unsupported_mr_rescale" if np.isfinite(
                    transforms[-1]).all() else "dicom_rescale_metadata",
                    caught.exception.failed_gates)

        series = _series(_orientations()["axial_lps"])
        request = _request(series)
        prepared = prepare_vs_t1_image(request, series)
        changed_scale_datasets = [
            replace_namespace(dataset, RescaleIntercept=1.0)
            for dataset in series.datasets
        ]
        changed_scale = SeriesVolume.from_datasets(changed_scale_datasets)
        # SeriesVolume intentionally hashes raw MR values, not modality rescale.
        self.assertEqual(changed_scale.source_binding, series.source_binding)
        with self.assertRaises(VSInputRejected) as caught:
            restore_vs_t1_mask(np.zeros(prepared.spatial_shape_xyz), prepared,
                               changed_scale)
        self.assertIn("unsupported_mr_rescale", caught.exception.failed_gates)

    def test_restore_rejects_wrong_shape_and_nonbinary_results(self):
        series = _series(_orientations()["coronal"])
        prepared = prepare_vs_t1_image(_request(series), series)
        with self.assertRaises(VSInputRejected) as caught:
            restore_vs_t1_mask(np.zeros((1, 2, 3)), prepared, series)
        self.assertIn("mask_shape", caught.exception.failed_gates)
        with self.assertRaises(VSInputRejected) as caught:
            restore_vs_t1_mask(np.full(prepared.spatial_shape_xyz, 2), prepared, series)
        self.assertIn("binary_mask", caught.exception.failed_gates)
        with self.assertRaises(VSInputRejected) as caught:
            restore_vs_t1_mask(np.full(prepared.spatial_shape_xyz, np.nan), prepared, series)
        self.assertIn("binary_mask", caught.exception.failed_gates)


def _series_with_same_identity_changed_pixels(series):
    frames = []
    for index, dataset in enumerate(series.datasets):
        changed = np.asarray(dataset.pixel_array).copy()
        if index == 2:
            changed[1, 3] += 1
        frames.append(replace_namespace(dataset, pixel_array=changed))
    return SeriesVolume.from_datasets(frames)


def replace_namespace(namespace, **updates):
    values = vars(namespace).copy()
    values.update(updates)
    return SimpleNamespace(**values)


if __name__ == "__main__":
    unittest.main()
