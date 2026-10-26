"""survival-kit wiki lookup — internal HTTP API for the chat (127.0.0.1 only, no vhost).

  GET  /health                                  "ok"
  GET  /books                                   the book map (Kiwix catalog)
  POST /lookup {question, model, history}       plan → search → read (lookup.Lookup.run)
  POST /invalidate                              the wiki's books changed (content manager)
Standard library only.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import lookup


def make_server(lk, port):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body):
            data = json.dumps(body).encode() if not isinstance(body, bytes) else body
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return None
            return data if isinstance(data, dict) else None

        def do_GET(self):
            if self.path == "/health":
                return self.send(200, b"ok")
            if self.path == "/books":
                try:
                    return self.send(200, lk.books())
                except OSError as e:
                    return self.send(502, {"error": f"{lookup.WIKI_DOWN} ({e})"})
            self.send(404, {"error": "not found"})

        def do_POST(self):
            data = self.body()
            if data is None:
                return self.send(400, {"error": "expected a JSON object"})
            if self.path == "/invalidate":
                lk.invalidate()
                return self.send(200, {"result": "ok"})
            if self.path == "/lookup":
                question = data.get("question")
                if not isinstance(question, str) or not question.strip():
                    return self.send(400, {"error": "question missing"})
                history = data.get("history") if isinstance(data.get("history"), list) else []
                return self.send(200, lk.run(question, str(data.get("model", "")), history))
            self.send(404, {"error": "not found"})

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    return httpd


def main():
    env = os.environ
    lk = lookup.Lookup(
        lookup.http_fetch,
        env["KIWIX_URL"],
        env["PUBLIC_WIKI_URL"],
        lookup.ollama_call(env.get("OLLAMA_URL", "http://127.0.0.1:11434")),
    )
    httpd = make_server(lk, int(env["LOOKUP_PORT"]))
    print(f"wiki lookup on 127.0.0.1:{env['LOOKUP_PORT']}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
