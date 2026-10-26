"""survival-kit chat — the web side (ADR-0005): JSON API, live events, the page.

On 127.0.0.1 behind nginx (https://chat.<domain>). Answers run in the worker thread, not in
the request: a page follows a job over Server-Sent Events and can reconnect at any time
(first a `replay` event with the text so far, then live events; every token carries `end`,
its end position in the full text, so nothing is shown twice).

API (writes take JSON bodies only — a form on another site can't send those)
  GET    /health                        "ok"
  GET    /api/models                    installed models
  GET    /api/chats                     chats, newest first
  POST   /api/chats {model}             new chat
  GET    /api/chats/<id>                chat + messages + its open job
  PATCH  /api/chats/<id> {title}        rename
  DELETE /api/chats/<id>                delete
  POST   /api/chats/<id>/ask {question, model}   queue a question → {job}
  DELETE /api/jobs/<id>                 cancel a waiting question
  GET    /api/jobs/<id>/events          the job's live events (text/event-stream)
  GET    /, /chat.js, /style.css        the page
Standard library only.
"""

import json
import os
import queue
import re
import threading
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import store as store_mod
import worker as worker_mod

STATIC = {"/": "index.html", "/chat.js": "chat.js", "/style.css": "style.css"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css"}
NO_MODELS = "No AI model on this box yet — add one under Content."
FINAL = ("done", "failed", "cancelled")
MAX_BODY = 64 * 1024  # a question is text; nothing legitimate is bigger


def utf16_len(text):
    """Length as the browser's JavaScript counts it (an emoji is 2) — token `end` positions."""
    return len(text.encode("utf-16-le")) // 2


@dataclass
class Config:
    port: int
    static_dir: Path


class Hub:
    """Fans the worker's events out to every page following a job."""

    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.subs = {}

    def subscribe(self, job_id):
        q = queue.Queue()
        with self.lock:
            self.subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id, q):
        with self.lock:
            subs = self.subs.get(job_id, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self.subs.pop(job_id, None)

    def publish(self, job_id, kind, data):
        if kind == "token":
            job = self.store.job(job_id)
            data = {"text": data, "end": utf16_len(job["text"] if job else data)}
        elif kind == "status":
            data = {"text": data}
        elif kind == "error":
            data = {"error": data}
        with self.lock:
            subs = list(self.subs.get(job_id, []))
        for q in subs:
            q.put((kind, data))


def make_server(config, store, worker, hub, models):
    """models() → installed model names (raises if Ollama is down)."""

    def installed():
        try:
            return list(models())
        except Exception:  # noqa: BLE001 — Ollama down: treat as none installed
            return []

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def json_body(self):
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return "415"
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return "413"
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return None
            return data if isinstance(data, dict) else None

        def route(self):
            m = re.fullmatch(r"/api/(chats|jobs)(?:/(\d+))?(/ask|/events)?", self.path.split("?")[0])
            return (m.group(1), int(m.group(2)) if m.group(2) else None, m.group(3)) if m else (None, None, None)

        def write_event(self, kind, data):
            self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        # --- GET -------------------------------------------------------------------

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/health":
                return self.send(200, b"ok", "text/plain")
            if path == "/api/models":
                return self.send(200, {"models": installed()})
            if path in STATIC:
                file = config.static_dir / STATIC[path]
                return self.send(200, file.read_bytes(), TYPES[file.suffix])
            kind, ident, sub = self.route()
            if kind == "chats" and ident is None and sub is None:
                return self.send(200, store.chats())
            if kind == "chats" and sub is None:
                chat = store.chat(ident)
                if chat is None:
                    return self.send(404, {"error": "no such chat"})
                job = store.open_job(ident) or store.last_failed_job(ident)  # a failure stays visible
                return self.send(200, {"chat": chat, "messages": store.messages(ident), "job": job})
            if kind == "jobs" and sub == "/events":
                return self.events(ident)
            self.send(404, {"error": "not found"})

        def events(self, job_id):
            if store.job(job_id) is None:
                return self.send(404, {"error": "no such question"})
            q = hub.subscribe(job_id)  # before reading the job: nothing can slip in between
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                job = store.job(job_id)
                position = store.queue_position(job_id) if job["state"] == "queued" else 0
                self.write_event("replay", {"state": job["state"], "status": job["status"], "text": job["text"],
                                            "position": position, "error": job["error"]})
                if job["state"] in FINAL:
                    return self.final(job)
                while True:
                    try:
                        kind, data = q.get(timeout=2)
                    except queue.Empty:
                        job = store.job(job_id)
                        if job is None or job["state"] in FINAL:
                            return self.final(job)
                        if job["state"] == "queued":
                            new = store.queue_position(job_id)
                            if new != position:
                                position = new
                                self.write_event("queue", {"position": position})
                        else:
                            self.wfile.write(b": still writing\n\n")  # keeps proxies from timing out
                            self.wfile.flush()
                        continue
                    self.write_event(kind, data)
                    if kind in ("done", "error"):
                        return None
            except (BrokenPipeError, ConnectionResetError):
                return None  # the page went away; the answer goes on
            finally:
                hub.unsubscribe(job_id, q)

        def final(self, job):
            if job is None:
                self.write_event("error", {"error": "this chat was deleted"})
            elif job["state"] == "done":
                last = store.messages(job["chat"])[-1]
                self.write_event("done", {"notice": last["notice"], "sources": last["sources"]})
            else:
                self.write_event("error", {"error": job["error"] or job["state"]})

        # --- writes ----------------------------------------------------------------

        def write(self, handler):
            data = self.json_body()
            if data == "415":
                return self.send(415, {"error": "send JSON"})
            if data == "413":
                self.close_connection = True  # the unread body follows
                return self.send(413, {"error": "too long"})
            if data is None:
                return self.send(400, {"error": "expected a JSON object"})
            return handler(data)

        def do_POST(self):
            kind, ident, sub = self.route()
            if kind == "chats" and ident is None and sub is None:
                return self.write(lambda d: self.send(200, {"id": store.create_chat(str(d.get("model", "")))}))
            if kind == "chats" and sub == "/ask":
                return self.write(lambda d: self.ask(ident, d))
            self.send(404, {"error": "not found"})

        def ask(self, chat_id, d):
            question, model = d.get("question"), d.get("model")
            if not isinstance(question, str) or not question.strip():
                return self.send(400, {"error": "the question is empty"})
            names = installed()
            if not names:
                return self.send(400, {"error": NO_MODELS})
            if model not in names:
                return self.send(400, {"error": f"unknown model: {model}"})
            if store.chat(chat_id) is None:
                return self.send(404, {"error": "no such chat"})
            job = store.ask(chat_id, question.strip(), model)
            worker.wake()
            return self.send(200, {"job": job})

        def do_PATCH(self):
            kind, ident, sub = self.route()
            if kind != "chats" or ident is None or sub:
                return self.send(404, {"error": "not found"})

            def rename(d):
                if store.chat(ident) is None:
                    return self.send(404, {"error": "no such chat"})
                store.rename(ident, str(d.get("title", "")))
                return self.send(200, {"result": "renamed"})

            return self.write(rename)

        def do_DELETE(self):
            kind, ident, sub = self.route()
            if kind == "chats" and ident is not None and not sub:
                store.delete(ident)
                return self.send(200, {"result": "deleted"})
            if kind == "jobs" and ident is not None and not sub:
                if store.cancel(ident):
                    hub.publish(ident, "error", "cancelled")
                    return self.send(200, {"result": "cancelled"})
                return self.send(409, {"error": "only a waiting question can be cancelled"})
            self.send(404, {"error": "not found"})

    httpd = ThreadingHTTPServer(("127.0.0.1", config.port), Handler)
    httpd.daemon_threads = True
    return httpd


# --- the real helpers (tests use stand-ins) -------------------------------------------


def _post(url, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def ollama_models(base):
    def models():
        with urllib.request.urlopen(f"{base}/api/tags", timeout=10) as r:
            return [m["name"].removesuffix(":latest") for m in json.load(r).get("models", [])]

    return models


def ollama_stream(base):
    def stream(model, messages):
        body = {"model": model, "messages": messages, "stream": True, "options": {"num_ctx": 8192}}
        with _post(f"{base}/api/chat", body, timeout=900) as r:  # slow CPUs: minutes are fine
            for line in r:
                if not line.strip():
                    continue
                part = json.loads(line)
                if part.get("error"):
                    raise RuntimeError(part["error"])
                text = (part.get("message") or {}).get("content", "")
                if text:
                    yield text
                if part.get("done"):
                    return

    return stream


def lookup_service(base):
    def call(question, model, history):
        with _post(f"{base}/lookup", {"question": question, "model": model, "history": history}, timeout=900) as r:
            return json.load(r)

    return call


def main():
    env = os.environ
    ollama = env.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    store = store_mod.Store(env["CHAT_DB"])
    store.recover()
    hub = Hub(store)
    models = ollama_models(ollama)
    work = worker_mod.Worker(store, lookup_service(env["LOOKUP_URL"].rstrip("/")), ollama_stream(ollama), models,
                             on_event=hub.publish)
    threading.Thread(target=work.loop, args=(threading.Event(),), daemon=True).start()
    httpd = make_server(Config(port=int(env["CHAT_PORT"]), static_dir=Path(env["STATIC_DIR"])), store, work, hub,
                        models)
    print(f"chat on 127.0.0.1:{env['CHAT_PORT']}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
