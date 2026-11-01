"""Tests for setup.py — Jellyfin's one-time setup, against a fake Jellyfin (no VM)."""

import io
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import setup

OPTIONS = {  # what Jellyfin 10.11 offers per library type (captured from a real server)
    "movies": [("Movie", ["TheMovieDb", "The Open Movie Database"],
                ["TheMovieDb", "The Open Movie Database", "Embedded Image Extractor", "Screen Grabber"])],
    "tvshows": [("Series", ["TheMovieDb"], ["TheMovieDb"]), ("Season", ["TheMovieDb"], ["TheMovieDb"]),
                ("Episode", ["TheMovieDb"], ["TheMovieDb", "Embedded Image Extractor", "Screen Grabber"])],
    "music": [("MusicAlbum", ["MusicBrainz"], ["TheAudioDB"]), ("Audio", [], ["Image Extractor"])],
}


class FakeJellyfin:
    def __init__(self, wizard_done=False, fail=None, user=("jellyfin", ""), libraries=()):
        self.calls = []  # (method, path, query, body, auth)
        self.wizard_done = wizard_done
        self.fail = fail  # a path that answers 500
        self.user = user  # (name, password) Jellyfin signs in
        self.libraries = list(libraries)
        self.policy = {"IsAdministrator": True, "EnableVideoPlaybackTranscoding": True,
                       "EnableAudioPlaybackTranscoding": True, "EnablePlaybackRemuxing": True,
                       "AuthenticationProviderId": "a", "PasswordResetProviderId": "p"}
        self.config = {"PluginRepositories": [{"Name": "Jellyfin Stable", "Url": "https://repo.jellyfin.org/x"}],
                       "QuickConnectAvailable": True, "ServerName": ""}
        self.network = {"AutoDiscovery": True, "EnableUPnP": True, "InternalHttpPort": 8096}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def answer(self, code, body=None):
                data = b"" if body is None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def handle_any(self, method):
                url = urllib.parse.urlsplit(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                body = json.loads(raw) if raw else None
                q = dict(urllib.parse.parse_qsl(url.query))
                fake.calls.append((method, url.path, q, body, self.headers.get("Authorization", "")))
                p = url.path
                if p == fake.fail:
                    return self.answer(500, {"error": "boom"})
                if p == "/System/Info/Public":
                    return self.answer(200, {"version": "10.11.11", "startupWizardCompleted": fake.wizard_done})
                if p == "/Startup/User" and method == "POST":
                    fake.user = (body["Name"], body["Password"])
                if p == "/Users/AuthenticateByName":
                    if (body["Username"], body["Pw"]) != fake.user:
                        return self.answer(401)
                    return self.answer(200, {"AccessToken": "tok", "User": {"Id": "u1", "Name": body["Username"]}})
                if p == "/Library/VirtualFolders" and method == "GET":
                    return self.answer(200, [{"Name": n} for n in fake.libraries])
                if p == "/Library/VirtualFolders" and method == "POST":
                    fake.libraries.append(q["name"])
                if p == "/Users/u1" and method == "GET":
                    return self.answer(200, {"Id": "u1", "Policy": fake.policy})
                if p == "/Libraries/AvailableOptions":
                    t = OPTIONS[q["libraryContentType"]]
                    return self.answer(200, {"TypeOptions": [
                        {"Type": ty, "MetadataFetchers": [{"Name": m} for m in meta],
                         "ImageFetchers": [{"Name": i} for i in img]} for ty, meta, img in t]})
                if p == "/System/Configuration" and method == "GET":
                    return self.answer(200, fake.config)
                if p == "/System/Configuration/network" and method == "GET":
                    return self.answer(200, fake.network)
                if p == "/Auth/Keys" and method == "GET":
                    return self.answer(200, {"Items": [{"AppName": "other", "AccessToken": "nope"},
                                                       {"AppName": "survival-kit", "AccessToken": "k-123"}]})
                return self.answer(204)

            def do_GET(self):
                self.handle_any("GET")

            def do_POST(self):
                self.handle_any("POST")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def body(self, method, path):
        return next(c[3] for c in self.calls if c[0] == method and c[1] == path)


LIB = "/var/lib/survival-kit/library/media"


class Setup(unittest.TestCase):
    def setUp(self):
        self.key = Path(tempfile.mkdtemp()) / "media" / "api-key"
        self.err = io.StringIO()

    def run_setup(self, fake, name="Anna", password="secret pw", deadline=None):
        self.addCleanup(fake.close)
        return setup.run(setup.Api(fake.url, deadline=deadline), name, password, str(self.key), LIB, log=self.err)

    def test_clean_user_name(self):
        self.assertEqual(setup.clean_user_name("Anna"), "Anna")
        self.assertEqual(setup.clean_user_name("Anna Nováková"), "Anna Nováková")
        self.assertEqual(setup.clean_user_name("Zoë O'Brien!"), "Zoë O'Brien")
        self.assertEqual(setup.clean_user_name("  a:b  "), "ab")
        self.assertEqual(setup.clean_user_name("!!!"), "owner")

    def test_run_sequence(self):
        fake = FakeJellyfin()
        self.assertEqual(self.run_setup(fake, name="Zoë O'Brien!"), "Zoë O'Brien")
        order = [(m, p) for m, p, *_ in fake.calls]
        wizard = [("POST", "/Startup/Configuration"), ("POST", "/Startup/User"), ("POST", "/Startup/RemoteAccess"),
                  ("POST", "/Startup/Complete"), ("POST", "/Users/AuthenticateByName")]
        positions = [order.index(c) for c in wizard]
        self.assertEqual(positions, sorted(positions), order)
        self.assertEqual(fake.body("POST", "/Startup/User"), {"Name": "Zoë O'Brien", "Password": "secret pw"})
        self.assertEqual(fake.body("POST", "/Users/AuthenticateByName"), {"Username": "Zoë O'Brien", "Pw": "secret pw"})
        remote = fake.body("POST", "/Startup/RemoteAccess")
        self.assertEqual((remote["EnableRemoteAccess"], remote["EnableAutomaticPortMapping"]), (False, False))
        # the three libraries, nothing from the internet, no heavy image extraction
        libs = [(c[2], c[3]) for c in fake.calls if c[0] == "POST" and c[1] == "/Library/VirtualFolders"]
        self.assertEqual([(q["name"], q["collectionType"], q["paths"]) for q, _ in libs],
                         [("Movies", "movies", f"{LIB}/movies"), ("Shows", "tvshows", f"{LIB}/shows"),
                          ("Music", "music", f"{LIB}/music")])
        for q, body in libs:
            opts = body["LibraryOptions"]
            self.assertFalse(opts["EnableRealtimeMonitor"])
            self.assertFalse(opts["EnableTrickplayImageExtraction"] or opts["ExtractTrickplayImagesDuringLibraryScan"])
            self.assertFalse(opts["EnableChapterImageExtraction"] or opts["ExtractChapterImagesDuringLibraryScan"])
            self.assertEqual(opts["MetadataSavers"], [])
            self.assertEqual(q["refreshLibrary"], "false")
            for t in opts["TypeOptions"]:
                self.assertEqual(t["MetadataFetchers"], [], t)
                self.assertTrue(set(t["ImageFetchers"]) <= setup.LOCAL_IMAGES, t)
        movie = libs[0][1]["LibraryOptions"]["TypeOptions"][0]
        self.assertEqual(movie["ImageFetchers"], ["Embedded Image Extractor", "Screen Grabber"])
        # the owner's playback: no video transcoding, sound and remux allowed; the rest kept
        policy = fake.body("POST", "/Users/u1/Policy")
        self.assertEqual((policy["EnableVideoPlaybackTranscoding"], policy["EnableAudioPlaybackTranscoding"],
                          policy["EnablePlaybackRemuxing"], policy["AuthenticationProviderId"]), (False, True, True, "a"))
        self.assertEqual(fake.body("POST", "/System/Configuration")["PluginRepositories"], [])
        net = fake.body("POST", "/System/Configuration/network")
        self.assertEqual((net["AutoDiscovery"], net["EnableUPnP"], net["InternalHttpPort"]), (False, False, 8096))
        # the box's key, root-only
        self.assertIn(("POST", "/Auth/Keys"), order)
        self.assertEqual(self.key.read_text().strip(), "k-123")
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(order[-1], ("POST", "/Library/Refresh"))
        # authenticated calls carry the session token; the password is in no URL
        self.assertIn('Token="tok"', next(c[4] for c in fake.calls if c[1] == "/Users/u1/Policy"))
        for _, path, q, *_ in fake.calls:
            self.assertNotIn("secret", path + json.dumps(q))

    def test_run_done_with_key_changes_nothing(self):
        fake = FakeJellyfin(wizard_done=True, user=("Anna", "secret pw"))
        self.key.parent.mkdir(parents=True)
        self.key.write_text("old\n")
        with self.assertRaises(setup.AlreadyDone):
            self.run_setup(fake)
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [])
        self.assertEqual(self.key.read_text(), "old\n")

    def test_run_resumes_after_the_wizard(self):
        """Setup stopped after the wizard (slow box): a re-run with the same name and password
        finishes it — no wizard calls, only the missing libraries, then the key."""
        fake = FakeJellyfin(wizard_done=True, user=("Anna", "secret pw"), libraries=["Movies"])
        self.assertEqual(self.run_setup(fake), "Anna")
        paths = [(m, p) for m, p, *_ in fake.calls]
        self.assertFalse(any(p.startswith("/Startup") and m == "POST" for m, p in paths), paths)
        made = [c[2]["name"] for c in fake.calls if c[0] == "POST" and c[1] == "/Library/VirtualFolders"]
        self.assertEqual(made, ["Shows", "Music"])
        self.assertEqual(self.key.read_text().strip(), "k-123")

    def test_resume_with_another_password_fails(self):
        fake = FakeJellyfin(wizard_done=True, user=("Anna", "other"))
        with self.assertRaises(setup.SetupError) as e:
            self.run_setup(fake)
        self.assertIn("name or password", str(e.exception))
        self.assertFalse(self.key.exists())

    def test_overall_deadline(self):
        import time  # noqa: PLC0415

        with self.assertRaises(setup.SetupError) as e:
            self.run_setup(FakeJellyfin(), deadline=time.monotonic() - 1)
        self.assertIn("too long", str(e.exception))

    def test_run_failure(self):
        fake = FakeJellyfin(fail="/Library/VirtualFolders")
        with self.assertRaises(setup.SetupError) as e:
            self.run_setup(fake)
        self.assertNotIn("\n", str(e.exception))
        self.assertFalse(self.key.exists())

    def library(self):
        lib = Path(tempfile.mkdtemp())
        for top in ["movies", "shows", "music"]:
            (lib / top).mkdir()
        return str(lib)

    def test_main_exit_codes(self):
        cases = [(FakeJellyfin(), "Anna", 0), (FakeJellyfin(), "Zoë!", 3), (FakeJellyfin(fail="/Startup/User"), "Anna", 1)]
        for fake, name, code in cases:
            with self.subTest(code=code):
                self.addCleanup(fake.close)
                env = {"MEDIA_URL": fake.url, "MEDIA_KEY_FILE": str(self.key), "MEDIA_LIBRARY": self.library(),
                       "MEDIA_WAIT": "5"}
                out = io.StringIO()
                got = setup.main(io.StringIO(f"{name}\nsecret pw\n"), out, env)
                self.assertEqual(got, code, out.getvalue())
                if code == 1:
                    self.assertEqual(len(out.getvalue().strip().splitlines()), 1, out.getvalue())
                self.key.unlink(missing_ok=True)
        fake = FakeJellyfin(wizard_done=True, user=("Anna", "secret pw"))
        self.addCleanup(fake.close)
        self.key.parent.mkdir(parents=True, exist_ok=True)
        self.key.write_text("k\n")
        env = {"MEDIA_URL": fake.url, "MEDIA_KEY_FILE": str(self.key), "MEDIA_LIBRARY": self.library(), "MEDIA_WAIT": "5"}
        self.assertEqual(setup.main(io.StringIO("Anna\nsecret pw\n"), io.StringIO(), env), 2)

    def test_main_waits_for_the_library_folders(self):
        fake = FakeJellyfin()
        self.addCleanup(fake.close)
        env = {"MEDIA_URL": fake.url, "MEDIA_KEY_FILE": str(self.key), "MEDIA_LIBRARY": "/nonexistent/media",
               "MEDIA_WAIT": "1"}
        out = io.StringIO()
        self.assertEqual(setup.main(io.StringIO("Anna\npw\n"), out, env), 1)
        self.assertIn("library", out.getvalue())
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [])

    def test_main_gives_up_waiting(self):
        env = {"MEDIA_URL": "http://127.0.0.1:9", "MEDIA_KEY_FILE": str(self.key), "MEDIA_LIBRARY": self.library(),
               "MEDIA_WAIT": "1"}
        out = io.StringIO()
        self.assertEqual(setup.main(io.StringIO("Anna\npw\n"), out, env), 1)
        self.assertIn("not answering", out.getvalue())

    def test_main_needs_two_lines(self):
        out = io.StringIO()
        self.assertEqual(setup.main(io.StringIO("Anna\n"), out, {"MEDIA_WAIT": "1"}), 1)
        self.assertEqual(setup.main(io.StringIO("Anna\n\n"), out, {"MEDIA_WAIT": "1"}), 1)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
