"""The Moby Thesaurus (public domain, Project Gutenberg 3202): one line per headword,
"root,synonym,synonym,…", CRLF, Latin-1. 25 MB, so only where each headword's line starts is
kept in memory; the line is read when asked for. Standard library only.
"""

import bisect
from pathlib import Path


def _key(word):
    return " ".join(word.split()).lower()


class Thesaurus:
    def __init__(self, path):
        self.path = Path(path)
        self.lines = {}  # key → byte offset
        names = {}
        offset = 0
        with open(self.path, "rb") as f:
            for line in f:
                root = line.split(b",", 1)[0].decode("latin-1").strip()
                key = _key(root)
                if key and key not in self.lines:
                    self.lines[key] = offset
                    names[key] = root
                offset += len(line)
        self.keys = sorted(names)
        self.names = names

    def synonyms(self, word):
        """The synonyms of `word` in Moby's order, None when it has no line."""
        offset = self.lines.get(_key(word))
        if offset is None:
            return None
        with open(self.path, "rb") as f:
            f.seek(offset)
            words = f.readline().decode("latin-1").split(",")[1:]
        return [w.strip() for w in words if w.strip()]

    def near(self, word, n=10):
        """Up to n headwords starting like `word`, in order."""
        start = _key(word)
        if not start:
            return []
        out = []
        for key in self.keys[bisect.bisect_left(self.keys, start):]:
            if not key.startswith(start) or len(out) == n:
                break
            out.append(self.names[key])
        return out
