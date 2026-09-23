"""Synthetic IPC, sliding-window, and source-binding tests for the KCL worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from test_vs_seg_t1_adapter import _orientations, _request, _series

from vs_seg_t1_adapter import prepare_vs_t1_image
from vs_seg_t1_worker import (
    INPUT_FILE_NAME,
    REQUEST_FILE_NAME,
    RESPONSE_FILE_NAME,
    ROI_SIZE_XYZ,
    SW_BATCH_SIZE,
    SW_MODE,
    SW_OVERLAP,
    SW_SIGMA_SCALE,
    VSWorkerProtocolError,
    load_staged_worker_input,
    logits_to_binary_candidate,
    run_sliding_window_inference,
    stage_vs_t1_worker_job,
    verify_worker_candidate,
    write_worker_candidate,
)


class VSSegT1WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.series = _series(_orientations()["oblique"])
        self.request = _request(self.series)
        self.prepared = prepare_vs_t1_image(self.request, self.series)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp_dir.name) / "job"
        self.staged = stage_vs_t1_worker_job(self.prepared, self.job_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _source_mask_to_model(source_mask_zyx, prepared):
        mask = source_mask_zyx.transpose(2, 1, 0)
        mask = np.transpose(mask, prepared.model_axis_to_source_axis)
        for axis, flip in enumerate(prepared.model_axis_flips):
            if flip:
                mask = np.flip(mask, axis=axis)
        return np.ascontiguousarray(mask, dtype=np.uint8)

    def test_stage_has_minimal_non_pickle_bound_request(self):
        request, image = load_staged_worker_input(self.job_dir)
        self.assertEqual(request, self.staged.request)
        np.testing.assert_array_equal(image, self.prepared.image_cxyz)
        self.assertEqual(request["input_shape_cxyz"], [1, *self.prepared.spatial_shape_xyz])
        self.assertEqual(request["roi_size_xyz"], list(ROI_SIZE_XYZ))
        self.assertEqual(request["type_status"], "unknown")
        self.assertEqual(request["type_scope"], "no-prediction")
        self.assertNotIn("study_instance_uid", request)
        self.assertNotIn("series_instance_uid", request)
        self.assertEqual(set(path.name for path in self.job_dir.iterdir()),
                         {INPUT_FILE_NAME, REQUEST_FILE_NAME})

    def test_bound_candidate_roundtrips_through_model_and_source_spaces(self):
        source_mask = np.zeros(self.series.volume.shape, dtype=np.uint8)
        source_mask[1:4, 2:6, 3:8] = 1
        source_mask[2, 4, 5] = 0
        model_mask = self._source_mask_to_model(source_mask, self.prepared)
        write_worker_candidate(self.job_dir, self.staged.request, model_mask)

        restored = verify_worker_candidate(self.staged, self.prepared, self.series)
        np.testing.assert_array_equal(restored.mask_zyx, source_mask)
        self.assertEqual(restored.source_binding, self.prepared.source_binding)
        self.assertEqual(restored.request_digest, self.prepared.request_digest)
        self.assertEqual(restored.model_id, self.prepared.model_id)
        self.assertEqual(restored.model_version, self.prepared.model_version)

    def test_stale_or_mutated_worker_reply_is_rejected(self):
        mask = np.zeros(self.prepared.spatial_shape_xyz, dtype=np.uint8)
        write_worker_candidate(self.job_dir, self.staged.request, mask)
        response_path = self.job_dir / RESPONSE_FILE_NAME
        response = json.loads(response_path.read_text())
        response["job_id"] = "0" * 32
        response_path.write_text(json.dumps(response, sort_keys=True, separators=(",", ":")))
        with self.assertRaises(VSWorkerProtocolError) as caught:
            verify_worker_candidate(self.staged, self.prepared, self.series)
        self.assertIn("response_binding", caught.exception.failed_gates)

    def test_worker_output_file_tampering_is_rejected(self):
        mask = np.zeros(self.prepared.spatial_shape_xyz, dtype=np.uint8)
        write_worker_candidate(self.job_dir, self.staged.request, mask)
        with (self.job_dir / "mask.npy").open("wb") as stream:
            np.save(stream, np.ones_like(mask), allow_pickle=False)
        with self.assertRaises(VSWorkerProtocolError) as caught:
            verify_worker_candidate(self.staged, self.prepared, self.series)
        self.assertIn("output_file_digest", caught.exception.failed_gates)

    def test_request_or_input_mutation_is_rejected(self):
        input_path = self.job_dir / INPUT_FILE_NAME
        with input_path.open("wb") as stream:
            np.save(stream, np.zeros_like(self.prepared.image_cxyz), allow_pickle=False)
        with self.assertRaises(VSWorkerProtocolError) as caught:
            load_staged_worker_input(self.job_dir)
        self.assertIn("input_file_digest", caught.exception.failed_gates)

    def test_nonbinary_outputs_and_invalid_logits_are_rejected(self):
        with self.assertRaises(VSWorkerProtocolError) as caught:
            write_worker_candidate(
                self.job_dir, self.staged.request,
                np.full(self.prepared.spatial_shape_xyz, 2, dtype=np.uint8))
        self.assertIn("binary_mask", caught.exception.failed_gates)

        bad_logits = np.zeros((1, 2, *self.prepared.spatial_shape_xyz), dtype=np.float32)
        bad_logits[0, 0, 0, 0, 0] = np.nan
        with self.assertRaises(VSWorkerProtocolError) as caught:
            logits_to_binary_candidate(bad_logits)
        self.assertIn("nonfinite_logits", caught.exception.failed_gates)

    def test_argmax_and_fixed_sliding_window_arguments(self):
        inputs = np.zeros((1, 1, 5, 6, 4), dtype=np.float32)
        inputs[0, 0, 1:3, 2:5, 1:3] = 2.0
        observed = {}

        def predictor(patches):
            foreground = patches[:, 0]
            return np.stack((-foreground, foreground), axis=1)

        def fake_inferer(**kwargs):
            observed.update({key: value for key, value in kwargs.items()
                             if key != "inputs" and key != "predictor"})
            return kwargs["predictor"](kwargs["inputs"])

        logits = run_sliding_window_inference(inputs, predictor, fake_inferer)
        mask = logits_to_binary_candidate(logits)
        np.testing.assert_array_equal(mask, inputs[0, 0] > 0)
        self.assertEqual(observed, {
            "roi_size": ROI_SIZE_XYZ,
            "sw_batch_size": SW_BATCH_SIZE,
            "overlap": SW_OVERLAP,
            "mode": SW_MODE,
            "sigma_scale": SW_SIGMA_SCALE,
        })

    def test_import_does_not_load_torch_or_monai(self):
        repository = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys, vs_seg_t1_worker; "
             "assert 'torch' not in sys.modules and 'monai' not in sys.modules"],
            cwd=repository, env=os.environ.copy(), capture_output=True, text=True,
            timeout=30, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_source_mismatch_stays_rejected_after_worker_returns(self):
        mask = np.zeros(self.prepared.spatial_shape_xyz, dtype=np.uint8)
        write_worker_candidate(self.job_dir, self.staged.request, mask)
        other_series = _series(_orientations()["axial_reversed"])
        with self.assertRaises(VSWorkerProtocolError) as caught:
            verify_worker_candidate(self.staged, self.prepared, other_series)
        self.assertIn("source_binding", caught.exception.failed_gates)


if __name__ == "__main__":
    unittest.main()
