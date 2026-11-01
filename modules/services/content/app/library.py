"""The library — one merged, checked view of the content on all locations (ADR-0006).

Services don't know about locations: they read /var/lib/survival-kit/library/<kind>,
a folder of symlinks to the copy in use of every book, map, translation model and
dictionary (kinds: wiki, maps, translate, dict) and of every media folder — film, series
season, album (kind media, see media.py). Files already on a location get the same checks as
uploads; a failing one is "invalid" (media is found by layout only, never invalid), the
older copy of a name on two locations is a "duplicate" — both stay where they are, not in use, until
auto-resolve (set_aside) moves them out of the tree. Standard library only.

Run as a program (survival-kit-library.service, at boot and after every change): rebuild
the index and the state file the content manager shows.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import media
from content import Refused
from locations import Location, ensure_tree, scan

DEVICE_NAME = "This device"
KINDS_ALL = ("wiki", "maps", "translate", "dict", "media")


# --- what is in use -------------------------------------------------------------------


def _winner(copies):
    """The copy of a name to use: the newest when every copy has a date, else by order."""
    by_order = sorted(copies, key=lambda e: e["order"])
    if all(e["date"] for e in copies):
        return sorted(by_order, key=lambda e: e["date"], reverse=True)[0]  # stable: ties by order
    return by_order[0]


def resolve(locs, kind, check, protected):
    """Every file of `kind` on `locs`, each with status in_use | duplicate | invalid.

    check(path, kind) → {"ok", "reason", "date"}. Entries are scan()'s plus kind, order,
    status, reason and date.
    """
    entries = []
    for loc in sorted(locs, key=lambda loc: loc.order):
        try:
            found = media.scan_items(loc) if kind == "media" else scan(loc, kind)
            for e in found:
                e.update(kind=kind, order=loc.order, date=None, reason=None)
                if kind == "media":  # layout only: never opened, the newest folder wins
                    e.update(status="in_use", date=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(e["mtime"])))
                elif e["refusal"]:
                    e.update(status="invalid", reason=e["refusal"])
                elif kind == "wiki" and e["name"][:-4] in protected:
                    e.update(status="invalid", reason="the box's own manual can't be replaced")
                else:
                    r = check(e["path"], kind)
                    e.update(status="in_use" if r["ok"] else "invalid", reason=r["reason"], date=r["date"])
        except OSError as err:  # a dead mount (pulled out), a locked folder: leave it out
            print(f"library: {loc.name}: {kind} can't be read ({err}); left out", file=sys.stderr, flush=True)
            continue
        entries += found
    groups = {}
    for e in entries:
        if e["status"] == "in_use":
            groups.setdefault(e["name"], []).append(e)
    for copies in groups.values():
        winner = _winner(copies)
        for e in copies:
            if e is not winner:
                e["status"] = "duplicate"
    return entries


# --- checks ---------------------------------------------------------------------------


def kiwix_book(path):
    """Kiwix's own reading of a ZIM (its <book> attributes), or None when it can't read it."""
    with tempfile.TemporaryDirectory() as d:
        lib = Path(d) / "library.xml"
        r = subprocess.run(["kiwix-manage", str(lib), "add", str(path)], capture_output=True)
        if r.returncode != 0:
            return None
        book = ET.parse(lib).getroot().find("book")
        return dict(book.attrib) if book is not None else None


def real_check(scheme):
    """check(path, kind) with the upload checks: Kiwix for books, pmtiles.check for maps,
    langfiles for translation models and dictionaries."""
    import langfiles  # noqa: PLC0415 — only the real run needs them
    import pmtiles  # noqa: PLC0415

    def check(path, kind):
        if kind == "wiki":
            book = kiwix_book(path)
            if book is None:
                return {"ok": False, "reason": "not a readable wiki book", "date": None}
            return {"ok": True, "reason": None, "date": book.get("date") or None}
        try:
            if kind == "maps":
                pmtiles.check(path, scheme)
            elif kind == "translate":
                langfiles.validate_model(path, langfiles.translate_name(path.name))
            else:
                langfiles.check_dict(path)
        except Refused as e:
            return {"ok": False, "reason": str(e), "date": None}
        mtime = time.gmtime(path.stat().st_mtime)  # no standard date in these formats
        return {"ok": True, "reason": None, "date": time.strftime("%Y-%m-%dT%H:%M:%S", mtime)}

    return check


class CheckCache:
    """Wraps check(): remembers results by (real path, size, mtime), saved as JSON.

    Checking a big book means Kiwix opening it; at boot only new or changed files are.
    """

    def __init__(self, path, check):
        self.path = Path(path)
        self.check = check
        try:
            self.old = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.old = {}
        self.new = {}  # only what was looked at this run is kept

    def __call__(self, path, kind):
        st = path.stat()
        key = f"{os.path.realpath(path)}|{st.st_size}|{st.st_mtime_ns}"
        result = self.old.get(key) or self.check(path, kind)
        self.new[key] = result
        return result

    def save(self):
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        tmp.write_text(json.dumps(self.new))
        os.replace(tmp, self.path)


# --- the index ------------------------------------------------------------------------


def _readable(path, bits):
    """Add read (and for folders, enter) rights for everyone; exFAT/NTFS refuse — fine, their
    mount options already make everything readable."""
    try:
        mode = path.stat().st_mode
        if mode & bits != bits:
            path.chmod(mode | bits)
    except OSError:
        pass


def _readable_tree(folder):
    """A media folder and everything in it readable for all (Jellyfin runs unprivileged);
    links inside it are not followed (the way down to it is checked by _behind_link)."""
    _readable(folder, 0o555)
    for top, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(top, d))]
        for d in dirs:
            _readable(Path(top) / d, 0o555)
        for f in files:
            if not os.path.islink(os.path.join(top, f)):
                _readable(Path(top) / f, 0o444)


def _behind_link(e):
    """A media item whose way from its location's tree down has become a link since the scan
    (a drive is anyone's): never opened up, linked or moved."""
    if e["kind"] != "media":
        return False
    root = e["path"].parents[e["name"].count("/") + 1]  # movies/X → X, movies, media → the tree
    return media.linked(root, e["path"])


def _open_up(e):
    """Make an in-use entry reachable for the unprivileged services: the item itself and the
    folders above it, on a drive up to and including the drive's root."""
    if e["kind"] == "media":
        depth = e["name"].count("/") + 1  # movies/X → X, movies, media
        _readable_tree(e["path"])
    else:
        depth = 1
        _readable(e["path"], 0o444)
    parents = e["path"].parents
    top = depth + 1 if e["location"] != "device" else depth - 1  # drive: + survival-kit/, its root
    for n in range(0, top + 1):
        _readable(parents[n], 0o555)


def build_index(entries_by_kind, library):
    """Swap `library` (a symlink) to a fresh folder of links to the in-use copies."""
    library = Path(library)
    parent = library.parent
    new = parent / f".library-{time.time_ns()}"
    for kind, entries in entries_by_kind.items():
        (new / kind).mkdir(parents=True)
        if kind == "media":  # Jellyfin refuses a library whose folder is missing
            for top in media.TOPS:
                (new / kind / top).mkdir()
        for e in entries:
            if e["status"] == "in_use" and not _behind_link(e):
                # kiwix-serve, nginx and Jellyfin run unprivileged: they must reach it
                _open_up(e)
                link = new / kind / e["name"]
                link.parent.mkdir(parents=True, exist_ok=True)  # media: movies/, shows/<series>/
                os.symlink(e["path"], link)
    new.chmod(0o755)
    if library.is_dir() and not library.is_symlink():
        shutil.rmtree(library)  # a plain folder from before: replaced once
    link = parent / f".library-link-{time.time_ns()}"
    os.symlink(new.name, link)
    os.replace(link, library)  # atomic: readers see the old index or the new one
    for old in parent.glob(".library-*"):
        if old != new and old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)


# --- auto-resolve ---------------------------------------------------------------------


def set_aside(loc, entries, today, root):
    """Move loc's invalid and duplicate files to root/<today>/<kind>/ — never delete.

    root is on the same filesystem as the location (a rename, no copy). A name already
    there gets -1, -2, … Media folders keep their place in the layout
    (root/<today>/media/movies/<name>). Returns the file (or folder) names moved.
    """
    moved = []
    for e in entries:
        if e["location"] != loc.id or e["status"] not in ("invalid", "duplicate") or _behind_link(e):
            continue
        day = Path(root) / today / e["kind"]
        if e["kind"] == "media":
            day = day / e["name"].rpartition("/")[0]  # movies, shows/<series>, music
            stem, dot, ext = e["file"], "", ""
        else:
            stem, dot, ext = e["file"].rpartition(".")
        day.mkdir(parents=True, exist_ok=True)
        dest, n = day / e["file"], 0
        while dest.exists():
            n += 1
            dest = day / f"{stem}-{n}{dot}{ext}"
        os.rename(e["path"], dest)
        moved.append(e["file"])
    return moved


# --- the locations right now ----------------------------------------------------------


def _json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def drive_present(uuid, target, by_uuid=Path("/dev/disk/by-uuid")):
    """Is the drive here right now — plugged in, and our mount in place? (The last mount
    run's state can't tell: after a pull-out the kernel keeps a dead mount.)"""
    return (Path(by_uuid) / uuid).exists() and os.path.ismount(target)


def current_locations(data_dir, drives_dir, registry_file, drive_state_file, present=drive_present):
    """This device, then every added drive that is usable now, in the order they were added."""
    locs = [Location(id="device", name=DEVICE_NAME, root=Path(data_dir), order=0)]
    state = _json(drive_state_file, {})
    drives = _json(registry_file, [])
    for n, d in enumerate(drives if isinstance(drives, list) else [], start=1):
        if state.get(d["uuid"], {}).get("mounted") and present(d["uuid"], Path(drives_dir) / d["uuid"]):
            locs.append(Location(id=d["uuid"], name=d["name"], root=Path(drives_dir) / d["uuid"] / "survival-kit", order=n))
    return locs


def _state_entry(e):
    keep = ("name", "file", "size", "mtime", "location", "status", "reason", "date")
    return {k: e[k] for k in keep} | {"path": str(e["path"])} | ({"type": e["type"]} if "type" in e else {})


def _post(url, headers):
    req = urllib.request.Request(url, data=b"", headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=5).close()


def notify_media(key_file, url, post=_post):
    """Ask Jellyfin to rescan its libraries with the box's key (best effort: no key — the
    owner set Jellyfin up by hand — or Jellyfin down → False, never an error)."""
    if not key_file or not url:
        return False
    try:
        key = Path(key_file).read_text().strip()
    except OSError:
        return False
    try:
        post(f"{url}/Library/Refresh", {"Authorization": f'MediaBrowser Token="{key}"'})
    except (OSError, ValueError) as err:
        print(f"library: Jellyfin rescan not asked ({err})", file=sys.stderr, flush=True)
        return False
    return True


def write_state(entries_by_kind, path):
    """The library's result for the content manager: {kind: [entry]} as JSON, atomically."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps({k: [_state_entry(e) for e in v] for k, v in entries_by_kind.items()}))
    tmp.chmod(0o644)
    os.replace(tmp, path)


class Places:
    """The locations as the content manager sees them, and the library's last result.

    usage(path) → (total, free) bytes of the filesystem holding path.
    """

    def __init__(self, data_dir, drives_dir, registry_file, drive_state_file, state_file, setaside_dir, usage=None,
                 present=drive_present):
        self.data_dir = Path(data_dir)
        self.drives_dir = Path(drives_dir)
        self.registry_file = registry_file
        self.drive_state_file = drive_state_file
        self.state_file = Path(state_file)
        self.setaside_dir = Path(setaside_dir)
        self.usage = usage or (lambda p: (shutil.disk_usage(p).total, shutil.disk_usage(p).free))
        self.present = present

    def all(self):
        return current_locations(self.data_dir, self.drives_dir, self.registry_file, self.drive_state_file, self.present)

    def get(self, id):
        for loc in self.all():
            if loc.id == id:
                return loc
        raise Refused("that drive is not connected")

    def entries(self, kind):
        """The library's entries of one kind, with path as a Path and kind set."""
        items = _json(self.state_file, {}).get(kind, [])
        return [e | {"path": Path(e["path"]), "kind": kind} for e in items]

    def disk(self, loc):
        return self.usage(loc.root)

    def setaside_root(self, loc):
        """Where auto-resolve moves files: the same filesystem as the location."""
        return self.setaside_dir if loc.id == "device" else loc.root.parent / "survival-kit-set-aside"


def main():
    env = os.environ
    ensure_tree(env["DATA_DIR"], DEVICE_NAME)
    locs = current_locations(env["DATA_DIR"], env["DRIVES_DIR"], env["REGISTRY"], env["DRIVE_STATE"])
    check = CheckCache(env["CACHE_FILE"], real_check(int(env.get("MAP_SCHEME", "4"))))
    protected = set(env.get("PROTECTED", "").split())
    entries = {kind: resolve(locs, kind, check, protected) for kind in KINDS_ALL}
    build_index(entries, env["LIBRARY_DIR"])
    check.save()
    write_state(entries, env["STATE_FILE"])
    notify_media(env.get("MEDIA_KEY_FILE"), env.get("MEDIA_URL"))
    for kind, v in entries.items():
        bad = [e for e in v if e["status"] != "in_use"]
        print(f"library: {kind}: {len(v) - len(bad)} in use, {len(bad)} not in use", flush=True)
    # reload the wiki's catalog; no-op at boot (kiwix-library runs after this unit)
    subprocess.run(["systemctl", "--no-block", "try-restart", "kiwix-library.service"], check=False)


if __name__ == "__main__":
    sys.exit(main())
