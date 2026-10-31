"""Unit tests for translate.py — splitting, tokenizers, routing (a stand-in model, no VM).

The stand-in "model" gives back the tokens it gets (plus any target prefix), so whatever the
tokenizers do must come back out unchanged; the real models are tried in the VM test.
"""

import tempfile
import unittest
from pathlib import Path

import archives
import translate
from content import Refused
from test_langfiles import make_model


class Result:
    def __init__(self, tokens):
        self.hypotheses = [tokens]


class Echo:
    """A CTranslate2 Translator stand-in: echoes the tokens (after the prefix, if any)."""

    def __init__(self, folder):
        self.folder = folder
        self.calls = []

    def translate_batch(self, batch, target_prefix=None, **kw):
        self.calls.append((batch, kw))
        prefixes = target_prefix or [[] for _ in batch]
        return [Result(list(p) + list(tokens)) for p, tokens in zip(prefixes, batch)]


class Tagged(Echo):
    """Marks every sentence with the pair it went through, to see the route."""

    def translate_batch(self, batch, target_prefix=None, **kw):
        tag = self.folder.name
        return [Result([f"[{tag}]", *tokens]) for tokens in batch]


def model(tmp, from_code, to_code, tokenizer="bpe", prefix="", load=Echo, extra=None):
    archive = make_model(Path(tmp) / f"{from_code}_{to_code}.argosmodel", from_code, to_code,
                         tokenizer=tokenizer, prefix=prefix, extra=extra)
    folder = archives.unpack(archive, Path(tmp))
    return translate.Model(folder, translate.read_info(folder), load=load)


class Split(unittest.TestCase):
    def test_split_sentences(self):
        self.assertEqual(translate.split("It rains. We stay home! Do we? Yes 2 times."),
                         [["It rains.", "We stay home!", "Do we?", "Yes 2 times."]])

    def test_split_keeps_paragraphs(self):
        text = "First one. Second one.\n\n\nNew paragraph.\n  \nLast."
        self.assertEqual(translate.split(text), [["First one.", "Second one."], ["New paragraph."], ["Last."]])

    def test_split_at_line_breaks(self):
        self.assertEqual(translate.split("A title\nThe text."), [["A title", "The text."]])

    def test_split_no_split_after_abbreviation_lowercase(self):
        self.assertEqual(translate.split("Fruit, e.g. this one."), [["Fruit, e.g. this one."]])

    def test_split_czech_capitals(self):
        self.assertEqual(translate.split("Prší. Čekáme."), [["Prší.", "Čekáme."]])

    def test_split_empty(self):
        self.assertEqual(translate.split("  \n\n "), [])


class Tokenizers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_bpe_round_trip(self):
        m = model(self.tmp, "en", "cs")
        self.assertEqual(m.translate(["Hello, world.", "hello world"]), ["Hello, world.", "hello world"])
        tokens = m._translator.calls[0][0][1]
        self.assertTrue(any(t.endswith("@@") for t in tokens), tokens)  # BPE did split words

    def test_sentencepiece_round_trip(self):
        import sentencepiece as spm  # noqa: PLC0415

        corpus = Path(self.tmp) / "corpus.txt"
        corpus.write_text("hello world\nthe house is big\nwe like the world\n" * 20)
        prefix = str(Path(self.tmp) / "sp")
        spm.SentencePieceTrainer.train(input=str(corpus), model_prefix=prefix, vocab_size=30,
                                       hard_vocab_limit=False, minloglevel=2)
        m = model(self.tmp, "de", "en", tokenizer="sentencepiece",
                  extra={"sp": Path(prefix + ".model").read_bytes()})
        self.assertEqual(m.translate(["the house is big"]), ["the house is big"])

    def test_target_prefix_removed(self):
        m = model(self.tmp, "en", "cs", prefix="__cs__")
        self.assertEqual(m.translate(["hello world"]), ["hello world"])
        self.assertTrue(m._translator.calls)

    def test_model_loads_once(self):
        loads = []

        def load(folder):
            loads.append(folder)
            return Echo(folder)

        m = model(self.tmp, "en", "cs", load=load)
        m.translate(["a"])
        m.translate(["b"])
        self.assertEqual(len(loads), 1)


class Routes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def translator(self, *pairs):
        return translate.Translator({p: model(self.tmp, *p, load=Tagged) for p in pairs})

    def test_languages(self):
        t = self.translator(("en", "cs"), ("cs", "en"))
        self.assertEqual(t.languages(), [{"code": "cs", "name": "CS"}, {"code": "en", "name": "EN"}])

    def test_route_direct(self):
        self.assertEqual(self.translator(("en", "cs")).route("en", "cs"), [("en", "cs")])

    def test_route_via_english(self):
        t = self.translator(("de", "en"), ("en", "cs"))
        self.assertEqual(t.route("de", "cs"), [("de", "en"), ("en", "cs")])

    def test_route_needs_both_halves(self):
        t = self.translator(("de", "en"), ("cs", "en"))
        with self.assertRaises(Refused):
            t.route("de", "cs")
        self.assertEqual(t.targets("de"), ["en"])

    def test_targets_include_pivot(self):
        t = self.translator(("de", "en"), ("en", "cs"), ("en", "de"), ("cs", "en"))
        self.assertEqual(t.targets("de"), ["cs", "en"])
        self.assertEqual(t.targets("en"), ["cs", "de"])
        self.assertEqual(t.targets("xx"), [])

    def test_translate_goes_through_route(self):
        t = self.translator(("de", "en"), ("en", "cs"))
        out = t.translate("Hallo Welt.", "de", "cs")
        self.assertTrue(out.startswith("["), out)  # both hops tagged it
        self.assertEqual(out.count("["), 2, out)

    def test_translate_caps_length(self):
        t = self.translator(("en", "cs"))
        with self.assertRaises(Refused) as e:
            t.translate("x" * (translate.MAX_CHARS + 1), "en", "cs")
        self.assertIn("5000", str(e.exception))

    def test_translate_joins_paragraphs(self):
        t = translate.Translator({("en", "cs"): model(self.tmp, "en", "cs")})
        self.assertEqual(t.translate("One. Two.\n\nThree.", "en", "cs"), "One. Two.\n\nThree.")

    def test_translate_same_language_and_empty(self):
        t = self.translator(("en", "cs"))
        self.assertEqual(t.translate("Hi.", "en", "en"), "Hi.")
        self.assertEqual(t.translate("   ", "en", "cs"), "")


if __name__ == "__main__":
    unittest.main()
