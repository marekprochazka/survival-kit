"""survival-kit content manager — the web side (ADR-0004, ADR-0006).

A small JSON API plus one page, on 127.0.0.1 behind nginx (https://content.<domain>).
Uploads are one file per request with the raw file as the body (Python 3.13 has no cgi
module, and this streams straight to disk). Standard library only.

Content lives on locations: "device" (this device) and added drives (by filesystem UUID).

API
  GET    /health                                  "ok"
  GET    /api/status                              disk, locations, drives, wiki, builtins,
                                                  maps, map_builtins, models (null on lite)
  GET    /api/check?kind=&file=&size=[&to=][&model=]  stored name + whether it exists;
                                                  space check on location `to` (default device)
  PUT    /api/upload?kind=&file=[&to=][&model=]   body = the file (Content-Length required);
                                                  kind = wiki | map | model (models: device)
  DELETE /api/wiki/<name>[?at=&file=], /api/maps/<name>[?at=&file=], /api/models/<name>
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
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import content
import drives as drv
import library
import pmtiles
from content import Refused

STATIC = {"/": "index.html", "/content.js": "content.js", "/style.css": "style.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css"}
NO_MODELS = "no AI models on this box (lite profile)"
NO_MAPS = "no maps on this box"
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


def render(template, s):
    """The page's lists as HTML, so viewing works without JavaScript."""
    e = html.escape
    d = s["disk"]
    rest = d["total"] - d["free"] - d["wiki"] - d["maps"] - d["models"]
    out = [
        '<section id="disk"><h2>Disk</h2>',
        f'<p>{_size(d["free"])} free of {_size(d["total"])}. '
        f'Wiki {_size(d["wiki"])}, maps {_size(d["maps"])}, AI models {_size(d["models"])}, '
        f"system and other {_size(max(rest, 0))}.</p>",
        "</section>",
        '<section id="wiki"><h2>Wiki books</h2>',
        "<table><tr><th>Book</th><th>Size</th><th>Imported</th><th></th></tr>",
    ]
    for b in s["wiki"]:
        day = time.strftime("%Y-%m-%d", time.localtime(b["mtime"]))
        out.append(
            f'<tr><td>{e(b["name"][:-4])}</td><td>{_size(b["size"])}</td><td>{day}</td>'
            f'<td><button data-delete="wiki" data-name="{e(b["name"])}" data-at="{e(b["location"])}" '
            f'data-file="{e(b["file"])}">Delete</button></td></tr>'
        )
    for b in s["builtins"]:
        note = "replaced by import" if b["replaced"] else "built in"
        out.append(f'<tr class="builtin"><td>{e(b["name"][:-4])}</td><td>{_size(b["size"])}</td><td>{note}</td><td></td></tr>')
    out.append("</table>")
    out.append(
        '<p><label>Import wiki files <input type="file" data-import="wiki" accept=".zim" multiple></label> '
        '<label>or a folder <input type="file" data-import="wiki" webkitdirectory></label></p></section>'
    )
    if s["maps"] is not None:
        out.append('<section id="maps"><h2>Maps</h2>')
        out.append("<table><tr><th>Map</th><th>Size</th><th>Imported</th><th></th></tr>")
        for m in s["maps"]:
            day = time.strftime("%Y-%m-%d", time.localtime(m["mtime"]))
            out.append(
                f'<tr><td>{e(m["name"][:-8])}</td><td>{_size(m["size"])}</td><td>{day}</td>'
                f'<td><button data-delete="maps" data-name="{e(m["name"])}" data-at="{e(m["location"])}" '
                f'data-file="{e(m["file"])}">Delete</button></td></tr>'
            )
        for m in s["map_builtins"]:
            note = "replaced by import" if m["replaced"] else "built in"
            out.append(f'<tr class="builtin"><td>{e(m["name"][:-8])}</td><td>{_size(m["size"])}</td><td>{note}</td><td></td></tr>')
        out.append("</table>")
        out.append(
            '<p><label>Import map files <input type="file" data-import="map" accept=".pmtiles" multiple></label></p></section>'
        )
    if s["models"] is not None:
        out.append('<section id="models"><h2>AI models</h2>')
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


def make_server(config, wiki, models, places, maps=None, drives=None):
    """places: library.Places. models / maps / drives: None when the box has no AI models
    (lite) / no maps service / no drive support (tests)."""

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
            t, f = places.disk(loc)
            locs.append({"id": loc.id, "name": loc.name, "total": t, "free": f,
                         "wiki": wiki.used(loc.id), "maps": maps.used(loc.id) if maps else 0})
        return {
            "disk": {
                "total": total,
                "free": free,
                "wiki": wiki.used("device"),
                "maps": maps.used("device") if maps else 0,
                "models": sum(m["size"] for m in model_items or []),
            },
            "locations": locs,
            "drives": drive_status(),
            "wiki": wiki.items(),
            "builtins": wiki.builtin_items(),
            "maps": maps.items() if maps else None,
            "map_builtins": maps.builtin_items() if maps else [],
            "models": model_items,
            "models_error": models_error,
        }

    def drive_status():
        if drives is None:
            return {"added": [], "available": []}
        state = drives.state()
        added = drives.registry.drives()
        known = {d["uuid"] for d in added}
        return {
            "added": [d | state.get(d["uuid"], {"mounted": False, "error": "not mounted yet"}) for d in added],
            "available": [c for c in drives.candidates() if c["uuid"] not in known],
        }

    def target(q):
        """(store, stored name, space factor, incoming dir, location or None) for a request."""
        kind, file = q.get("kind", ""), q.get("file", "")
        if kind in ("wiki", "map"):
            store = wiki if kind == "wiki" else maps
            if store is None:
                raise Refused(NO_MAPS)
            name = content.wiki_name(file, wiki.protected) if kind == "wiki" else content.map_name(file)
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
                if kind == "wiki":
                    wiki.delete(name, q.get("at"), q.get("file"))
                elif kind == "maps":
                    if maps is None:
                        raise Refused(NO_MAPS)
                    maps.delete(name, q.get("at"), q.get("file"))
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
                entries = places.entries("wiki") + (places.entries("maps") if maps else [])
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

            if path == "/api/resolve":
                return self.route(resolve)
            if path == "/api/drives/add":
                return self.route(add)
            if path.startswith("/api/drives/"):
                return self.route(drive_action)
            self.send(404, {"error": "not found"})

    def drive_result(uuid):
        s = drives.state().get(uuid, {"mounted": False, "error": "not mounted"})
        return {"mounted": s["mounted"], "error": s["error"]}

    httpd = ThreadingHTTPServer(("127.0.0.1", config.port), Handler)
    httpd.daemon_threads = True
    return httpd


# --- the real helpers (used by main; tests use stand-ins) ----------------------------


def wiki_check(path):
    """The wiki shelf's validate: Refused unless Kiwix can read the book."""
    if library.kiwix_book(path) is None:
        raise Refused("not a readable wiki book")


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
    models = content.Models(Ollama(config.model_incoming)) if env.get("OLLAMA") == "1" else None
    drives = Drives(
        registry=drv.Registry(env["REGISTRY"]),
        candidates=lambda: drv.candidates(drv.read_lsblk(), env["DRIVES_DIR"]),
        state=lambda: library._json(env["DRIVE_STATE"], {}),
        apply=drives_apply,
    )

    httpd = make_server(config, wiki, models, places, maps, drives)
    print(f"content manager on 127.0.0.1:{config.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
