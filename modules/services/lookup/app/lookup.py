"""survival-kit wiki lookup — find what the box's wiki says about a question (ADR-0005).

Pipeline (the box enforces it; the model only plans):
  book map (Kiwix catalog) → the model picks books + search words → Kiwix full-text search
  → read the best articles (HTML → plain text, trimmed) → hand them to the chat.
Standard library only; Kiwix and the model are injected so it can be tested offline.
"""

import html
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

_json = json  # model_call's `json=` flag shadows the module inside it

TOP_HITS = 5  # search results kept
TOP_READ = 3  # articles read
ARTICLE_CHARS = 4000  # per article, so 3 articles + the conversation fit an 8k context
WIKI_DOWN = "the wiki could not be reached"

PLAN_SYSTEM = """You choose where to look in an offline wiki before a question is answered.
The wiki's books, one per line (id — title: description [tags]):
{books}

Reply with JSON only: {{"books": [ids of the books worth searching], "words": "2-4 precise English keywords"}}.
Pick only ids from the list. Prefer specific nouns (e.g. "burn treatment") over whole sentences."""


def _local(tag):
    return tag.rsplit("}", 1)[-1]  # drop the XML namespace


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el):
    return "".join(el.itertext()).strip() if el is not None else ""


# --- parsing Kiwix ------------------------------------------------------------------


def parse_catalog(xml):
    """Books from Kiwix's catalog (/catalog/v2/entries, Atom)."""
    books = []
    for entry in ET.fromstring(xml):
        if _local(entry.tag) != "entry":
            continue
        book = None
        for c in entry:
            if _local(c.tag) == "link" and c.get("type") == "text/html":
                book = c.get("href", "").removeprefix("/content/").strip("/")
        if not book:
            continue
        tags = [t for t in _text(_child(entry, "tags")).split(";") if t and not t.startswith("_")]
        count = _text(_child(entry, "articleCount"))
        books.append(
            {
                "book": book,
                "title": _text(_child(entry, "title")),
                "summary": _text(_child(entry, "summary")),
                "tags": tags,
                "articles": int(count) if count.isdigit() else 0,
            }
        )
    return books


def book_map_text(books):
    return "\n".join(
        f"{b['book']} — {b['title']}: {b['summary']}" + (f" [{', '.join(b['tags'])}]" if b["tags"] else "")
        for b in books
    )


def parse_search(xml):
    """Hits from Kiwix's full-text search (format=xml, RSS)."""
    hits = []
    channel = _child(ET.fromstring(xml), "channel")
    for item in channel if channel is not None else []:
        if _local(item.tag) != "item":
            continue
        path = _text(_child(item, "link"))
        parts = path.split("/")
        hits.append(
            {
                "title": _text(_child(item, "title")),
                "path": path,
                "book": parts[2] if len(parts) > 2 else "",
                "snippet": re.sub(r"\s+", " ", _text(_child(item, "description"))),
            }
        )
    return hits


class _Text(HTMLParser):
    SKIP = {"script", "style", "header", "footer", "nav", "noscript", "sup", "head", "template"}
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "br", "tr", "dd", "dt", "section"}
    VOID = {"br", "img", "hr", "meta", "link", "input", "wbr", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            if tag == "br" and not self.skip:
                self.out.append("\n")
            return
        a = dict(attrs)
        hidden = "catlinks" in (a.get("id") or "") + (a.get("class") or "")
        if self.skip or tag in self.SKIP or hidden:
            self.skip.append(tag)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if self.skip:
            if self.skip[-1] == tag:
                self.skip.pop()
            return
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))  # in HTML, a newline in text is a space


def html_to_text(page, limit):
    """The article's visible text, whitespace collapsed, cut at `limit` on a word boundary."""
    p = _Text()
    p.feed(page)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.out).split("\n"))
    text = "\n".join(ln for ln in lines if ln)
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip() + "…"
    return text


def parse_plan(reply, known):
    """The model's plan, or None if it isn't usable."""
    try:
        plan = json.loads(reply)
    except (ValueError, TypeError):
        return None
    if not isinstance(plan, dict):
        return None
    books = [b for b in plan.get("books") or [] if isinstance(b, str) and b in known]
    words = plan.get("words")
    words = " ".join(words) if isinstance(words, list) else words
    if not books or not isinstance(words, str) or not words.strip():
        return None
    return {"books": books, "words": words.strip()}


# --- the pipeline -------------------------------------------------------------------


class Lookup:
    """fetch(url) → str (raises OSError when Kiwix is unreachable);
    model_call(model, messages, json=bool) → str (the model's reply)."""

    def __init__(self, fetch, kiwix, public, model_call):
        self.fetch = fetch
        self.kiwix = kiwix.rstrip("/")
        self.public = public.rstrip("/")
        self.model_call = model_call
        self._books = None

    def books(self):
        if self._books is None:
            self._books = parse_catalog(self.fetch(f"{self.kiwix}/catalog/v2/entries?count=-1"))
        return self._books

    def invalidate(self):
        """The wiki's books changed (content manager import/delete)."""
        self._books = None

    def search(self, words, books, n=TOP_HITS):
        query = [("books.name", b) for b in books]
        query += [("pattern", words), ("format", "xml"), ("pageLength", str(n))]
        return parse_search(self.fetch(f"{self.kiwix}/search?" + urllib.parse.urlencode(query)))[:n]

    def read(self, path, limit=ARTICLE_CHARS):
        page = self.fetch(self.kiwix + path)
        m = re.search(r"<title>(.*?)</title>", page, re.S)
        parts = path.split("/")
        return {
            "title": html.unescape(m.group(1).strip()) if m else parts[-1].replace("_", " "),
            "book": parts[2] if len(parts) > 2 else "",
            "url": self.public + path,
            "text": html_to_text(page, limit),
        }

    def plan(self, question, model, history, books):
        recent = [m["content"] for m in history if m.get("role") == "user"][-2:]
        context = "".join(f"Earlier question: {q}\n" for q in recent)
        messages = [
            {"role": "system", "content": PLAN_SYSTEM.format(books=book_map_text(books))},
            {"role": "user", "content": f"{context}Question: {question}"},
        ]
        try:
            plan = parse_plan(self.model_call(model, messages, json=True), {b["book"] for b in books})
        except Exception:  # noqa: BLE001 — a failed plan just means: search everything
            plan = None
        return plan or {"books": [b["book"] for b in books], "words": question.strip()}

    def run(self, question, model, history):
        """Never raises: a wiki that can't be reached gives no articles and an error note."""
        try:
            books = self.books()
            plan = self.plan(question, model, history, books)
            hits = self.search(plan["words"], plan["books"]) if plan["books"] else []
            articles = [self.read(h["path"]) for h in hits[:TOP_READ]]
            return {"plan": plan, "hits": hits, "articles": articles, "error": None}
        except (OSError, ET.ParseError) as e:
            self.invalidate()
            return {"plan": None, "hits": [], "articles": [], "error": f"{WIKI_DOWN} ({e})"}


# --- the real helpers (tests use stand-ins) -------------------------------------------


def http_fetch(url, timeout=30):
    """GET a Kiwix URL as text (raises OSError when Kiwix is unreachable)."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def ollama_call(base):
    """model_call for Lookup: one non-streamed chat request to the local Ollama."""
    import urllib.request

    def call(model, messages, json=False):
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": 8192},
        }
        if json:
            body["format"] = "json"
        req = urllib.request.Request(
            f"{base.rstrip('/')}/api/chat",
            data=_json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as r:  # a slow CPU may need minutes
            return _json.load(r)["message"]["content"]

    return call
