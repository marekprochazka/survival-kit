"""survival-kit content manager — the web side (ADR-0004).

A small JSON API plus one page, on 127.0.0.1 behind nginx (https://content.<domain>).
Uploads are one file per request with the raw file as the body (Python 3.13 has no cgi
module, and this streams straight to disk). Standard library only.

API
  GET    /health                               "ok"
  GET    /api/status                           disk, wiki, builtins, models (null on lite), locations
  GET    /api/check?kind=&file=&size=[&model=] stored name + whether it exists; space check
  PUT    /api/upload?kind=&file=[&model=]      body = the file (Content-Length required)
  DELETE /api/wiki/<name>, /api/models/<name>
  GET    /, /content.js, /style.css            the page
"""

import html
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import content
from content import Refused

STATIC = {"/": "index.html", "/content.js": "content.js", "/style.css": "style.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css"}
NO_MODELS = "no AI models on this box (lite profile)"
MODELS_DOWN = "not available right now"


@dataclass
class Config:
    port: int
    static_dir: Path
    wiki_incoming: Path
    model_incoming: Path
    locations: dict


def _size(n):
    return f"{n / 1000**3:.1f} GB" if n >= 10**8 else f"{n / 1000**2:.0f} MB"


def render(template, s):
    """The page's lists as HTML, so viewing works without JavaScript."""
    e = html.escape
    d = s["disk"]
    rest = d["total"] - d["free"] - d["wiki"] - d["models"]
    out = [
        '<section id="disk"><h2>Disk</h2>',
        f'<p>{_size(d["free"])} free of {_size(d["total"])}. '
        f'Wiki {_size(d["wiki"])}, AI models {_size(d["models"])}, system and other {_size(max(rest, 0))}.</p>',
        "</section>",
        f'<section id="wiki"><h2>Wiki books</h2><p class="where">{e(s["locations"]["wiki"])}</p>',
        "<table><tr><th>Book</th><th>Size</th><th>Imported</th><th></th></tr>",
    ]
    for b in s["wiki"]:
        day = time.strftime("%Y-%m-%d", time.localtime(b["mtime"]))
        out.append(
            f'<tr><td>{e(b["name"][:-4])}</td><td>{_size(b["size"])}</td><td>{day}</td>'
            f'<td><button data-delete="wiki" data-name="{e(b["name"])}">Delete</button></td></tr>'
        )
    for b in s["builtins"]:
        note = "replaced by import" if b["replaced"] else "built in"
        out.append(f'<tr class="builtin"><td>{e(b["name"][:-4])}</td><td>{_size(b["size"])}</td><td>{note}</td><td></td></tr>')
    out.append("</table>")
    out.append(
        '<p><label>Import wiki files <input type="file" data-import="wiki" accept=".zim" multiple></label> '
        '<label>or a folder <input type="file" data-import="wiki" webkitdirectory></label></p></section>'
    )
    if s["models"] is not None:
        out.append(f'<section id="models"><h2>AI models</h2><p class="where">{e(s["locations"]["models"])}</p>')
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


def make_server(config, wiki, models, disk):
    """disk() → (total, free) bytes of the filesystem holding the content."""

    def status():
        total, free = disk()
        # Ollama may be starting, crashed or out of memory: the wiki part must still work
        model_items, models_error = (None, None)
        if models:
            try:
                model_items = models.items()
            except Exception:  # noqa: BLE001
                model_items, models_error = [], MODELS_DOWN
        return {
            "disk": {
                "total": total,
                "free": free,
                "wiki": wiki.used(),
                "models": sum(m["size"] for m in model_items or []),
            },
            "wiki": wiki.items(),
            "builtins": wiki.builtin_items(),
            "models": model_items,
            "models_error": models_error,
            "locations": config.locations,
        }

    def target(q):
        """(store, stored name, space factor, incoming dir) for a request's kind/file."""
        kind, file = q.get("kind", ""), q.get("file", "")
        if kind == "wiki":
            return wiki, content.wiki_name(file, wiki.protected), 1, config.wiki_incoming
        if kind == "model":
            if models is None:
                raise Refused(NO_MODELS)
            name = content.model_name(file)  # also checks the .gguf extension
            if q.get("model"):
                name = content.clean_model_name(q["model"])
            # the upload and Ollama's own copy exist side by side for a moment
            return models, name, 2, config.model_incoming
        raise Refused("unknown kind")

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
                    store, name, factor, _ = target(q)
                    size = q.get("size", "0")
                    if not size.isdigit():
                        raise Refused("size must be a number of bytes")
                    total, free = disk()
                    content.check_space(factor * int(size), free, total)
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
                store, name, factor, incoming = target(q)
                length = self.headers.get("Content-Length")
                if length is None or not length.isdigit():
                    raise Refused("the upload needs a Content-Length")
                total, free = disk()
                content.check_space(factor * int(length), free, total)
                existed = store.exists(name)
                tmp = content.receive(self.rfile, int(length), incoming)
                store.install(tmp, name)
                self.send(200, {"name": name, "result": "replaced" if existed else "added"})

            self.route(upload)

        def do_DELETE(self):
            path, _ = self.parts()

            def delete():
                kind, _, name = path.removeprefix("/api/").partition("/")
                name = urllib.parse.unquote(name)
                if kind == "wiki":
                    wiki.delete(name)
                elif kind == "models":
                    if models is None:
                        raise Refused(NO_MODELS)
                    models.delete(name)
                else:
                    raise Refused("not found", status=404)
                self.send(200, {"name": name, "result": "deleted"})

            self.route(delete)

    httpd = ThreadingHTTPServer(("127.0.0.1", config.port), Handler)
    httpd.daemon_threads = True
    return httpd


# --- the real helpers (used by main; tests use stand-ins) ----------------------------


def kiwix_validate(path):
    """Can Kiwix read it? Adding it to a throw-away catalog is Kiwix's own check."""
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(["kiwix-manage", f"{d}/library.xml", "add", str(path)], capture_output=True)
        return r.returncode == 0


def kiwix_refresh():
    subprocess.run(["systemctl", "restart", "kiwix-library.service"], check=True)
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


def main():
    env = os.environ
    zims = Path(env["ZIMS_DIR"])
    state = Path(env["STATE_DIR"])
    config = Config(
        port=int(env["CONTENT_PORT"]),
        static_dir=Path(env["STATIC_DIR"]),
        wiki_incoming=zims / ".incoming",
        model_incoming=state / "incoming",
        locations={"wiki": str(zims), "models": env.get("MODELS_DIR", "")},
    )
    _clear(config.wiki_incoming)
    _clear(config.model_incoming)
    builtins_dir = Path(env["BUILTINS_DIR"]) if env.get("BUILTINS_DIR") else None
    builtins = {p.name: p.stat().st_size for p in builtins_dir.glob("*.zim")} if builtins_dir else {}
    wiki = content.Wiki(
        zims,
        builtins=builtins,
        protected=set(env.get("PROTECTED", "").split()),
        validate=kiwix_validate,
        refresh=kiwix_refresh,
    )
    models = content.Models(Ollama(config.model_incoming)) if env.get("OLLAMA") == "1" else None

    def disk():
        u = shutil.disk_usage(zims)
        return u.total, u.free

    httpd = make_server(config, wiki, models, disk)
    print(f"content manager on 127.0.0.1:{config.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
