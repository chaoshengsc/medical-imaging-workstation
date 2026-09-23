"""Model input must reject ambiguous DICOM series before pixel/model work."""

from pathlib import Path
import sys
import unittest

from pydicom.dataset import Dataset
from pydicom.uid import MRImageStorage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from neurovfm_dicom_input_preflight import validate_headers


def frame(index: int, series: str = "1.2.3", sop: str | None = None):
    ds = Dataset()
    ds.Modality = "MR"
    ds.SOPClassUID = MRImageStorage
    ds.StudyInstanceUID = "1.2.2"
    ds.SeriesInstanceUID = series
    ds.SOPInstanceUID = sop or f"1.2.3.{index + 1}"
    ds.Rows = 4
    ds.Columns = 4
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0, 0, float(index) * 1.5]
    ds.PixelSpacing = [0.4, 0.4]
    return ds


class NeuroVFMDICOMInputTests(unittest.TestCase):
    def test_accepts_one_uniform_3d_series(self):
        geometry, ordered, shape = validate_headers([frame(1), frame(0)], "1.2.3", 2)
        self.assertEqual(shape, (4, 4))
        self.assertEqual([float(ds.ImagePositionPatient[2]) for ds in ordered], [0.0, 1.5])
        self.assertTrue(geometry.uniform_z_geometry_valid)

    def test_rejects_mixed_series(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            validate_headers([frame(0), frame(1, series="1.2.4")], "1.2.3", 2)

    def test_rejects_reused_sop(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            validate_headers([frame(0, sop="1.2.5"), frame(1, sop="1.2.5")], "1.2.3", 2)

    def test_rejects_missing_slice(self):
        with self.assertRaisesRegex(ValueError, "frame count"):
            validate_headers([frame(0)], "1.2.3", 2)


if __name__ == "__main__":
    unittest.main()
