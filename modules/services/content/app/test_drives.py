"""Unit tests for drives.py — finding drives, filesystem rules, the registry, mounting (no VM)."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import drives
from content import Refused

OURS = Path("/var/lib/survival-kit/drives")


def dev(name, type="part", fstype=None, uuid=None, label=None, size=10**9, model=None, mounts=(None,), children=()):
    d = {"name": name, "path": f"/dev/{name}", "uuid": uuid, "fstype": fstype, "label": label,
         "size": size, "model": model, "type": type, "mountpoints": list(mounts)}
    if children:
        d["children"] = list(children)
    return d


# the notebook's own disk (/ and /boot on it, plus a free partition), a USB disk with two
# partitions, a FAT32 stick, a LUKS drive, a BitLocker drive, a DVD and a swap-only disk
LSBLK = {
    "blockdevices": [
        dev("sda", "disk", model="SSD", children=[
            dev("sda1", fstype="vfat", uuid="AAAA-0001", mounts=["/boot"]),
            dev("sda2", fstype="ext4", uuid="sys-root", mounts=["/"]),
            dev("sda3", fstype="ext4", uuid="sys-free"),
        ]),
        dev("sdb", "disk", model="Big USB", children=[
            dev("sdb1", fstype="ext4", uuid="u-ext4", label="BIG", size=2 * 10**12),
            dev("sdb2", fstype="exfat", uuid="u-exfat", mounts=["/run/media/deck/PHOTOS"]),
        ]),
        dev("sdc", "disk", model="Stick", fstype="vfat", uuid="u-fat", label="STICK"),
        dev("sdd", "disk", children=[dev("sdd1", fstype="crypto_LUKS", uuid="u-luks")]),
        dev("sde", "disk", children=[dev("sde1", fstype="BitLocker", uuid="u-bl")]),
        dev("sr0", "rom", fstype="iso9660", uuid="2026-10-27-12-00-00-00", label="MAPS"),
        dev("sdf", "disk", children=[dev("sdf1", fstype="swap", uuid="u-swap")]),
        dev("sdg", "disk", children=[dev("sdg1", fstype="ntfs", uuid="u-ntfs", mounts=[str(OURS / "u-ntfs")])]),
    ]
}


class Candidates(unittest.TestCase):
    def setUp(self):
        self.found = {c["uuid"]: c for c in drives.candidates(LSBLK, OURS)}

    def test_candidates_excludes_system_disk(self):
        for uuid in ["sys-root", "sys-free", "AAAA-0001"]:
            self.assertNotIn(uuid, self.found)

    def test_candidates_marks_desktop_mount(self):
        self.assertTrue(self.found["u-exfat"]["desktop"])
        self.assertFalse(self.found["u-ext4"]["desktop"])
        self.assertEqual(self.found["u-ext4"]["label"], "BIG")
        self.assertEqual(self.found["u-ext4"]["model"], "Big USB")  # from the disk
        self.assertEqual(self.found["u-ext4"]["size"], 2 * 10**12)

    def test_candidates_include_our_own_mounts(self):
        self.assertIn("u-ntfs", self.found)  # already added: still a drive, not a system disk

    def test_candidates_refusals(self):
        self.assertEqual(self.found["u-fat"]["refusal"], "FAT32 can't hold files over 4 GB — use exFAT, NTFS or ext4")
        self.assertEqual(self.found["u-luks"]["refusal"], "encrypted drives are not supported yet")
        self.assertEqual(self.found["u-bl"]["refusal"], "encrypted drives are not supported yet")
        self.assertIsNone(self.found["u-ext4"]["refusal"])

    def test_candidates_hides_iso_and_swap(self):
        self.assertNotIn("2026-10-27-12-00-00-00", self.found)
        self.assertNotIn("u-swap", self.found)


class Filesystems(unittest.TestCase):
    def test_mount_args_per_fstype(self):
        self.assertEqual(drives.mount_args("ext4"), ["-t", "ext4", "-o", "noatime"])
        self.assertEqual(drives.mount_args("btrfs"), ["-t", "btrfs", "-o", "noatime"])
        owned = "uid=0,gid=0,dmask=022,fmask=133,noatime"
        self.assertEqual(drives.mount_args("exfat"), ["-t", "exfat", "-o", owned])
        self.assertEqual(drives.mount_args("ntfs"), ["-t", "ntfs3", "-o", owned])
        with self.assertRaises(Refused):
            drives.mount_args("vfat")


class Registry(unittest.TestCase):
    def setUp(self):
        self.reg = drives.Registry(Path(tempfile.mkdtemp()) / "drives.json")

    def test_empty_when_missing(self):
        self.assertEqual(self.reg.drives(), [])

    def test_add_keeps_order(self):
        self.reg.add("u-1", "ext4", "Big", "2026-10-30")
        self.reg.add("u-2", "exfat", "Photos", "2026-10-31")
        self.assertEqual([d["uuid"] for d in self.reg.drives()], ["u-1", "u-2"])
        self.assertEqual(self.reg.drives()[0], {"uuid": "u-1", "fstype": "ext4", "name": "Big", "added": "2026-10-30"})

    def test_add_same_uuid_refused(self):
        self.reg.add("u-1", "ext4", "Big", "2026-10-30")
        with self.assertRaises(Refused) as cm:
            self.reg.add("u-1", "ext4", "Clone", "2026-10-31")
        self.assertIn("already added", str(cm.exception))

    def test_forget(self):
        self.reg.add("u-1", "ext4", "Big", "2026-10-30")
        self.reg.forget("u-1")
        self.assertEqual(self.reg.drives(), [])
        with self.assertRaises(Refused) as cm:
            self.reg.forget("u-1")
        self.assertEqual(cm.exception.status, 404)


class Udev(unittest.TestCase):
    def test_udev_rules(self):
        rules = drives.udev_rules(["u-1", "u-2"])
        self.assertIn('ENV{ID_FS_UUID}=="u-1", ENV{UDISKS_IGNORE}="1"', rules)
        self.assertIn('ENV{ID_FS_UUID}=="u-2", ENV{UDISKS_IGNORE}="1"', rules)


class MountAll(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.by_uuid = self.tmp / "by-uuid"
        self.by_uuid.mkdir()
        self.dir = self.tmp / "drives"
        self.rules = self.tmp / "rules" / "90-survival-kit-drives.rules"
        self.calls = []
        self.mounted = []  # (source, target)

    def plug(self, uuid):
        (self.tmp / uuid).write_bytes(b"")  # stands in for /dev/sdX
        (self.by_uuid / uuid).symlink_to(self.tmp / uuid)
        return str(self.tmp / uuid)

    def fake_run(self, args):
        self.calls.append(args)

    def mount_all(self, recorded):
        return drives.mount_all(recorded, self.dir, self.fake_run, lambda: list(self.mounted), self.by_uuid, self.rules)

    def drive(self, uuid, fstype="ext4", name="D"):
        return {"uuid": uuid, "fstype": fstype, "name": name, "added": "2026-10-30"}

    def test_mount_all_one_bad_drive_others_mounted(self):
        src = self.plug("u-2")
        state = self.mount_all([self.drive("u-1"), self.drive("u-2", "exfat", "Photos")])
        self.assertEqual(state["u-1"], {"mounted": False, "error": "not connected"})
        self.assertEqual(state["u-2"], {"mounted": True, "error": None})
        self.assertIn(["mount", *drives.mount_args("exfat"), src, str(self.dir / "u-2")], self.calls)
        marker = json.loads((self.dir / "u-2" / "survival-kit" / "survival-kit.json").read_text())
        self.assertEqual(marker["name"], "Photos")

    def test_mount_all_skips_mount_when_already_ours(self):
        src = self.plug("u-1")
        self.mounted.append((src, str(self.dir / "u-1")))
        state = self.mount_all([self.drive("u-1")])
        self.assertTrue(state["u-1"]["mounted"])
        self.assertFalse([c for c in self.calls if c[0] == "mount"])

    def test_mount_all_future_marker_reported_not_overwritten(self):
        self.plug("u-1")
        tree = self.dir / "u-1" / "survival-kit"
        tree.mkdir(parents=True)
        (tree / "survival-kit.json").write_text('{"format": 9, "name": "Future"}')
        state = self.mount_all([self.drive("u-1")])
        self.assertFalse(state["u-1"]["mounted"])
        self.assertIn("newer survival-kit", state["u-1"]["error"])
        self.assertEqual((tree / "survival-kit.json").read_text(), '{"format": 9, "name": "Future"}')

    def test_mount_all_unmounts_forgotten(self):
        self.mounted.append(("/dev/sdz1", str(self.dir / "u-old")))
        self.mount_all([])
        self.assertIn(["umount", str(self.dir / "u-old")], self.calls)

    def test_mount_all_takes_over_desktop_mount(self):
        src = self.plug("u-1")
        self.mounted.append((src, "/run/media/deck/BIG"))
        self.mount_all([self.drive("u-1")])
        umount = self.calls.index(["umount", "/run/media/deck/BIG"])
        mount = next(i for i, c in enumerate(self.calls) if c[0] == "mount")
        self.assertLess(umount, mount)

    def test_mount_all_refuses_other_mounts(self):
        src = self.plug("u-1")
        self.mounted.append((src, "/srv/elsewhere"))
        state = self.mount_all([self.drive("u-1")])
        self.assertFalse(state["u-1"]["mounted"])
        self.assertIn("/srv/elsewhere", state["u-1"]["error"])
        self.assertFalse([c for c in self.calls if c[0] in ("mount", "umount")])

    def test_mount_all_failed_mount_reported(self):
        self.plug("u-1")

        def run(args):
            if args[0] == "mount":
                raise subprocess.CalledProcessError(32, args, stderr="mount: wrong fs type\n")
            self.calls.append(args)

        state = drives.mount_all([self.drive("u-1")], self.dir, run, lambda: [], self.by_uuid, self.rules)
        self.assertEqual(state["u-1"], {"mounted": False, "error": "mount: wrong fs type"})

    def test_mount_all_writes_udev_rules_and_reloads(self):
        self.plug("u-1")
        self.mount_all([self.drive("u-1"), self.drive("u-2")])
        self.assertIn('"u-1"', self.rules.read_text())
        self.assertIn('"u-2"', self.rules.read_text())  # hidden even while away
        self.assertIn(["udevadm", "control", "--reload"], self.calls)
        self.assertIn(["udevadm", "trigger", "--action=change", "--subsystem-match=block"], self.calls)


class Mounts(unittest.TestCase):
    def test_parse_mounts_unescapes_spaces(self):
        text = "/dev/sdb1 /run/media/deck/MY\\040DISK exfat rw 0 0\nproc /proc proc rw 0 0\n"
        self.assertIn(("/dev/sdb1", "/run/media/deck/MY DISK"), drives.parse_mounts(text))


if __name__ == "__main__":
    unittest.main()
