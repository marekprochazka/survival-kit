"""Tests for server.py — the HTTP API on a real local server, with stand-ins for Kiwix/Ollama."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import content
import drives as drv
import langfiles
import locations
import pmtiles
import pmtiles_fixture
import server
from test_content import PROTECTED, Box, FakeOllama
from test_langfiles import make_dict, make_model

GB = 1000**3


def usage(path):
    """This device: 50 of 100 GB free; added drives: 3 of 10 GB."""
    return (10 * GB, 3 * GB) if "/drives/" in str(path) else (100 * GB, 50 * GB)


def fixture_bytes(**kw):
    with tempfile.TemporaryDirectory() as d:
        return pmtiles_fixture.write(Path(d) / "m.pmtiles", **kw).read_bytes()


class Sizes(unittest.TestCase):
    def test_size_mb_below_a_gb(self):
        self.assertEqual(server._size(15_051_084), "15 MB")
        self.assertEqual(server._size(127_212_288), "127 MB")  # was "0.1 GB"
        self.assertEqual(server._size(999_000_000), "999 MB")
        self.assertEqual(server._size(2_019_000_000), "2.0 GB")


def model_bytes(from_code="en", to_code="de"):
    with tempfile.TemporaryDirectory() as d:
        return make_model(Path(d) / "m.argosmodel", from_code, to_code).read_bytes()


def dict_bytes(entries=None):
    with tempfile.TemporaryDirectory() as d:
        return make_dict(Path(d) / "d.dictd.tar.xz", entries or {"house": "dum"}).read_bytes()


class Api(unittest.TestCase):
    models_enabled = True
    maps_enabled = True
    language_enabled = True

    def setUp(self):
        self.box = Box(usage=usage)
        root = self.box.root
        self.dev = self.box.device().root
        self.zims = self.dev / "wiki"
        (root / "state" / "incoming").mkdir(parents=True)
        static = root / "static"
        static.mkdir()
        (static / "index.html").write_text("<html><!--CONTENT--></html>")
        (static / "content.js").write_text("// js")
        (static / "style.css").write_text("/* css */")
        self.wiki = content.Shelf(
            self.box.places,
            "wiki",
            builtins={"devdocs_en_git.zim": 100, "survival-kit.zim": 50},
            protected=PROTECTED,
            validate=lambda p: None,
            refresh=self.box.rebuild,
            noun="book",
        )
        self.maps_dir = self.dev / "maps"
        maps = (
            content.Shelf(
                self.box.places,
                "maps",
                builtins={"czechia.pmtiles": 100, "world.pmtiles": 10},
                protected=set(),
                validate=lambda p: pmtiles.check(p, 4),
                refresh=self.box.rebuild,
                noun="map",
            )
            if self.maps_enabled
            else None
        )
        translate = dicts = None
        if self.language_enabled:
            translate = content.Shelf(
                self.box.places,
                "translate",
                builtins={"en_cs.argosmodel": 70, "cs_en.argosmodel": 71},
                protected=set(),
                validate=server.model_check,
                refresh=self.box.rebuild,
                noun="translation model",
                named=True,
            )
            dicts = content.Shelf(
                self.box.places,
                "dict",
                builtins={"wordnet.dictd.tar.xz": 30},
                protected=set(),
                validate=server.dict_check,
                refresh=self.box.rebuild,
                noun="dictionary",
            )
        self.ollama = FakeOllama()
        models = content.Models(self.ollama) if self.models_enabled else None
        config = server.Config(port=0, static_dir=static, model_incoming=root / "state" / "incoming")
        # drives: what lsblk would offer, and which are plugged in when the mount service runs
        self.offered = []
        self.plugged = set()
        self.drives = server.Drives(
            registry=drv.Registry(self.box.registry),
            candidates=lambda: list(self.offered),
            state=lambda: json.loads(self.box.drive_state.read_text()) if self.box.drive_state.exists() else {},
            apply=self.mount_service,
        )
        self.httpd = server.make_server(config, self.wiki, models, self.box.places, maps, self.drives, translate, dicts)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def mount_service(self):
        """Stands in for survival-kit-drives + the library: mount what is plugged in."""
        state = {}
        for d in self.drives.registry.drives():
            if d["uuid"] in self.plugged:
                locations.ensure_tree(self.box.root / "drives" / d["uuid"] / "survival-kit", d["name"])
                state[d["uuid"]] = {"mounted": True, "error": None}
            else:
                state[d["uuid"]] = {"mounted": False, "error": "not connected"}
        self.box.drive_state.write_text(json.dumps(state))
        self.box.rebuild()

    def offer(self, uuid, fstype="ext4", label="BIG", refusal=None):
        self.offered.append({"uuid": uuid, "path": "/dev/sdb1", "label": label, "model": "USB", "size": 10 * GB,
                             "fstype": fstype, "desktop": False, "refusal": refusal})
        self.plugged.add(uuid)

    def add_drive(self, uuid):
        self.offer(uuid)
        status, r = self.json("POST", f"/api/drives/add?uuid={uuid}")
        self.assertEqual((status, r["mounted"]), (200, True), r)
        return self.box.root / "drives" / uuid / "survival-kit"

    def call(self, method, path, data=None, headers=None):
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                body = r.read()
                return r.status, body
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json(self, method, path, data=None):
        status, body = self.call(method, path, data)
        return status, json.loads(body)

    def test_health_and_static(self):
        self.assertEqual(self.call("GET", "/health"), (200, b"ok"))
        status, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"devdocs_en_git", page)  # lists are rendered into the page (no JS needed)
        self.assertEqual(self.call("GET", "/content.js")[0], 200)
        self.assertEqual(self.call("GET", "/style.css")[0], 200)
        self.assertEqual(self.call("GET", "/../etc/passwd")[0], 404)

    def test_status_shape(self):
        status, s = self.json("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(s["disk"]["total"], 100 * GB)
        self.assertEqual(s["disk"]["free"], 50 * GB)
        self.assertEqual(
            set(s),
            {"disk", "wiki", "builtins", "maps", "map_builtins", "models", "models_error", "locations", "drives",
             "translate", "translate_builtins", "dict", "dict_builtins"},
        )
        self.assertIsNone(s["models_error"])
        self.assertEqual(s["models"], [])
        self.assertEqual(s["maps"], [])
        self.assertEqual([b["name"] for b in s["map_builtins"]], ["czechia.pmtiles", "world.pmtiles"])
        self.assertEqual(s["disk"]["maps"], 0)

    def test_upload_translation_model(self):
        data = model_bytes("en", "de")
        status, r = self.json("PUT", "/api/upload?kind=translate&file=translate-en_de-1_9_6.argosmodel", data)
        self.assertEqual((status, r["name"], r["result"]), (200, "en_de.argosmodel", "added"), r)
        s = self.json("GET", "/api/status")[1]
        self.assertEqual([m["name"] for m in s["translate"]], ["en_de.argosmodel"])
        self.assertEqual(s["disk"]["languages"], len(data))
        status, r = self.json("GET", "/api/check?kind=translate&file=en_cs.argosmodel&size=10")
        self.assertEqual((status, r["exists"]), (200, "builtin"))

    def test_upload_model_with_wrong_pair_refused(self):
        status, r = self.json("PUT", "/api/upload?kind=translate&file=fr_en.argosmodel", model_bytes("en", "de"))
        self.assertEqual(status, 400)
        self.assertIn("en_de", r["error"])
        status, r = self.json("PUT", "/api/upload?kind=translate&file=x.zip", b"x")
        self.assertEqual(status, 400)
        self.assertEqual(self.json("GET", "/api/status")[1]["translate"], [])
        self.assertEqual(list((self.dev / ".incoming").iterdir()), [])

    def test_upload_dictionary(self):
        status, r = self.json("PUT", "/api/upload?kind=dict&file=freedict-eng-ces-0.1.3.dictd.tar.xz", dict_bytes())
        self.assertEqual((status, r["name"]), (200, "eng-ces.dictd.tar.xz"), r)
        self.assertEqual([d["name"] for d in self.json("GET", "/api/status")[1]["dict"]], ["eng-ces.dictd.tar.xz"])
        status, r = self.json("PUT", "/api/upload?kind=dict&file=junk.dictd.tar.xz", b"nope")
        self.assertEqual(status, 400)
        self.assertIn("not a dictionary", r["error"])

    def test_delete_language_files(self):
        self.json("PUT", "/api/upload?kind=translate&file=en_de.argosmodel", model_bytes("en", "de"))
        self.json("PUT", "/api/upload?kind=dict&file=eng-ces.dictd.tar.xz", dict_bytes())
        self.assertEqual(self.json("DELETE", "/api/translate/en_de.argosmodel")[0], 200)
        self.assertEqual(self.json("DELETE", "/api/dict/eng-ces.dictd.tar.xz")[0], 200)
        s = self.json("GET", "/api/status")[1]
        self.assertEqual((s["translate"], s["dict"]), ([], []))
        self.assertEqual(self.json("DELETE", "/api/translate/en_cs.argosmodel")[0], 403)
        self.assertEqual(self.json("DELETE", "/api/dict/wordnet.dictd.tar.xz")[0], 403)

    def test_page_lists_languages(self):
        page = self.call("GET", "/")[1].decode()
        self.assertIn('id="languages"', page)
        self.assertIn("Translation models", page)
        self.assertIn("Dictionaries", page)
        self.assertIn('data-import="translate"', page)
        self.assertIn('data-import="dict"', page)
        self.assertIn("<td>en_cs</td><td>built in</td>", page)
        self.assertIn("<td>wordnet</td><td>built in</td>", page)

    def test_page_has_maps_section(self):
        page = self.call("GET", "/")[1]
        self.assertIn(b'id="maps"', page)
        self.assertIn(b'data-import="map"', page)

    def test_upload_map_roundtrip(self):
        data = fixture_bytes()
        status, r = self.json("PUT", "/api/upload?kind=map&file=Austria.PMTiles", data)
        self.assertEqual((status, r["name"], r["result"], r["note"]), (200, "austria.pmtiles", "added", None))
        s = self.json("GET", "/api/status")[1]
        self.assertEqual([m["name"] for m in s["maps"]], ["austria.pmtiles"])
        self.assertEqual(s["disk"]["maps"], len(data))
        self.assertEqual(self.json("DELETE", "/api/maps/austria.pmtiles")[0], 200)
        self.assertEqual(self.json("GET", "/api/status")[1]["maps"], [])

    def test_upload_map_note_and_builtin_replace(self):
        status, r = self.json("GET", "/api/check?kind=map&file=czechia.pmtiles&size=10")
        self.assertEqual((status, r["exists"]), (200, "builtin"))
        status, r = self.json("PUT", "/api/upload?kind=map&file=czechia.pmtiles", fixture_bytes(scheme=None))
        self.assertEqual((status, r["result"]), (200, "replaced"))  # the built-in, like wiki books
        self.assertIn("Getting more maps", r["note"])
        flags = {b["name"]: b for b in self.json("GET", "/api/status")[1]["map_builtins"]}
        self.assertTrue(flags["czechia.pmtiles"]["replaced"])

    def test_upload_map_refused(self):
        status, r = self.json("PUT", "/api/upload?kind=map&file=junk.pmtiles", b"x" * 300)
        self.assertEqual(status, 400)
        self.assertIn("not a PMTiles map", r["error"])
        status, r = self.json("PUT", "/api/upload?kind=map&file=pic.pmtiles", fixture_bytes(tile_type=2))
        self.assertIn("raster", r["error"])
        self.assertEqual(self.json("PUT", "/api/upload?kind=map&file=a.mbtiles", b"x")[0], 400)
        self.assertEqual(self.json("DELETE", "/api/maps/czechia.pmtiles")[0], 403)
        self.assertEqual(self.json("GET", "/api/status")[1]["maps"], [])
        self.assertEqual(list((self.dev / ".incoming").iterdir()), [])

    def test_upload_wiki_roundtrip(self):
        status, r = self.json("PUT", "/api/upload?kind=wiki&file=Book_2026-01.zim", b"zimdata")
        self.assertEqual((status, r["name"]), (200, "Book.zim"))
        self.assertEqual([b["name"] for b in self.json("GET", "/api/status")[1]["wiki"]], ["Book.zim"])
        status, _ = self.json("DELETE", "/api/wiki/Book.zim")
        self.assertEqual(status, 200)
        self.assertEqual(self.json("GET", "/api/status")[1]["wiki"], [])

    def test_upload_model_roundtrip(self):
        status, r = self.json("PUT", "/api/upload?kind=model&file=My-Model.gguf&model=my%20model", b"gguf")
        self.assertEqual((status, r["name"]), (200, "my-model"))
        self.assertEqual(self.json("GET", "/api/status")[1]["models"], [{"name": "my-model", "size": 4}])
        self.assertEqual(self.json("DELETE", "/api/models/my-model")[0], 200)

    def test_check_reports_builtin_clash(self):
        status, r = self.json("GET", "/api/check?kind=wiki&file=devdocs_en_git_2026-11.zim&size=10")
        self.assertEqual((status, r["name"], r["exists"]), (200, "devdocs_en_git.zim", "builtin"))
        status, r = self.json("GET", f"/api/check?kind=wiki&file=big.zim&size={60 * GB}")
        self.assertEqual(status, 400)
        self.assertIn("not enough space", r["error"])

    def test_page_survives_ollama_down(self):
        def down():
            raise OSError("connection refused")

        self.ollama.tags = down
        status, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"devdocs_en_git", page)  # the wiki part still works
        status, s = self.json("GET", "/api/status")
        self.assertEqual(status, 200)
        if self.models_enabled:
            self.assertIn(b"not available right now", page)
            self.assertEqual(s["models_error"], "not available right now")

    def test_long_name_refused_cleanly(self):
        status, r = self.json("PUT", "/api/upload?kind=wiki&file=" + "a" * 300 + ".zim", b"x")
        self.assertEqual(status, 400)
        self.assertEqual(list((self.dev / ".incoming").iterdir()), [])

    def test_check_bad_size_refused(self):
        self.assertEqual(self.json("GET", "/api/check?kind=wiki&file=a.zim&size=lots")[0], 400)

    def test_ollama_error_message_is_text(self):
        import subprocess
        from unittest import mock

        done = subprocess.CompletedProcess([], 1, stdout="", stderr="pulling…\nError: invalid file magic\n")
        with mock.patch("subprocess.run", return_value=done):
            with self.assertRaises(RuntimeError) as cm:
                server.Ollama(self.zims)._run("create", "x")
        self.assertEqual(str(cm.exception), "Error: invalid file magic")

    def test_ollama_panic_message_is_the_panic_line(self):
        import subprocess
        from unittest import mock

        trace = "panic: $HOME is not defined\n\ngoroutine 1 [running]:\n\tgithub.com/ollama/ollama/main.go:12 +0x13\n"
        done = subprocess.CompletedProcess([], 2, stdout="", stderr=trace)
        with mock.patch("subprocess.run", return_value=done):
            with self.assertRaises(RuntimeError) as cm:
                server.Ollama(self.zims)._run("create", "x")
        self.assertEqual(str(cm.exception), "panic: $HOME is not defined")

    def test_upload_without_length_refused(self):
        conn = urllib.request.urlopen  # noqa: F841 — raw socket keeps Content-Length out
        import http.client

        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1])
        c.putrequest("PUT", "/api/upload?kind=wiki&file=a.zim")
        c.endheaders()
        self.assertIn(c.getresponse().status, (400, 411))

    def test_api_refusals(self):
        self.assertEqual(self.json("DELETE", "/api/wiki/survival-kit.zim")[0], 403)
        self.assertEqual(self.json("DELETE", "/api/wiki/devdocs_en_git.zim")[0], 403)
        self.assertEqual(self.json("PUT", "/api/upload?kind=wiki&file=survival-kit.zim", b"x")[0], 403)
        self.assertEqual(self.json("PUT", "/api/upload?kind=wiki&file=a.txt", b"x")[0], 400)
        self.assertEqual(self.json("DELETE", "/api/wiki/..%2Fx.zim")[0], 400)
        self.assertEqual(self.json("PUT", "/api/upload?kind=nope&file=a.zim", b"x")[0], 400)
        self.assertEqual(list((self.dev / ".incoming").iterdir()), [])

    # --- locations and drives (ADR-0006) ---

    def test_upload_to_drive_location(self):
        tree = self.add_drive("u-1")
        status, r = self.json("PUT", "/api/upload?kind=wiki&file=book.zim&to=u-1", b"zimdata")
        self.assertEqual((status, r["result"]), (200, "added"))
        self.assertEqual((tree / "wiki" / "book.zim").read_bytes(), b"zimdata")
        self.assertEqual(list((tree / ".incoming").iterdir()), [])
        [item] = self.json("GET", "/api/status")[1]["wiki"]
        self.assertEqual((item["location"], item["status"]), ("u-1", "in_use"))

    def test_upload_unknown_location_refused(self):
        status, r = self.json("PUT", "/api/upload?kind=wiki&file=book.zim&to=u-404", b"x")
        self.assertEqual(status, 400)
        self.assertIn("not connected", r["error"])

    def test_space_checked_on_target_location(self):
        self.add_drive("u-1")
        size = 2 * GB  # fits this device (50 GB free), not the drive (3 GB free, 2 GiB kept)
        self.assertEqual(self.json("GET", f"/api/check?kind=wiki&file=a.zim&size={size}")[0], 200)
        status, r = self.json("GET", f"/api/check?kind=wiki&file=a.zim&size={size}&to=u-1")
        self.assertEqual(status, 400)
        self.assertIn("not enough space", r["error"])

    def test_replace_removes_only_in_use_copy(self):
        tree = self.add_drive("u-1")
        (self.zims / "book.zim").write_bytes(b"device")
        self.box.rebuild()
        status, r = self.json("PUT", "/api/upload?kind=wiki&file=book.zim&to=u-1", b"new")
        self.assertEqual(r["result"], "replaced")
        self.assertFalse((self.zims / "book.zim").exists())
        self.assertEqual((tree / "wiki" / "book.zim").read_bytes(), b"new")

    def test_delete_only_clicked_copy(self):
        tree = self.add_drive("u-1")
        (self.zims / "book.zim").write_bytes(b"a")
        (tree / "wiki" / "book.zim").write_bytes(b"b")
        self.box.rebuild()
        self.assertEqual(self.json("DELETE", "/api/wiki/book.zim?at=u-1&file=book.zim")[0], 200)
        self.assertTrue((self.zims / "book.zim").exists())
        self.assertFalse((tree / "wiki" / "book.zim").exists())

    def test_resolve_moves_invalid_and_duplicates(self):
        tree = self.add_drive("u-1")
        (self.zims / "book.zim").write_bytes(b"a")
        (tree / "wiki" / "book.zim").write_bytes(b"dup")
        (tree / "wiki" / "survival-kit.zim").write_bytes(b"manual?")  # invalid: a manual's name
        (tree / "wiki" / "keep.zim").write_bytes(b"k")
        self.box.rebuild()
        status, r = self.json("POST", "/api/resolve?at=u-1")
        self.assertEqual((status, sorted(r["moved"])), (200, ["book.zim", "survival-kit.zim"]))
        aside = list((tree.parent / "survival-kit-set-aside").glob("*/wiki/*"))
        self.assertEqual(sorted(p.name for p in aside), ["book.zim", "survival-kit.zim"])
        self.assertTrue((tree / "wiki" / "keep.zim").exists())
        self.assertTrue((self.zims / "book.zim").exists())
        statuses = {(i["location"], i["name"]): i["status"] for i in self.json("GET", "/api/status")[1]["wiki"]}
        self.assertEqual(statuses, {("device", "book.zim"): "in_use", ("u-1", "keep.zim"): "in_use"})

    def test_resolve_on_this_device(self):
        (self.zims / "junk.zim").write_bytes(b"x")
        (self.zims / "survival-kit.zim").write_bytes(b"manual?")
        self.box.rebuild()
        status, r = self.json("POST", "/api/resolve?at=device")
        self.assertEqual((status, r["moved"]), (200, ["survival-kit.zim"]))
        self.assertEqual([p.name for p in (self.dev / ".set-aside").glob("*/wiki/*")], ["survival-kit.zim"])

    def test_damaged_drive_list_keeps_the_page(self):
        self.box.registry.write_text("{nope")
        status, s = self.json("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertIn("damaged", s["drives"]["error"])
        self.assertIn(b"damaged", self.call("GET", "/")[1])
        self.offer("u-1")
        self.assertEqual(self.json("POST", "/api/drives/add?uuid=u-1")[0], 400)
        self.assertEqual(self.box.registry.read_text(), "{nope")

    def test_status_lists_locations_and_drives(self):
        self.add_drive("u-1")
        self.offer("u-2", label="OTHER")
        s = self.json("GET", "/api/status")[1]
        self.assertEqual([(loc["id"], loc["free"]) for loc in s["locations"]], [("device", 50 * GB), ("u-1", 3 * GB)])
        [added] = s["drives"]["added"]
        self.assertEqual((added["uuid"], added["name"], added["mounted"]), ("u-1", "BIG", True))
        self.assertEqual([d["uuid"] for d in s["drives"]["available"]], ["u-2"])

    def test_add_drive_refused_for_fat32(self):
        self.offer("u-fat", fstype="vfat", refusal="FAT32 can't hold files over 4 GB — use exFAT, NTFS or ext4")
        status, r = self.json("POST", "/api/drives/add?uuid=u-fat")
        self.assertEqual(status, 400)
        self.assertIn("FAT32", r["error"])
        self.assertEqual(self.drives.registry.drives(), [])

    def test_add_unknown_drive_refused(self):
        self.assertEqual(self.json("POST", "/api/drives/add?uuid=u-404")[0], 404)
        self.add_drive("u-1")
        self.assertEqual(self.json("POST", "/api/drives/add?uuid=u-1")[0], 400)  # already added

    def test_add_drive_name(self):
        self.offer("u-1")
        r = self.json("POST", "/api/drives/add?uuid=u-1&name=%20My%20%20big%20drive%20")[1]
        self.assertEqual(r["name"], "My big drive")

    def test_unplugged_drive_and_reconnect(self):
        tree = self.add_drive("u-1")
        (tree / "maps").mkdir(exist_ok=True)
        (tree / "wiki" / "far.zim").write_bytes(b"far")
        self.plugged.discard("u-1")
        status, r = self.json("POST", "/api/drives/u-1/reconnect")
        self.assertEqual((status, r["mounted"], r["error"]), (200, False, "not connected"))
        self.assertEqual(self.json("GET", "/api/status")[1]["wiki"], [])
        self.plugged.add("u-1")
        self.assertTrue(self.json("POST", "/api/drives/u-1/reconnect")[1]["mounted"])
        self.assertEqual([i["name"] for i in self.json("GET", "/api/status")[1]["wiki"]], ["far.zim"])

    def test_render_lists_drives_and_statuses(self):
        tree = self.add_drive("u-1")
        self.offer("u-fat", fstype="vfat", label="STICK", refusal="FAT32 can't hold files over 4 GB")
        (self.zims / "book.zim").write_bytes(b"a")
        (tree / "wiki" / "book.zim").write_bytes(b"b")
        (tree / "wiki" / "survival-kit.zim").write_bytes(b"c")
        self.box.rebuild()
        page = self.call("GET", "/")[1].decode()
        self.assertIn('id="drives"', page)
        self.assertIn("BIG", page)  # the added drive, by name
        self.assertIn('data-drive="u-1" data-action="forget"', page)
        self.assertIn("STICK", page)
        self.assertIn("FAT32 can&#x27;t hold files over 4 GB", page)  # refused: no Add button
        self.assertNotIn('data-action="add" data-drive="u-fat"', page)
        self.assertIn("duplicate — not in use", page)
        self.assertIn("invalid — the box&#x27;s own manual can&#x27;t be replaced", page)
        self.assertIn('data-resolve="u-1"', page)  # auto-resolve offered where needed
        self.assertNotIn('data-resolve="device"', page)
        self.assertIn('<select id="save-to"', page)
        self.assertIn('<option value="device" selected>', page)  # most free space
        self.assertIn('<option value="u-1">', page)

    def test_render_hint_when_no_drive_can_be_added(self):
        hint = "Plug in a drive to add it here."
        self.assertIn(hint, self.call("GET", "/")[1].decode())  # nothing plugged in
        self.offer("u-new", label="BIG2")
        page = self.call("GET", "/")[1].decode()
        self.assertNotIn(hint, page)  # a drive to add is listed instead
        self.assertIn('data-action="add" data-drive="u-new"', page)

    def test_render_drive_missing_offers_reconnect(self):
        self.add_drive("u-1")
        self.plugged.discard("u-1")
        self.json("POST", "/api/drives/u-1/reconnect")
        page = self.call("GET", "/")[1].decode()
        self.assertIn("not connected", page)
        self.assertIn('data-drive="u-1" data-action="reconnect"', page)
        self.assertNotIn('<option value="u-1">', page)  # can't save to a missing drive

    def test_forget_drive_keeps_files(self):
        tree = self.add_drive("u-1")
        (tree / "wiki" / "far.zim").write_bytes(b"far")
        self.assertEqual(self.json("POST", "/api/drives/u-1/forget")[0], 200)
        self.assertEqual(self.drives.registry.drives(), [])
        self.assertTrue((tree / "wiki" / "far.zim").exists())
        self.assertEqual(self.json("POST", "/api/drives/u-1/forget")[0], 404)


class LiteApi(Api):
    """A lite box: no Ollama → no models section, model uploads refused."""

    models_enabled = False

    def test_status_shape(self):
        s = self.json("GET", "/api/status")[1]
        self.assertIsNone(s["models"])
        self.assertIsNone(s["models_error"])

    def test_upload_model_roundtrip(self):
        status, r = self.json("PUT", "/api/upload?kind=model&file=m.gguf", b"gguf")
        self.assertEqual(status, 400)
        self.assertIn("no AI models", r["error"])
        self.assertEqual(self.json("DELETE", "/api/models/m")[0], 400)


class NoMapsApi(Api):
    """A box without the maps service: no maps section, map uploads refused."""

    maps_enabled = False

    def test_status_shape(self):
        s = self.json("GET", "/api/status")[1]
        self.assertIsNone(s["maps"])
        self.assertEqual(s["map_builtins"], [])

    def test_page_has_maps_section(self):
        self.assertNotIn(b'id="maps"', self.call("GET", "/")[1])

    def test_upload_map_roundtrip(self):
        status, r = self.json("PUT", "/api/upload?kind=map&file=a.pmtiles", fixture_bytes())
        self.assertEqual(status, 400)
        self.assertIn("no maps", r["error"])
        self.assertEqual(self.json("DELETE", "/api/maps/a.pmtiles")[0], 400)

    test_upload_map_note_and_builtin_replace = test_upload_map_roundtrip
    test_upload_map_refused = test_upload_map_roundtrip


class NoLanguageApi(Api):
    """A box without the Language service: no Languages section, its uploads refused."""

    language_enabled = False

    def test_status_shape(self):
        s = self.json("GET", "/api/status")[1]
        self.assertIsNone(s["translate"])
        self.assertIsNone(s["dict"])
        self.assertEqual((s["translate_builtins"], s["dict_builtins"]), ([], []))

    def test_page_lists_languages(self):
        self.assertNotIn(b'id="languages"', self.call("GET", "/")[1])

    def test_upload_translation_model(self):
        status, r = self.json("PUT", "/api/upload?kind=translate&file=en_de.argosmodel", model_bytes())
        self.assertEqual(status, 400)
        self.assertIn("no Language service", r["error"])
        self.assertEqual(self.json("DELETE", "/api/dict/x.dictd.tar.xz")[0], 400)

    test_upload_model_with_wrong_pair_refused = test_upload_translation_model
    test_upload_dictionary = test_upload_translation_model
    test_delete_language_files = test_upload_translation_model


if __name__ == "__main__":
    unittest.main()
