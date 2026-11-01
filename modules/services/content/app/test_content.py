"""Unit tests for content.py — names, space, uploads, wiki, maps and models (no HTTP, no VM)."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import content
import library
import locations
from content import Refused

GB = 1000**3
GIB = 1024**3
PROTECTED = {"survival-kit", "survival-kit-dev"}


def ok_check(path, kind):
    return {"ok": True, "reason": None, "date": None}


class Box:
    """This device + optional added drives in a temp folder, with a real library state."""

    def __init__(self, usage=lambda p: (100 * GB, 50 * GB), check=ok_check):
        self.root = Path(tempfile.mkdtemp())
        self.check = check
        locations.ensure_tree(self.root / "data", "This device")
        self.registry = self.root / "drives.json"
        self.drive_state = self.root / "run-drives.json"
        self.places = library.Places(
            self.root / "data", self.root / "drives", self.registry, self.drive_state,
            self.root / "library.json", self.root / "data" / ".set-aside", usage=usage,
            present=lambda uuid, target: (target / "survival-kit").is_dir(),
        )
        self.rebuild()

    def rebuild(self):
        locs = self.places.all()
        entries = {k: library.resolve(locs, k, self.check, PROTECTED) for k in library.KINDS_ALL}
        library.write_state(entries, self.places.state_file)

    def add_drive(self, uuid, name="Drive", mounted=True):
        """A drive as the mount service leaves it: listed, mounted, tree created."""
        drives = json.loads(self.registry.read_text()) if self.registry.exists() else []
        drives.append({"uuid": uuid, "fstype": "ext4", "name": name, "added": "2026-10-30"})
        self.registry.write_text(json.dumps(drives))
        state = json.loads(self.drive_state.read_text()) if self.drive_state.exists() else {}
        state[uuid] = {"mounted": mounted, "error": None if mounted else "not connected"}
        self.drive_state.write_text(json.dumps(state))
        locations.ensure_tree(self.root / "drives" / uuid / "survival-kit", name)
        self.rebuild()
        return self.places.get(uuid) if mounted else None

    def device(self):
        return self.places.get("device")


class Names(unittest.TestCase):
    def test_wiki_name_strips_date(self):
        self.assertEqual(
            content.wiki_name("archlinux_en_all_maxi_2026-12.zim", PROTECTED),
            "archlinux_en_all_maxi.zim",
        )
        self.assertEqual(content.wiki_name("Book.ZIM", PROTECTED), "Book.zim")

    def test_wiki_name_sanitizes(self):
        self.assertEqual(content.wiki_name("../../etc/x y.zim", PROTECTED), "x_y.zim")
        self.assertEqual(content.wiki_name("čaj.zim", PROTECTED), "_aj.zim")
        self.assertEqual(content.wiki_name("..hidden.zim", PROTECTED), "hidden.zim")

    def test_wiki_name_refuses(self):
        for bad in ["notes.txt", ".zim", "...zim", "survival-kit.zim", "survival-kit-dev_2026-10.zim"]:
            with self.subTest(bad=bad), self.assertRaises(Refused):
                content.wiki_name(bad, PROTECTED)

    def test_wiki_name_protected_is_403(self):
        with self.assertRaises(Refused) as cm:
            content.wiki_name("survival-kit.zim", PROTECTED)
        self.assertEqual(cm.exception.status, 403)

    def test_names_too_long_refused(self):
        with self.assertRaises(Refused):
            content.wiki_name("a" * 300 + ".zim", PROTECTED)
        with self.assertRaises(Refused):
            content.model_name("a" * 300 + ".gguf")
        self.assertEqual(content.wiki_name("a" * 200 + ".zim", PROTECTED), "a" * 200 + ".zim")

    def test_model_name(self):
        self.assertEqual(
            content.model_name("Llama-3.2-3B-Instruct-Q4_K_M.gguf"), "llama-3.2-3b-instruct-q4_k_m"
        )
        self.assertEqual(content.model_name("/x/My Model!.GGUF"), "my-model")
        for bad in ["x.bin", ".gguf", "!!!.gguf"]:
            with self.subTest(bad=bad), self.assertRaises(Refused):
                content.model_name(bad)

    def test_clean_model_name(self):
        self.assertEqual(content.clean_model_name("  Qwen 2.5 / 3B "), "qwen-2.5-3b")
        with self.assertRaises(Refused):
            content.clean_model_name("---")


class Space(unittest.TestCase):
    def test_margin(self):
        self.assertEqual(content.margin(100 * GB), 5 * GB)
        self.assertEqual(content.margin(20 * GB), 2 * GIB)

    def test_check_space(self):
        content.check_space(needed=1 * GB, free=10 * GB, total=100 * GB)  # 1 + 5 <= 10
        with self.assertRaises(Refused) as cm:
            content.check_space(needed=6 * GB, free=10 * GB, total=100 * GB)  # 6 + 5 > 10
        self.assertIn("not enough space", str(cm.exception))


class Receive(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_receive_ok(self):
        path = content.receive(io.BytesIO(b"x" * 3000), 3000, self.dir, chunk=1024)
        self.assertEqual(path.read_bytes(), b"x" * 3000)
        self.assertEqual(path.parent, self.dir)

    def test_receive_short_body_removes_temp(self):
        with self.assertRaises(Refused):
            content.receive(io.BytesIO(b"x" * 10), 3000, self.dir)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_receive_write_error_removes_temp(self):
        class Broken(io.RawIOBase):
            def read(self, n=-1):
                raise OSError("No space left on device")

        with self.assertRaises(Refused):
            content.receive(Broken(), 3000, self.dir)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_receive_unique_temp_names(self):
        a = content.receive(io.BytesIO(b"a"), 1, self.dir)
        b = content.receive(io.BytesIO(b"b"), 1, self.dir)
        self.assertNotEqual(a, b)


class WikiTest(unittest.TestCase):
    def setUp(self):
        self.box = Box()
        self.dev = self.box.device()
        self.zims = self.dev.root / "wiki"
        self.incoming = self.dev.root / ".incoming"
        self.refreshed = 0
        self.readable = True

        def refresh():
            self.refreshed += 1
            self.box.rebuild()

        def validate(path):
            if not self.readable:
                raise Refused("not a readable wiki book")

        self.wiki = content.Shelf(
            self.box.places,
            "wiki",
            builtins={"devdocs_en_git.zim": 100, "survival-kit.zim": 50},
            protected=PROTECTED,
            validate=validate,
            refresh=refresh,
            noun="book",
        )

    def upload(self, data=b"zim", loc=None):
        return content.receive(io.BytesIO(data), len(data), (loc or self.dev).root / ".incoming")

    def test_wiki_install_and_replace(self):
        self.wiki.install(self.upload(b"one"), "book.zim", self.dev)
        self.assertEqual(self.wiki.exists("book.zim"), "import")
        self.wiki.install(self.upload(b"two!"), "book.zim", self.dev)
        self.assertEqual((self.zims / "book.zim").read_bytes(), b"two!")
        self.assertEqual([i["name"] for i in self.wiki.items()], ["book.zim"])
        self.assertEqual(self.wiki.used(), 4)

    def test_wiki_unreadable_refused_and_removed(self):
        self.readable = False
        with self.assertRaises(Refused) as cm:
            self.wiki.install(self.upload(), "bad.zim", self.dev)
        self.assertIn("not a readable wiki book", str(cm.exception))
        self.assertEqual(list(self.incoming.iterdir()), [])
        self.assertFalse((self.zims / "bad.zim").exists())

    def test_wiki_install_error_removes_temp(self):
        def broken(path):
            raise RuntimeError("kiwix-manage missing")

        self.wiki.validate = broken
        tmp = self.upload()
        with self.assertRaises(RuntimeError):
            self.wiki.install(tmp, "a.zim", self.dev)
        self.assertEqual(list(self.incoming.iterdir()), [])

    def test_install_to_drive_replaces_in_use_copy_on_device(self):
        drive = self.box.add_drive("u-1")
        self.wiki.install(self.upload(b"old"), "book.zim", self.dev)
        self.wiki.install(self.upload(b"new", drive), "book.zim", drive)
        self.assertFalse((self.zims / "book.zim").exists())
        self.assertEqual((drive.root / "wiki" / "book.zim").read_bytes(), b"new")
        [item] = self.wiki.items()
        self.assertEqual((item["location"], item["status"]), ("u-1", "in_use"))

    def test_replace_leaves_duplicates_alone(self):
        d1 = self.box.add_drive("u-1")
        d2 = self.box.add_drive("u-2")
        (self.zims / "book.zim").write_bytes(b"in use")
        (d1.root / "wiki" / "book.zim").write_bytes(b"duplicate")
        self.box.rebuild()
        self.wiki.install(self.upload(b"new", d2), "book.zim", d2)
        self.assertFalse((self.zims / "book.zim").exists())  # the copy in use was replaced
        self.assertEqual((d1.root / "wiki" / "book.zim").read_bytes(), b"duplicate")

    def test_delete_only_the_copy_asked_for(self):
        drive = self.box.add_drive("u-1")
        (self.zims / "book.zim").write_bytes(b"a")
        (drive.root / "wiki" / "book_2024-01.zim").write_bytes(b"b")
        self.box.rebuild()
        self.wiki.delete("book.zim", at="u-1", file="book_2024-01.zim")
        self.assertTrue((self.zims / "book.zim").exists())
        self.assertFalse((drive.root / "wiki" / "book_2024-01.zim").exists())
        with self.assertRaises(Refused) as cm:
            self.wiki.delete("book.zim", at="u-1")
        self.assertEqual(cm.exception.status, 404)

    def test_items_show_location_and_status(self):
        drive = self.box.add_drive("u-1")
        (self.zims / "book.zim").write_bytes(b"a")
        (drive.root / "wiki" / "book.zim").write_bytes(b"b")
        self.box.rebuild()
        self.assertEqual(
            [(i["location"], i["status"]) for i in self.wiki.items()],
            [("device", "in_use"), ("u-1", "duplicate")],
        )
        self.assertEqual(self.wiki.used("u-1"), 1)

    def test_wiki_builtin_replaced_flag(self):
        self.assertEqual(self.wiki.exists("devdocs_en_git.zim"), "builtin")
        self.wiki.install(self.upload(), "devdocs_en_git.zim", self.dev)
        flags = {b["name"]: b for b in self.wiki.builtin_items()}
        self.assertTrue(flags["devdocs_en_git.zim"]["replaced"])
        self.assertTrue(flags["survival-kit.zim"]["protected"])
        self.wiki.delete("devdocs_en_git.zim")
        flags = {b["name"]: b for b in self.wiki.builtin_items()}
        self.assertFalse(flags["devdocs_en_git.zim"]["replaced"])

    def test_wiki_delete_builtin_refused(self):
        with self.assertRaises(Refused) as cm:
            self.wiki.delete("survival-kit.zim")
        self.assertEqual(cm.exception.status, 403)
        for bad in ["../x.zim", ".incoming", "nope.zim"]:
            with self.subTest(bad=bad), self.assertRaises(Refused):
                self.wiki.delete(bad)

    def test_wiki_refresh_called(self):
        self.wiki.install(self.upload(), "a.zim", self.dev)
        self.wiki.delete("a.zim")
        self.assertEqual(self.refreshed, 2)

    def test_wiki_items_skip_hidden_and_other(self):
        (self.zims / "notes.txt").write_text("x")
        self.wiki.install(self.upload(), "a.zim", self.dev)
        self.assertEqual([i["name"] for i in self.wiki.items()], ["a.zim"])


class MapNames(unittest.TestCase):
    def test_map_name(self):
        self.assertEqual(content.map_name("Austria Z12.PMTiles"), "austria-z12.pmtiles")
        self.assertEqual(content.map_name("../x.pmtiles"), "x.pmtiles")
        self.assertEqual(content.map_name("..hidden.pmtiles"), "hidden.pmtiles")
        for bad in ["x.mbtiles", ".pmtiles", "!!!.pmtiles"]:
            with self.subTest(bad=bad), self.assertRaises(Refused):
                content.map_name(bad)
        with self.assertRaises(Refused):
            content.map_name("a" * 300 + ".pmtiles")

    def test_map_name_accented_letters_kept(self):
        # "Österreich" used to become "-sterreich"
        self.assertEqual(content.map_name("Österreich.pmtiles"), "osterreich.pmtiles")
        self.assertEqual(content.map_name("Île-de-France.pmtiles"), "ile-de-france.pmtiles")
        self.assertEqual(content.map_name("Česko z12.pmtiles"), "cesko-z12.pmtiles")
        # letters NFKD doesn't split get a plain spelling
        self.assertEqual(content.map_name("Łódź.pmtiles"), "lodz.pmtiles")
        self.assertEqual(content.map_name("Straße.pmtiles"), "strasse.pmtiles")
        self.assertEqual(content.map_name("Øresund Æbeltoft.pmtiles"), "oresund-aebeltoft.pmtiles")
        self.assertEqual(content.map_name("Москва z10.pmtiles"), "z10.pmtiles")  # no leading dash
        with self.assertRaises(Refused) as no_latin:  # no Latin letters at all: a clear refusal
            content.map_name("Ελλάδα.pmtiles")
        self.assertIn("Latin letters or digits", str(no_latin.exception))


class MapsTest(unittest.TestCase):
    def setUp(self):
        self.box = Box()
        self.dev = self.box.device()
        self.dir = self.dev.root / "maps"
        self.incoming = self.dev.root / ".incoming"
        self.note = None
        self.usable = True

        def validate(path):
            if not self.usable:
                raise Refused("not a PMTiles map")
            return self.note

        self.maps = content.Shelf(
            self.box.places,
            "maps",
            builtins={"czechia.pmtiles": 100, "world.pmtiles": 10},
            protected=set(),
            validate=validate,
            refresh=self.box.rebuild,
            noun="map",
        )

    def upload(self, data=b"map"):
        return content.receive(io.BytesIO(data), len(data), self.incoming)

    def test_maps_shelf_replace_builtin_and_restore(self):
        self.assertEqual(self.maps.exists("czechia.pmtiles"), "builtin")
        self.maps.install(self.upload(), "czechia.pmtiles", self.dev)
        flags = {b["name"]: b for b in self.maps.builtin_items()}
        self.assertTrue(flags["czechia.pmtiles"]["replaced"])
        self.assertFalse(flags["world.pmtiles"]["protected"])
        self.maps.delete("czechia.pmtiles")
        self.assertEqual(self.maps.exists("czechia.pmtiles"), "builtin")
        with self.assertRaises(Refused) as cm:
            self.maps.delete("world.pmtiles")
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("built-in maps", str(cm.exception))

    def test_maps_refused_file_removed(self):
        self.usable = False
        with self.assertRaises(Refused):
            self.maps.install(self.upload(), "bad.pmtiles", self.dev)
        self.assertEqual(list(self.incoming.iterdir()), [])
        self.assertFalse((self.dir / "bad.pmtiles").exists())

    def test_maps_install_returns_note(self):
        self.note = "doubtful"
        self.assertEqual(self.maps.install(self.upload(), "a.pmtiles", self.dev), "doubtful")
        self.assertEqual([i["name"] for i in self.maps.items()], ["a.pmtiles"])

    def test_maps_names_checked(self):
        for bad in ["../x.pmtiles", "x.zim", ".incoming"]:
            with self.subTest(bad=bad), self.assertRaises(Refused):
                self.maps.delete(bad)
        with self.assertRaises(Refused) as cm:
            self.maps.delete("nope.pmtiles")
        self.assertIn("no such map", str(cm.exception))


class FakeOllama:
    def __init__(self):
        self.models = {}

    def tags(self):
        return [{"name": f"{n}:latest", "size": s} for n, s in sorted(self.models.items())]

    def create(self, name, path):
        self.models[name] = Path(path).stat().st_size

    def remove(self, name):
        del self.models[name]


class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.ollama = FakeOllama()
        self.models = content.Models(self.ollama)

    def test_models_install_deletes_upload(self):
        tmp = content.receive(io.BytesIO(b"gguf"), 4, self.dir)
        self.models.install(tmp, "m1")
        self.assertFalse(tmp.exists())
        self.assertEqual(self.models.exists("m1"), "import")
        self.assertEqual(self.models.used(), 4)

    def test_models_install_failure_still_deletes_upload(self):
        def boom(name, path):
            raise RuntimeError("ollama create failed")

        self.ollama.create = boom
        tmp = content.receive(io.BytesIO(b"gguf"), 4, self.dir)
        with self.assertRaises(Refused):
            self.models.install(tmp, "m1")
        self.assertFalse(tmp.exists())

    def test_models_delete(self):
        self.ollama.models["m1"] = 1
        self.models.delete("m1")
        self.assertIsNone(self.models.exists("m1"))
        with self.assertRaises(Refused):
            self.models.delete("m1")


if __name__ == "__main__":
    unittest.main()
