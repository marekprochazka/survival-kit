"""Unit tests for files_view.py — the layout of each person's space in Files (no VM)."""

import os
import subprocess
import tempfile
import time
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

    def test_wanted_includes_media(self):
        w = self.want()
        self.assertEqual(w[str(self.home / "Library/This device/media")], (str(self.data / "media"), True))
        self.assertEqual(w[str(self.home / "Library/Big/media")], (str(self.tree / "media"), True))

    def test_wanted_builtins_per_file(self):
        store, farm = Path(self.tmp.name) / "store", Path(self.tmp.name) / "farm"
        store.mkdir()
        farm.mkdir()
        (store / "a.zim").write_text("book")
        (farm / "a.zim").symlink_to(store / "a.zim")
        w = self.want({"wiki": farm, "maps": None})
        self.assertEqual(w[str(self.home / "Library/Built-in/wiki/a.zim")], (str(store / "a.zim"), True))
        self.assertFalse([t for t in w if "Built-in/maps" in t])

    def test_wanted_skips_drive_with_links(self):
        """A drive's files/ (or wiki/, maps/, survival-kit/) pointing elsewhere must never be
        bound: a crafted stick could otherwise hand out e.g. /var/lib/survival-kit."""
        secret = Path(self.tmp.name) / "secret"
        (secret / "anna@files.deck").mkdir(parents=True)
        self.tree.mkdir(parents=True)
        (self.tree / "files").symlink_to(secret)
        w = self.want()
        self.assertFalse([t for t in w if "/Big" in t], w)
        self.assertIn(str(self.home / "This device"), w)

    def test_wanted_skips_linked_personal_folder(self):
        secret = Path(self.tmp.name) / "secret"
        secret.mkdir()
        (self.tree / "files").mkdir(parents=True)
        (self.tree / "files/anna@files.deck").symlink_to(secret)
        w = self.want()
        self.assertNotIn(str(self.home / "Big"), w)
        self.assertIn(str(self.home / "Library/Big/wiki"), w)


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

    def test_reconcile_removes_leftovers_after_reboot(self):
        """After a reboot nothing is mounted: a drive that is gone leaves no empty folder."""
        want = self.want()
        big = {str(self.home / "Big"): (str(self.src), False),
               str(self.home / "Library/Big/wiki"): (str(self.src), True)}
        for t in big:
            Path(t).mkdir(parents=True)
        got = self.reconcile(want, want | big, set())
        self.assertEqual(got, want)
        self.assertFalse([c for c in self.calls if c[0] == "umount"])
        self.assertFalse((self.home / "Big").exists())
        self.assertFalse((self.home / "Library/Big").exists())

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


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.view = t / "view"
        self.home = self.view / "users/anna"
        self.home.mkdir(parents=True, mode=0o700)  # as File Browser makes it at sign-up
        self.locs = [device(t / "data"), drive("u1", "Big", t / "drives/u1/survival-kit")]
        self.me = (os.getuid(), os.getgid())

    def folders(self):
        return [loc.root / "files/anna" for loc in self.locs]

    def test_prepare_makes_personal_folders(self):
        files_view.prepare(self.view, ["anna"], self.locs, self.me)
        for f in self.folders():
            self.assertTrue(f.is_dir())
            self.assertEqual(f.stat().st_mode & 0o777, 0o700)

    def test_prepare_home_not_writable(self):
        files_view.prepare(self.view, ["anna"], self.locs, self.me)
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o755)  # root-owned when run as root

    def test_prepare_second_run_changes_nothing(self):
        """The path unit watches view/users: a run that touches it again would trigger itself."""
        files_view.prepare(self.view, ["anna"], self.locs, self.me)
        before = [p.stat().st_ctime_ns for p in [self.home, *self.folders()]]
        time.sleep(0.01)
        files_view.prepare(self.view, ["anna"], self.locs, self.me)
        self.assertEqual([p.stat().st_ctime_ns for p in [self.home, *self.folders()]], before)

    @unittest.skipIf(os.getuid() == 0, "root may chown")
    def test_prepare_chown_failure_ignored(self):
        files_view.prepare(self.view, ["anna"], self.locs, (0, 0))  # like exFAT: no owners
        self.assertTrue(all(f.is_dir() for f in self.folders()))

    def test_prepare_does_not_follow_links(self):
        outside = Path(self.tmp.name) / "outside"
        (outside / "anna").mkdir(parents=True, mode=0o755)
        tree = self.locs[1].root
        tree.mkdir(parents=True)
        (tree / "files").symlink_to(outside)
        files_view.prepare(self.view, ["anna"], self.locs, self.me)
        self.assertEqual((outside / "anna").stat().st_mode & 0o777, 0o755)  # untouched
        self.assertTrue((self.locs[0].root / "files/anna").is_dir())

    def test_homes_skips_links(self):
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        (self.view / "users/evil").symlink_to(elsewhere)
        self.assertEqual(files_view.homes(self.view), ["anna"])

    def test_homes_lists_accounts(self):
        for name in ("anna@files.deck", "ben", ".tmp"):
            (self.view / "users" / name).mkdir(exist_ok=True)
        (self.view / "users/stray.txt").write_text("")
        self.assertEqual(files_view.homes(self.view), ["anna", "anna@files.deck", "ben"])


class SettleTest(unittest.TestCase):
    def test_settle_runs_again_when_inputs_changed_during_a_run(self):
        """A sign-up or drive change during a run is folded into it by systemd: run again."""
        state = {"inputs": 1, "runs": 0}

        def step():
            state["runs"] += 1
            if state["runs"] == 1:
                state["inputs"] = 2  # changed while the first run was busy

        files_view.settle(step, lambda: state["inputs"])
        self.assertEqual(state["runs"], 2)

    def test_settle_gives_up_after_five_runs(self):
        state = {"runs": 0}

        def step():
            state["runs"] += 1

        files_view.settle(step, lambda: state["runs"])  # always changing
        self.assertEqual(state["runs"], 5)


if __name__ == "__main__":
    unittest.main()
