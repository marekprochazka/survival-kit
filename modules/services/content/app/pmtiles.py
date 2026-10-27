"""PMTiles map files: read the header, check that an import will draw on this box.

Format: github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md — a fixed 127-byte header
(little-endian), then directories, a JSON description ("metadata") and the tiles.
"""

import gzip
import json
import os
import struct

from content import Refused

HEADER = struct.Struct("<7sB11Q6B4iB2i")  # 127 bytes
RASTER = {2: "png", 3: "jpeg", 4: "webp", 5: "avif"}
NONE, GZIP = 1, 2  # compression codes we can read
GETTING_MORE = "see 'Getting more maps' in the manual"


def read_header(path):
    """The header fields we use; Refused when the file isn't a PMTiles map."""
    with open(path, "rb") as f:
        raw = f.read(HEADER.size)
    if len(raw) < HEADER.size or raw[:7] != b"PMTiles":
        raise Refused("not a PMTiles map")
    (
        _,
        version,
        root_off,
        root_len,
        meta_off,
        meta_len,
        _,
        _,
        data_off,
        data_len,
        *_counts,
        _clustered,
        internal,
        _tilecomp,
        tile_type,
        min_zoom,
        max_zoom,
        min_lon,
        min_lat,
        max_lon,
        max_lat,
    ) = HEADER.unpack(raw)[:-3]  # drop the centre (zoom, lon, lat)
    return {
        "version": version,
        "tile_type": tile_type,
        "internal_compression": internal,
        "metadata_offset": meta_off,
        "metadata_length": meta_len,
        "end": max(root_off + root_len, meta_off + meta_len, data_off + data_len),
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "bounds": [v / 1e7 for v in (min_lon, min_lat, max_lon, max_lat)],
    }


def check(path, scheme_major):
    """Refused unless the map can be drawn here; returns a note for doubtful-but-usable maps."""
    h = read_header(path)
    if h["version"] != 3:
        raise Refused(f"only PMTiles version 3 maps can be used (this file is version {h['version']})")
    if h["tile_type"] in RASTER:
        raise Refused("this is a picture (raster) map; only vector maps work here")
    if h["tile_type"] != 1:
        raise Refused("not a vector map")
    if os.path.getsize(path) < h["end"]:
        raise Refused("the file is incomplete (cut off while copying?)")
    version = _metadata(path, h).get("version")
    major = str(version).split(".")[0] if version is not None else ""
    if not major.isdigit():
        return f"the map doesn't say which map version it was made with; if it draws wrongly, {GETTING_MORE}"
    if int(major) != scheme_major:
        raise Refused(
            f"this map was made for map version {major}; this box needs version {scheme_major} — {GETTING_MORE}"
        )
    return None


def _metadata(path, h):
    """The map's JSON description ({} when stored in a compression we don't read)."""
    with open(path, "rb") as f:
        f.seek(h["metadata_offset"])
        raw = f.read(h["metadata_length"])
    try:
        if h["internal_compression"] == GZIP:
            raw = gzip.decompress(raw)
        elif h["internal_compression"] != NONE:
            return {}
        meta = json.loads(raw or b"{}")
    except (OSError, EOFError, ValueError) as e:
        raise Refused("the map's description can't be read (damaged file?)") from e
    return meta if isinstance(meta, dict) else {}
