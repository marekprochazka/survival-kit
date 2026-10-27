"""Tiny PMTiles v3 files for tests (unit tests here, the VM test in checks/services.nix).

One empty vector tile (z0) plus a JSON description — valid enough for `pmtiles show` and for
our import check; knobs make the broken variants the check must refuse.
Usage as a script: python3 pmtiles_fixture.py <out.pmtiles> [max_zoom] [w,s,e,n]
"""

import gzip
import json
import struct
import sys
from pathlib import Path

HEADER = struct.Struct("<7sB11Q6B4iB2i")  # same layout as pmtiles.py
GZIP = 2


def _varint(n):
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def write(path, *, version=3, tile_type=1, scheme="4.15.2", bounds=(12.0, 48.5, 18.9, 51.1),
          max_zoom=12, truncate=False):
    tile = gzip.compress(b"", mtime=0)  # an MVT with no layers
    # root directory, one entry: tile id 0 (z0/0/0), run length 1, length, offset 0 (+1)
    root = gzip.compress(_varint(1) + _varint(0) + _varint(1) + _varint(len(tile)) + _varint(1), mtime=0)
    meta = {"name": "test map", "vector_layers": []}
    if scheme is not None:
        meta["version"] = scheme
    metadata = gzip.compress(json.dumps(meta).encode(), mtime=0)
    root_off = HEADER.size
    meta_off = root_off + len(root)
    data_off = meta_off + len(metadata)
    e7 = [round(v * 1e7) for v in bounds]
    header = HEADER.pack(
        b"PMTiles", version,
        root_off, len(root), meta_off, len(metadata), data_off + len(tile), 0, data_off, len(tile),
        1, 1, 1,  # addressed tiles, tile entries, tile contents
        1, GZIP, GZIP, tile_type, 0, max_zoom,  # clustered, compressions, type, zooms
        *e7, 0, round((bounds[0] + bounds[2]) / 2 * 1e7), round((bounds[1] + bounds[3]) / 2 * 1e7),
    )
    data = header + root + metadata + tile
    if truncate:
        data = data[: meta_off + 4]  # cut off inside the description
    Path(path).write_bytes(data)
    return Path(path)


if __name__ == "__main__":
    out = sys.argv[1]
    zoom = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    box = tuple(float(v) for v in sys.argv[3].split(",")) if len(sys.argv) > 3 else (12.0, 48.5, 18.9, 51.1)
    write(out, max_zoom=zoom, bounds=box)
