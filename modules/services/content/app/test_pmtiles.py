"""Unit tests for pmtiles.py — which map files can be imported (no HTTP, no VM)."""

import os
import tempfile
import unittest
from pathlib import Path

import pmtiles
import pmtiles_fixture
from content import Refused


class Check(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def fixture(self, **kw):
        return pmtiles_fixture.write(self.dir / "m.pmtiles", **kw)

    def refused(self, path, text):
        with self.assertRaises(Refused) as cm:
            pmtiles.check(path, 4)
        self.assertIn(text, str(cm.exception))

    def test_pmtiles_ok(self):
        self.assertIsNone(pmtiles.check(self.fixture(), 4))

    def test_pmtiles_header(self):
        h = pmtiles.read_header(self.fixture(max_zoom=9))
        self.assertEqual((h["version"], h["tile_type"], h["max_zoom"]), (3, 1, 9))
        self.assertEqual(h["bounds"], [12.0, 48.5, 18.9, 51.1])

    def test_pmtiles_no_version_note(self):
        note = pmtiles.check(self.fixture(scheme=None), 4)
        self.assertIn("Getting more maps", note)

    def test_pmtiles_raster(self):
        self.refused(self.fixture(tile_type=2), "raster")

    def test_pmtiles_v2(self):
        self.refused(self.fixture(version=2), "version 3")

    def test_pmtiles_truncated(self):
        self.refused(self.fixture(truncate=True), "incomplete")

    def test_pmtiles_garbage(self):
        path = self.dir / "junk.pmtiles"
        path.write_bytes(os.urandom(200))
        self.refused(path, "not a PMTiles map")
        path.write_bytes(b"PMT")  # shorter than a header
        self.refused(path, "not a PMTiles map")

    def test_pmtiles_scheme_mismatch(self):
        self.refused(self.fixture(scheme="5.0.0"), "needs version 4")


if __name__ == "__main__":
    unittest.main()
