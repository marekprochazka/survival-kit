"""Tests for the chat's HTTP API and live events (server.py) — a real local server, a real worker
thread, stand-ins for the lookup service and the model."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import server
import store
import worker
from test_chat import ARTICLE

FOUND = {"plan": {"books": ["med"], "words": "burn"}, "hits": [{}], "articles": [ARTICLE], "error": None}


class Gate:
    """Streams a first part (longer than the worker's hold-back) then waits until released."""

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Event()

    def __call__(self, model, messages):
        yield "Cool it under cool, "
        self.started.set()
        self.release.wait(10)
        yield "running water."


class Api(unittest.TestCase):
    models = ["llama"]

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        static = root / "static"
        static.mkdir()
        for name in ["index.html", "chat.js", "style.css"]:
            (static / name).write_text(f"<!-- {name} -->")
        self.store = store.Store(root / "chats.db")
        self.gate = Gate()
        self.hub = server.Hub(self.store)
        self.worker = worker.Worker(self.store, lambda q, m, h: FOUND, self.gate, lambda: list(self.models),
                                    on_event=self.hub.publish)
        self.stop = threading.Event()
        threading.Thread(target=self.worker.loop, args=(self.stop,), daemon=True).start()
        self.httpd = server.make_server(server.Config(port=0, static_dir=static), self.store, self.worker,
                                        self.hub, lambda: list(self.models))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.gate.release.set()
        self.stop.set()
        self.worker.wake()
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None, ctype="application/json"):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw.strip().startswith((b"{", b"[")) else raw
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def events(self, job, until=("done", "error"), limit=200):
        """Read the job's event stream until a final event (or `until`)."""
        got = []
        with urllib.request.urlopen(f"{self.base}/api/jobs/{job}/events", timeout=10) as r:
            kind = None
            for raw in r:
                line = raw.decode().rstrip("\n")
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: "):
                    got.append((kind, json.loads(line[6:])))
                    if kind in until or len(got) >= limit:
                        break
        return got

    def new_chat(self):
        return self.call("POST", "/api/chats", {"model": "llama"})[1]["id"]

    def test_chat_crud(self):
        chat = self.new_chat()
        self.assertEqual(self.call("PATCH", f"/api/chats/{chat}", {"title": "Burns"})[0], 200)
        status, chats = self.call("GET", "/api/chats")
        self.assertEqual((status, chats[0]["title"]), (200, "Burns"))
        self.assertEqual(self.call("DELETE", f"/api/chats/{chat}")[0], 200)
        self.assertEqual(self.call("GET", "/api/chats")[1], [])
        self.assertEqual(self.call("GET", f"/api/chats/{chat}")[0], 404)

    def test_ask_and_stream_to_done(self):
        chat = self.new_chat()
        status, r = self.call("POST", f"/api/chats/{chat}/ask", {"question": "burn?", "model": "llama"})
        self.assertEqual(status, 200)
        self.gate.release.set()
        evs = self.events(r["job"])
        kinds = [k for k, _ in evs]
        self.assertEqual(kinds[0], "replay")
        self.assertIn("status", kinds)
        self.assertEqual(kinds[-1], "done")
        text = "".join(d["text"] for k, d in evs if k == "token")
        self.assertEqual(text, "Cool it under cool, running water.")
        messages = self.call("GET", f"/api/chats/{chat}")[1]["messages"]
        self.assertEqual(messages[-1]["sources"][0]["url"], ARTICLE["url"])

    def test_events_replay_after_reconnect(self):
        chat = self.new_chat()
        job = self.call("POST", f"/api/chats/{chat}/ask", {"question": "burn?", "model": "llama"})[1]["job"]
        self.assertTrue(self.gate.started.wait(5))
        first = self.events(job, until=("replay",))  # the page reloads mid-answer…
        self.assertEqual(first[0][1]["text"], "Cool it under cool, ")
        self.assertEqual(first[0][1]["state"], "running")
        self.gate.release.set()
        evs = self.events(job)  # …and reconnects
        replay = evs[0][1]
        tokens = [d for k, d in evs if k == "token"]
        rebuilt = replay["text"]
        for t in tokens:  # what the page does: skip text it already has
            start = t["end"] - len(t["text"])
            if t["end"] > len(rebuilt):
                rebuilt += t["text"][len(rebuilt) - start:]
        self.assertTrue(rebuilt.endswith("running water.") or replay["state"] == "done")

    def test_second_question_reports_queue(self):
        a = self.call("POST", f"/api/chats/{self.new_chat()}/ask", {"question": "one", "model": "llama"})[1]["job"]
        self.assertTrue(self.gate.started.wait(5))
        b = self.call("POST", f"/api/chats/{self.new_chat()}/ask", {"question": "two", "model": "llama"})[1]["job"]
        replay = self.events(b, until=("replay",))[0][1]
        self.assertEqual((replay["state"], replay["position"]), ("queued", 1))
        self.assertEqual(self.call("DELETE", f"/api/jobs/{b}")[0], 200)  # cancel the waiting one
        self.assertEqual(self.store.job(b)["state"], "cancelled")
        self.assertEqual(self.call("DELETE", f"/api/jobs/{a}")[0], 409)  # a running answer can't be

    def test_job_finishes_without_client(self):
        chat = self.new_chat()
        job = self.call("POST", f"/api/chats/{chat}/ask", {"question": "burn?", "model": "llama"})[1]["job"]
        self.gate.release.set()
        for _ in range(100):
            if self.store.job(job)["state"] == "done":
                break
            threading.Event().wait(0.05)
        self.assertEqual(self.store.job(job)["state"], "done")
        replay = self.events(job, until=("replay",))[0][1]
        self.assertEqual((replay["state"], replay["text"]), ("done", "Cool it under cool, running water."))

    def test_writes_need_json(self):
        self.assertEqual(self.call("POST", "/api/chats", b"model=llama", ctype="text/plain")[0], 415)

    def test_no_models_message(self):
        self.models.clear()
        try:
            status, r = self.call("GET", "/api/models")
            self.assertEqual(r["models"], [])
            chat = self.call("POST", "/api/chats", {"model": ""})[1]["id"]
            status, r = self.call("POST", f"/api/chats/{chat}/ask", {"question": "x", "model": ""})
            self.assertEqual(status, 400)
            self.assertIn("No AI model on this box yet", r["error"])
        finally:
            self.models.append("llama")


if __name__ == "__main__":
    unittest.main()
