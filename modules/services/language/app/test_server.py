"""Tests for server.py — the catalog of what is installed and the HTTP API (stand-in model)."""

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import server
from test_langfiles import make_dict, make_model
from test_translate import Echo
from test_words import MOBY


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.builtins = self.tmp / "builtins"
        for d in ("translate", "dict"):
            (self.builtins / d).mkdir(parents=True)
        make_model(self.builtins / "translate" / "en_cs.argosmodel", "en", "cs")
        make_model(self.builtins / "translate" / "cs_en.argosmodel", "cs", "en")
        make_dict(self.builtins / "dict" / "wordnet.dictd.tar.xz", {"house": "a building to live in"}, title="WordNet")
        (self.builtins / "moby.txt").write_bytes(MOBY.encode("latin-1"))
        self.cache = self.tmp / "cache"
        self.cache.mkdir()
        self.data = self.tmp / "data"
        for d in ("translate", "dict"):
            (self.data / d).mkdir(parents=True)
        self.library = self.tmp / "library"
        self.swap()
        self.catalog = server.Catalog(self.library, self.builtins, self.cache, load=Echo)

    def swap(self, links=()):
        """A fresh library index (a symlink to a folder of links), as library.py makes it."""
        new = self.tmp / f".library-{time.time_ns()}"
        for d in ("translate", "dict"):
            (new / d).mkdir(parents=True)
        for kind, name, target in links:
            os.symlink(target, new / kind / name)
        tmp_link = self.tmp / ".link"
        os.symlink(new.name, tmp_link)
        os.replace(tmp_link, self.library)


class Catalog(Base):
    def test_languages_lists_builtins(self):
        translator, dicts, thes = self.catalog.current()
        self.assertEqual([x["code"] for x in translator.languages()], ["cs", "en"])
        self.assertEqual([(i, d.title) for i, d in dicts.items()], [("wordnet", "WordNet")])
        self.assertEqual(thes.synonyms("big")[0], "large")

    def test_library_entry_overrides_builtin(self):
        mine = make_model(self.data / "translate" / "en_cs.argosmodel", "en", "cs")
        self.swap([("translate", "en_cs.argosmodel", mine)])
        self.assertEqual(self.catalog.sources()["translate"]["en_cs.argosmodel"], self.library / "translate" / "en_cs.argosmodel")
        self.assertEqual(self.catalog.sources()["translate"]["cs_en.argosmodel"], self.builtins / "translate" / "cs_en.argosmodel")

    def test_catalog_drops_missing_files(self):
        de = make_model(self.data / "translate" / "de_en.argosmodel", "de", "en")
        eng = make_dict(self.data / "dict" / "eng-ces.dictd.tar.xz", {"house": "dum"}, title="English-Czech")
        self.swap([("translate", "de_en.argosmodel", de), ("dict", "eng-ces.dictd.tar.xz", eng)])
        translator, dicts, _ = self.catalog.current()
        self.assertIn("de", [x["code"] for x in translator.languages()])
        self.assertEqual(list(dicts), ["wordnet", "eng-ces"])
        de.unlink()  # the drive went away; the library hasn't caught up yet
        eng.unlink()
        translator, dicts, _ = self.catalog.current()
        self.assertEqual([x["code"] for x in translator.languages()], ["cs", "en"])
        self.assertEqual(list(dicts), ["wordnet"])

    def test_catalog_skips_broken_file(self):
        bad = self.data / "translate" / "fr_en.argosmodel"
        bad.write_bytes(b"not a zip")
        self.swap([("translate", "fr_en.argosmodel", bad)])
        translator, _, _ = self.catalog.current()
        self.assertEqual([x["code"] for x in translator.languages()], ["cs", "en"])

    def test_catalog_rebuilds_after_library_swap(self):
        first = self.catalog.current()
        self.assertIs(self.catalog.current()[0], first[0])  # nothing changed: same objects
        de = make_model(self.data / "translate" / "de_en.argosmodel", "de", "en")
        self.swap([("translate", "de_en.argosmodel", de)])
        translator, _, _ = self.catalog.current()
        self.assertIn("de", [x["code"] for x in translator.languages()])
        # a model already loaded stays loaded (same unpacked folder)
        self.assertIs(translator.models[("en", "cs")], first[0].models[("en", "cs")])

    def test_cache_pruned(self):
        de = make_model(self.data / "translate" / "de_en.argosmodel", "de", "en")
        self.swap([("translate", "de_en.argosmodel", de)])
        self.catalog.current()
        before = len(list(self.cache.iterdir()))
        self.swap()
        self.catalog.current()
        self.assertEqual(len(list(self.cache.iterdir())), before - 1)


class Api(Base):
    def setUp(self):
        super().setUp()
        static = self.tmp / "static"
        static.mkdir()
        (static / "index.html").write_text("<html></html>")
        (static / "language.js").write_text("// js")
        (static / "style.css").write_text("/* css */")
        self.httpd = server.make_server(server.Config(port=0, static_dir=static), self.catalog)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health_and_static(self):
        self.assertEqual(self.call("GET", "/health"), (200, b"ok"))
        self.assertEqual(self.call("GET", "/")[0], 200)
        self.assertEqual(self.call("GET", "/language.js")[0], 200)
        self.assertEqual(self.call("GET", "/nope")[0], 404)

    def test_languages_endpoint(self):
        status, r = self.call("GET", "/api/languages")
        self.assertEqual(status, 200)
        self.assertEqual(r["languages"], [{"code": "cs", "name": "CS"}, {"code": "en", "name": "EN"}])
        self.assertEqual(r["targets"], {"cs": ["en"], "en": ["cs"]})
        self.assertEqual(r["direct"], {"cs": ["en"], "en": ["cs"]})
        self.assertEqual(r["dictionaries"], [{"id": "wordnet", "title": "WordNet"}])
        self.assertTrue(r["thesaurus"])

    def test_languages_marks_pivot(self):
        de = make_model(self.data / "translate" / "de_en.argosmodel", "de", "en")
        self.swap([("translate", "de_en.argosmodel", de)])
        r = self.call("GET", "/api/languages")[1]
        self.assertEqual(r["targets"]["de"], ["cs", "en"])
        self.assertEqual(r["direct"]["de"], ["en"])  # cs only through English

    def test_translate_endpoint(self):
        status, r = self.call("POST", "/api/translate", {"text": "Hello, world.", "from": "en", "to": "cs"})
        self.assertEqual((status, r), (200, {"text": "Hello, world."}))

    def test_translate_refused_is_400(self):
        status, r = self.call("POST", "/api/translate", {"text": "Hi", "from": "en", "to": "de"})
        self.assertEqual(status, 400)
        self.assertIn("no translation", r["error"])
        status, r = self.call("POST", "/api/translate", {"text": 5, "from": "en", "to": "cs"})
        self.assertEqual(status, 400)
        status, r = self.call("POST", "/api/translate", {"text": "x" * 5001, "from": "en", "to": "cs"})
        self.assertEqual(status, 400)
        self.assertIn("5000", r["error"])

    def test_translate_needs_json(self):
        req = urllib.request.Request(self.base + "/api/translate", data=b"text=hi", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 415)

    def test_define_endpoint(self):
        status, r = self.call("GET", "/api/define?dict=wordnet&word=House")
        self.assertEqual(status, 200)
        self.assertIn("a building", r["entries"][0])
        status, r = self.call("GET", "/api/define?dict=wordnet&word=hou")
        self.assertEqual((r["entries"], r["near"]), ([], ["house"]))
        self.assertEqual(self.call("GET", "/api/define?dict=nope&word=x")[0], 404)

    def test_synonyms_endpoint(self):
        status, r = self.call("GET", "/api/synonyms?word=Big")
        self.assertEqual((status, r["words"][:2]), (200, ["large", "great"]))
        status, r = self.call("GET", "/api/synonyms?word=bi")
        self.assertEqual((r["words"], r["near"]), ([], ["big", "Bigwig"]))


if __name__ == "__main__":
    unittest.main()
