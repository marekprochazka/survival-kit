"""Unit tests for library.py — checks, newer-wins, the symlink index, set-aside (no VM)."""

import json
import os
import tempfile
import unittest
from pathlib import Path

import library
import locations
from locations import Location
from test_langfiles import make_dict, make_model

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


class Unreadable(Base):
    def test_unreadable_location_left_out(self):
        """A dead mount (EIO) or a locked folder must not stop the library."""
        self.put(self.device, "wiki", "here.zim")
        self.put(self.drive, "wiki", "far.zim")
        (self.drive.root / "wiki").chmod(0)
        self.addCleanup((self.drive.root / "wiki").chmod, 0o755)
        entries = library.resolve([self.device, self.drive], "wiki", fake_check({}), PROTECTED)
        self.assertEqual(self.status(entries), {("device", "here.zim"): "in_use"})

    def test_build_opens_the_tree_on_a_drive(self):
        a = self.put(self.drive, "wiki", "a.zim")
        self.drive.root.chmod(0o700)  # survival-kit/, made by a user with umask 077
        self.tmp.chmod(0o700)  # the drive's root
        self.addCleanup(self.tmp.chmod, 0o755)
        Index.build(self)
        self.assertEqual(self.drive.root.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.tmp.stat().st_mode & 0o777, 0o755)
        self.assertTrue(a.exists())


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
        locs = library.current_locations(self.tmp / "data", self.tmp / "drives", reg, state, present=lambda u, t: True)
        self.assertEqual([(l.id, l.name, l.order) for l in locs], [("device", "This device", 0), ("u-b", "B", 1), ("u-a", "A", 2)])
        self.assertEqual(locs[1].root, self.tmp / "drives" / "u-b" / "survival-kit")

    def test_current_locations_skips_drive_not_here_now(self):
        """A drive pulled out: the last mount run still says mounted, but it's gone."""
        reg = self.tmp / "drives.json"
        reg.write_text(json.dumps([{"uuid": "u-a", "fstype": "ext4", "name": "A", "added": "2026-10-30"}]))
        state = self.tmp / "state.json"
        state.write_text(json.dumps({"u-a": {"mounted": True, "error": None}}))
        locs = library.current_locations(self.tmp / "data", self.tmp / "drives", reg, state, present=lambda u, t: False)
        self.assertEqual([l.id for l in locs], ["device"])

    def test_drive_present_needs_device_and_mount(self):
        by_uuid = self.tmp / "by-uuid"
        by_uuid.mkdir()
        self.assertFalse(library.drive_present("u-a", self.tmp, by_uuid))  # unplugged
        (by_uuid / "u-a").write_text("")
        self.assertFalse(library.drive_present("u-a", self.tmp / "data", by_uuid))  # not a mount
        self.assertTrue(library.drive_present("u-a", Path("/"), by_uuid))

    def test_current_locations_without_drive_files(self):
        locs = library.current_locations(self.tmp / "data", self.tmp / "drives", self.tmp / "none.json", self.tmp / "none2.json")
        self.assertEqual([l.id for l in locs], ["device"])


if __name__ == "__main__":
    unittest.main()


class LanguageKinds(Base):
    def test_real_check_language_kinds(self):
        check = library.real_check(4)
        good = make_model(self.device.root / "translate" / "en_cs.argosmodel", "en", "cs")
        r = check(good, "translate")
        self.assertTrue(r["ok"], r)
        self.assertRegex(r["date"], r"^\d{4}-\d\d-\d\dT")
        wrong = make_model(self.device.root / "translate" / "de_en.argosmodel", "en", "cs")
        self.assertFalse(check(wrong, "translate")["ok"])  # the name says another pair
        broken = self.put(self.device, "translate", "fr_en.argosmodel", b"nope")
        r = check(broken, "translate")
        self.assertFalse(r["ok"])
        self.assertIn("not an Argos translation model", r["reason"])
        d = make_dict(self.device.root / "dict" / "eng-ces.dictd.tar.xz", {"house": "dum"})
        self.assertTrue(check(d, "dict")["ok"])
        self.assertFalse(check(self.put(self.device, "dict", "x.dictd.tar.xz", b"nope"), "dict")["ok"])

    def test_index_has_language_kinds(self):
        self.put(self.drive, "translate", "en_cs.argosmodel")
        self.put(self.device, "dict", "eng-ces.dictd.tar.xz")
        lib = self.tmp / "library"
        entries = {k: library.resolve([self.device, self.drive], k, fake_check({}), PROTECTED)
                   for k in library.KINDS_ALL}
        library.build_index(entries, lib)
        self.assertEqual(os.listdir(lib / "translate"), ["en_cs.argosmodel"])
        self.assertEqual(os.listdir(lib / "dict"), ["eng-ces.dictd.tar.xz"])


class MediaKind(Base):
    def item(self, loc, name, mtime=None, files=("a.mkv",)):
        folder = loc.root / "media" / name
        for f in files:
            (folder / f).parent.mkdir(parents=True, exist_ok=True)
            (folder / f).write_bytes(b"x")
            if mtime:
                os.utime(folder / f, (mtime, mtime))
        if mtime:
            os.utime(folder, (mtime, mtime))
        return folder

    def resolve(self):
        return library.resolve([self.device, self.drive], "media", fake_check({}, bad=("a.mkv",)), PROTECTED)

    def test_resolve_media_newer_wins(self):
        self.item(self.device, "movies/X", mtime=1000)
        self.item(self.drive, "movies/X", mtime=2000)
        self.assertEqual(self.status(self.resolve()),
                         {("device", "movies/X"): "duplicate", ("u-1", "movies/X"): "in_use"})

    def test_resolve_media_never_invalid(self):
        self.item(self.device, "movies/Odd: Name", files=("a.mkv", "x.nfo", "Sample/s.mkv"))
        [e] = self.resolve()  # the check would call a.mkv bad — media isn't checked by content
        self.assertEqual((e["status"], e["type"]), ("in_use", "film"))

    def test_resolve_media_series_split(self):
        self.item(self.device, "shows/S/Season 01")
        self.item(self.drive, "shows/S/Season 02")
        self.assertEqual(self.status(self.resolve()),
                         {("device", "shows/S/Season 01"): "in_use", ("u-1", "shows/S/Season 02"): "in_use"})

    def test_build_index_media(self):
        film = self.item(self.drive, "movies/X")
        s1 = self.item(self.device, "shows/S/Season 01")
        s2 = self.item(self.drive, "shows/S/Season 02")
        album = self.item(self.device, "music/A", files=("01.flac",))
        lib = self.tmp / "library"
        library.build_index({"media": self.resolve()}, lib)
        m = lib / "media"
        self.assertTrue((m / "movies/X").is_symlink())
        self.assertEqual((m / "movies/X").resolve(), film.resolve())
        self.assertTrue((m / "shows/S").is_dir() and not (m / "shows/S").is_symlink())
        self.assertEqual((m / "shows/S/Season 01").resolve(), s1.resolve())
        self.assertEqual((m / "shows/S/Season 02").resolve(), s2.resolve())
        self.assertEqual((m / "music/A").resolve(), album.resolve())

    def test_build_index_media_folders_always_there(self):
        """Jellyfin refuses a library whose folder doesn't exist: an empty box has all three."""
        lib = self.tmp / "library"
        library.build_index({"media": []}, lib)
        self.assertEqual(sorted(os.listdir(lib / "media")), ["movies", "music", "shows"])

    def test_build_index_media_readable_on_drive(self):
        film = self.item(self.drive, "movies/X", files=("deep/a.mkv",))
        (film / "deep/a.mkv").chmod(0o600)
        (film / "deep").chmod(0o700)
        film.chmod(0o700)
        for d in [film.parent, film.parent.parent, self.drive.root, self.tmp]:
            d.chmod(0o700)
        self.addCleanup(self.tmp.chmod, 0o755)
        library.build_index({"media": self.resolve()}, self.tmp / "library")
        self.assertEqual((film / "deep/a.mkv").stat().st_mode & 0o777, 0o644)
        for d in [film / "deep", film, film.parent, film.parent.parent, self.drive.root, self.tmp]:
            self.assertEqual(d.stat().st_mode & 0o777, 0o755, d)

    def test_index_and_set_aside_skip_items_behind_a_new_link(self):
        """The folder above an item became a link after the scan (a drive is anyone's)."""
        import shutil  # noqa: PLC0415

        self.item(self.drive, "music/A", mtime=1000)  # a duplicate (set-aside would move it)
        self.item(self.device, "music/A", mtime=2000)
        self.item(self.drive, "music/B")  # in use (the index would open it up)
        entries = self.resolve()
        outside = self.tmp / "outside"
        for name in ["A", "B"]:
            (outside / name).mkdir(parents=True)
            (outside / name / "a.mkv").write_bytes(b"x")
            (outside / name / "a.mkv").chmod(0o600)
        secret = outside / "B" / "a.mkv"
        shutil.rmtree(self.drive.root / "media/music")
        os.symlink(outside, self.drive.root / "media/music")
        library.build_index({"media": entries}, self.tmp / "library")
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.tmp / "library/media/music/B").exists())
        self.assertEqual(library.set_aside(self.drive, entries, "2026-11-01", self.tmp / "sa"), [])
        self.assertTrue((outside / "A" / "a.mkv").exists())

    def test_set_aside_media_folder(self):
        self.item(self.device, "movies/X", mtime=1000)
        newer = self.item(self.drive, "movies/X", mtime=2000)
        root = self.tmp / "set-aside"
        earlier = root / "2026-11-01/media/movies/X"
        earlier.mkdir(parents=True)
        moved = library.set_aside(self.device, self.resolve(), "2026-11-01", root)
        self.assertEqual(moved, ["X"])
        self.assertTrue((root / "2026-11-01/media/movies/X-1/a.mkv").exists())
        self.assertFalse((self.device.root / "media/movies/X").exists())
        self.assertTrue(newer.exists())

    def test_notify_media(self):
        key = self.tmp / "api-key"
        calls = []
        self.assertFalse(library.notify_media(str(key), "http://127.0.0.1:8096", post=lambda u, h: calls.append((u, h))))
        self.assertEqual(calls, [])
        key.write_text("k123\n")
        self.assertTrue(library.notify_media(str(key), "http://127.0.0.1:8096", post=lambda u, h: calls.append((u, h))))
        self.assertEqual(calls, [("http://127.0.0.1:8096/Library/Refresh",
                                  {"Authorization": 'MediaBrowser Token="k123"'})])

        def down(u, h):
            raise OSError("connection refused")

        self.assertFalse(library.notify_media(str(key), "http://127.0.0.1:8096", post=down))
        self.assertFalse(library.notify_media(None, None))
