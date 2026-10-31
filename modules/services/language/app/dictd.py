"""A dictd dictionary, unpacked (archives.unpack): dict.index + dict.dict.

Words are found ignoring case and outer spaces; the entries are the dictionary's own text.
The index is kept in memory (WordNet: ~150 000 words), the data read by offset. Standard
library only.
"""

import bisect
from pathlib import Path

import langfiles


def _key(word):
    return " ".join(word.split()).lower()


class Dictionary:
    def __init__(self, folder):
        folder = Path(folder)
        self.data = folder / "dict.dict"
        self.words = {}  # key → [(offset, length)]
        self.title = None
        names = {}
        for word, off, length in langfiles.parse_index((folder / "dict.index").read_text("utf-8")):
            if word in langfiles.TITLE_WORDS:
                self.title = langfiles.entry_title(self._read(off, length))
            if not word.strip() or word.startswith(("00-database", "00database")):
                continue
            key = _key(word)
            spots = self.words.setdefault(key, [])
            if (off, length) not in spots:
                spots.append((off, length))
            names.setdefault(key, word)
        self.title = self.title or "Dictionary"
        self.keys = sorted(names)
        self.names = names

    def _read(self, off, length):
        with open(self.data, "rb") as f:
            f.seek(off)
            return f.read(length).decode("utf-8", "replace")

    def lookup(self, word):
        """The entries of `word` (texts), [] when it isn't in the dictionary."""
        return [self._read(off, length).strip() for off, length in self.words.get(_key(word), [])]

    def near(self, word, n=10):
        """Up to n words starting like `word`, in order."""
        start = _key(word)
        if not start:
            return []
        out = []
        for key in self.keys[bisect.bisect_left(self.keys, start):]:
            if not key.startswith(start) or len(out) == n:
                break
            out.append(self.names[key])
        return out
