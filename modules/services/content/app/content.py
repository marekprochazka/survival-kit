"""survival-kit content manager — the file logic (ADR-0004).

Everything here works on plain files and injected helpers, so it can be tested without
HTTP, Kiwix or Ollama. server.py maps the web API onto it. Standard library only.
"""

import os
import re
import tempfile
from pathlib import Path

GIB = 1024**3
MAX_NAME = 200  # characters; file systems allow 255 bytes per name


class Refused(Exception):
    """A request we won't do; the message is shown to the user as is.

    status: 400 = bad input, 403 = not allowed (built-in, protected), 404 = not found.
    """

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --- names --------------------------------------------------------------------------


def _stem(filename, ext):
    """Base name without directories, checked for (case-insensitive) extension."""
    base = os.path.basename(filename.replace("\\", "/"))
    if not base.lower().endswith(ext):
        raise Refused(f"only {ext} files can be imported here")
    return base[: -len(ext)]


def wiki_name_plain(filename):
    """File name a wiki book is stored under: <clean stem>.zim.

    Kiwix's date suffix (_YYYY-MM) is dropped, so a newer download keeps the book's
    address (/content/<stem>) and replaces the older one. Unsafe characters become "_";
    leading dots are dropped (no hidden files).
    """
    stem = _stem(filename, ".zim")
    stem = re.sub(r"_\d{4}-\d{2}$", "", stem)
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem).lstrip(".")
    if not stem:
        raise Refused("this file name can't be used for a wiki book")
    if len(stem) > MAX_NAME:
        raise Refused(f"this file name is too long (at most {MAX_NAME} characters)")
    return stem + ".zim"


def wiki_name(filename, protected):
    """wiki_name_plain for an upload: the box's own manuals are refused."""
    name = wiki_name_plain(filename)
    if name[:-4] in protected:
        raise Refused(f"'{name[:-4]}' is the box's own manual and can't be replaced", status=403)
    return name


def clean_model_name(name):
    """Ollama-safe model name: lower case, [a-z0-9._-], separators collapsed."""
    name = re.sub(r"[^a-z0-9._-]+", "-", name.strip().lower()).strip("-._")
    if not name:
        raise Refused("this model name can't be used")
    if len(name) > MAX_NAME:
        raise Refused(f"this model name is too long (at most {MAX_NAME} characters)")
    return name


def model_name(filename):
    """Model name derived from a .gguf file name."""
    return clean_model_name(_stem(filename, ".gguf"))


def map_name(filename):
    """File name a map is stored under: <stem>.pmtiles, lower case, [a-z0-9._-] only.

    The name is also how the map page tells maps apart, and an import replaces a
    built-in map of the same name (world, central-europe, czechia).
    """
    stem = re.sub(r"[^a-z0-9._-]+", "-", _stem(filename, ".pmtiles").lower()).lstrip(".")
    if not stem.strip("-._"):
        raise Refused("this file name can't be used for a map")
    if len(stem) > MAX_NAME:
        raise Refused(f"this file name is too long (at most {MAX_NAME} characters)")
    return stem + ".pmtiles"


# --- space --------------------------------------------------------------------------


def margin(total):
    """Space always kept free: 2 GiB or 5 % of the disk, whichever is larger."""
    return max(2 * GIB, total // 20)


def check_space(needed, free, total):
    if needed + margin(total) > free:
        gb = lambda n: f"{n / 1000**3:.1f} GB"  # noqa: E731
        raise Refused(
            f"not enough space: need {gb(needed)} (+ {gb(margin(total))} kept free), free {gb(free)}"
        )


# --- uploads ------------------------------------------------------------------------


def receive(stream, length, incoming, chunk=1 << 20):
    """Stream exactly `length` bytes into a new temp file in `incoming`.

    Anything short of a complete upload (cut-off body, write error) removes the temp
    file, so a partial book or model never appears.
    """
    fd, name = tempfile.mkstemp(prefix=".up-", dir=incoming)
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            left = length
            while left > 0:
                data = stream.read(min(chunk, left))
                if not data:
                    raise Refused("the upload was cut off; nothing was imported")
                out.write(data)
                left -= len(data)
        return path
    except Refused:
        path.unlink(missing_ok=True)
        raise
    except OSError as e:
        path.unlink(missing_ok=True)
        raise Refused(f"could not save the upload: {e.strerror or e}") from e


# --- wiki books and maps --------------------------------------------------------------


ITEM = ("name", "file", "size", "mtime", "location", "status", "reason")


class Shelf:
    """Wiki books (.zim), maps (.pmtiles), translation models (.argosmodel) or dictionaries
    (.dictd.tar.xz) on all locations, next to the built-in ones.

    places: library.Places — the locations (this device, added drives) and the library's
    last result: which copy of a name is in use, which are duplicates or invalid (ADR-0006).
    builtins: file name → size of the built-in files (not deletable; an import of the same
    name replaces one until it is deleted). protected: stems that can't even be replaced.
    validate(path) → a note for the user or None; raises Refused when the file is unusable
    (validate(path, name) when named).
    refresh(): rebuild the library and tell the services.  noun: "book", "map" (messages).
    """

    def __init__(self, places, kind, builtins, protected, validate, refresh, noun, named=False):
        self.places = places
        self.kind = kind  # the folder on every location: wiki/, maps/, translate/, dict/
        self.ext = {"wiki": ".zim", "maps": ".pmtiles", "translate": ".argosmodel", "dict": ".dictd.tar.xz"}[kind]
        self.named = named  # validate(path, stored name) — a translation model's name is its pair
        self.builtins = dict(builtins)
        self.protected = set(protected)
        self.validate = validate
        self.refresh = refresh
        self.noun = noun

    def _check(self, name):
        if "/" in name or name.startswith(".") or not name.endswith(self.ext):
            raise Refused(f"not a {self.noun} name")

    def _stem(self, name):
        return name[: -len(self.ext)]

    def _in_use(self, name):
        return next((e for e in self.places.entries(self.kind) if e["name"] == name and e["status"] == "in_use"), None)

    def items(self):
        """Every file on every location, with where it is and whether it is in use."""
        return [{k: e[k] for k in ITEM} for e in self.places.entries(self.kind)]

    def builtin_items(self):
        return [
            {
                "name": name,
                "size": size,
                "replaced": self._in_use(name) is not None,
                "protected": self._stem(name) in self.protected,
            }
            for name, size in sorted(self.builtins.items())
        ]

    def exists(self, name):
        self._check(name)
        if self._in_use(name):
            return "import"
        return "builtin" if name in self.builtins else None

    def install(self, tmp, name, loc):
        """Move a received upload (in loc's .incoming/) into loc; returns validate's note.

        It replaces the copy of this name in use — wherever that is; other copies (duplicates
        on other locations) are left alone.
        """
        try:
            self._check(name)
            if self._stem(name) in self.protected:
                raise Refused("the box's own manuals can't be replaced", status=403)
            note = self.validate(tmp, name) if self.named else self.validate(tmp)
            os.chmod(tmp, 0o644)  # kiwix-serve / nginx run unprivileged
            target = loc.root / self.kind / name
            old = self._in_use(name)
            os.replace(tmp, target)  # atomic: same filesystem
        except BaseException:
            Path(tmp).unlink(missing_ok=True)  # whatever went wrong, no upload is left behind
            raise
        if old and old["path"] != target:
            old["path"].unlink(missing_ok=True)
        self.refresh()
        return note

    def delete(self, name, at=None, file=None):
        """Delete one copy: the one on location `at` (named `file` there), else the one in use."""
        self._check(name)
        copies = [e for e in self.places.entries(self.kind) if e["name"] == name]
        if at:
            copies = [e for e in copies if e["location"] == at and (file is None or e["file"] == file)]
        else:
            copies = [e for e in copies if e["status"] == "in_use"]
        if not copies:
            if name in self.builtins and not at:
                raise Refused(f"built-in {self.noun}s can't be deleted", status=403)
            raise Refused(f"no such {self.noun}", status=404)
        copies[0]["path"].unlink(missing_ok=True)
        self.refresh()

    def used(self, at=None):
        return sum(e["size"] for e in self.items() if at is None or e["location"] == at)


# --- models -------------------------------------------------------------------------


class Models:
    """AI models in the local Ollama.

    ollama: tags() → [{name, size}], create(name, path), remove(name).
    """

    def __init__(self, ollama):
        self.ollama = ollama

    def items(self):
        return [
            {"name": t["name"].removesuffix(":latest"), "size": t["size"]}
            for t in self.ollama.tags()
        ]

    def exists(self, name):
        return "import" if any(m["name"] == name for m in self.items()) else None

    def install(self, tmp, name):
        try:
            self.ollama.create(name, tmp)
        except Refused:
            raise
        except Exception as e:  # ollama's own message is the useful part
            raise Refused(f"the model could not be added: {e}") from e
        finally:
            Path(tmp).unlink(missing_ok=True)  # Ollama keeps its own copy

    def delete(self, name):
        if self.exists(name) is None:
            raise Refused("no such model", status=404)
        self.ollama.remove(name)

    def used(self):
        return sum(m["size"] for m in self.items())
