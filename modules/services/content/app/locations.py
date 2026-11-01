"""Locations — the places that hold the box's content (ADR-0006).

Every location has the same tree: a marker file, then one folder per kind. This device's
tree is /var/lib/survival-kit/data; an added drive's is the survival-kit/ folder at its
root. Nothing outside that tree is ever listed or touched. Standard library only.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import content
import langfiles
from content import Refused

FORMAT = 1  # the tree's layout version, written into the marker
MARKER = "survival-kit.json"
DIRS = ("wiki", "maps", "models", "translate", "dict", "media", ".incoming")
# kind → (file extension, the clean name a file is known by)
KINDS = {
    "wiki": (".zim", content.wiki_name_plain),
    "maps": (".pmtiles", content.map_name),
    "translate": (langfiles.MODEL_EXT, langfiles.translate_name),  # Language: translation models
    "dict": (langfiles.DICT_EXT, langfiles.dict_name),  # Language: dictionaries
}


@dataclass(frozen=True)
class Location:
    """id: "device" or the drive's filesystem UUID; order: 0 = device, then add order."""

    id: str
    name: str
    root: Path
    order: int


def read_marker(root):
    """The tree's marker as a dict, None when there is none; Refused when it can't be used."""
    path = Path(root) / MARKER
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Refused(
            f"{path} can't be read ({e}) — Forget the drive, fix or remove that file on another computer, then add it again"
        ) from e
    if not isinstance(data, dict) or not isinstance(data.get("format"), int):
        raise Refused(f"{path} is not a survival-kit marker")
    if data["format"] > FORMAT:
        raise Refused(f"this drive was set up by a newer survival-kit (format {data['format']}); update this box first")
    return data


def ensure_tree(root, name):
    """Create the tree's folders and marker where missing; an existing marker is kept."""
    root = Path(root)
    marker = read_marker(root)  # refuses before anything is created
    try:
        for d in DIRS:
            (root / d).mkdir(mode=0o755, parents=True, exist_ok=True)
    except OSError as e:
        raise Refused(f"can't create the survival-kit folders in {root}: {e.strerror or e}") from e
    if marker is None:
        tmp = root / f".{MARKER}.tmp"
        tmp.write_text(json.dumps({"format": FORMAT, "name": name}) + "\n")
        os.replace(tmp, root / MARKER)


def scan(loc, kind):
    """The files of one kind on a location: [{name, file, path, size, mtime, location, refusal}].

    name is the clean name the file is known by (e.g. a ZIM's date suffix dropped); a file
    whose name can't be cleaned keeps its own name and gets a refusal. Hidden files, other
    extensions and sub-folders are ignored. A location that isn't there has no files.
    """
    ext, clean = KINDS[kind]
    folder = loc.root / kind
    if not folder.is_dir():
        return []
    files = []
    for p in sorted(folder.iterdir()):
        if p.name.startswith(".") or not p.name.lower().endswith(ext) or not p.is_file():
            continue
        try:
            name, refusal = clean(p.name), None
        except Refused as e:
            name, refusal = p.name, str(e)
        st = p.stat()
        files.append(
            {
                "name": name,
                "file": p.name,
                "path": p,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "location": loc.id,
                "refusal": refusal,
            }
        )
    return files
