"""A stand-in for Ollama in VM tests (no real model can run there): /api/tags lists one
model; /api/chat answers the planning call with an empty plan (→ search all books) and
streams a fixed answer. A question containing "test page" takes ~6 s (to test the queue)."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            return self.reply({"models": [{"name": "test-model:latest", "size": 1}]})
        self.send_error(404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if req.get("format") == "json":
            return self.reply({"message": {"role": "assistant", "content": '{"books": [], "words": ""}'}})
        slow = "test page" in req["messages"][-1]["content"]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for word in ["The wiki says ", "this is a ", "test page."]:
            if slow:
                time.sleep(2)
            line = {"message": {"role": "assistant", "content": word}, "done": False}
            self.wfile.write((json.dumps(line) + "\n").encode())
            self.wfile.flush()
        self.wfile.write(b'{"message": {"role": "assistant", "content": ""}, "done": true}\n')


ThreadingHTTPServer(("127.0.0.1", 11500), Handler).serve_forever()
