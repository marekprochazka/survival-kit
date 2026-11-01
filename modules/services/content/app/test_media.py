"""Unit tests for media.py — names, file checks, title suggestion and the layout scan."""

import os
import tempfile
import unittest
from pathlib import Path

import media
from content import Refused
from locations import Location

FORBIDDEN = ':*?"<>|'


def tree():
    return Path(tempfile.mkdtemp())


def write(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class Names(unittest.TestCase):
    def test_clean_part_keeps_real_letters(self):
        for name in ["Amélie (2001)", "Kolja", "千と千尋", "Rock & Roll!"]:
            with self.subTest(name=name):
                self.assertEqual(media.clean_part(name), name)
        cleaned = media.clean_part('a:b*c?"d<e>f|g')
        self.assertFalse(any(c in cleaned for c in FORBIDDEN), cleaned)
        self.assertFalse(media.clean_part("..x").startswith("."))
        self.assertEqual(media.clean_part("x. "), "x")
        self.assertNotIn("\x07", media.clean_part("a\x07b"))
        for bad in ["/", "...", "", "é" * 101]:  # é×101 = 202 bytes
            with self.subTest(bad=bad), self.assertRaises(Refused):
                media.clean_part(bad)

    def test_suggest_title(self):
        self.assertEqual(media.suggest("The.Kid.1921.1080p.BluRay.x264.mkv"), {"title": "The Kid", "year": 1921})
        self.assertEqual(media.suggest("my_holiday_film.mp4"), {"title": "my holiday film", "year": None})
        self.assertEqual(media.suggest("Amélie (2001).mkv"), {"title": "Amélie", "year": 2001})
        self.assertEqual(media.suggest("C:\\films\\Up.2009.mkv"), {"title": "Up", "year": 2009})

    def test_items(self):
        self.assertEqual(media.film_item("The Kid", 1921), "movies/The Kid (1921)")
        self.assertEqual(media.film_item("Kid", None), "movies/Kid")
        self.assertEqual(media.season_item("Doctor Who", 3), "shows/Doctor Who/Season 03")
        self.assertEqual(media.season_item("Doctor Who", 0), "shows/Doctor Who/Season 00")
        self.assertEqual(media.music_item("Blue Train"), "music/Blue Train")
        for call in [lambda: media.season_item("S", 100), lambda: media.season_item("S", -1),
                     lambda: media.film_item("T", 1700), lambda: media.film_item("T", 2101)]:
            with self.assertRaises(Refused):
                call()

    def test_file_names(self):
        film = "movies/The Kid (1921)"
        self.assertEqual(media.file_name("film", film, "x.MKV"), "The Kid (1921).mkv")
        self.assertEqual(media.file_name("film", film, "x.cs.srt"), "The Kid (1921).cs.srt")
        self.assertEqual(media.file_name("film", film, "x.eng.srt"), "The Kid (1921).eng.srt")
        self.assertEqual(media.file_name("film", film, "x.srt"), "The Kid (1921).srt")
        self.assertEqual(media.file_name("series", "shows/Doctor Who/Season 03", "Doctor.Who.S03E01.mkv"),
                         "Doctor.Who.S03E01.mkv")
        self.assertEqual(media.file_name("music", "music/A", "CD1/01 Song.flac"), "CD1/01 Song.flac")
        self.assertEqual(media.file_name("music", "music/A", "01 Song.flac"), "01 Song.flac")
        for kind, name in [("music", "a/b/c.flac"), ("film", "x.exe"), ("series", "../x.mkv"), ("music", "cover.gif")]:
            with self.subTest(name=name), self.assertRaises(Refused):
                media.file_name(kind, "music/A" if kind == "music" else film, name)


SAMPLES = {
    "mkv": b"\x1a\x45\xdf\xa3" + b"\0" * 20,
    "webm": b"\x1a\x45\xdf\xa3" + b"\0" * 20,
    "mp4": b"\0\0\0\x18ftypisom" + b"\0" * 12,
    "m4v": b"\0\0\0\x18ftypM4V " + b"\0" * 12,
    "m4a": b"\0\0\0\x18ftypM4A " + b"\0" * 12,
    "mov": b"\0\0\0\x14ftypqt  " + b"\0" * 12,
    "avi": b"RIFF\0\0\0\0AVI LIST" + b"\0" * 8,
    "wav": b"RIFF\0\0\0\0WAVEfmt " + b"\0" * 8,
    "mp3": b"ID3\x04\0\0\0\0\0\0" + b"\0" * 10,
    "flac": b"fLaC" + b"\0" * 20,
    "ogg": b"OggS" + b"\0" * 20,
    "opus": b"OggS" + b"\0" * 20,
    "jpg": b"\xff\xd8\xff\xe0" + b"\0" * 20,
    "jpeg": b"\xff\xd8\xff\xe0" + b"\0" * 20,
    "png": b"\x89PNG\r\n\x1a\n" + b"\0" * 16,
    "srt": "1\n00:00:01,000 --> 00:00:02,000\nAhoj světe\n".encode(),
    "ass": b"[Script Info]\nTitle: x\n",
    "vtt": b"WEBVTT\n\n00:01.000 --> 00:02.000\nHi\n",
}


class Sniff(unittest.TestCase):
    def test_sniff(self):
        d = tree()
        for ext, data in SAMPLES.items():
            with self.subTest(ext=ext):
                media.sniff(write(d / f"f.{ext}", data), ext)
        mp3_frame = write(d / "frame.mp3", b"\xff\xfb\x90\x64" + b"\0" * 20)
        media.sniff(mp3_frame, "mp3")
        for name, data, ext in [("png.mkv", SAMPLES["png"], "mkv"), ("junk.srt", b"\0\xff\xfe\x00" * 10, "srt"),
                                ("empty.flac", b"", "flac"), ("text.vtt", b"hello\n", "vtt")]:
            with self.subTest(name=name), self.assertRaises(Refused):
                media.sniff(write(d / name, data), ext)


class Scan(unittest.TestCase):
    def setUp(self):
        self.root = tree()
        self.loc = Location(id="device", name="This device", root=self.root, order=0)
        m = self.root / "media"
        write(m / "movies/Kid (1921)/Kid (1921).mkv", b"x" * 10)
        write(m / "movies/Kid (1921)/Kid (1921).nfo", b"y" * 5)
        write(m / "movies/Kid (1921)/Sample/sample.mkv", b"z" * 3)
        write(m / "movies/Odd: Name/a.mkv")
        (m / "movies/Empty").mkdir(parents=True)
        write(m / "movies/loose.mkv")
        write(m / "movies/.hidden/a.mkv")
        os.symlink("/etc", m / "movies/Link")
        write(m / "shows/S/Season 01/e1.mkv", b"x" * 4)
        write(m / "shows/S/Specials/e0.mkv")
        write(m / "shows/S/ep.mkv")
        elsewhere = tree()
        write(elsewhere / "Season 01/e.mkv")
        os.symlink(elsewhere, m / "shows/LinkSeries")
        os.symlink(elsewhere / "Season 01", m / "shows/S/LinkSeason")
        write(m / "music/A/01.flac", b"x" * 7)

    def test_scan_items_layout_only(self):
        found = {e["name"]: e for e in media.scan_items(self.loc)}
        self.assertEqual(
            set(found),
            {"movies/Kid (1921)", "movies/Odd: Name", "movies/Empty", "shows/S/Season 01", "shows/S/Specials", "music/A"},
        )
        self.assertEqual(found["movies/Kid (1921)"]["size"], 18)  # every file inside, incl. Sample/
        self.assertEqual(found["movies/Empty"]["size"], 0)
        self.assertEqual(found["shows/S/Season 01"]["type"], "season")
        self.assertEqual(found["movies/Kid (1921)"]["type"], "film")
        self.assertEqual(found["music/A"]["type"], "album")
        self.assertEqual(found["shows/S/Season 01"]["file"], "Season 01")
        for e in found.values():
            self.assertIsNone(e["refusal"])
            self.assertEqual(e["location"], "device")
            self.assertTrue(e["path"].is_dir())

    def test_scan_items_never_follows_links_above_items(self):
        """A drive is anyone's: a link at media/, media/<top> or the tree's root must not make
        the root library index (and chmod) whatever it points at."""
        target = tree()
        write(target / "secret/a.mkv")
        (target / "secret/a.mkv").chmod(0o600)
        for link in ["media/music", "media/movies", "media/shows"]:
            with self.subTest(link=link):
                loc = Location(id="u", name="u", root=tree(), order=1)
                (loc.root / "media").mkdir()
                os.symlink(target, loc.root / link)
                self.assertEqual(media.scan_items(loc), [])
        loc = Location(id="u", name="u", root=tree(), order=1)
        os.symlink(target, loc.root / "media")
        self.assertEqual(media.scan_items(loc), [])
        linked_root = tree() / "survival-kit"
        os.symlink(self.root, linked_root)
        self.assertEqual(media.scan_items(Location(id="u", name="u", root=linked_root, order=1)), [])
        self.assertEqual((target / "secret/a.mkv").stat().st_mode & 0o777, 0o600)

    def test_scan_items_no_media_folder(self):
        empty = Location(id="x", name="x", root=tree(), order=1)
        self.assertEqual(media.scan_items(empty), [])

    def test_scan_items_mtime_is_newest(self):
        kid = self.root / "media/movies/Kid (1921)"
        os.utime(kid, (1000, 1000))
        os.utime(kid / "Kid (1921).mkv", (5000, 5000))
        found = {e["name"]: e for e in media.scan_items(self.loc)}
        self.assertGreaterEqual(found["movies/Kid (1921)"]["mtime"], 5000)


MKV = SAMPLES["mkv"]
FLAC = SAMPLES["flac"]
SRT = SAMPLES["srt"]


class Shelf(unittest.TestCase):
    def setUp(self):
        from test_content import Box  # noqa: PLC0415 — Box imports this module's neighbours

        self.box = Box()
        self.refreshes = []

        def refresh():
            self.refreshes.append(1)
            self.box.rebuild()

        self.shelf = media.MediaShelf(self.box.places, refresh)
        self.dev = self.box.device()

    def send(self, batch, name, data):
        import io  # noqa: PLC0415

        self.shelf.receive(batch, name, len(data), io.BytesIO(data))

    def film(self, title="The Kid", year="1921", loc=None, files=(("x.mkv", MKV),)):
        total = sum(len(d) for _, d in files)
        b = self.shelf.begin("film", {"title": title, "year": year}, loc or self.dev, total)
        for name, data in files:
            self.send(b["batch"], name, data)
        return b, self.shelf.finish(b["batch"])

    def staging(self, loc=None):
        return [p.name for p in ((loc or self.dev).root / ".incoming").iterdir()]

    def test_batch_film(self):
        b, r = self.film(files=(("x.mkv", MKV), ("x.cs.srt", SRT)))
        self.assertEqual((b["item"], b["exists"], r["result"]), ("movies/The Kid (1921)", None, "added"))
        folder = self.dev.root / "media/movies/The Kid (1921)"
        self.assertEqual(sorted(os.listdir(folder)), ["The Kid (1921).cs.srt", "The Kid (1921).mkv"])
        self.assertEqual((folder / "The Kid (1921).mkv").stat().st_mode & 0o777, 0o644)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o755)
        self.assertEqual(len(self.refreshes), 1)
        self.assertEqual(self.staging(), [])
        [item] = self.shelf.items()
        self.assertEqual((item["name"], item["type"], item["location"]), ("movies/The Kid (1921)", "film", "device"))

    def test_batch_film_needs_one_video(self):
        for files in [(("x.srt", SRT),), (("a.mkv", MKV), ("b.mp4", SAMPLES["mp4"]))]:
            with self.subTest(files=[f for f, _ in files]):
                with self.assertRaises(Refused):
                    self.film(files=files)
                self.assertFalse((self.dev.root / "media/movies/The Kid (1921)").exists())
                self.assertEqual(self.staging(), [])

    def test_batch_series_and_music_need_their_files(self):
        b = self.shelf.begin("series", {"series": "S", "season": "1"}, self.dev, len(SRT))
        self.send(b["batch"], "e.srt", SRT)
        with self.assertRaises(Refused):
            self.shelf.finish(b["batch"])
        b = self.shelf.begin("music", {"name": "A"}, self.dev, len(SAMPLES["jpg"]))
        self.send(b["batch"], "cover.jpg", SAMPLES["jpg"])
        with self.assertRaises(Refused):
            self.shelf.finish(b["batch"])
        b = self.shelf.begin("music", {"name": "A"}, self.dev, 2 * len(FLAC))
        self.send(b["batch"], "CD1/01.flac", FLAC)
        self.send(b["batch"], "CD2/01.flac", FLAC)
        self.shelf.finish(b["batch"])
        self.assertTrue((self.dev.root / "media/music/A/CD2/01.flac").exists())
        b = self.shelf.begin("series", {"series": "S", "season": "2"}, self.dev, len(MKV))
        self.send(b["batch"], "S.S02E01.mkv", MKV)
        self.assertEqual(self.shelf.finish(b["batch"])["item"], "shows/S/Season 02")
        self.assertEqual(self.staging(), [])

    def test_batch_replace(self):
        drive = self.box.add_drive("u-1")
        self.film(loc=drive)
        b, r = self.film(loc=self.dev, files=(("y.mkv", MKV + b"new"),))
        self.assertEqual((b["exists"], r["result"]), ("import", "replaced"))
        self.assertFalse((drive.root / "media/movies/The Kid (1921)").exists())
        new = self.dev.root / "media/movies/The Kid (1921)/The Kid (1921).mkv"
        self.assertEqual(new.read_bytes(), MKV + b"new")
        b, r = self.film(loc=self.dev, files=(("z.mkv", MKV + b"newer"),))  # same location
        self.assertEqual(r["result"], "replaced")
        self.assertEqual(new.read_bytes(), MKV + b"newer")
        self.assertEqual(self.staging(), [])

    def test_batch_over_declared_size(self):
        b = self.shelf.begin("film", {"title": "T", "year": ""}, self.dev, len(MKV) - 1)
        with self.assertRaises(Refused):
            self.send(b["batch"], "x.mkv", MKV)
        self.assertEqual(self.staging(), [])
        with self.assertRaises(Refused) as e:
            self.shelf.finish(b["batch"])
        self.assertEqual(e.exception.status, 404)

    def test_batch_bad_files(self):
        b = self.shelf.begin("film", {"title": "T", "year": ""}, self.dev, 100)
        self.send(b["batch"], "x.mkv", MKV)
        with self.assertRaises(Refused):
            self.send(b["batch"], "y.srt", SRT) or self.send(b["batch"], "z.srt", SRT)  # same stored name
        with self.assertRaises(Refused):
            self.send(b["batch"], "x.exe", b"MZ")
        b2 = self.shelf.begin("film", {"title": "U", "year": ""}, self.dev, 100)
        with self.assertRaises(Refused):
            self.send(b2["batch"], "fake.mkv", b"not a video")  # the content check
        self.assertEqual(os.listdir(self.dev.root / ".incoming" / f"media-{b2['batch']}"), [])
        self.shelf.cancel(b2["batch"])
        with self.assertRaises(Refused) as e:
            self.send("nope", "x.mkv", MKV)
        self.assertEqual(e.exception.status, 404)
        self.shelf.cancel(b["batch"])
        self.assertEqual(self.staging(), [])

    def test_space_check_on_total(self):
        with self.assertRaises(Refused):
            self.shelf.begin("film", {"title": "T", "year": ""}, self.dev, 49 * 1000**3)  # 50 GB free
        self.assertEqual(self.staging(), [])

    def test_staging_cleared_at_start(self):
        import server  # noqa: PLC0415

        left = self.dev.root / ".incoming/media-abc/x.mkv"
        left.parent.mkdir(parents=True)
        left.write_bytes(MKV)
        server._clear(self.dev.root / ".incoming")
        self.assertEqual(self.staging(), [])

    def test_delete_item(self):
        self.film()
        b = self.shelf.begin("series", {"series": "S", "season": "1"}, self.dev, len(MKV))
        self.send(b["batch"], "e1.mkv", MKV)
        self.shelf.finish(b["batch"])
        self.shelf.delete("movies/The Kid (1921)", "device")
        self.assertFalse((self.dev.root / "media/movies/The Kid (1921)").exists())
        self.shelf.delete("shows/S/Season 01", None)  # the copy in use
        self.assertFalse((self.dev.root / "media/shows/S").exists())  # the last season took the series
        self.assertEqual(self.shelf.items(), [])
        with self.assertRaises(Refused) as e:
            self.shelf.delete("movies/Gone", "device")
        self.assertEqual(e.exception.status, 404)

    def test_import_and_delete_refuse_links_above_items(self):
        outside = Path(tempfile.mkdtemp())
        (outside / "keep").write_text("x")
        os.symlink(outside, self.dev.root / "media/movies")  # no movies/ yet on a new tree
        with self.assertRaises(Refused):
            self.film()
        self.assertEqual(sorted(os.listdir(outside)), ["keep"])
        self.assertEqual(self.staging(), [])
        # an item the library listed before the folder above it became a link
        os.unlink(self.dev.root / "media/movies")
        self.film()
        import shutil  # noqa: PLC0415

        shutil.move(str(self.dev.root / "media/movies/The Kid (1921)"), str(outside / "The Kid (1921)"))
        (self.dev.root / "media/movies").rmdir()
        os.symlink(outside, self.dev.root / "media/movies")
        with self.assertRaises(Refused):
            self.shelf.delete("movies/The Kid (1921)", "device")
        self.assertTrue((outside / "The Kid (1921)").is_dir())

    def test_delete_never_leaves_the_tree(self):
        self.film()
        outside = Path(tempfile.mkdtemp())
        (outside / "keep").write_text("x")
        for bad in ["movies/../../wiki", "/etc", "movies", "shows/S", "movies/a/b", "other/x", "movies/.."]:
            with self.subTest(bad=bad), self.assertRaises(Refused):
                self.shelf.delete(bad, "device")
        # the folder became a link after the library last looked (a drive edited elsewhere)
        folder = self.dev.root / "media/movies/The Kid (1921)"
        import shutil  # noqa: PLC0415

        shutil.rmtree(folder)
        os.symlink(outside, folder)
        with self.assertRaises(Refused):
            self.shelf.delete("movies/The Kid (1921)", "device")
        self.assertTrue((outside / "keep").exists())


if __name__ == "__main__":
    unittest.main()
