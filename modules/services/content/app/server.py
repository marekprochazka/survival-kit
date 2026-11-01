"""survival-kit content manager — the web side (ADR-0004, ADR-0006).

A small JSON API plus one page, on 127.0.0.1 behind nginx (https://content.<domain>).
Uploads are one file per request with the raw file as the body (Python 3.13 has no cgi
module, and this streams straight to disk). Standard library only.

Content lives on locations: "device" (this device) and added drives (by filesystem UUID).

API
  GET    /health                                  "ok"
  GET    /api/status                              disk, locations, drives, wiki, builtins,
                                                  maps, map_builtins, models (null on lite),
                                                  translate, translate_builtins, dict, dict_builtins
  GET    /api/check?kind=&file=&size=[&to=][&model=]  stored name + whether it exists;
                                                  space check on location `to` (default device)
  PUT    /api/upload?kind=&file=[&to=][&model=]   body = the file (Content-Length required);
                                                  kind = wiki | map | translate | dict | model
                                                  (models: device)
  DELETE /api/<wiki|maps|translate|dict>/<name>[?at=&file=], /api/models/<name>
                                                  one copy: on location `at`, else the one in use
  POST   /api/resolve?at=                         move that location's invalid and duplicate
                                                  files out of the tree (set aside, not deleted)
  POST   /api/drives/add?uuid=[&name=], /api/drives/<uuid>/forget, /api/drives/<uuid>/reconnect
  GET    /, /content.js, /style.css               the page
"""

import html
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import content
import drives as drv
import langfiles
import library
import pmtiles
from content import Refused

STATIC = {"/": "index.html", "/content.js": "content.js", "/style.css": "style.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css"}
NO_MODELS = "no AI models on this box (lite profile)"
NO_MAPS = "no maps on this box"
NO_LANGUAGE = "no Language service on this box"
# upload kind → (folder kind, the name a file is stored under, message when there is no such shelf)
UPLOADS = {
    "map": ("maps", content.map_name, NO_MAPS),
    "translate": ("translate", langfiles.translate_name, NO_LANGUAGE),
    "dict": ("dict", langfiles.dict_name, NO_LANGUAGE),
}
MODELS_DOWN = "not available right now"
MAX_DRIVE_NAME = 60


@dataclass
class Config:
    port: int
    static_dir: Path
    model_incoming: Path


@dataclass
class Drives:
    """Added drives, as the server sees them (tests use stand-ins).

    registry: drives.Registry; candidates() → drives.candidates(…); state() → {uuid:
    {mounted, error}} from the last mount run; apply() → re-run the mounting, then the library.
    """

    registry: object
    candidates: Callable
    state: Callable
    apply: Callable


def _size(n):
    return f"{n / 1000**3:.1f} GB" if n >= 10**9 else f"{n / 1000**2:.0f} MB"


NOT_IN_USE = {"duplicate": "duplicate — not in use", "invalid": "invalid"}


def _status(item):
    if item["status"] == "invalid":
        return f'invalid — {item["reason"]}'
    return NOT_IN_USE.get(item["status"], "")


def _drives(s, e):
    """The Drives section: where content lives, added drives, drives that could be added."""
    locs = {loc["id"]: loc for loc in s["locations"]}
    items = s["wiki"] + (s["maps"] or []) + (s["translate"] or []) + (s["dict"] or [])
    trouble = {}
    for i in items:
        if i["status"] != "in_use":
            trouble[i["location"]] = trouble.get(i["location"], 0) + 1

    def resolve(id):
        n = trouble.get(id)
        return f'<button data-resolve="{e(id)}" data-count="{n}">Auto-resolve ({n})</button>' if n else ""

    out = [
        '<section id="drives"><h2>Drives</h2>',
        *([f'<p class="error">{e(s["drives"]["error"])}</p>'] if s["drives"].get("error") else []),
        "<p>Books, maps and languages can live on this device and on drives that stay plugged in. "
        "Files the box can't use, and older copies of a book or map it has elsewhere, are marked "
        "&ldquo;not in use&rdquo;; <em>Auto-resolve</em> moves them out of the way (nothing is deleted).</p>",
        "<table><tr><th>Where</th><th>Space</th><th>State</th><th></th></tr>",
    ]
    dev = locs["device"]
    out.append(
        f'<tr><td>This device</td><td>{_size(dev["free"])} free of {_size(dev["total"])}</td>'
        f'<td>ready</td><td>{resolve("device")}</td></tr>'
    )
    for d in s["drives"]["added"]:
        loc = locs.get(d["uuid"])
        space = f'{_size(loc["free"])} free of {_size(loc["total"])}' if loc else ""
        state = "ready" if loc else e(d["error"] or "not connected")
        buttons = [] if loc else [f'<button data-drive="{e(d["uuid"])}" data-action="reconnect">Reconnect</button>']
        buttons.append(resolve(d["uuid"]))
        buttons.append(f'<button data-drive="{e(d["uuid"])}" data-action="forget" data-name="{e(d["name"])}">Forget</button>')
        out.append(f'<tr><td>{e(d["name"])}</td><td>{space}</td><td>{state}</td><td>{" ".join(b for b in buttons if b)}</td></tr>')
    out.append("</table>")
    if s["drives"]["available"]:
        out.append("<h3>Drives you can add</h3>")
        out.append("<table><tr><th>Drive</th><th>Size</th><th>Type</th><th></th></tr>")
        for c in s["drives"]["available"]:
            name = c["label"] or c["model"] or c["path"]
            note = " (open on the desktop — it will be taken over)" if c["desktop"] else ""
            action = (
                f'<span class="error">{e(c["refusal"])}</span>'
                if c["refusal"]
                else f'<button data-action="add" data-drive="{e(c["uuid"])}" data-name="{e(name)}">Add</button>'
            )
            out.append(
                f'<tr><td>{e(name)}{e(note)}</td><td>{_size(c["size"] or 0)}</td><td>{e(c["fstype"])}</td><td>{action}</td></tr>'
            )
        out.append("</table>")
    else:
        out.append('<p class="note">Plug in a drive to add it here.</p>')
    out.append(
        "<p>Adding never formats a drive: the box keeps its files in a <code>survival-kit</code> folder "
        "on it and leaves everything else alone. <em>Forget</em> stops using a drive; its files stay on it.</p>"
    )
    # where new imports go: the drive with the most free space first
    ready = sorted(s["locations"], key=lambda loc: -loc["free"])
    opts = [
        f'<option value="{e(loc["id"])}"{" selected" if n == 0 else ""}>{e(loc["name"])} ({_size(loc["free"])} free)</option>'
        for n, loc in enumerate(ready)
    ]
    out.append(f'<p><label>Save new books, maps and languages to <select id="save-to">{"".join(opts)}</select></label></p></section>')
    return out


def _items(s, kind, items, builtins, cut, e):
    names = {loc["id"]: loc["name"] for loc in s["locations"]}
    out = ["<table><tr><th>Name</th><th>Where</th><th>Size</th><th>Imported</th><th></th></tr>"]
    for i in items:
        day = time.strftime("%Y-%m-%d", time.localtime(i["mtime"]))
        state = _status(i)
        cls = ' class="unused"' if state else ""
        note = f'<br><small>{e(state)}</small>' if state else ""
        out.append(
            f'<tr{cls}><td>{e(i["name"][:-cut])}{note}</td><td>{e(names.get(i["location"], i["location"]))}</td>'
            f'<td>{_size(i["size"])}</td><td>{day}</td>'
            f'<td><button data-delete="{kind}" data-name="{e(i["name"])}" data-at="{e(i["location"])}" '
            f'data-file="{e(i["file"])}">Delete</button></td></tr>'
        )
    for b in builtins:
        note = "replaced by import" if b["replaced"] else "built in"
        out.append(
            f'<tr class="builtin"><td>{e(b["name"][:-cut])}</td><td>built in</td><td>{_size(b["size"])}</td>'
            f"<td>{note}</td><td></td></tr>"
        )
    out.append("</table>")
    return out


def render(template, s):
    """The page's lists as HTML, so viewing works without JavaScript."""
    e = html.escape
    out = _drives(s, e)
    out.append('<section id="wiki"><h2>Wiki books</h2>')
    out += _items(s, "wiki", s["wiki"], s["builtins"], 4, e)
    out.append(
        '<p><label>Import wiki files <input type="file" data-import="wiki" accept=".zim" multiple></label> '
        '<label>or a folder <input type="file" data-import="wiki" webkitdirectory></label></p></section>'
    )
    if s["maps"] is not None:
        out.append('<section id="maps"><h2>Maps</h2>')
        out += _items(s, "maps", s["maps"], s["map_builtins"], 8, e)
        out.append(
            '<p><label>Import map files <input type="file" data-import="map" accept=".pmtiles" multiple></label></p></section>'
        )
    if s["translate"] is not None:
        out.append('<section id="languages"><h2>Languages</h2>')
        out.append("<h3>Translation models</h3>")
        out += _items(s, "translate", s["translate"], s["translate_builtins"], len(langfiles.MODEL_EXT), e)
        out.append(
            '<p><label>Import translation models <input type="file" data-import="translate" accept=".argosmodel" multiple>'
            "</label></p>"
        )
        out.append("<h3>Dictionaries</h3>")
        out += _items(s, "dict", s["dict"], s["dict_builtins"], len(langfiles.DICT_EXT), e)
        out.append(
            '<p><label>Import dictionaries <input type="file" data-import="dict" accept=".xz" multiple></label></p></section>'
        )
    if s["models"] is not None:
        d = s["disk"]
        out.append('<section id="models"><h2>AI models</h2>')
        out.append(
            f'<p class="note">AI models are stored on this device ({_size(d["free"])} free) — '
            "put big books and maps on added drives.</p>"
        )
        if s["models_error"]:
            out.append(f'<p class="error">AI models: {e(s["models_error"])} (is Ollama still starting?)</p>')
        out.append("<table><tr><th>Model</th><th>Size</th><th></th></tr>")
        for m in s["models"]:
            out.append(
                f'<tr><td>{e(m["name"])}</td><td>{_size(m["size"])}</td>'
                f'<td><button data-delete="models" data-name="{e(m["name"])}">Delete</button></td></tr>'
            )
        out.append("</table>")
        out.append('<p><label>Import a model <input type="file" data-import="model" accept=".gguf"></label></p></section>')
    out.append('<section id="log" aria-live="polite"></section>')
    return template.replace("<!--CONTENT-->", "\n".join(out))


def make_server(config, wiki, models, places, maps=None, drives=None, translate=None, dicts=None):
    """places: library.Places. models / maps / drives / translate + dicts: None when the box
    has no AI models (lite) / no maps service / no drive support (tests) / no Language service."""

    shelves = {"wiki": wiki, "maps": maps, "translate": translate, "dict": dicts}  # by folder

    def languages_used(at):
        return sum(x.used(at) for x in (translate, dicts) if x)

    lock = threading.Lock()  # one drive action / auto-resolve at a time (drives.json, renames)

    def status():
        device = places.get("device")
        total, free = places.disk(device)
        # Ollama may be starting, crashed or out of memory: the wiki part must still work
        model_items, models_error = (None, None)
        if models:
            try:
                model_items = models.items()
            except Exception:  # noqa: BLE001
                model_items, models_error = [], MODELS_DOWN
        locs = []
        for loc in places.all():
            try:
                t, f = places.disk(loc)
            except OSError:  # a drive going away right now: left out, the page still works
                continue
            locs.append({"id": loc.id, "name": loc.name, "total": t, "free": f,
                         "wiki": wiki.used(loc.id), "maps": maps.used(loc.id) if maps else 0,
                         "languages": languages_used(loc.id)})
        return {
            "disk": {
                "total": total,
                "free": free,
                "wiki": wiki.used("device"),
                "maps": maps.used("device") if maps else 0,
                "languages": languages_used("device"),
                "models": sum(m["size"] for m in model_items or []),
            },
            "locations": locs,
            "drives": drive_status(),
            "wiki": wiki.items(),
            "builtins": wiki.builtin_items(),
            "maps": maps.items() if maps else None,
            "map_builtins": maps.builtin_items() if maps else [],
            "translate": translate.items() if translate else None,
            "translate_builtins": translate.builtin_items() if translate else [],
            "dict": dicts.items() if dicts else None,
            "dict_builtins": dicts.builtin_items() if dicts else [],
            "models": model_items,
            "models_error": models_error,
        }

    def drive_status():
        if drives is None:
            return {"added": [], "available": []}
        try:
            added = drives.registry.drives()
        except Refused as e:  # damaged list: say so, keep the rest of the page
            return {"added": [], "available": [], "error": str(e)}
        known = {d["uuid"] for d in added}
        return {
            "added": [d | drive_result(d["uuid"]) for d in added],
            "available": [c for c in drives.candidates() if c["uuid"] not in known],
        }

    def target(q):
        """(store, stored name, space factor, incoming dir, location or None) for a request."""
        kind, file = q.get("kind", ""), q.get("file", "")
        if kind == "wiki" or kind in UPLOADS:
            if kind == "wiki":
                store, name = wiki, content.wiki_name(file, wiki.protected)
            else:
                folder, clean, missing = UPLOADS[kind]
                store = shelves[folder]
                if store is None:
                    raise Refused(missing)
                name = clean(file)
            loc = places.get(q.get("to") or "device")
            return store, name, 1, loc.root / ".incoming", loc
        if kind == "model":
            if models is None:
                raise Refused(NO_MODELS)
            name = content.model_name(file)  # also checks the .gguf extension
            if q.get("model"):
                name = content.clean_model_name(q["model"])
            # models live on this device (Ollama's one store); the upload and Ollama's own
            # copy exist side by side for a moment
            return models, name, 2, config.model_incoming, None
        raise Refused("unknown kind")

    def space(factor, size, loc):
        total, free = places.disk(loc or places.get("device"))
        content.check_space(factor * size, free, total)

    def drive_named(uuid):
        if drives is None or not any(d["uuid"] == uuid for d in drives.registry.drives()):
            raise Refused("no such drive", status=404)

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def route(self, fn):
            try:
                fn()
            except Refused as e:
                self.close_connection = True  # an unread upload body may follow
                self.send(e.status, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 — report, keep serving
                self.log_error("failed: %r", e)
                self.close_connection = True
                self.send(500, {"error": f"something went wrong: {e}"})

        def parts(self):
            url = urllib.parse.urlsplit(self.path)
            return url.path, dict(urllib.parse.parse_qsl(url.query))

        def do_GET(self):
            path, q = self.parts()
            if path == "/health":
                return self.send(200, b"ok", "text/plain")
            if path == "/api/status":
                return self.route(lambda: self.send(200, status()))
            if path == "/api/check":

                def check():
                    store, name, factor, _, loc = target(q)
                    size = q.get("size", "0")
                    if not size.isdigit():
                        raise Refused("size must be a number of bytes")
                    space(factor, int(size), loc)
                    self.send(200, {"name": name, "exists": store.exists(name)})

                return self.route(check)
            if path in STATIC:

                def page():
                    file = config.static_dir / STATIC[path]
                    body = file.read_bytes()
                    if path == "/":
                        body = render(body.decode(), status()).encode()
                    self.send(200, body, TYPES[file.suffix])

                return self.route(page)
            self.send(404, {"error": "not found"})

        def do_PUT(self):
            path, q = self.parts()

            def upload():
                if path != "/api/upload":
                    raise Refused("not found", status=404)
                store, name, factor, incoming, loc = target(q)
                length = self.headers.get("Content-Length")
                if length is None or not length.isdigit():
                    raise Refused("the upload needs a Content-Length")
                space(factor, int(length), loc)
                existed = store.exists(name)
                tmp = content.receive(self.rfile, int(length), incoming)
                note = store.install(tmp, name, loc) if loc else store.install(tmp, name)
                self.send(200, {"name": name, "result": "replaced" if existed else "added", "note": note})

            self.route(upload)

        def do_DELETE(self):
            path, q = self.parts()

            def delete():
                kind, _, name = path.removeprefix("/api/").partition("/")
                name = urllib.parse.unquote(name)
                if kind in shelves:
                    if shelves[kind] is None:
                        raise Refused(NO_MAPS if kind == "maps" else NO_LANGUAGE)
                    shelves[kind].delete(name, q.get("at"), q.get("file"))
                elif kind == "models":
                    if models is None:
                        raise Refused(NO_MODELS)
                    models.delete(name)
                else:
                    raise Refused("not found", status=404)
                self.send(200, {"name": name, "result": "deleted"})

            self.route(delete)

        def do_POST(self):
            path, q = self.parts()

            def resolve():
                loc = places.get(q.get("at", ""))
                entries = [e for kind, shelf in shelves.items() if shelf for e in places.entries(kind)]
                moved = library.set_aside(loc, entries, time.strftime("%Y-%m-%d"), places.setaside_root(loc))
                wiki.refresh()
                self.send(200, {"moved": moved})

            def add():
                if drives is None:
                    raise Refused("no drive support here")
                uuid = q.get("uuid", "")
                if any(d["uuid"] == uuid for d in drives.registry.drives()):
                    raise Refused("a drive with this ID is already added")
                found = next((c for c in drives.candidates() if c["uuid"] == uuid), None)
                if found is None:
                    raise Refused("that drive is not plugged in (or is used by the system)", status=404)
                if found["refusal"]:
                    raise Refused(found["refusal"])
                name = " ".join(q.get("name", "").split())[:MAX_DRIVE_NAME]
                name = name or found["label"] or found["model"] or "Drive"
                drives.registry.add(uuid, found["fstype"], name, time.strftime("%Y-%m-%d"))
                drives.apply()
                self.send(200, {"uuid": uuid, "name": name, "result": "added"} | drive_result(uuid))

            def drive_action():
                uuid, _, action = path.removeprefix("/api/drives/").partition("/")
                drive_named(uuid)
                if action == "forget":
                    drives.registry.forget(uuid)
                    drives.apply()
                    return self.send(200, {"uuid": uuid, "result": "forgotten"})
                if action == "reconnect":
                    drives.apply()
                    return self.send(200, {"uuid": uuid, "result": "reconnected"} | drive_result(uuid))
                raise Refused("not found", status=404)

            def locked(fn):
                def run():
                    with lock:
                        fn()

                return run

            if path == "/api/resolve":
                return self.route(locked(resolve))
            if path == "/api/drives/add":
                return self.route(locked(add))
            if path.startswith("/api/drives/"):
                return self.route(locked(drive_action))
            self.send(404, {"error": "not found"})

    def drive_result(uuid):
        """Mounted = usable right now (checked live, not just the last mount run's word)."""
        if any(loc.id == uuid for loc in places.all()):
            return {"mounted": True, "error": None}
        s = drives.state().get(uuid, {})
        return {"mounted": False, "error": (not s.get("mounted") and s.get("error")) or "not connected"}

    httpd = ThreadingHTTPServer(("127.0.0.1", config.port), Handler)
    httpd.daemon_threads = True
    return httpd


# --- the real helpers (used by main; tests use stand-ins) ----------------------------


def wiki_check(path):
    """The wiki shelf's validate: Refused unless Kiwix can read the book."""
    if library.kiwix_book(path) is None:
        raise Refused("not a readable wiki book")


def model_check(path, name):
    """A translation model upload: an Argos package of the pair its name says."""
    langfiles.validate_model(path, name)


def dict_check(path):
    """A dictionary upload: a dictd archive."""
    langfiles.check_dict(path)


def library_refresh():
    """Rebuild the library (which copies are in use), then the wiki's catalog from it."""
    subprocess.run(["systemctl", "restart", "survival-kit-library.service"], check=True)
    subprocess.run(["systemctl", "restart", "kiwix-library.service"], check=True)


def kiwix_refresh():
    library_refresh()
    # the wiki lookup (chat) caches the book list: tell it (best effort, it may be off)
    url = os.environ.get("LOOKUP_URL")
    if url:
        try:
            req = urllib.request.Request(f"{url}/invalidate", data=b"{}", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).close()
        except OSError:
            pass


class Ollama:
    """The local Ollama: list via its API, create/remove via the CLI (as done by hand)."""

    url = "http://127.0.0.1:11434"

    def __init__(self, workdir):
        self.workdir = Path(workdir)

    def tags(self):
        with urllib.request.urlopen(f"{self.url}/api/tags", timeout=10) as r:
            return [{"name": m["name"], "size": m["size"]} for m in json.load(r).get("models", [])]

    def _run(self, *args):
        r = subprocess.run(["ollama", *args], capture_output=True, text=True)
        if r.returncode != 0:
            lines = (r.stderr or r.stdout).strip().splitlines()
            # the useful line: an "Error: …" message or a crash's "panic: …", else the last one
            useful = [ln for ln in lines if ln.startswith(("Error:", "panic:"))]
            raise RuntimeError((useful or lines or ["ollama failed"])[0 if useful else -1])

    def create(self, name, path):
        modelfile = self.workdir / f".Modelfile-{os.getpid()}-{time.monotonic_ns()}"
        modelfile.write_text(f"FROM {path}\n")
        try:
            self._run("create", name, "-f", str(modelfile))
        finally:
            modelfile.unlink(missing_ok=True)

    def remove(self, name):
        self._run("rm", name)


def _clear(directory):
    """Leftovers of uploads cut off by a restart or power loss."""
    directory.mkdir(parents=True, exist_ok=True)
    for p in directory.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()



def drives_apply():
    """Mount (or unmount) per the list of added drives, then rebuild the library."""
    subprocess.run(["systemctl", "restart", "survival-kit-drives.service"], check=True)
    kiwix_refresh()


def main():
    env = os.environ
    state = Path(env["STATE_DIR"])
    config = Config(
        port=int(env["CONTENT_PORT"]),
        static_dir=Path(env["STATIC_DIR"]),
        model_incoming=state / "incoming",
    )
    places = library.Places(
        env["DATA_DIR"], env["DRIVES_DIR"], env["REGISTRY"], env["DRIVE_STATE"], env["STATE_FILE"], env["SET_ASIDE_DIR"]
    )
    _clear(config.model_incoming)
    for loc in places.all():
        _clear(loc.root / ".incoming")

    def sizes(var, ext):
        """name → size of the built-in files in the directory env[var] names (if any)."""
        d = Path(env[var]) if env.get(var) else None
        return {p.name: p.stat().st_size for p in d.glob("*" + ext)} if d else {}

    wiki = content.Shelf(
        places,
        "wiki",
        builtins=sizes("BUILTINS_DIR", ".zim"),
        protected=set(env.get("PROTECTED", "").split()),
        validate=wiki_check,
        refresh=kiwix_refresh,
        noun="book",
    )
    maps = None
    if env.get("MAPS") == "1":
        scheme = int(env.get("MAP_SCHEME", "4"))
        maps = content.Shelf(
            places,
            "maps",
            builtins=sizes("MAP_BUILTINS_DIR", ".pmtiles"),
            protected=set(),
            validate=lambda path: pmtiles.check(path, scheme),
            refresh=kiwix_refresh,  # the library links maps too; the page reloads it
            noun="map",
        )
    translate = dicts = None
    if env.get("LANGUAGE") == "1":
        translate = content.Shelf(
            places,
            "translate",
            builtins=sizes("TRANSLATE_BUILTINS_DIR", langfiles.MODEL_EXT),
            protected=set(),
            validate=model_check,
            refresh=library_refresh,  # the Language service follows the library by itself
            noun="translation model",
            named=True,
        )
        dicts = content.Shelf(
            places,
            "dict",
            builtins=sizes("DICT_BUILTINS_DIR", langfiles.DICT_EXT),
            protected=set(),
            validate=dict_check,
            refresh=library_refresh,
            noun="dictionary",
        )
    models = content.Models(Ollama(config.model_incoming)) if env.get("OLLAMA") == "1" else None
    drives = Drives(
        registry=drv.Registry(env["REGISTRY"]),
        candidates=lambda: drv.candidates(drv.read_lsblk(), env["DRIVES_DIR"]),
        state=lambda: library._json(env["DRIVE_STATE"], {}),
        apply=drives_apply,
    )

    httpd = make_server(config, wiki, models, places, maps, drives, translate, dicts)
    print(f"content manager on 127.0.0.1:{config.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
