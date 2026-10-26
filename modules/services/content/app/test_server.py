"""Tests for server.py — the HTTP API on a real local server, with stand-ins for Kiwix/Ollama."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import content
import server
from test_content import PROTECTED, FakeOllama

GB = 1000**3


class Api(unittest.TestCase):
    models_enabled = True

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.zims = root / "zims"
        (self.zims / ".incoming").mkdir(parents=True)
        (root / "state" / "incoming").mkdir(parents=True)
        static = root / "static"
        static.mkdir()
        (static / "index.html").write_text("<html><!--CONTENT--></html>")
        (static / "content.js").write_text("// js")
        (static / "style.css").write_text("/* css */")
        self.wiki = content.Wiki(
            self.zims,
            builtins={"devdocs_en_git.zim": 100, "survival-kit.zim": 50},
            protected=PROTECTED,
            validate=lambda p: True,
            refresh=lambda: None,
        )
        self.ollama = FakeOllama()
        models = content.Models(self.ollama) if self.models_enabled else None
        config = server.Config(
            port=0,
            static_dir=static,
            wiki_incoming=self.zims / ".incoming",
            model_incoming=root / "state" / "incoming",
            locations={"wiki": str(self.zims), "models": "/var/lib/ollama/models"},
        )
        self.httpd = server.make_server(config, self.wiki, models, lambda: (100 * GB, 50 * GB))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

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
        self.assertEqual(set(s), {"disk", "wiki", "builtins", "models", "models_error", "locations"})
        self.assertIsNone(s["models_error"])
        self.assertEqual(s["models"], [])

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
        self.assertEqual(list((self.zims / ".incoming").iterdir()), [])

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
        self.assertEqual(list((self.zims / ".incoming").iterdir()), [])


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


if __name__ == "__main__":
    unittest.main()
