"""Added drives (ADR-0006): finding them, the list of added ones, mounting them at boot.

The list (/var/lib/survival-kit/drives.json) is runtime data, not configuration: adding a
drive never needs a rebuild. `drives.py mount-all` (survival-kit-drives.service, at boot
and after every add/forget/reconnect) mounts each listed drive by its filesystem UUID at
/var/lib/survival-kit/drives/<uuid>; a missing or broken drive is reported, never fatal.
The box never formats a drive and touches nothing outside its survival-kit/ folder.
Standard library only.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from content import Refused
from locations import ensure_tree

# filesystems with Linux permissions; exFAT/NTFS get theirs from mount options
LINUX_FS = {"ext4", "btrfs", "xfs", "f2fs"}
OWNED = "uid=0,gid=0,dmask=022,fmask=133,noatime"  # root writes, everyone reads
ENCRYPTED = "encrypted drives are not supported yet"
REFUSED = {
    "vfat": "FAT32 can't hold files over 4 GB — use exFAT, NTFS or ext4",
    "crypto_LUKS": ENCRYPTED,
    "BitLocker": ENCRYPTED,
}
DESKTOP = "/run/media/"  # where the desktop (udisks) mounts what is opened in the file manager
LSBLK = ["lsblk", "--json", "--bytes", "-o", "NAME,PATH,UUID,FSTYPE,LABEL,SIZE,MODEL,TYPE,MOUNTPOINTS"]


# --- finding drives -------------------------------------------------------------------


def _walk(node):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _mounts(node):
    return [m for m in node.get("mountpoints") or [] if m]


def candidates(lsblk, ours):
    """The filesystems that could be added, from `lsblk --json` output.

    A disk the system uses (anything of it mounted outside the desktop's and our own
    mount folders — /, /boot, swap …) is left out entirely, free partitions included.
    Refused filesystems are listed with the reason.
    """
    ours = str(ours)

    def foreign(m):
        return not (m.startswith(DESKTOP) or m == ours or m.startswith(ours + "/"))

    found = []
    for disk in lsblk.get("blockdevices", []):
        nodes = list(_walk(disk))
        if any(foreign(m) for n in nodes for m in _mounts(n)):
            continue
        for n in nodes:
            fstype = n.get("fstype")
            if n.get("type") not in ("disk", "part") or not n.get("uuid"):
                continue
            if fstype not in LINUX_FS | {"exfat", "ntfs"} and fstype not in REFUSED:
                continue
            found.append(
                {
                    "uuid": n["uuid"],
                    "path": n["path"],
                    "label": n.get("label"),
                    "model": n.get("model") or disk.get("model"),
                    "size": n.get("size"),
                    "fstype": fstype,
                    "desktop": any(m.startswith(DESKTOP) for m in _mounts(n)),
                    "refusal": REFUSED.get(fstype),
                }
            )
    return found


def read_lsblk():
    return json.loads(subprocess.run(LSBLK, check=True, capture_output=True, text=True).stdout)


def mount_args(fstype):
    """`mount` arguments for a filesystem type."""
    if fstype in LINUX_FS:
        return ["-t", fstype, "-o", "noatime"]
    if fstype == "exfat":
        return ["-t", "exfat", "-o", OWNED]
    if fstype == "ntfs":
        return ["-t", "ntfs3", "-o", OWNED]  # the kernel's driver
    raise Refused(REFUSED.get(fstype, f"{fstype} drives are not supported"))


# --- the list of added drives ---------------------------------------------------------


class Registry:
    """drives.json: [{uuid, fstype, name, added}] in the order the drives were added."""

    def __init__(self, path):
        self.path = Path(path)

    def drives(self):
        """The list; Refused when the file is damaged (never silently treated as empty)."""
        try:
            items = json.loads(self.path.read_text())
        except FileNotFoundError:
            return []
        except ValueError as e:
            raise Refused(f"the list of added drives ({self.path}) is damaged: {e}") from e
        if not isinstance(items, list):
            raise Refused(f"the list of added drives ({self.path}) is damaged")
        return items

    def _write(self, items):
        write_json(self.path, items)

    def add(self, uuid, fstype, name, today):
        items = self.drives()
        if any(d["uuid"] == uuid for d in items):
            raise Refused("a drive with this ID is already added")
        self._write(items + [{"uuid": uuid, "fstype": fstype, "name": name, "added": today}])

    def forget(self, uuid):
        items = self.drives()
        if not any(d["uuid"] == uuid for d in items):
            raise Refused("no such drive", status=404)
        self._write([d for d in items if d["uuid"] != uuid])


def write_json(path, data):
    """Atomically (temp file + rename): readers never see half a file."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n")
    tmp.chmod(0o644)
    os.replace(tmp, path)


def udev_rules(uuids, systemctl="systemctl"):
    """Hide added drives from the desktop (no Eject/Safely remove under running services), and
    re-run the mounting when one is pulled out or plugged back in."""
    lines = ["# survival-kit: added drives (written by survival-kit-drives.service)"]
    for u in uuids:
        lines.append(f'ENV{{ID_FS_UUID}}=="{u}", ENV{{UDISKS_IGNORE}}="1"')
        lines.append(
            f'ACTION=="add|remove", SUBSYSTEM=="block", ENV{{ID_FS_UUID}}=="{u}", '
            f'RUN+="{systemctl} --no-block restart survival-kit-drives.service"'
        )
    return "\n".join(lines) + "\n"


# --- mounting -------------------------------------------------------------------------


def parse_mounts(text):
    """(source, target) pairs from /proc/self/mounts (octal escapes like \\040 undone)."""
    out = []
    for line in text.splitlines():
        parts = line.split(" ")
        if len(parts) >= 2:
            out.append(tuple(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), p) for p in parts[:2]))
    return out


def _try(run, args):
    """Housekeeping that must not stop the mounting: report and go on."""
    try:
        run(args)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"drives: {' '.join(args)}: {_error(e)}", file=sys.stderr, flush=True)


def _error(e):
    if isinstance(e, subprocess.CalledProcessError):
        return (e.stderr or "").strip() or f"{e.cmd[0]} failed"
    return str(e) if isinstance(e, Refused) else (e.strerror or str(e))


def mount_all(recorded, drives_dir, run, mounts, by_uuid, rules_file, systemctl="systemctl"):
    """Mount every recorded drive at drives_dir/<uuid>; unmount the forgotten ones.

    run(args) runs a command (raises CalledProcessError); mounts() → [(source, target)].
    Returns {uuid: {"mounted": usable now, "error": why not}} — one drive's trouble never
    stops the others.
    """
    drives_dir = Path(drives_dir)
    current = mounts()
    known = {d["uuid"] for d in recorded}
    for _, target in current:
        if Path(target).parent == drives_dir and Path(target).name not in known:
            _try(run, ["umount", target])
    state = {}
    for d in recorded:
        uuid, target = d["uuid"], drives_dir / d["uuid"]
        here = [s for s, t in current if t == str(target)]  # what is mounted at our folder now
        try:
            device = Path(by_uuid) / uuid
            if not device.exists():
                if here:  # pulled out: the kernel keeps a dead mount until it is unmounted
                    _try(run, ["umount", "-l", str(target)])
                raise Refused("not connected")
            source = os.path.realpath(device)
            if here and here[-1] != source:  # back as another device: the old mount is dead
                _try(run, ["umount", "-l", str(target)])
                here = []
            where = [t for s, t in current if s == source and t != str(target)]
            if not here:
                for t in where:
                    if not t.startswith(DESKTOP):
                        raise Refused(f"the drive is in use at {t}")
                for t in where:
                    run(["umount", t])  # opened on the desktop: taken over
                target.mkdir(parents=True, exist_ok=True)
                run(["mount", *mount_args(d["fstype"]), source, str(target)])
            ensure_tree(target / "survival-kit", d["name"])
            state[uuid] = {"mounted": True, "error": None}
        except (Refused, OSError, subprocess.CalledProcessError) as e:
            state[uuid] = {"mounted": False, "error": _error(e)}
    rules = Path(rules_file)
    rules.parent.mkdir(parents=True, exist_ok=True)
    rules.write_text(udev_rules([d["uuid"] for d in recorded], systemctl))
    _try(run, ["udevadm", "control", "--reload"])
    _try(run, ["udevadm", "trigger", "--action=change", "--subsystem-match=block"])
    return state


def main():
    env = os.environ
    if sys.argv[1:] != ["mount-all"]:
        sys.exit("usage: drives.py mount-all")

    def run(args):
        subprocess.run(args, check=True, capture_output=True, text=True)

    systemctl = env.get("SYSTEMCTL", "systemctl")
    try:
        recorded = Registry(env["REGISTRY"]).drives()
    except Refused as e:  # never unmount everything because the list can't be read
        print(f"drives: {e}", file=sys.stderr, flush=True)
        return
    # at boot a USB drive may show up a few seconds late: wait up to 10 s for missing ones
    for _ in range(10):
        if all((Path("/dev/disk/by-uuid") / d["uuid"]).exists() for d in recorded):
            break
        time.sleep(1)
    state = mount_all(
        recorded,
        env["DRIVES_DIR"],
        run,
        lambda: parse_mounts(Path("/proc/self/mounts").read_text()),
        "/dev/disk/by-uuid",
        "/run/udev/rules.d/90-survival-kit-drives.rules",
        systemctl,
    )
    out = Path(env["DRIVE_STATE"])
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, state)
    for uuid, s in state.items():
        print(f"drives: {uuid}: {'mounted' if s['mounted'] else s['error']}", flush=True)
    # rebuild the library (no-op at boot: it starts after this unit) — e.g. after a pull-out
    subprocess.run([systemctl, "--no-block", "try-restart", "survival-kit-library.service"], check=False)


if __name__ == "__main__":
    main()
