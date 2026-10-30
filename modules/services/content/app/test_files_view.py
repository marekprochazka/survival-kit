"""Unit tests for files_view.py — the layout of each person's space in Files (no VM)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import files_view
from locations import Location


def device(root):
    return Location(id="device", name="This device", root=Path(root), order=0)


def drive(uuid, name, root, order=1):
    return Location(id=uuid, name=name, root=Path(root), order=order)


class FolderNamesTest(unittest.TestCase):
    def test_folder_names_device_and_drives(self):
        locs = [device("/d"), drive("u1", "Big", "/x")]
        self.assertEqual(files_view.folder_names(locs), {"device": "This device", "u1": "Big"})

    def test_folder_names_unsafe_chars(self):
        locs = [device("/d"), drive("u1", "a/b", "/x", 1), drive("u2", ".hidden", "/y", 2), drive("u3", "  ", "/z", 3)]
        names = files_view.folder_names(locs)
        self.assertEqual((names["u1"], names["u2"], names["u3"]), ("a-b", "hidden", "Drive"))

    def test_folder_names_reserved_and_duplicates(self):
        locs = [device("/d"), drive("u1", "Library", "/x", 1), drive("u2", "Big", "/y", 2), drive("u3", "big", "/z", 3)]
        names = files_view.folder_names(locs)
        self.assertEqual((names["u1"], names["u2"], names["u3"]), ("Library (2)", "Big", "big (2)"))


class WantedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.view, self.data, self.tree = t / "view", t / "data", t / "drives/u1/survival-kit"
        self.locs = [device(self.data), drive("u1", "Big", self.tree)]
        self.home = self.view / "users/anna@files.deck"

    def want(self, builtins=None):
        return files_view.wanted(self.view, ["anna@files.deck"], self.locs, builtins or {"wiki": None, "maps": None})

    def test_wanted_personal_folders_rw(self):
        w = self.want()
        self.assertEqual(w[str(self.home / "This device")], (str(self.data / "files/anna@files.deck"), False))
        self.assertEqual(w[str(self.home / "Big")], (str(self.tree / "files/anna@files.deck"), False))

    def test_wanted_library_read_only(self):
        w = self.want()
        self.assertEqual(w[str(self.home / "Library/This device/wiki")], (str(self.data / "wiki"), True))
        self.assertEqual(w[str(self.home / "Library/Big/maps")], (str(self.tree / "maps"), True))

    def test_wanted_builtins_per_file(self):
        store, farm = Path(self.tmp.name) / "store", Path(self.tmp.name) / "farm"
        store.mkdir()
        farm.mkdir()
        (store / "a.zim").write_text("book")
        (farm / "a.zim").symlink_to(store / "a.zim")
        w = self.want({"wiki": farm, "maps": None})
        self.assertEqual(w[str(self.home / "Library/Built-in/wiki/a.zim")], (str(store / "a.zim"), True))
        self.assertFalse([t for t in w if "Built-in/maps" in t])


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.src = t / "src"
        self.src.mkdir()
        (self.src / "book.zim").write_text("book")
        self.home = t / "view/users/anna"
        self.calls = []
        self.fail = set()

    def run_(self, args):
        if args[-1] in self.fail:
            raise subprocess.CalledProcessError(32, args, stderr="mount: failed")
        self.calls.append(args)

    def want(self):
        return {
            str(self.home / "This device"): (str(self.src), False),
            str(self.home / "Library/This device/wiki"): (str(self.src), True),
            str(self.home / "Library/Built-in/wiki/book.zim"): (str(self.src / "book.zim"), True),
        }

    def reconcile(self, want, had, mounted, same=lambda t, s: True):
        return files_view.reconcile(want, had, mounted, self.run_, same)

    def test_reconcile_mounts_new(self):
        want = self.want()
        got = self.reconcile(want, {}, set())
        self.assertEqual(got, want)
        self.assertEqual(self.calls, [
            ["mount", "--bind", str(self.src), str(self.home / "This device")],
            ["mount", "--bind", "-o", "ro", str(self.src), str(self.home / "Library/This device/wiki")],
            ["mount", "--bind", "-o", "ro", str(self.src / "book.zim"), str(self.home / "Library/Built-in/wiki/book.zim")],
        ])
        self.assertTrue((self.home / "Library/This device/wiki").is_dir())
        self.assertTrue((self.home / "Library/Built-in/wiki/book.zim").is_file())

    def test_reconcile_keeps_live(self):
        want = self.want()
        got = self.reconcile(want, dict(want), set(want))
        self.assertEqual(got, want)
        self.assertEqual(self.calls, [])

    def test_reconcile_removes_unwanted(self):
        want = self.want()
        big = {str(self.home / "Big"): (str(self.src), False),
               str(self.home / "Library/Big/wiki"): (str(self.src), True)}
        for t in big:
            Path(t).mkdir(parents=True)
        got = self.reconcile(want, want | big, set(want) | set(big))
        self.assertEqual(got, want)
        self.assertEqual(self.calls, [["umount", "-l", str(self.home / "Library/Big/wiki")],
                                      ["umount", "-l", str(self.home / "Big")]])
        self.assertFalse((self.home / "Big").exists())
        self.assertFalse((self.home / "Library/Big").exists())  # its empty parent too
        self.assertTrue((self.home / "Library").is_dir())

    def test_reconcile_rebinds_stale_mount(self):
        want = self.want()
        stale = str(self.home / "This device")
        got = self.reconcile(want, dict(want), set(want), same=lambda t, s: t != stale)
        self.assertEqual(got, want)
        self.assertEqual(self.calls, [["umount", "-l", stale], ["mount", "--bind", str(self.src), stale]])

    def test_reconcile_failed_mount_left_out(self):
        want = self.want()
        bad = str(self.home / "Library/This device/wiki")
        self.fail.add(bad)
        got = self.reconcile(want, {}, set())
        self.assertNotIn(bad, got)
        self.assertEqual(set(got), set(want) - {bad})

    def test_reconcile_state_from_json_lists(self):
        """The state file holds lists; a run after a restart must still see them as unchanged."""
        want = self.want()
        had = {t: list(v) for t, v in want.items()}
        self.assertEqual(self.reconcile(want, had, set(want)), want)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
