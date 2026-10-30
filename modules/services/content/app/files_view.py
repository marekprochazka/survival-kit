"""Files (https://files.deck) — each person's space, built from bind mounts (ADR-0006 amendment).

File Browser shows /var/lib/survival-kit-files/view; signing up creates view/users/<account>/.
That folder holds one folder per location (this device, each connected added drive) bound
read-write to <location>/files/<account>, and Library/ with the box's books and maps bound
read-only. Bind mounts, not symlinks: File Browser refuses links that leave a person's space.
Run as a program (survival-kit-files-view.service, at boot, after a sign-up, after every
drive change): bring the mounts in line with the accounts and locations now. Standard
library only.
"""

import json
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path

from drives import parse_mounts, write_json
from library import current_locations

RESERVED = ("Library", "Built-in", "This device")
KINDS = ("wiki", "maps")


# --- the layout -----------------------------------------------------------------------


def _safe(name):
    """A drive name as one folder name: no slashes or control characters, not hidden."""
    name = re.sub(r"[/\\\x00-\x1f]", "-", name).strip().lstrip(".").strip()
    return name or "Drive"


def folder_names(locs):
    """Location id → its folder name in a space: this device, then each drive by add order,
    unique without regard to case (a later drive gets " (2)", " (3)", …)."""
    taken = {r.lower() for r in RESERVED}
    names = {}
    for loc in sorted(locs, key=lambda loc: loc.order):
        if loc.id == "device":
            names[loc.id] = "This device"
            continue
        base = name = _safe(loc.name)
        n = 1
        while name.lower() in taken:
            n += 1
            name = f"{base} ({n})"
        taken.add(name.lower())
        names[loc.id] = name
    return names


def wanted(view, homes, locs, builtins):
    """Every mount the spaces need: {target: (source, read_only)}, absolute paths as strings.

    builtins: kind → the folder of the box's own files of that kind (links), or None.
    """
    names = folder_names(locs)
    want = {}
    for h in homes:
        home = Path(view) / "users" / h
        for loc in locs:
            want[str(home / names[loc.id])] = (str(loc.root / "files" / h), False)
            for kind in KINDS:
                want[str(home / "Library" / names[loc.id] / kind)] = (str(loc.root / kind), True)
        for kind in KINDS:
            if builtins.get(kind) is None:
                continue
            for p in sorted(Path(builtins[kind]).iterdir()):
                real = os.path.realpath(p)
                if not p.name.startswith(".") and os.path.isfile(real):
                    want[str(home / "Library/Built-in" / kind / p.name)] = (real, True)
    return want


def homes(view):
    """The accounts with a space: the folders File Browser made in view/users at sign-up."""
    users = Path(view) / "users"
    if not users.is_dir():
        return []
    return sorted(p.name for p in users.iterdir() if p.is_dir() and not p.name.startswith("."))


def _set(path, mode, owner):
    """Mode and owner, each only when different: the path unit watches view/users, and a run
    that changes something there would start itself again. Errors are ignored (exFAT/NTFS have
    no owners or modes; the mount options give them)."""
    st = path.stat()
    if (st.st_uid, st.st_gid) != owner:
        try:
            os.chown(path, *owner)
        except OSError:
            pass
    if st.st_mode & 0o7777 != mode:
        try:
            path.chmod(mode)
        except OSError:
            pass


def prepare(view, homes, locs, owner):
    """Each space's top folder: root's, so nothing can be dropped there (File Browser gets 403);
    each person's folder on every location: <loc>/files/<account>, File Browser's (owner)."""
    for h in homes:
        _set(Path(view) / "users" / h, 0o755, (0, 0))
        for loc in locs:
            folder = loc.root / "files" / h
            try:
                folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                _set(folder, 0o700, owner)
            except OSError as e:  # a drive gone bad: its folder is left out
                print(f"files: {folder}: {e.strerror or e}", file=sys.stderr, flush=True)


# --- the mounts -----------------------------------------------------------------------


def _try(run, args):
    try:
        run(args)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"files: {' '.join(args)}: {_error(e)}", file=sys.stderr, flush=True)


def _error(e):
    if isinstance(e, subprocess.CalledProcessError):
        return (e.stderr or "").strip() or f"{e.cmd[0]} failed"
    return e.strerror or str(e)


def _depth(target):
    return len(Path(target).parts)


def _remove_mount_point(target):
    """An empty folder or file left by a mount; inside Library/ also its emptied parents."""
    p = Path(target)
    try:
        if p.is_dir():
            p.rmdir()
        elif p.is_file() and p.stat().st_size == 0:
            p.unlink()
        else:
            return
    except OSError:
        return
    if "Library" not in p.parts:
        return
    for parent in p.parents:
        if parent.name == "Library":
            return
        try:
            parent.rmdir()
        except OSError:
            return


def reconcile(want, had, mounted, run, same):
    """Bring the mounts from `had` to `want`; returns what is mounted afterwards.

    had: the last run's result (values may be lists, from JSON). mounted: the targets the
    kernel has mounted now. same(target, source): the target is a live bind of the source
    (False after a drive was pulled out and plugged back: the old bind is dead).
    """
    now = {}
    for t in sorted(had, key=_depth, reverse=True):  # deepest first
        entry = tuple(had[t])
        if want.get(t) == entry and t in mounted and same(t, entry[0]):
            now[t] = entry
            continue
        if t in mounted:
            _try(run, ["umount", "-l", t])
        _remove_mount_point(t)
    for t in sorted(want, key=_depth):  # parents first
        if t in now:
            continue
        source, read_only = want[t]
        try:
            if os.path.isfile(source):
                Path(t).parent.mkdir(parents=True, exist_ok=True)
                Path(t).touch(exist_ok=True)
            else:
                Path(t).mkdir(parents=True, exist_ok=True)
            run(["mount", "--bind", *(["-o", "ro"] if read_only else []), source, t])
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"files: {t}: can't mount {source}: {_error(e)}", file=sys.stderr, flush=True)
            continue
        now[t] = (source, read_only)
    return now


def _same(target, source):
    try:
        a, b = os.stat(target), os.stat(source)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def main():
    env = os.environ
    view = Path(env["VIEW_DIR"])
    locs = current_locations(env["DATA_DIR"], env["DRIVES_DIR"], env["REGISTRY"], env["DRIVE_STATE"])
    owner = pwd.getpwnam(env["OWNER"])
    accounts = homes(view)
    prepare(view, accounts, locs, (owner.pw_uid, owner.pw_gid))
    builtins = {"wiki": env.get("BUILTIN_WIKI") or None, "maps": env.get("BUILTIN_MAPS") or None}
    want = wanted(view, accounts, locs, builtins)
    try:
        had = json.loads(Path(env["VIEW_STATE"]).read_text())
    except (OSError, ValueError):
        had = {}
    mounted = {t for _, t in parse_mounts(Path("/proc/self/mounts").read_text())}

    def run(args):
        subprocess.run(args, check=True, capture_output=True, text=True)

    now = reconcile(want, had if isinstance(had, dict) else {}, mounted, run, _same)
    write_json(env["VIEW_STATE"], now)
    print(f"files: {len(accounts)} spaces, {len(locs)} locations, {len(now)} of {len(want)} mounts", flush=True)


if __name__ == "__main__":
    sys.exit(main())
