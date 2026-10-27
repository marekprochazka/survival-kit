# Maps

`modules/services/maps/` — <https://maps.deck>: offline vector maps drawn in the browser
(ADR-0002, amended 2026-10-27). On in both profiles. **No map server**: nginx serves the
page and the map files; the browser does the rest.

## How it works

A map is one **`.pmtiles`** file: a small index plus thousands of *tiles* (square pieces of
the map per zoom level), each a vector tile (roads, rivers, labels as geometry, not
pictures). The page reads the index, works out which tiles the screen needs and fetches
just those **byte ranges** (`Range: bytes=…` — nginx answers 206 for static files). A 250 MB
map costs only the few hundred KB on screen.

**MapLibre GL JS** draws them with WebGL — with no GPU, Firefox falls back to software
rendering, which was tested usable in VirtualBox without 3D acceleration (2026-10-27; the
lighter canvas renderer protomaps-leaflet was tried and set aside). The look comes from the
**Protomaps basemap style** (`@protomaps/basemaps`, flavour `light` or `dark` following the
system, labels `lang: "en"` = English name where present, else the local one), plus fonts
(glyphs) and icons (sprites) from Protomaps' `basemaps-assets`.

## Files

| File | What |
|---|---|
| `default.nix` | Builds the site (page + vendored files), registry entry (a **static site**: `root`, no port), nginx locations, the imports dir |
| `builtins.nix` | **Generated** by `utils/fetch-maps`: the built-in maps, pinned by hash (`requireFile`) |
| `site/index.html`, `site/maps.css` | The page |
| `site/maps.js` | Lists the maps, opens them, builds the style, ruler and grid |
| `site/geo.js` | Map maths without a browser: tile bounds, which map draws a tile, distances, grid lines |

Served at `maps.deck`: `/` the site (store path); `/builtin/` the built-in maps (store);
`/imported/` `/var/lib/survival-kit/maps` (written by the content manager). Both map folders
are listed as JSON (`autoindex_format json`), which is how the page finds the maps — nothing
to regenerate after an import. Paths with a `/.` (uploads in progress in `.incoming/`) answer
404. Maps are sent with `Cache-Control: no-cache`: an import can replace a map of the same
name.

## Several maps at once

Every map is its own MapLibre source (`deck://<name>/{z}/{x}/{y}`, a custom protocol that
reads the tile from the right file) with its own zoom range; deeper zooms stretch a map's
last level. Coarse maps are drawn first. Where maps overlap, the coarser one hands a tile
over and draws nothing there (`geo.js` `yields`):

- below its own max zoom: when a more detailed map **touches** the tile — safe, because
  `pmtiles extract` keeps whole tiles wherever they touch the area;
- at its max zoom (the tile may be stretched far deeper): only when the detailed map
  covers the tile **completely** — otherwise a gap would open next to the detailed area.

So nothing is drawn twice except thin strips along a detailed map's edge, and nothing goes
blank. An import with a built-in's name hides the built-in (the page prefers `/imported/`).

## Built-in maps

| Name | Area (`--bbox`) | `--maxzoom` | Size |
|---|---|---|---|
| `world` | everything | 5 | 15 MB |
| `central-europe` | `5.8,45.4,24.2,55.1` | 9 | 127 MB |
| `czechia` | `12.0,48.5,18.9,51.1` | 12 | 250 MB |

They are cut from the **Protomaps daily planet build** (`https://build.protomaps.com/YYYYMMDD.pmtiles`,
layer scheme v4 — the bundled style draws v4; the content manager refuses other versions).

### Refreshing the built-in maps (and building on a new machine)

The daily builds are **deleted within a week**, so Nix can't fetch the maps by URL like the
wiki books. Instead, in the **development repository** (the flake plus `utils/`, where
`utils/build-iso` lives too — not part of `/etc/nixos`; an installed box already has its
maps in the store and keeps them when it rebuilds):

1. Run `utils/fetch-maps` from the repository root (needs internet, ~400 MB). It takes the
   newest daily build, cuts the three maps into `tmp/maps/`, adds them to the Nix store
   (`nix-store --add-fixed sha256`) and rewrites `modules/services/maps/builtins.nix` with
   the build date and the new hashes.
2. Commit `builtins.nix`.

On a machine where the maps are not in the store, building the system or the ISO stops with
a message naming `utils/fetch-maps`. Running it there gives *newer* maps (new hashes) — to
build exactly the same ISO, copy `tmp/maps/*.pmtiles` over and add them with
`nix-store --add-fixed sha256 <file>` instead. (Once there is a place to publish them, the
three files can be hosted and fetched by URL — only `builtins.nix` changes.)

VM tests never need the real maps: `checks/services.nix` sets
`survivalKit.services.maps.builtins` to tiny stand-ins made by
`modules/services/content/app/pmtiles_fixture.py`.

## Updating MapLibre, pmtiles.js, the style or the assets

Bump version + hash in `default.nix` (`nix store prefetch-file <url>`) and
`THIRD-PARTY.md`. A new **major** style version may need a new map scheme: then cut new
built-in maps, raise `MAP_SCHEME` in the content manager, and update the manual's "Getting
more maps".
