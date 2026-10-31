"""Language files — translation models and dictionaries as content (Language service).

Translation models are Argos Translate packages (.argosmodel: a zip with metadata.json, a
CTranslate2 model and a tokenizer). Dictionaries are FreeDict dictd archives (.dictd.tar.xz:
an .index and a .dict or .dict.dz), kept as one file; the Language service unpacks them.
Here: the names they are stored under and the checks on import and in the library — the
files are only read, never unpacked to disk. Standard library only.
"""

import contextlib
import json
import lzma
import os
import re
import stat
import tarfile
import zipfile
import zlib
from pathlib import PurePosixPath

from content import MAX_NAME, Refused

MAX_UNPACKED = 2 * 1024**3  # bytes; a bigger model is refused (zip bombs)
# dictionaries (FreeDict's biggest unpack to ~100 MB): smaller limits, checked while streaming
MAX_INDEX = 32 * 1024**2
MAX_DATA = 512 * 1024**2
XZ_MEMLIMIT = 128 * 1024**2  # what xz may use to unpack (FreeDict's archives need 64 MB at most)
MODEL_EXT = ".argosmodel"
DICT_EXT = ".dictd.tar.xz"
CODE = r"[a-z]{2,3}"
B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
TITLE_WORDS = ("00-database-short", "00databaseshort")


def _base(filename):
    return os.path.basename(filename.replace("\\", "/")).lower()


def translate_name(filename):
    """File name a translation model is stored under: <from>_<to>.argosmodel.

    Argos names its downloads translate-<from>_<to>-<version>; one model per language pair
    is kept, so a newer version replaces the older one.
    """
    m = re.fullmatch(rf"(?:translate-)?({CODE})_({CODE})(?:-[0-9_.]+)?{re.escape(MODEL_EXT)}", _base(filename))
    if not m:
        raise Refused(f"only Argos translation models (translate-<from>_<to>…{MODEL_EXT}) can be imported here")
    return f"{m[1]}_{m[2]}{MODEL_EXT}"


def dict_name(filename):
    """File name a dictionary is stored under: <name>.dictd.tar.xz.

    FreeDict names its downloads freedict-<name>-<version>; prefix and version are dropped,
    so a newer version replaces the older one. Unsafe characters become "_".
    """
    base = _base(filename)
    if not base.endswith(DICT_EXT):
        raise Refused(f"only FreeDict dictionaries in dictd format ({DICT_EXT}) can be imported here")
    stem = base[: -len(DICT_EXT)].removeprefix("freedict-")
    stem = re.sub(r"-\d.*$", "", stem)
    stem = re.sub(r"[^a-z0-9._-]", "_", stem).lstrip(".")
    if not stem:
        raise Refused("this file name can't be used for a dictionary")
    if len(stem) > MAX_NAME:
        raise Refused(f"this file name is too long (at most {MAX_NAME} characters)")
    return stem + DICT_EXT


def _safe(name):
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and "\\" not in name


# --- translation models -----------------------------------------------------------------


def check_model(path):
    """What an .argosmodel holds: {from_code, to_code, from_name, to_name, tokenizer, target_prefix}.

    tokenizer: "sentencepiece" or "bpe" (Moses + BPE, the OPUS-MT packages). Raises Refused.
    """
    bad = "not an Argos translation model"
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if any(not _safe(i.filename) or stat.S_ISLNK(i.external_attr >> 16) for i in infos):
                raise Refused(f"{bad} (it holds unsafe paths)")
            if sum(i.file_size for i in infos) > MAX_UNPACKED:
                raise Refused(f"{bad} (too big unpacked)")
            names = {i.filename for i in infos}
            metas = [n for n in names if PurePosixPath(n).name == "metadata.json" and len(PurePosixPath(n).parts) <= 2]
            if len(metas) != 1:
                raise Refused(f"{bad} (no metadata.json)")
            top = str(PurePosixPath(metas[0]).parent)
            inside = (lambda n: n) if top == "." else (lambda n: f"{top}/{n}")
            if inside("model/model.bin") not in names:
                raise Refused(f"{bad} (no model/model.bin)")
            if inside("sentencepiece.model") in names:
                tokenizer = "sentencepiece"
            elif inside("bpe.model") in names:
                tokenizer = "bpe"
            else:
                raise Refused(f"{bad} (no sentencepiece.model or bpe.model)")
            meta = json.loads(z.read(metas[0]))
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        raise Refused(f"{bad} ({e})") from e
    codes = [meta.get(k) if isinstance(meta, dict) else None for k in ("from_code", "to_code")]
    if not all(isinstance(c, str) and re.fullmatch(CODE, c) for c in codes):
        raise Refused(f"{bad} (its metadata names no languages)")
    names = [meta.get(k) if isinstance(meta.get(k), str) and meta.get(k) else c
             for k, c in zip(("from_name", "to_name"), codes)]
    prefix = meta.get("target_prefix") if isinstance(meta.get("target_prefix"), str) else ""
    return {"from_code": codes[0], "to_code": codes[1], "from_name": names[0], "to_name": names[1],
            "tokenizer": tokenizer, "target_prefix": prefix}


def validate_model(path, name):
    """check_model, and the pair in the stored name is the model's own."""
    info = check_model(path)
    pair = f"{info['from_code']}_{info['to_code']}"
    if name != pair + MODEL_EXT:
        raise Refused(f"the file is named {name[: -len(MODEL_EXT)]} but the model translates {pair}")
    return info


# --- dictionaries -------------------------------------------------------------------------


def b64num(s):
    """A dictd base64 number (most significant digit first)."""
    n = 0
    for ch in s:
        i = B64.find(ch)
        if i < 0:
            raise ValueError(f"bad number {s!r}")
        n = n * 64 + i
    return n


def parse_index(text):
    """dictd index lines → [(headword, offset, length)]. Raises ValueError."""
    out = []
    for line in text.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) not in (3, 4) or not fields[1] or not fields[2]:
            raise ValueError(f"bad index line {line[:60]!r}")
        out.append((fields[0], b64num(fields[1]), b64num(fields[2])))
    return out


def entry_title(text):
    """The title in a 00-database-short entry: its first non-empty line that isn't the headword
    (dictfmt repeats the headword on the first line; FreeDict's entries are the title alone)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rest = [ln for ln in lines if ln not in TITLE_WORDS]
    return rest[0] if rest else None


XZ_MAGIC = b"\xfd7zXZ\x00"


class _Xz:
    """An xz stream to read from, decompressed with a memory cap (lzma.open has none)."""

    def __init__(self, raw):
        self.raw = raw
        self.unxz = lzma.LZMADecompressor(memlimit=XZ_MEMLIMIT)
        self.buffer = b""

    def read(self, n=-1):
        n = 1 << 20 if n is None or n < 0 else n
        while len(self.buffer) < n and not self.unxz.eof:
            data = b"" if self.unxz.needs_input is False else self.raw.read(1 << 16)
            if not data and self.unxz.needs_input:
                raise EOFError("the archive is cut off")
            self.buffer += self.unxz.decompress(data, n - len(self.buffer))
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out


@contextlib.contextmanager
def _tar_stream(path):
    """The archive as a forward-only tar stream; xz is opened with a memory cap (its header
    says how much it needs — a crafted file can ask for GBs)."""
    with open(path, "rb") as raw:
        if raw.read(6) == XZ_MAGIC:
            raw.seek(0)
            with tarfile.open(fileobj=_Xz(raw), mode="r|") as t:
                yield t
        else:
            raw.seek(0)
            with tarfile.open(fileobj=raw, mode="r|*") as t:
                yield t


def dict_members(names):
    """(index member, data member) among an archive's member names. Raises ValueError."""
    indexes = [n for n in names if n.endswith(".index")]
    datas = [n for n in names if n.endswith((".dict", ".dict.dz"))]
    if len(indexes) != 1 or len(datas) != 1:
        raise ValueError("it must hold one .index and one .dict or .dict.dz")
    return indexes[0], datas[0]


def dict_index(path):
    """First pass over a dictd archive: (index text, data member name). Every member is
    checked (no unsafe paths, no links); only the index is read, at most MAX_INDEX bytes.
    Raises Refused, ValueError or a tar/lzma error."""
    names, index = [], None
    with _tar_stream(path) as t:
        for m in t:
            if not _safe(m.name) or not (m.isfile() or m.isdir()):
                raise Refused("it holds unsafe paths or links")
            if not m.isfile():
                continue
            names.append(m.name)
            if m.name.endswith(".index"):
                if m.size > MAX_INDEX:
                    raise Refused("its index is too big")
                index = t.extractfile(m).read().decode("utf-8")
    dict_members(names)
    return index, next(n for n in names if n.endswith((".dict", ".dict.dz")))


def copy_dict_data(path, name, write):
    """Second pass: the data member `name`, decompressed when .dz, handed to write(chunk) bit
    by bit; at most MAX_DATA bytes. Returns its size."""
    with _tar_stream(path) as t:
        for m in t:
            if m.name != name:
                continue
            raw = t.extractfile(m)
            unzip = zlib.decompressobj(16 + zlib.MAX_WBITS) if name.endswith(".dz") else None
            size = 0
            while True:
                chunk = raw.read(1 << 20)
                if not chunk:
                    break
                while chunk:
                    if unzip:
                        out = unzip.decompress(chunk, 1 << 20)  # never more than 1 MB at once
                        chunk = unzip.unconsumed_tail
                    else:
                        out, chunk = chunk, b""
                    size += len(out)
                    if size > MAX_DATA:
                        raise Refused("its data is too big unpacked")
                    write(out)
                    if unzip and unzip.eof:
                        chunk = b""
            return size
    raise ValueError(f"{name} is missing")


def check_dict(path):
    """What a dictd archive holds: {title, words}. Raises Refused. Streams: memory use stays
    small whatever the archive says about itself."""
    bad = "not a dictionary in dictd format"
    stem = os.path.basename(str(path))[: -len(DICT_EXT)] if str(path).endswith(DICT_EXT) else "dictionary"
    try:
        index_text, data_name = dict_index(path)
        entries = parse_index(index_text)
        del index_text
        spot = next(((off, length) for word, off, length in entries if word in TITLE_WORDS), None)
        title = bytearray()
        pos = 0

        def keep(chunk):  # only the title entry's bytes are kept
            nonlocal pos
            if spot and pos < spot[0] + spot[1] and pos + len(chunk) > spot[0]:
                title.extend(chunk[max(0, spot[0] - pos) : spot[0] + spot[1] - pos])
            pos += len(chunk)

        size = copy_dict_data(path, data_name, keep)
    except Refused as e:
        raise Refused(f"{bad} ({e})") from e
    except (tarfile.TarError, lzma.LZMAError, zlib.error, OSError, EOFError, ValueError, UnicodeDecodeError) as e:
        raise Refused(f"{bad} ({e})") from e
    if any(off + length > size for _, off, length in entries):
        raise Refused(f"{bad} (its index points outside its data)")
    words = sum(1 for word, _, _ in entries if word.strip() and not word.startswith(("00-database", "00database")))
    name = entry_title(title.decode("utf-8", "replace")) if spot else None
    return {"title": name or stem, "words": words}
