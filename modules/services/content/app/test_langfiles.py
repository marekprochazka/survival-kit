"""Unit tests for langfiles.py — names and import checks of translation models and dictionaries.

make_model() and make_dict() build small but well-formed files; the language service's tests
use them too.
"""

import gzip
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import langfiles
from content import Refused

B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
BPE_CODES = "#version: 0.2\nh e\nhe l\nhel lo\nw o\nwo r\nwor l\nworl d\n"


def b64num(n):
    """A number in dictd's base64 (most significant digit first)."""
    out = ""
    while True:
        out = B64[n % 64] + out
        n //= 64
        if not n:
            return out


def make_model(path, from_code, to_code, tokenizer="bpe", extra=None, prefix=""):
    """An .argosmodel-shaped zip: metadata, a stand-in model.bin and a tokenizer file.

    tokenizer: "bpe" (bpe.model holds BPE_CODES), "sentencepiece" (bytes from extra["sp"] or a
    stand-in) or None. extra: more members {name: bytes}, inside the top folder unless the name
    starts with "/" (then at the archive root, without the slash).
    """
    top = f"translate-{from_code}_{to_code}-1_0"
    meta = {"package_version": "1.0", "from_code": from_code, "to_code": to_code,
            "from_name": from_code.upper(), "to_name": to_code.upper()}
    if prefix:
        meta["target_prefix"] = prefix
    extra = dict(extra or {})
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{top}/metadata.json", json.dumps(meta))
        z.writestr(f"{top}/model/model.bin", b"stand-in")
        z.writestr(f"{top}/model/shared_vocabulary.json", "[]")
        if tokenizer == "bpe":
            z.writestr(f"{top}/bpe.model", BPE_CODES)
        elif tokenizer == "sentencepiece":
            z.writestr(f"{top}/sentencepiece.model", extra.pop("sp", b"stand-in"))
        for name, data in extra.items():
            z.writestr(name[1:] if name.startswith("/") else f"{top}/{name}", data)
    return Path(path)


def dict_files(entries, title="Test dictionary"):
    """(index text, data bytes) of a dictd database with a short title and the entries."""
    items = {"00-database-short": f"00-database-short\n     {title}\n"}
    items.update({w: f"{w}\n   {text}\n" for w, text in entries.items()})
    data, index = b"", []
    for word in sorted(items, key=str.lower):
        body = items[word].encode()
        index.append(f"{word}\t{b64num(len(data))}\t{b64num(len(body))}\n")
        data += body
    return "".join(index), data


def make_dict(path, entries, title="Test dictionary", dz=True, stem="tst-eng"):
    """A FreeDict-shaped .dictd.tar.xz: <stem>/<stem>.index + .dict.dz (or .dict)."""
    index, data = dict_files(entries, title)
    members = {f"{stem}/{stem}.index": index.encode()}
    if dz:
        members[f"{stem}/{stem}.dict.dz"] = gzip.compress(data)
    else:
        members[f"{stem}/{stem}.dict"] = data
    members[f"{stem}/README"] = b"test\n"
    _tar(path, members)
    return Path(path)


def _tar(path, members):
    with tarfile.open(path, "w:xz") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


class Names(unittest.TestCase):
    def test_translate_name_from_argos_download(self):
        self.assertEqual(langfiles.translate_name("translate-en_cs-1_9_6.argosmodel"), "en_cs.argosmodel")

    def test_translate_name_plain(self):
        self.assertEqual(langfiles.translate_name("en_cs.argosmodel"), "en_cs.argosmodel")
        self.assertEqual(langfiles.translate_name("C:\\Downloads\\translate-de_en-1_0.ARGOSMODEL"), "de_en.argosmodel")

    def test_translate_name_refuses_other(self):
        for bad in ["model.zip", "en-cs.argosmodel", "english_czech.argosmodel", "translate-en_cs.zip"]:
            with self.assertRaises(Refused, msg=bad):
                langfiles.translate_name(bad)

    def test_dict_name_drops_prefix_and_version(self):
        self.assertEqual(langfiles.dict_name("freedict-eng-ces-0.1.3.dictd.tar.xz"), "eng-ces.dictd.tar.xz")
        self.assertEqual(langfiles.dict_name("freedict-eng-deu-1.9-fd1.dictd.tar.xz"), "eng-deu.dictd.tar.xz")
        self.assertEqual(langfiles.dict_name("My Dict.dictd.tar.xz"), "my_dict.dictd.tar.xz")

    def test_dict_name_refuses_other_ext(self):
        for bad in ["eng-ces.tar.xz", "eng-ces.dict.dz", ".dictd.tar.xz"]:
            with self.assertRaises(Refused, msg=bad):
                langfiles.dict_name(bad)


class Models(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_check_model_bpe(self):
        info = langfiles.check_model(make_model(self.dir / "m.argosmodel", "en", "cs"))
        self.assertEqual(info["tokenizer"], "bpe")
        self.assertEqual((info["from_code"], info["to_code"]), ("en", "cs"))
        self.assertEqual((info["from_name"], info["to_name"]), ("EN", "CS"))
        self.assertEqual(info["target_prefix"], "")

    def test_check_model_sentencepiece(self):
        info = langfiles.check_model(make_model(self.dir / "m.argosmodel", "de", "en", tokenizer="sentencepiece"))
        self.assertEqual(info["tokenizer"], "sentencepiece")

    def test_check_model_refuses_not_zip(self):
        p = self.dir / "m.argosmodel"
        p.write_bytes(b"not a zip")
        with self.assertRaises(Refused):
            langfiles.check_model(p)

    def test_check_model_refuses_missing_model_bin(self):
        p = self.dir / "m.argosmodel"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("t/metadata.json", json.dumps({"from_code": "en", "to_code": "cs"}))
            z.writestr("t/bpe.model", BPE_CODES)
        with self.assertRaises(Refused):
            langfiles.check_model(p)

    def test_check_model_refuses_no_tokenizer(self):
        with self.assertRaises(Refused):
            langfiles.check_model(make_model(self.dir / "m.argosmodel", "en", "cs", tokenizer=None))

    def test_check_model_refuses_traversal(self):
        p = make_model(self.dir / "m.argosmodel", "en", "cs", extra={"/../evil": b"x"})
        with self.assertRaises(Refused):
            langfiles.check_model(p)

    def test_check_model_refuses_huge(self):
        p = make_model(self.dir / "m.argosmodel", "en", "cs")
        with mock.patch.object(langfiles, "MAX_UNPACKED", 10), self.assertRaises(Refused):
            langfiles.check_model(p)

    def test_validate_model_name_must_match_pair(self):
        p = make_model(self.dir / "m.argosmodel", "en", "cs")
        langfiles.validate_model(p, "en_cs.argosmodel")
        with self.assertRaises(Refused) as e:
            langfiles.validate_model(p, "de_en.argosmodel")
        self.assertIn("de_en", str(e.exception))
        self.assertIn("en_cs", str(e.exception))


class Dicts(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_check_dict_reads_title_and_words(self):
        for dz in (True, False):
            p = make_dict(self.dir / f"d{dz}.dictd.tar.xz", {"house": "dům", "dog": "pes"}, title="English-Czech", dz=dz)
            self.assertEqual(langfiles.check_dict(p), {"title": "English-Czech", "words": 2})

    def test_check_dict_title_without_headword_line(self):
        # FreeDict's own files: the entry is just the title (seen in eng-ces 0.1.3)
        data = b"English-Czech FreeDict Dictionary ver. 0.1.3\nhouse\n  dum\n"
        index = f"00databaseshort\tA\t{b64num(45)}\nhouse\t{b64num(45)}\t{b64num(12)}\n"
        _tar(self.dir / "d.dictd.tar.xz", {"x/x.index": index.encode(), "x/x.dict": data})
        self.assertEqual(langfiles.check_dict(self.dir / "d.dictd.tar.xz"),
                         {"title": "English-Czech FreeDict Dictionary ver. 0.1.3", "words": 1})

    def test_check_dict_refuses_bad_index_line(self):
        _tar(self.dir / "d.dictd.tar.xz", {"x/x.index": b"house\tA\n", "x/x.dict": b"house\n"})
        with self.assertRaises(Refused):
            langfiles.check_dict(self.dir / "d.dictd.tar.xz")

    def test_check_dict_refuses_offset_outside_data(self):
        _tar(self.dir / "d.dictd.tar.xz", {"x/x.index": b"house\tA\tZZ\n", "x/x.dict": b"house\n"})
        with self.assertRaises(Refused):
            langfiles.check_dict(self.dir / "d.dictd.tar.xz")

    def test_check_dict_refuses_two_indexes(self):
        index, data = dict_files({"a": "b"})
        _tar(self.dir / "d.dictd.tar.xz", {"x/x.index": index.encode(), "x/y.index": index.encode(), "x/x.dict": data})
        with self.assertRaises(Refused):
            langfiles.check_dict(self.dir / "d.dictd.tar.xz")

    def test_check_dict_refuses_not_tar(self):
        (self.dir / "d.dictd.tar.xz").write_bytes(b"nope")
        with self.assertRaises(Refused):
            langfiles.check_dict(self.dir / "d.dictd.tar.xz")

    def test_check_dict_refuses_huge(self):
        p = make_dict(self.dir / "d.dictd.tar.xz", {"house": "dům"})
        with mock.patch.object(langfiles, "MAX_UNPACKED", 10), self.assertRaises(Refused):
            langfiles.check_dict(p)


if __name__ == "__main__":
    unittest.main()
