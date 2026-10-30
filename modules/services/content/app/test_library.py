"""Unit tests for library.py — checks, newer-wins, the symlink index, set-aside (no VM)."""

import json
import os
import tempfile
import unittest
from pathlib import Path

import library
import locations
from locations import Location

PROTECTED = {"survival-kit", "survival-kit-dev"}


def fake_check(dates, bad=()):
    """check(path, kind): file content b"bad" or a name in `bad` → invalid; date from `dates` by path."""
    calls = []

    def check(path, kind):
        calls.append(path)
        if path.read_bytes() == b"bad" or path.name in bad:
            return {"ok": False, "reason": "not a readable wiki book", "date": None}
        return {"ok": True, "reason": None, "date": dates.get(str(path))}

    check.calls = calls
    return check


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.device = self.loc("device", 0)
        self.drive = self.loc("u-1", 1)

    def loc(self, id, order):
        root = self.tmp / id
        locations.ensure_tree(root, id)
        return Location(id=id, name=id, root=root, order=order)

    def put(self, loc, kind, name, data=b"x"):
        p = loc.root / kind / name
        p.write_bytes(data)
        return p

    def status(self, entries):
        return {(e["location"], e["name"]): e["status"] for e in entries}


class Resolve(Base):
    def test_newer_wins_across_locations(self):
        old = self.put(self.device, "wiki", "book.zim")
        new = self.put(self.drive, "wiki", "book_2025-06.zim")
        check = fake_check({str(old): "2024-01-01", str(new): "2025-06-01"})
        entries = library.resolve([self.device, self.drive], "wiki", check, PROTECTED)
        self.assertEqual(
            self.status(entries),
            {("device", "book.zim"): "duplicate", ("u-1", "book.zim"): "in_use"},
        )

    def test_tie_prefers_device_then_add_order(self):
        third = self.loc("u-2", 2)
        for loc in [third, self.drive, self.device]:
            self.put(loc, "maps", "a.pmtiles")
        entries = library.resolve([third, self.drive, self.device], "maps", fake_check({}), PROTECTED)
        self.assertEqual(
            self.status(entries),
            {("device", "a.pmtiles"): "in_use", ("u-1", "a.pmtiles"): "duplicate", ("u-2", "a.pmtiles"): "duplicate"},
        )

    def test_unknown_date_falls_back_to_order(self):
        dated = self.put(self.drive, "wiki", "b.zim")
        self.put(self.device, "wiki", "b.zim")
        entries = library.resolve([self.device, self.drive], "wiki", fake_check({str(dated): "2030-01-01"}), PROTECTED)
        self.assertEqual(self.status(entries)[("device", "b.zim")], "in_use")

    def test_invalid_marked_with_reason(self):
        self.put(self.drive, "wiki", "junk.zim", b"bad")
        [e] = library.resolve([self.drive], "wiki", fake_check({}), PROTECTED)
        self.assertEqual((e["status"], e["reason"]), ("invalid", "not a readable wiki book"))

    def test_unusable_name_invalid(self):
        self.put(self.drive, "maps", "!!!.pmtiles")
        [e] = library.resolve([self.drive], "maps", fake_check({}), PROTECTED)
        self.assertEqual(e["status"], "invalid")
        self.assertIn("can't be used", e["reason"])

    def test_protected_name_invalid(self):
        self.put(self.drive, "wiki", "survival-kit_2026-01.zim")
        check = fake_check({})
        [e] = library.resolve([self.drive], "wiki", check, PROTECTED)
        self.assertEqual(e["status"], "invalid")
        self.assertIn("manual", e["reason"])
        self.assertEqual(check.calls, [])  # not even opened

    def test_invalid_never_wins(self):
        good = self.put(self.device, "wiki", "c.zim")
        self.put(self.drive, "wiki", "c.zim", b"bad")
        entries = library.resolve([self.device, self.drive], "wiki", fake_check({str(good): "2020-01-01"}), PROTECTED)
        self.assertEqual(
            self.status(entries), {("device", "c.zim"): "in_use", ("u-1", "c.zim"): "invalid"}
        )

    def test_missing_location_skipped(self):
        gone = Location(id="u-9", name="gone", root=self.tmp / "nope", order=3)
        self.put(self.device, "wiki", "d.zim")
        entries = library.resolve([self.device, gone], "wiki", fake_check({}), PROTECTED)
        self.assertEqual(self.status(entries), {("device", "d.zim"): "in_use"})


class Index(Base):
    def build(self):
        lib = self.tmp / "library"
        wiki = library.resolve([self.device, self.drive], "wiki", fake_check({}), PROTECTED)
        maps = library.resolve([self.device, self.drive], "maps", fake_check({}), PROTECTED)
        library.build_index({"wiki": wiki, "maps": maps}, lib)
        return lib

    def test_build_index_atomic_symlinks(self):
        a = self.put(self.drive, "wiki", "a.zim")
        self.put(self.device, "wiki", "junk.zim", b"bad")
        lib = self.build()
        self.assertTrue(lib.is_symlink())
        self.assertEqual(sorted(os.listdir(lib / "wiki")), ["a.zim"])
        self.assertEqual((lib / "wiki" / "a.zim").resolve(), a.resolve())
        self.assertEqual(os.listdir(lib / "maps"), [])
        first = lib.resolve()
        self.put(self.device, "maps", "m.pmtiles")
        self.build()
        self.assertEqual(os.listdir(lib / "maps"), ["m.pmtiles"])
        self.assertFalse(first.exists())  # the previous index is gone
        self.assertEqual([p.name for p in self.tmp.glob(".library-*")], [lib.resolve().name])

    def test_build_replaces_a_plain_folder(self):
        (self.tmp / "library" / "wiki").mkdir(parents=True)
        lib = self.build()
        self.assertTrue(lib.is_symlink())

    def test_build_makes_readable(self):
        a = self.put(self.drive, "wiki", "a.zim")
        a.chmod(0o600)
        (self.drive.root / "wiki").chmod(0o700)
        self.build()
        self.assertEqual(a.stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.drive.root / "wiki").stat().st_mode & 0o777, 0o755)


class Cache(Base):
    def test_cache_reuses_until_changed(self):
        p = self.put(self.drive, "wiki", "a.zim")
        check = fake_check({})
        cached = library.CheckCache(self.tmp / "checks.json", check)
        cached(p, "wiki")
        cached.save()
        again = library.CheckCache(self.tmp / "checks.json", check)
        self.assertEqual(again(p, "wiki")["ok"], True)
        self.assertEqual(len(check.calls), 1)
        os.utime(p, (1, 1))
        again(p, "wiki")
        self.assertEqual(len(check.calls), 2)

    def test_cache_file_broken_starts_empty(self):
        (self.tmp / "checks.json").write_text("{nope")
        p = self.put(self.drive, "wiki", "a.zim")
        library.CheckCache(self.tmp / "checks.json", fake_check({}))(p, "wiki")


class SetAside(Base):
    def test_set_aside_moves_never_deletes(self):
        keep = self.put(self.device, "wiki", "e.zim")
        dup = self.put(self.drive, "wiki", "e.zim", b"dup")
        junk = self.put(self.drive, "wiki", "junk.zim", b"bad")
        entries = library.resolve([self.device, self.drive], "wiki", fake_check({}), PROTECTED)
        root = self.tmp / "set-aside"
        (root / "2026-10-30" / "wiki").mkdir(parents=True)
        (root / "2026-10-30" / "wiki" / "e.zim").write_bytes(b"earlier")
        moved = library.set_aside(self.drive, entries, "2026-10-30", root)
        self.assertEqual(sorted(moved), ["e.zim", "junk.zim"])
        self.assertFalse(dup.exists() or junk.exists())
        self.assertTrue(keep.exists())
        day = root / "2026-10-30" / "wiki"
        self.assertEqual((day / "e-1.zim").read_bytes(), b"dup")
        self.assertEqual((day / "e.zim").read_bytes(), b"earlier")
        self.assertEqual((day / "junk.zim").read_bytes(), b"bad")

    def test_set_aside_other_location_untouched(self):
        self.put(self.device, "wiki", "j.zim", b"bad")
        entries = library.resolve([self.device, self.drive], "wiki", fake_check({}), PROTECTED)
        self.assertEqual(library.set_aside(self.drive, entries, "2026-10-30", self.tmp / "sa"), [])


class Current(Base):
    def test_current_locations_mounted_drives_in_add_order(self):
        reg = self.tmp / "drives.json"
        reg.write_text(json.dumps([
            {"uuid": "u-b", "fstype": "ext4", "name": "B", "added": "2026-10-30"},
            {"uuid": "u-a", "fstype": "exfat", "name": "A", "added": "2026-10-31"},
            {"uuid": "u-c", "fstype": "ext4", "name": "C", "added": "2026-11-01"},
        ]))
        state = self.tmp / "state.json"
        state.write_text(json.dumps({"u-a": {"mounted": True, "error": None}, "u-b": {"mounted": True, "error": None},
                                     "u-c": {"mounted": False, "error": "not connected"}}))
        locs = library.current_locations(self.tmp / "data", self.tmp / "drives", reg, state)
        self.assertEqual([(l.id, l.name, l.order) for l in locs], [("device", "This device", 0), ("u-b", "B", 1), ("u-a", "A", 2)])
        self.assertEqual(locs[1].root, self.tmp / "drives" / "u-b" / "survival-kit")

    def test_current_locations_without_drive_files(self):
        locs = library.current_locations(self.tmp / "data", self.tmp / "drives", self.tmp / "none.json", self.tmp / "none2.json")
        self.assertEqual([l.id for l in locs], ["device"])


if __name__ == "__main__":
    unittest.main()
