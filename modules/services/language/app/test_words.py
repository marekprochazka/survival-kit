"""Unit tests for archives.py, dictd.py and thesaurus.py (no VM).

The fixture builders come from the content manager's test_langfiles.py (copied next to this
app by checks/language-unit.nix).
"""

import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import archives
import langfiles
import dictd
import thesaurus
from test_langfiles import make_dict, make_model

MOBY = (
    "big,large,great,huge,sizable\r\n"
    "house,home,dwelling,abode\r\n"
    "Bigwig,VIP,notable\r\n"
)


class Archives(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cache = self.tmp / "cache"
        self.cache.mkdir()

    def test_unpack_model_once(self):
        m = make_model(self.tmp / "en_cs.argosmodel", "en", "cs", extra={"stanza/big.pt": b"x" * 100})
        folder = archives.unpack(m, self.cache)
        self.assertTrue((folder / "metadata.json").is_file())
        self.assertTrue((folder / "model" / "model.bin").is_file())
        self.assertTrue((folder / "bpe.model").is_file())
        self.assertFalse((folder / "stanza").exists())  # not needed: left in the archive
        done = (folder / ".done").stat().st_mtime_ns
        self.assertEqual(archives.unpack(m, self.cache), folder)
        self.assertEqual((folder / ".done").stat().st_mtime_ns, done)

    def test_unpack_redoes_unfinished(self):
        m = make_model(self.tmp / "en_cs.argosmodel", "en", "cs")
        folder = archives.unpack(m, self.cache)
        (folder / ".done").unlink()
        (folder / "junk").write_text("x")
        self.assertEqual(archives.unpack(m, self.cache), folder)
        self.assertFalse((folder / "junk").exists())

    def test_unpack_dict_decompresses_dz(self):
        d = make_dict(self.tmp / "eng-ces.dictd.tar.xz", {"house": "dum"}, dz=True)
        folder = archives.unpack(d, self.cache)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), [".done", "dict.dict", "dict.index"])
        self.assertIn(b"house", (folder / "dict.dict").read_bytes())

    def test_unpack_dict_refuses_huge_data(self):
        d = make_dict(self.tmp / "big.dictd.tar.xz", {f"w{i}": "x" * 100 for i in range(50)})
        with mock.patch.object(langfiles, "MAX_DATA", 1000), self.assertRaises(archives.Unusable):
            archives.unpack(d, self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])  # nothing half-written left

    def test_extract_refuses_traversal(self):
        bad = self.tmp / "bad.dictd.tar.xz"
        with tarfile.open(bad, "w:xz") as t:
            for name, data in {"x/x.index": b"a\tA\tB\n", "../../evil.dict": b"a\n"}.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        with self.assertRaises(archives.Unusable):
            archives.unpack(bad, self.cache)
        self.assertFalse((self.tmp / "evil.dict").exists())
        zbad = self.tmp / "bad.argosmodel"
        with zipfile.ZipFile(zbad, "w") as z:
            z.writestr("t/metadata.json", '{"from_code": "en", "to_code": "cs"}')
            z.writestr("t/model/model.bin", b"x")
            z.writestr("t/bpe.model", b"x")
            z.writestr("../evil", b"x")
        with self.assertRaises(archives.Unusable):
            archives.unpack(zbad, self.cache)
        self.assertEqual([p for p in self.cache.iterdir() if not p.name.startswith(".")], [])

    def test_prune_keeps_listed(self):
        a = archives.unpack(make_model(self.tmp / "a.argosmodel", "en", "cs"), self.cache)
        b = archives.unpack(make_model(self.tmp / "b.argosmodel", "cs", "en"), self.cache)
        archives.prune(self.cache, {a})
        self.assertTrue(a.is_dir())
        self.assertFalse(b.exists())

    def test_key_changes_with_file(self):
        m = make_model(self.tmp / "en_cs.argosmodel", "en", "cs")
        first = archives.unpack(m, self.cache)
        os.utime(m, ns=(1, 1))
        self.assertNotEqual(archives.unpack(m, self.cache), first)


class Dictionary(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        archive = make_dict(tmp / "d.dictd.tar.xz",
                            {"house": "a building for people to live in", "household": "the people of a house",
                             "dog": "an animal", "House music": "a kind of music"},
                            title="Test English")
        self.d = dictd.Dictionary(archives.unpack(archive, tmp))

    def test_title_from_database_short(self):
        self.assertEqual(self.d.title, "Test English")

    def test_lookup_exact(self):
        entries = self.d.lookup("dog")
        self.assertEqual(len(entries), 1)
        self.assertIn("an animal", entries[0])

    def test_lookup_ignores_case_and_spaces(self):
        for word in ["  House ", "HOUSE", "house"]:
            entries = self.d.lookup(word)
            self.assertEqual(len(entries), 1, word)
            self.assertIn("a building", entries[0])

    def test_lookup_missing_gives_near(self):
        self.assertEqual(self.d.lookup("hou"), [])
        self.assertEqual(self.d.near("hou"), ["house", "House music", "household"])
        self.assertEqual(self.d.near("zzz"), [])
        self.assertNotIn("00-database-short", self.d.near("0"))


class Thesaurus(unittest.TestCase):
    def setUp(self):
        path = Path(tempfile.mkdtemp()) / "moby.txt"
        path.write_bytes(MOBY.encode("latin-1"))
        self.t = thesaurus.Thesaurus(path)

    def test_synonyms(self):
        self.assertEqual(self.t.synonyms("big"), ["large", "great", "huge", "sizable"])

    def test_synonyms_ignores_case_and_spaces(self):
        self.assertEqual(self.t.synonyms("  BIG "), ["large", "great", "huge", "sizable"])
        self.assertEqual(self.t.synonyms("bigwig"), ["VIP", "notable"])

    def test_synonyms_missing_is_none(self):
        self.assertIsNone(self.t.synonyms("blue"))
        self.assertEqual(self.t.near("bi"), ["big", "Bigwig"])


if __name__ == "__main__":
    unittest.main()
