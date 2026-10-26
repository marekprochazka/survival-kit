"""Tests for the lookup's two front doors: the internal HTTP API (server.py) and MCP (mcp.py)."""

import io
import json
import threading
import unittest
import urllib.error
import urllib.request

import mcp
import server

BOOK = "wikipedia_en_medicine_mini_2026-10"
PUBLIC = "https://wiki.deck"


class FakeLookup:
    public = PUBLIC

    def __init__(self):
        self.invalidated = 0
        self.read_paths = []

    def books(self):
        return [{"book": BOOK, "title": "WikiMed", "summary": "Medicine", "tags": ["medical"], "articles": 1}]

    def invalidate(self):
        self.invalidated += 1

    def search(self, words, books, n=5):
        self.searched = (words, books)
        return [{"title": "Burn", "path": f"/content/{BOOK}/Burn", "book": BOOK, "snippet": "Burns occur…"}]

    def read(self, path, limit=4000):
        self.read_paths.append(path)
        return {"title": "Burn", "book": BOOK, "url": PUBLIC + path, "text": "Cool the burn."}

    def run(self, question, model, history):
        return {"plan": {"books": [BOOK], "words": question}, "hits": [], "articles": [], "error": None}


class Http(unittest.TestCase):
    def setUp(self):
        self.lookup = FakeLookup()
        self.httpd = server.make_server(self.lookup, 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None):
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def test_http_books(self):
        status, books = self.call("GET", "/books")
        self.assertEqual((status, books[0]["book"]), (200, BOOK))

    def test_http_lookup(self):
        status, r = self.call("POST", "/lookup", {"question": "burn", "model": "m", "history": []})
        self.assertEqual((status, r["plan"]["words"]), (200, "burn"))

    def test_http_invalidate(self):
        self.assertEqual(self.call("POST", "/invalidate", {})[0], 200)
        self.assertEqual(self.lookup.invalidated, 1)

    def test_http_bad_json_400(self):
        self.assertEqual(self.call("POST", "/lookup", b"not json")[0], 400)
        self.assertEqual(self.call("POST", "/lookup", {"model": "m"})[0], 400)  # no question


class Mcp(unittest.TestCase):
    def setUp(self):
        self.lookup = FakeLookup()
        self.srv = mcp.McpServer(self.lookup)

    def rpc(self, method, params=None, id=1):
        return self.srv.handle({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})

    def test_mcp_initialize_and_list(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "survival-kit-wiki")
        self.assertIsNone(self.srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        tools = {t["name"]: t for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertEqual(set(tools), {"wiki_books", "wiki_search", "wiki_read"})
        self.assertEqual(tools["wiki_search"]["inputSchema"]["required"], ["words"])

    def test_mcp_call_search(self):
        r = self.rpc("tools/call", {"name": "wiki_search", "arguments": {"words": "burn treatment"}})
        text = r["result"]["content"][0]["text"]
        self.assertIn(f"{PUBLIC}/content/{BOOK}/Burn", text)
        self.assertEqual(self.lookup.searched, ("burn treatment", [BOOK]))  # no books → all

    def test_mcp_read(self):
        r = self.rpc("tools/call", {"name": "wiki_read", "arguments": {"url": f"{PUBLIC}/content/{BOOK}/Burn"}})
        self.assertIn("Cool the burn.", r["result"]["content"][0]["text"])
        self.assertEqual(self.lookup.read_paths, [f"/content/{BOOK}/Burn"])

    def test_mcp_read_rejects_foreign_url(self):
        for url in ["https://example.com/content/x", "file:///etc/passwd", f"{PUBLIC}/catalog/v2/entries",
                    "/content/../etc", f"{PUBLIC}/content/a/../../search?x=1"]:
            with self.subTest(url=url):
                r = self.rpc("tools/call", {"name": "wiki_read", "arguments": {"url": url}})
                self.assertTrue(r["result"]["isError"])
        self.assertEqual(self.lookup.read_paths, [])

    def test_mcp_kiwix_garbage_is_a_tool_error(self):
        import xml.etree.ElementTree as ET

        def broken(*a, **k):
            raise ET.ParseError("not XML")

        self.lookup.search = broken
        r = self.rpc("tools/call", {"name": "wiki_search", "arguments": {"words": "burn"}})
        self.assertTrue(r["result"]["isError"])

    def test_mcp_unknown_method(self):
        self.assertEqual(self.rpc("resources/list")["error"]["code"], -32601)

    def test_mcp_serve_lines(self):
        inp = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
            + "this is not json\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        out = io.StringIO()
        self.srv.serve(inp, out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(replies), 2)  # tools/list + a parse error; no reply to the notification
        self.assertEqual(replies[1]["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
