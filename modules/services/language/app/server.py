"""survival-kit Language — translator, dictionary, thesaurus (the web side).

On 127.0.0.1 behind nginx (https://language.<domain>). What is installed comes from the
library index (/var/lib/survival-kit/library/{translate,dict}, imports on any location) and
the built-ins (the en↔cs models, WordNet, Moby); an import of a built-in's name replaces it.
The catalog follows the library by itself: a new index (library.py swaps a symlink) or a
file gone (a drive pulled out) is noticed on the next request — no restart.

API (writes take JSON bodies only — a form on another site can't send those)
  GET  /health                                  "ok"
  GET  /api/languages                           {languages: [{code, name}], targets: {code: [code]},
                                                 direct: {code: [code]} (the rest go through English),
                                                 dictionaries: [{id, title}], thesaurus: bool}
  POST /api/translate {text, from, to}          {text}; one translation at a time
  GET  /api/define?dict=&word=                  {entries: [text], near: [word]}
  GET  /api/synonyms?word=                      {words: [word], near: [word]}
  GET  /, /language.js, /style.css              the page
"""

import json
import os
import shutil
import sys
import threading
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import archives
import dictd
import langfiles
import thesaurus
import translate
from content import Refused

STATIC = {"/": "index.html", "/language.js": "language.js", "/style.css": "style.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css"}
MAX_BODY = 64 * 1024
KINDS = {"translate": langfiles.MODEL_EXT, "dict": langfiles.DICT_EXT}
BUILTIN_DICT = "wordnet"  # listed first


def log(message):
    print(f"language: {message}", file=sys.stderr, flush=True)


class Catalog:
    """What can be used right now: (Translator, {id: Dictionary}, Thesaurus or None).

    load(folder) → a CTranslate2 translator (tests: a stand-in). Unpacked files live in
    `cache`; models already loaded are kept across rebuilds.
    """

    def __init__(self, library, builtins, cache, load=None):
        self.library = Path(library)
        self.builtins = Path(builtins)
        self.cache = Path(cache)
        self.load = load
        self.lock = threading.Lock()
        self.translating = threading.Lock()  # one translation at a time, across rebuilds
        self.loaded = translate.Loaded()  # at most 2 models in memory
        self.stamp = None
        self.state = None
        self.models = {}  # unpacked folder → Model (keeps loaded models)
        self.dicts = {}  # unpacked folder → Dictionary
        moby = self.builtins / "moby.txt"
        self.thesaurus = thesaurus.Thesaurus(moby) if moby.exists() else None

    def sources(self):
        """{kind: {name: path}} — the built-ins, replaced by library entries of the same name."""
        out = {}
        for kind, ext in KINDS.items():
            found = {}
            for base in (self.builtins / kind, self.library / kind):
                if base.is_dir():
                    found.update({p.name: p for p in sorted(base.glob("*" + ext))})
            out[kind] = found
        return out

    def _stamp(self):
        try:
            index = os.readlink(self.library)
        except OSError:
            index = None
        files = []
        for kind in KINDS:
            folder = self.library / kind
            if folder.is_dir():
                files += [(p.name, p.exists()) for p in sorted(folder.iterdir())]
        return index, tuple(files)

    def current(self):
        with self.lock:
            stamp = self._stamp()
            if stamp != self.stamp or self.state is None:
                self.state = self._build()
                self.stamp = stamp
            return self.state

    def _open(self, path, cached, make):
        """(folder, make(folder)) for one file, or None when it can't be used right now — a
        broken file, a drive just pulled out, a damaged cache folder (removed, so it is
        unpacked again) or anything else: one file never takes the service down."""
        folder = None
        try:
            folder = archives.unpack(path, self.cache)
            return folder, cached.get(folder) or make(folder)
        except Exception as e:  # noqa: BLE001
            log(f"{path.name} left out: {e!r}")
            if folder is not None and not isinstance(e, archives.Unusable):
                shutil.rmtree(folder, ignore_errors=True)
            return None

    def _build(self):
        src = self.sources()
        models, dicts, ids = {}, {}, {}
        for path in src["translate"].values():
            got = self._open(path, self.models, lambda f: translate.Model(f, translate.read_info(f), load=self.load))
            if got:
                models[got[0]] = got[1]
        for name, path in src["dict"].items():
            got = self._open(path, self.dicts, dictd.Dictionary)
            if got:
                dicts[got[0]] = got[1]
                ids[name[: -len(langfiles.DICT_EXT)]] = got[1]
        self.models, self.dicts = models, dicts
        archives.prune(self.cache, set(models) | set(dicts))
        order = sorted(ids, key=lambda i: (i != BUILTIN_DICT, ids[i].title.lower()))
        by_pair = {m.pair: m for m in models.values()}
        translator = translate.Translator(by_pair, lock=self.translating, loaded=self.loaded)
        return translator, {i: ids[i] for i in order}, self.thesaurus


@dataclass
class Config:
    port: int
    static_dir: Path


def make_server(config, catalog):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass  # no access log: what people look up stays theirs

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/health":
                return self.send(200, b"ok", "text/plain")
            if url.path in STATIC:
                file = config.static_dir / STATIC[url.path]
                return self.send(200, file.read_bytes(), TYPES[file.suffix])
            translator, dicts, thes = catalog.current()
            word = q.get("word", "")
            if url.path == "/api/languages":
                langs = translator.languages()
                return self.send(200, {
                    "languages": langs,
                    "targets": {lang["code"]: translator.targets(lang["code"]) for lang in langs},
                    "direct": {lang["code"]: sorted(t for f, t in translator.models if f == lang["code"]) for lang in langs},
                    "dictionaries": [{"id": i, "title": d.title} for i, d in dicts.items()],
                    "thesaurus": thes is not None,
                })
            if url.path == "/api/define":
                d = dicts.get(q.get("dict", ""))
                if d is None:
                    return self.send(404, {"error": "no such dictionary"})
                entries = d.lookup(word)
                return self.send(200, {"entries": entries, "near": [] if entries else d.near(word)})
            if url.path == "/api/synonyms":
                if thes is None:
                    return self.send(404, {"error": "no thesaurus"})
                words = thes.synonyms(word)
                return self.send(200, {"words": words or [], "near": [] if words else thes.near(word)})
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/translate":
                return self.send(404, {"error": "not found"})
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self.send(415, {"error": "send JSON"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self.close_connection = True  # the unread body follows
                return self.send(413, {"error": "too long"})
            try:
                d = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                d = None
            if not isinstance(d, dict) or not all(isinstance(d.get(k), str) for k in ("text", "from", "to")):
                return self.send(400, {"error": "expected {text, from, to}"})
            translator = catalog.current()[0]
            try:
                return self.send(200, {"text": translator.translate(d["text"], d["from"], d["to"])})
            except Refused as e:
                return self.send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 — a model that fails: say so, keep serving
                log(f"translation failed: {e!r}")
                return self.send(500, {"error": "the translation failed"})

    return ThreadingHTTPServer(("127.0.0.1", config.port), Handler)


def main():
    env = os.environ
    catalog = Catalog(env["LIBRARY_DIR"], env["BUILTINS_DIR"], env["CACHE_DIR"])
    catalog.current()  # unpack the built-ins now, not on the first visit
    httpd = make_server(Config(port=int(env["LANGUAGE_PORT"]), static_dir=Path(env["STATIC_DIR"])), catalog)
    print(f"language on 127.0.0.1:{httpd.server_address[1]}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
