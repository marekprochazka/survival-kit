"""Unpacking translation models and dictionaries into the service's cache.

Content stays as the files people imported (one .argosmodel or .dictd.tar.xz each); the
service unpacks what it needs once per file into CACHE/<key>/, where key changes with the
file's real path, size and time. A model keeps metadata.json, model/ and its tokenizer
(info.json = langfiles.check_model's result); a dictionary becomes dict.index + dict.dict
(.dz decompressed, so entries are read by offset). Checks first (langfiles), paths never
leave the folder. Standard library only.
"""

import hashlib
import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import langfiles
from content import Refused

DONE = ".done"


class Unusable(Exception):
    """A file that can't be unpacked; the message says why."""


def _key(archive):
    st = os.stat(archive)
    raw = f"{os.path.realpath(archive)}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def unpack(archive, cache):
    """The unpacked folder of `archive` (a model or a dictionary), made once. Raises Unusable."""
    archive, cache = Path(archive), Path(cache)
    folder = cache / _key(archive)
    if (folder / DONE).exists():
        return folder
    part = cache / f".part-{folder.name}"
    for old in (folder, part):
        if old.exists():
            shutil.rmtree(old)
    part.mkdir()
    try:
        if archive.name.endswith(langfiles.MODEL_EXT):
            _model(archive, part)
        else:
            _dict(archive, part)
        (part / DONE).write_text("")
        os.replace(part, folder)
    except (Refused, OSError, zipfile.BadZipFile, tarfile.TarError, EOFError, ValueError) as e:
        shutil.rmtree(part, ignore_errors=True)
        raise Unusable(f"{archive.name}: {e}") from e
    return folder


def _write(dest, rel, src):
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as out:
        shutil.copyfileobj(src, out, 1 << 20)


def _model(archive, dest):
    info = langfiles.check_model(archive)  # also refuses unsafe paths and zip bombs
    tokenizer = "bpe.model" if info["tokenizer"] == "bpe" else "sentencepiece.model"
    with zipfile.ZipFile(archive) as z:
        meta = next(n for n in z.namelist() if PurePosixPath(n).name == "metadata.json" and len(PurePosixPath(n).parts) <= 2)
        top = PurePosixPath(meta).parent
        for i in z.infolist():
            rel = PurePosixPath(i.filename).relative_to(top) if top != PurePosixPath(".") else PurePosixPath(i.filename)
            if i.is_dir() or not (rel.parts[0] == "model" or str(rel) in ("metadata.json", tokenizer)):
                continue
            with z.open(i) as src:
                _write(dest, str(rel), src)
    (dest / "info.json").write_text(json.dumps(info))


def _dict(archive, dest):
    langfiles.check_dict(archive)  # also refuses unsafe paths, links and huge archives
    with tarfile.open(archive, "r:*") as t:
        files = {m.name: m for m in t.getmembers() if m.isfile()}
        index, data = langfiles.dict_members(files)
        _write(dest, "dict.index", t.extractfile(files[index]))
        raw = t.extractfile(files[data])
        (dest / "dict.dict").write_bytes(langfiles.read_data(raw, data, langfiles.MAX_UNPACKED))


def prune(cache, keep):
    """Remove unpacked folders (and unfinished ones) not in `keep`."""
    keep = {Path(k).name for k in keep}
    for p in Path(cache).iterdir():
        if p.is_dir() and not p.is_symlink() and p.name not in keep:
            shutil.rmtree(p, ignore_errors=True)
