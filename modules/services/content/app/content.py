"""survival-kit content manager — the file logic (ADR-0004).

Everything here works on plain files and injected helpers, so it can be tested without
HTTP, Kiwix or Ollama. server.py maps the web API onto it. Standard library only.
"""

import os
import re
import tempfile
from pathlib import Path

GIB = 1024**3


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


def wiki_name(filename, protected):
    """File name a wiki book is stored under: <clean stem>.zim.

    Kiwix's date suffix (_YYYY-MM) is dropped, so a newer download keeps the book's
    address (/content/<stem>) and replaces the older one. Unsafe characters become "_";
    leading dots are dropped (no hidden files). The box's own manuals are refused.
    """
    stem = _stem(filename, ".zim")
    stem = re.sub(r"_\d{4}-\d{2}$", "", stem)
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem).lstrip(".")
    if not stem:
        raise Refused("this file name can't be used for a wiki book")
    if stem in protected:
        raise Refused(f"'{stem}' is the box's own manual and can't be replaced", status=403)
    return stem + ".zim"


def clean_model_name(name):
    """Ollama-safe model name: lower case, [a-z0-9._-], separators collapsed."""
    name = re.sub(r"[^a-z0-9._-]+", "-", name.strip().lower()).strip("-._")
    if not name:
        raise Refused("this model name can't be used")
    return name


def model_name(filename):
    """Model name derived from a .gguf file name."""
    return clean_model_name(_stem(filename, ".gguf"))


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


# --- wiki ---------------------------------------------------------------------------


class Wiki:
    """Imported books in `zims` (Kiwix's drop-in dir) next to the built-in starter books.

    builtins: file name → size of the books that come with the system (not deletable).
    validate(path) → bool: can Kiwix read it?   refresh(): rebuild the catalog.
    """

    def __init__(self, zims, builtins, protected, validate, refresh):
        self.zims = Path(zims)
        self.builtins = dict(builtins)
        self.protected = set(protected)
        self.validate = validate
        self.refresh = refresh

    def _path(self, name):
        if "/" in name or name.startswith(".") or not name.endswith(".zim"):
            raise Refused("not a wiki book name")
        return self.zims / name

    def items(self):
        books = []
        for p in sorted(self.zims.glob("*.zim")):
            if p.is_file() and not p.name.startswith("."):
                st = p.stat()
                books.append({"name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
        return books

    def builtin_items(self):
        return [
            {
                "name": name,
                "size": size,
                "replaced": (self.zims / name).is_file(),
                "protected": name[: -len(".zim")] in self.protected,
            }
            for name, size in sorted(self.builtins.items())
        ]

    def exists(self, name):
        if self._path(name).is_file():
            return "import"
        return "builtin" if name in self.builtins else None

    def install(self, tmp, name):
        target = self._path(name)
        if name[: -len(".zim")] in self.protected:
            Path(tmp).unlink(missing_ok=True)
            raise Refused("the box's own manuals can't be replaced", status=403)
        if not self.validate(tmp):
            Path(tmp).unlink(missing_ok=True)
            raise Refused("not a readable wiki book")
        os.chmod(tmp, 0o644)  # kiwix-serve runs unprivileged
        os.replace(tmp, target)  # atomic: same directory tree
        self.refresh()

    def delete(self, name):
        path = self._path(name)
        if not path.is_file():
            if name in self.builtins:
                raise Refused("built-in books can't be deleted", status=403)
            raise Refused("no such book", status=404)
        path.unlink()
        self.refresh()

    def used(self):
        return sum(b["size"] for b in self.items())


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
