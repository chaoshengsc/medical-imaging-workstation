"""Reject malformed checkpoint metadata before any torch deserialization."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from neurovfm_static_audit import inspect_checkpoint, parse_tensor_metadata


class NeuroVFMStaticAuditTests(unittest.TestCase):
    def test_rejects_executable_global(self):
        with self.assertRaisesRegex(ValueError, "disallowed pickle GLOBAL"):
            parse_tensor_metadata(b"\x80\x02cposix\nsystem\n.")

    def test_rejects_unknown_opcode(self):
        with self.assertRaisesRegex(ValueError, "disallowed pickle opcode"):
            parse_tensor_metadata(b"\x80\x02N.")

    def test_rejects_non_tensor_top_level(self):
        with self.assertRaisesRegex(ValueError, "checkpoint must contain only named tensors"):
            parse_tensor_metadata(b"\x80\x02}q\x00X\x01\x00\x00\x00xq\x01K\x01s.")

    def test_rejects_wrong_digest_before_opening_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.bin"
            path.write_bytes(b"not a ZIP file")
            with self.assertRaisesRegex(ValueError, "checkpoint SHA256 differs"):
                inspect_checkpoint(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
