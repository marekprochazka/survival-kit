"""Unit tests for content.py — names, space, uploads, wiki and models (no HTTP, no VM)."""

import io
import os
import tempfile
import unittest
from pathlib import Path

import content
from content import Refused

GB = 1000**3
GIB = 1024**3
PROTECTED = {"survival-kit", "survival-kit-dev"}


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
        self.zims = Path(tempfile.mkdtemp())
        self.incoming = self.zims / ".incoming"
        self.incoming.mkdir()
        self.refreshed = 0
        self.readable = True

        def refresh():
            self.refreshed += 1

        self.wiki = content.Wiki(
            self.zims,
            builtins={"devdocs_en_git.zim": 100, "survival-kit.zim": 50},
            protected=PROTECTED,
            validate=lambda p: self.readable,
            refresh=refresh,
        )

    def upload(self, data=b"zim"):
        return content.receive(io.BytesIO(data), len(data), self.incoming)

    def test_wiki_install_and_replace(self):
        self.wiki.install(self.upload(b"one"), "book.zim")
        self.assertEqual(self.wiki.exists("book.zim"), "import")
        self.wiki.install(self.upload(b"two!"), "book.zim")
        self.assertEqual((self.zims / "book.zim").read_bytes(), b"two!")
        self.assertEqual([i["name"] for i in self.wiki.items()], ["book.zim"])
        self.assertEqual(self.wiki.used(), 4)

    def test_wiki_unreadable_refused_and_removed(self):
        self.readable = False
        with self.assertRaises(Refused) as cm:
            self.wiki.install(self.upload(), "bad.zim")
        self.assertIn("not a readable wiki book", str(cm.exception))
        self.assertEqual(list(self.incoming.iterdir()), [])
        self.assertFalse((self.zims / "bad.zim").exists())

    def test_wiki_builtin_replaced_flag(self):
        self.assertEqual(self.wiki.exists("devdocs_en_git.zim"), "builtin")
        self.wiki.install(self.upload(), "devdocs_en_git.zim")
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
        self.wiki.install(self.upload(), "a.zim")
        self.wiki.delete("a.zim")
        self.assertEqual(self.refreshed, 2)

    def test_wiki_items_skip_hidden_and_other(self):
        (self.zims / "notes.txt").write_text("x")
        self.wiki.install(self.upload(), "a.zim")
        self.assertEqual([i["name"] for i in self.wiki.items()], ["a.zim"])


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
