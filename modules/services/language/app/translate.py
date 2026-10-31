"""Translation with Argos Translate models, without the argostranslate package.

A model (unpacked by archives.py) is a CTranslate2 model plus a tokenizer. Two kinds exist:
SentencePiece (sentencepiece.model) and, in the OPUS-MT packages (1.9.x, incl. en↔cs),
Moses + BPE (bpe.model, subword-nmt codes): Moses tokenizes (sacremoses), BPE splits words
(Argos's apply_bpe.py, MIT, copied in at build time), the model translates, "@@ " joins the
pieces again and Moses detokenizes — as argostranslate 1.11 does (tokenizer.py, translate.py).
The heavy libraries are imported only when a model is first used. A pair without a model
goes through English when both halves exist (de → en → cs).
"""

import json
import re
import threading
from pathlib import Path

from content import Refused

MAX_CHARS = 5000
MAX_SENTENCE = 400  # characters; a model cuts off what is much longer (no error), so cut first
PIVOT = "en"
_BREAK = re.compile(r"[.!?…]+[\"'”’»)\]]*\s+|[。！？]+[\"'”’»)\]」』]*\s*")


def read_info(folder):
    """What langfiles.check_model said about the model (archives.unpack saved it)."""
    return json.loads((Path(folder) / "info.json").read_text())


def _cut(sentence):
    """A sentence longer than MAX_SENTENCE in pieces, at the last comma or space that fits."""
    out = []
    while len(sentence) > MAX_SENTENCE:
        at = sentence.rfind(", ", 0, MAX_SENTENCE)
        if at > 0:
            out.append(sentence[: at + 1])
            sentence = sentence[at + 2 :]
            continue
        at = sentence.rfind(" ", 0, MAX_SENTENCE + 1)
        if at > 0:
            out.append(sentence[:at])
            sentence = sentence[at + 1 :]
        else:
            out.append(sentence[:MAX_SENTENCE])
            sentence = sentence[MAX_SENTENCE:]
    return [*out, sentence]


def _sentences(line):
    """A line split after . ! ? … unless the next word starts with a small letter (scripts
    without capitals split too), and after 。！？; over-long sentences cut."""
    out, start = [], 0
    for m in _BREAK.finditer(line):
        nxt = line[m.end() : m.end() + 1]
        if nxt and not nxt.islower():
            out.append(line[start : m.end()].strip())
            start = m.end()
    out.append(line[start:].strip())
    return [piece for s in out if s for piece in _cut(s)]


def split(text):
    """Paragraphs (between blank lines) of sentences (also split at line breaks)."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        sentences = [s for line in block.splitlines() for s in _sentences(line)]
        if sentences:
            paragraphs.append(sentences)
    return paragraphs


def _ctranslate2(folder):
    import ctranslate2  # noqa: PLC0415 — heavy: only when a model is used

    return ctranslate2.Translator(str(Path(folder) / "model"), device="cpu", compute_type="auto")


class _Bpe:
    def __init__(self, folder, from_code, to_code):
        from apply_bpe import BPE  # noqa: PLC0415
        from sacremoses import MosesDetokenizer, MosesPunctNormalizer, MosesTokenizer  # noqa: PLC0415

        self.normalizer = MosesPunctNormalizer(from_code)
        self.tokenizer = MosesTokenizer(from_code)
        self.detokenizer = MosesDetokenizer(to_code)
        with open(Path(folder) / "bpe.model", encoding="utf-8") as f:
            self.bpe = BPE(f)

    def encode(self, sentence):
        tokens = " ".join(self.tokenizer.tokenize(self.normalizer.normalize(sentence)))
        return self.bpe.segment_tokens(tokens.strip("\r\n ").split(" "))

    def decode(self, tokens):
        return self.detokenizer.detokenize(" ".join(tokens).replace("@@ ", "").split(" "))


class _SentencePiece:
    def __init__(self, folder):
        import sentencepiece  # noqa: PLC0415

        self.sp = sentencepiece.SentencePieceProcessor(model_file=str(Path(folder) / "sentencepiece.model"))

    def encode(self, sentence):
        return self.sp.encode(sentence, out_type=str)

    def decode(self, tokens):
        return self.sp.decode(tokens)


class Model:
    """One unpacked model. load(folder) → a CTranslate2 Translator (tests: a stand-in)."""

    def __init__(self, folder, info, load=None):
        self.folder = Path(folder)
        self.info = info
        self.pair = (info["from_code"], info["to_code"])
        self.load = load or _ctranslate2
        self._translator = None
        self._tokenizer = None

    def _ready(self):
        if self._translator is None:
            if self.info["tokenizer"] == "bpe":
                self._tokenizer = _Bpe(self.folder, *self.pair)
            else:
                self._tokenizer = _SentencePiece(self.folder)
            self._translator = self.load(self.folder)

    def unload(self):
        """Free the model's memory; it loads again on its next use."""
        self._translator = None
        self._tokenizer = None

    def translate(self, sentences):
        """Each sentence translated (one batch)."""
        if not sentences:
            return []
        self._ready()
        tokens = [self._tokenizer.encode(s) for s in sentences]
        prefix = self.info.get("target_prefix") or ""
        results = self._translator.translate_batch(
            tokens,
            target_prefix=[[prefix]] * len(tokens) if prefix else None,
            replace_unknowns=True,
            beam_size=4,
            length_penalty=0.2,
        )
        out = []
        for r in results:
            value = self._tokenizer.decode(r.hypotheses[0])
            if prefix and value.startswith(prefix):
                value = value[len(prefix) :]
            out.append(value.strip())
        return out


class Loaded:
    """Which models are in memory: at most `limit` (2 — a translation through English needs
    both halves), the one used longest ago is unloaded first. Used under the translation lock."""

    def __init__(self, limit=2):
        self.limit = limit
        self.models = []  # oldest use first

    def use(self, model):
        if model in self.models:
            self.models.remove(model)
        self.models.append(model)
        while len(self.models) > self.limit:
            self.models.pop(0).unload()


class Translator:
    """The installed models: {(from, to): Model}. One translation at a time (CPU-bound).

    lock and loaded are shared by the catalog's successive Translators (a rebuild must not
    let a second translation start, or load a model twice)."""

    def __init__(self, models, lock=None, loaded=None):
        self.models = dict(models)
        self.lock = lock or threading.Lock()
        self.loaded = loaded or Loaded()

    def languages(self):
        names = {}
        for m in self.models.values():
            names.setdefault(m.pair[0], m.info["from_name"])
            names.setdefault(m.pair[1], m.info["to_name"])
        return sorted(({"code": c, "name": n} for c, n in names.items()), key=lambda x: (x["name"].lower(), x["code"]))

    def targets(self, src):
        direct = {dst for s, dst in self.models if s == src}
        if (src, PIVOT) in self.models:
            direct |= {dst for s, dst in self.models if s == PIVOT}
        return sorted(direct - {src})

    def route(self, src, dst):
        if (src, dst) in self.models:
            return [(src, dst)]
        if (src, PIVOT) in self.models and (PIVOT, dst) in self.models:
            return [(src, PIVOT), (PIVOT, dst)]
        raise Refused(f"no translation from {src} to {dst} on this box")

    def translate(self, text, src, dst):
        if len(text) > MAX_CHARS:
            raise Refused(f"at most {MAX_CHARS} characters at a time")
        paragraphs = split(text)
        if src == dst or not paragraphs:
            return text.strip() if src == dst else ""
        route = self.route(src, dst)
        with self.lock:
            for pair in route:
                self.loaded.use(self.models[pair])
                flat = self.models[pair].translate([s for p in paragraphs for s in p])
                it = iter(flat)
                paragraphs = [[next(it) for _ in p] for p in paragraphs]
        return "\n\n".join(" ".join(p) for p in paragraphs)
