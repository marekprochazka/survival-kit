"""Media — films, series and music for Jellyfin (spec 2026-11-01-media). Standard library only.

The unit of media is a folder (an "item"), not a file:
  movies/<Title (Year)>/            a film: its video, subtitles, anything else beside it
  shows/<Series>/<Season NN>/       one season of a series
  music/<Album>/                    an album (Jellyfin sorts music by the tags in the files)
An item's key is that path inside media/, e.g. "shows/Doctor Who/Season 03".

Names keep their real letters — the folder name is the title people see (no internet
metadata). Uploads are cleaned strictly; on drives any existing name is used as it is.
"""

import os
import re
import unicodedata
from pathlib import Path

from content import MAX_NAME, Refused

VIDEO = {"mkv", "mp4", "m4v", "webm", "avi", "mov"}
AUDIO = {"mp3", "flac", "m4a", "ogg", "opus", "wav"}
SUBS = {"srt", "vtt", "ass"}
IMAGES = {"jpg", "jpeg", "png"}
ALLOWED = {"film": VIDEO | SUBS, "series": VIDEO | SUBS | IMAGES, "music": AUDIO | IMAGES}
TOPS = {"movies": "film", "shows": "season", "music": "album"}
YEARS = range(1880, 2101)
SEASONS = range(0, 100)

# characters exFAT/NTFS (and paths) can't hold: ":" reads best as " - ", the rest go
_REPLACE = str.maketrans({":": " - ", "/": "-", "\\": "-", "|": "-", "*": None, "?": None, '"': None, "<": None, ">": None})


# --- names ----------------------------------------------------------------------------


def clean_part(name):
    """One path component of an uploaded item or file name, with its real letters kept."""
    name = "".join(c for c in name.translate(_REPLACE) if unicodedata.category(c) != "Cc")
    name = " ".join(name.split()).lstrip(". ").rstrip(". ")
    if not any(c.isalnum() for c in name):
        raise Refused("this name can't be used — give it some letters or digits")
    if len(name.encode()) > MAX_NAME:
        raise Refused(f"this name is too long (at most {MAX_NAME} bytes)")
    return name


# release names: everything from the first of these on is not part of the title
_TAGS = re.compile(
    r"^(\d{3,4}p|4k|uhd|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|web|hdtv|dvdrip|dvd|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|dts|remux|proper|repack|extended)$",
    re.IGNORECASE,
)


def suggest(filename):
    """A film's title and year guessed from its file name, for the import form."""
    stem = Path(filename.replace("\\", "/")).name
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    m = re.match(r"^(.*?)\s*\((\d{4})\)", stem)
    if m and int(m.group(2)) in YEARS:
        return {"title": m.group(1).strip(), "year": int(m.group(2))}
    words = re.split(r"[\s._]+", stem.strip())
    title, year = [], None
    for n, w in enumerate(words):
        if n > 0 and re.fullmatch(r"\d{4}", w) and int(w) in YEARS:
            year = int(w)
            break
        if _TAGS.match(w):
            break
        title.append(w)
    return {"title": " ".join(title).strip(), "year": year}


def film_item(title, year):
    if year is not None and year not in YEARS:
        raise Refused(f"the year must be between {YEARS.start} and {YEARS.stop - 1}")
    return "movies/" + clean_part(f"{title} ({year})" if year is not None else title)


def season_item(series, season):
    if season not in SEASONS:
        raise Refused(f"the season must be a number from {SEASONS.start} to {SEASONS.stop - 1}")
    return f"shows/{clean_part(series)}/Season {season:02d}"


def music_item(name):
    return "music/" + clean_part(name)


def _ext(name):
    return name.rsplit(".", 1)[1].lower() if "." in name else ""


def file_name(kind, item, filename):
    """The name an uploaded file gets inside its item (relative, "/"-separated)."""
    parts = [p for p in filename.replace("\\", "/").split("/") if p]
    if not parts or len(parts) > (2 if kind == "music" else 1):
        raise Refused(f"{filename}: files can't be in sub-folders here" if parts else "no file name")
    ext = _ext(parts[-1])
    if ext not in ALLOWED[kind]:
        raise Refused(f"{parts[-1]}: this kind of file can't be imported here")
    if kind == "film":
        stem = item.rsplit("/", 1)[1]
        if ext in SUBS:
            tag = parts[-1][: -len(ext) - 1].rsplit(".", 1)
            if len(tag) == 2 and re.fullmatch(r"[A-Za-z]{2,3}", tag[1]):
                return f"{stem}.{tag[1].lower()}.{ext}"
        return f"{stem}.{ext}"
    return "/".join(clean_part(p) for p in parts)


# --- file checks ----------------------------------------------------------------------


def _text(head):
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 with a byte-order mark
        return head.decode("utf-16", errors="replace")
    if b"\0" in head:
        return None
    return head.decode("utf-8", errors="replace")  # also Latin-1/cp1250 subtitles


def sniff(path, ext):
    """Refused unless the start of the file looks like what its extension says."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if not head:
        raise Refused(f"{Path(path).name}: the file is empty")
    ftyp = head[4:8] == b"ftyp"
    ok = {
        "mkv": head.startswith(b"\x1a\x45\xdf\xa3"),
        "webm": head.startswith(b"\x1a\x45\xdf\xa3"),
        "mp4": ftyp,
        "m4v": ftyp,
        "m4a": ftyp,
        "mov": ftyp or head[4:8] in (b"moov", b"mdat", b"wide", b"free"),
        "avi": head[:4] == b"RIFF" and head[8:12] == b"AVI ",
        "wav": head[:4] == b"RIFF" and head[8:12] == b"WAVE",
        "mp3": head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0),
        "flac": head.startswith(b"fLaC"),
        "ogg": head.startswith(b"OggS"),
        "opus": head.startswith(b"OggS"),
        "jpg": head.startswith(b"\xff\xd8\xff"),
        "jpeg": head.startswith(b"\xff\xd8\xff"),
        "png": head.startswith(b"\x89PNG\r\n\x1a\n"),
    }
    if ext in SUBS:
        text = _text(head)
        good = text is not None and (ext != "vtt" or text.lstrip("﻿").startswith("WEBVTT"))
    else:
        good = ok.get(ext, False)
    if not good:
        raise Refused(f"{Path(path).name}: not a .{ext} file (its content says otherwise)")


# --- what is on a location ------------------------------------------------------------


def _dirs(folder):
    """Real sub-folders, no hidden ones and no links (a drive's link could point anywhere)."""
    try:
        children = sorted(folder.iterdir())
    except FileNotFoundError:
        return []
    return [p for p in children if not p.name.startswith(".") and not p.is_symlink() and p.is_dir()]


def _measure(folder):
    """(bytes of every file inside, newest mtime of the folder and its files); links not followed."""
    size, newest = 0, folder.lstat().st_mtime
    for top, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(top, d))]
        for f in files:
            st = os.lstat(os.path.join(top, f))
            if not os.path.islink(os.path.join(top, f)):
                size += st.st_size
                newest = max(newest, st.st_mtime)
    return size, int(newest)


def scan_items(loc):
    """The media items on a location, found by layout only — nothing about them is "invalid".

    Entries have scan()'s keys (name = item key) plus type (film | season | album).
    """
    media = loc.root / "media"
    found = []
    for top, kind in TOPS.items():
        if kind == "season":
            folders = [(f"{top}/{s.name}/{d.name}", d) for s in _dirs(media / top) for d in _dirs(s)]
        else:
            folders = [(f"{top}/{d.name}", d) for d in _dirs(media / top)]
        for name, path in folders:
            size, mtime = _measure(path)
            found.append({"name": name, "file": path.name, "path": path, "size": size, "mtime": mtime,
                          "location": loc.id, "refusal": None, "type": kind})
    return found
