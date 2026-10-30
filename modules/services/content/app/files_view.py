"""Files (https://files.deck) — each person's space, built from bind mounts (ADR-0006 amendment).

File Browser shows /var/lib/survival-kit-files/view; signing up creates view/users/<account>/.
That folder holds one folder per location (this device, each connected added drive) bound
read-write to <location>/files/<account>, and Library/ with the box's books and maps bound
read-only. Bind mounts, not symlinks: File Browser refuses links that leave a person's space.
Run as a program (survival-kit-files-view.service, at boot, after a sign-up, after every
drive change): bring the mounts in line with the accounts and locations now. Standard
library only.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

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
