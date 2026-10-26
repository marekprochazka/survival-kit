"""Unit tests for lookup.py — fixtures are real Kiwix 3.8.2 output (catalog, search, article)."""

import json
import unittest
from pathlib import Path

import lookup

FIX = Path(__file__).parent / "fixtures"
MED = "wikipedia_en_medicine_mini_2026-10"
LUA = "devdocs_en_lua_2026-08"
KIWIX = "http://127.0.0.1:8080"
PUBLIC = "https://wiki.deck"


def fake_fetch(calls=None, down=False):
    """Serves the fixtures like Kiwix would."""

    def fetch(url):
        if calls is not None:
            calls.append(url)
        if down:
            raise OSError("connection refused")
        if "/catalog/v2/entries" in url:
            return (FIX / "catalog.xml").read_text()
        if "/search?" in url:
            return (FIX / "search.xml").read_text()
        if "/content/" in url:
            return (FIX / "article.html").read_text()
        raise AssertionError(url)

    return fetch


class Parsing(unittest.TestCase):
    def test_parse_catalog(self):
        books = {b["book"]: b for b in lookup.parse_catalog((FIX / "catalog.xml").read_text())}
        self.assertEqual(set(books), {MED, LUA})
        med = books[MED]
        self.assertEqual(med["title"], "WikiMed Medical Encyclopedia")
        self.assertIn("medical encyclopedia", med["summary"])
        self.assertEqual(med["tags"], ["medical", "wikipedia"])  # no _ftindex:… etc.
        self.assertEqual(med["articles"], 340299)

    def test_book_map_text(self):
        text = lookup.book_map_text(lookup.parse_catalog((FIX / "catalog.xml").read_text()))
        self.assertIn(f"{MED} — WikiMed Medical Encyclopedia:", text)
        self.assertEqual(len(text.splitlines()), 2)

    def test_parse_search(self):
        hits = lookup.parse_search((FIX / "search.xml").read_text())
        self.assertEqual(len(hits), 3)
        self.assertEqual(hits[0]["title"], "Burn")
        self.assertEqual(hits[0]["path"], f"/content/{MED}/Burn")
        self.assertEqual(hits[0]["book"], MED)
        self.assertNotIn("<b>", hits[0]["snippet"])

    def test_html_to_text(self):
        text = lookup.html_to_text((FIX / "article.html").read_text(), limit=4000)
        self.assertIn("Burns occur mainly in the home", text)
        for junk in ["startup.js", "TemplateStyles", "mw-content", "{", "Hidden categories"]:
            self.assertNotIn(junk, text)
        cut = lookup.html_to_text((FIX / "article.html").read_text(), limit=1000)  # mini: ~4k chars
        self.assertLessEqual(len(cut), 1001)
        self.assertTrue(cut.endswith("…"))
        short = lookup.html_to_text("<p>Cool  the\n burn.</p><script>x()</script>", limit=100)
        self.assertEqual(short, "Cool the burn.")

    def test_html_unclosed_tags_in_skipped_region(self):
        page = "<header><p>menu<li>x<col><embed></header><p>Real text.</p>"
        self.assertEqual(lookup.html_to_text(page, limit=100), "Real text.")

    def test_parse_plan(self):
        known = {MED, LUA}
        plan = lookup.parse_plan(json.dumps({"books": [MED, "nope"], "words": "burn treatment"}), known)
        self.assertEqual(plan, {"books": [MED], "words": "burn treatment"})
        for bad in ["not json", '{"books": [], "words": "x"}', '{"books": ["nope"], "words": "x"}',
                    f'{{"books": ["{MED}"], "words": ""}}', "[]"]:
            with self.subTest(bad=bad):
                self.assertIsNone(lookup.parse_plan(bad, known))


class Run(unittest.TestCase):
    def make(self, plan_reply, down=False, calls=None, model_fails=False):
        def model_call(model, messages, json=False):
            if model_fails:
                raise OSError("ollama down")
            self.assertTrue(json)
            self.assertIn(MED, messages[-1]["content"] + messages[0]["content"])  # the book map is shown
            return plan_reply

        return lookup.Lookup(fake_fetch(calls, down), KIWIX, PUBLIC, model_call)

    def test_run_happy(self):
        calls = []
        lk = self.make(json.dumps({"books": [MED], "words": "burn treatment"}), calls=calls)
        r = lk.run("How do I treat a burn?", "llama", [])
        self.assertIsNone(r["error"])
        self.assertEqual(r["plan"], {"books": [MED], "words": "burn treatment"})
        self.assertEqual(len(r["hits"]), 3)
        self.assertEqual(len(r["articles"]), 3)
        self.assertEqual(r["articles"][0]["url"], f"{PUBLIC}/content/{MED}/Burn")
        self.assertIn("Burns occur", r["articles"][0]["text"])
        search = [c for c in calls if "/search?" in c][0]
        self.assertIn(f"books.name={MED}", search)
        self.assertIn("pattern=burn+treatment", search)

    def test_run_bad_plan_searches_all_books(self):
        calls = []
        lk = self.make("I think you should look at medicine", calls=calls)
        r = lk.run("burn", "llama", [])
        self.assertEqual(sorted(r["plan"]["books"]), sorted([MED, LUA]))
        self.assertEqual(r["plan"]["words"], "burn")
        search = [c for c in calls if "/search?" in c][0]
        self.assertIn(f"books.name={LUA}", search)

    def test_run_model_down_still_searches(self):
        r = self.make("", model_fails=True).run("burn", "llama", [])
        self.assertEqual(len(r["articles"]), 3)

    def test_run_kiwix_down_sets_error(self):
        r = self.make("{}", down=True).run("burn", "llama", [])
        self.assertEqual(r["articles"], [])
        self.assertTrue(r["error"])

    def test_run_skips_missing_article(self):
        import urllib.error

        base = fake_fetch()

        def fetch(url):
            if url.endswith("/Burn"):
                raise urllib.error.HTTPError(url, 404, "not found", None, None)
            return base(url)

        lk = lookup.Lookup(fetch, KIWIX, PUBLIC, lambda *a, **k: json.dumps({"books": [MED], "words": "burn"}))
        r = lk.run("burn", "m", [])
        self.assertIsNone(r["error"])
        urls = [a["url"] for a in r["articles"]]
        self.assertEqual(len(urls), 2)  # 3 hits, the missing one skipped
        self.assertFalse(any(u.endswith("/Burn") for u in urls))

    def test_search_pattern_capped(self):
        calls = []
        lk = self.make("{}", calls=calls)
        lk.search("w " * 1000, [MED])
        self.assertLessEqual(len([c for c in calls if "/search?" in c][0]), 600)

    def test_books_cached_until_invalidated(self):
        calls = []
        lk = self.make("{}", calls=calls)
        lk.books()
        lk.books()
        self.assertEqual(sum("/catalog/" in c for c in calls), 1)
        lk.invalidate()
        lk.books()
        self.assertEqual(sum("/catalog/" in c for c in calls), 2)


if __name__ == "__main__":
    unittest.main()
