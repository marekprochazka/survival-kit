"""survival-kit wiki lookup — MCP server over stdio (command: survival-kit-wiki-mcp).

For MCP clients such as oterm or mcphost: the *client's* model decides when to call these
tools (no model runs here). JSON-RPC 2.0, one message per line.
  wiki_books                  what the wiki contains (the book map)
  wiki_search {words, books?} full-text search, best hits with links
  wiki_read {url}             an article's text (only links into this box's wiki)
Standard library only.
"""

import json
import os
import re
import sys

import lookup

DEFAULT_VERSION = "2025-06-18"
TOOLS = [
    {
        "name": "wiki_books",
        "description": "List the books in this box's offline wiki (id, title, description, tags).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "wiki_search",
        "description": "Full-text search in the offline wiki. Use 2-4 precise English keywords. "
        "Returns article titles, links and snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "words": {"type": "string", "description": "2-4 precise keywords"},
                "books": {"type": "array", "items": {"type": "string"}, "description": "book ids (default: all)"},
            },
            "required": ["words"],
        },
    },
    {
        "name": "wiki_read",
        "description": "Read an article from the offline wiki by its link (from wiki_search).",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
]
SAFE_PATH = re.compile(r"^/content/[^/?#]+/[^?#]+$")


class McpServer:
    def __init__(self, lk):
        self.lookup = lk

    def _path(self, url):
        """A link into this box's wiki → its path; anything else is refused."""
        path = url[len(self.lookup.public) :] if url.startswith(self.lookup.public + "/") else url
        if not SAFE_PATH.match(path) or ".." in path.split("/"):
            raise ValueError("only links into this box's wiki can be read")
        return path

    def call_tool(self, name, args):
        if name == "wiki_books":
            return lookup.book_map_text(self.lookup.books())
        if name == "wiki_search":
            words = args.get("words")
            if not isinstance(words, str) or not words.strip():
                raise ValueError("words missing")
            books = args.get("books") or [b["book"] for b in self.lookup.books()]
            hits = self.lookup.search(words.strip(), books)
            if not hits:
                return "No articles found."
            return "\n\n".join(f"{h['title']} — {self.lookup.public}{h['path']}\n{h['snippet']}" for h in hits)
        if name == "wiki_read":
            article = self.lookup.read(self._path(str(args.get("url", ""))))
            return f"{article['title']} ({article['url']})\n\n{article['text']}"
        raise ValueError(f"unknown tool: {name}")

    def handle(self, msg):
        """One JSON-RPC message → the reply (None for notifications)."""
        if "id" not in msg:
            return None  # notifications (e.g. notifications/initialized) get no reply
        mid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}

        def ok(result):
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        if method == "initialize":
            return ok(
                {
                    "protocolVersion": params.get("protocolVersion") or DEFAULT_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "survival-kit-wiki", "version": "1"},
                }
            )
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": TOOLS})
        if method == "tools/call":
            try:
                text = self.call_tool(params.get("name"), params.get("arguments") or {})
                return ok({"content": [{"type": "text", "text": text}], "isError": False})
            except Exception as e:  # noqa: BLE001 — a tool failure must not end the server
                return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method: {method}"}}

    def serve(self, stdin, stdout):
        for line in stdin:
            if not line.strip():
                continue
            try:
                reply = self.handle(json.loads(line))
            except (ValueError, TypeError, AttributeError):
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            if reply is not None:
                stdout.write(json.dumps(reply) + "\n")
                stdout.flush()


def main():
    env = os.environ

    def no_model(*_):
        raise RuntimeError("no model in the MCP server")

    lk = lookup.Lookup(lookup.http_fetch, env["KIWIX_URL"], env["PUBLIC_WIKI_URL"], no_model)
    McpServer(lk).serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
