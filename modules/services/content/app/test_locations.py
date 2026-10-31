"""Unit tests for locations.py — the content tree on a location, its marker, scanning (no VM)."""

import json
import tempfile
import unittest
from pathlib import Path

import locations
from content import Refused
from locations import Location


class Tree(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "survival-kit"

    def marker(self):
        return json.loads((self.root / "survival-kit.json").read_text())

    def test_ensure_tree_creates_layout(self):
        locations.ensure_tree(self.root, "Big")
        for d in ["wiki", "maps", "models", ".incoming"]:
            self.assertTrue((self.root / d).is_dir(), d)
        self.assertEqual(self.marker(), {"format": 1, "name": "Big"})

    def test_ensure_tree_creates_language_dirs(self):
        locations.ensure_tree(self.root, "Big")
        for d in ["translate", "dict"]:
            self.assertTrue((self.root / d).is_dir(), d)

    def test_ensure_tree_keeps_existing_marker(self):
        self.root.mkdir()
        (self.root / "survival-kit.json").write_text('{"format": 1, "name": "Old"}')
        (self.root / "wiki").mkdir()
        (self.root / "wiki" / "mine.zim").write_bytes(b"x")
        locations.ensure_tree(self.root, "New")
        self.assertEqual(self.marker()["name"], "Old")
        self.assertEqual((self.root / "wiki" / "mine.zim").read_bytes(), b"x")

    def test_marker_not_json_refused(self):
        self.root.mkdir()
        (self.root / "survival-kit.json").write_text("{nope")
        with self.assertRaises(Refused) as cm:
            locations.ensure_tree(self.root, "X")
        self.assertIn("Forget", str(cm.exception))  # the drive stays hidden until forgotten
        self.assertEqual((self.root / "survival-kit.json").read_text(), "{nope")
        self.assertFalse((self.root / "wiki").exists())

    def test_marker_future_format_refused(self):
        self.root.mkdir()
        (self.root / "survival-kit.json").write_text('{"format": 2, "name": "Future"}')
        with self.assertRaises(Refused) as cm:
            locations.ensure_tree(self.root, "X")
        self.assertIn("newer", str(cm.exception))
        self.assertEqual(self.marker(), {"format": 2, "name": "Future"})

    def test_tree_path_is_a_file_refused(self):
        self.root.write_text("not a folder")
        with self.assertRaises(Refused):
            locations.ensure_tree(self.root, "X")
        self.assertEqual(self.root.read_text(), "not a folder")

    def test_read_marker_absent(self):
        self.assertIsNone(locations.read_marker(self.root))


class Scan(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        locations.ensure_tree(self.root, "Drive")
        self.loc = Location(id="u-1", name="Drive", root=self.root, order=1)

    def put(self, kind, name, data=b"x"):
        (self.root / kind / name).write_bytes(data)

    def test_scan_translate_and_dict(self):
        self.put("translate", "translate-en_cs-1_9_6.argosmodel")
        self.put("dict", "freedict-eng-ces-0.1.3.dictd.tar.xz")
        self.put("dict", "notes.txt")
        self.assertEqual([f["name"] for f in locations.scan(self.loc, "translate")], ["en_cs.argosmodel"])
        self.assertEqual([f["name"] for f in locations.scan(self.loc, "dict")], ["eng-ces.dictd.tar.xz"])

    def test_scan_cleans_names_ignores_others(self):
        self.put("wiki", "wikipedia_en_all_2024-01.zim")
        self.put("wiki", "notes.txt")
        (self.root / "wiki" / "sub").mkdir()
        (self.root / "wiki" / "sub" / "deep.zim").write_bytes(b"x")
        self.put(".incoming", "partial.zim")
        self.put("maps", "Austria.PMTILES", b"xyz")
        wiki = locations.scan(self.loc, "wiki")
        self.assertEqual([e["name"] for e in wiki], ["wikipedia_en_all.zim"])
        self.assertEqual(wiki[0]["file"], "wikipedia_en_all_2024-01.zim")
        self.assertEqual(wiki[0]["location"], "u-1")
        maps = locations.scan(self.loc, "maps")
        self.assertEqual([(e["name"], e["size"]) for e in maps], [("austria.pmtiles", 3)])
        self.assertEqual(maps[0]["path"], self.root / "maps" / "Austria.PMTILES")

    def test_scan_hidden_files_ignored(self):
        self.put("wiki", ".half.zim")
        self.assertEqual(locations.scan(self.loc, "wiki"), [])

    def test_scan_unusable_name_flagged(self):
        self.put("maps", "!!!.pmtiles")
        [e] = locations.scan(self.loc, "maps")
        self.assertEqual(e["name"], "!!!.pmtiles")
        self.assertIn("can't be used", e["refusal"])

    def test_scan_missing_location_empty(self):
        gone = Location(id="u-2", name="Gone", root=self.root / "nope", order=2)
        self.assertEqual(locations.scan(gone, "wiki"), [])


if __name__ == "__main__":
    unittest.main()
