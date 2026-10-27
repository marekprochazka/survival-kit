# Maps

The **Maps** tile (<https://maps.deck>) shows offline maps — no internet needed. It opens
on Czechia; drag to move, scroll (or **+**/**−**) to zoom.

## What's on the box

| Map | Detail |
|---|---|
| World | countries and capitals |
| Central Europe (Germany, Poland, Czechia, Slovakia, Austria, Hungary, Switzerland, Slovenia) | towns, main roads, rivers, mountains, forests |
| Czechia | villages and the roads between them |

Where maps overlap, the more detailed one is shown. Zooming in further than a map's detail
just makes it bigger — it doesn't get more detailed. Place names are in English where the
map has an English name ("Prague"), otherwise in the local language ("Hradec Králové").

The maps come from [OpenStreetMap](https://www.openstreetmap.org/copyright) (© OpenStreetMap
contributors), cut on the date shown on [What's on this box](whats-on-this-box.html).

## Distances

- **Scale bar** (bottom left) — always there; it changes with the zoom.
- **Ruler** (button, top right) — click points on the map; the box shows the total and each
  leg, each point shows the distance so far. **Clear** starts over; **Ruler** again or
  **Esc** ends measuring. Distances are straight lines ("as the crow flies"), not along roads.
- **Grid** (button) — lines of latitude and longitude with their values; the spacing gets
  finer as you zoom in. Handy for telling someone where you are ("50.1° N, 14.4° E").

## More maps

Import more `.pmtiles` maps on the [Content](content.html) page, then reload the map. A map
named like a built-in one (e.g. `czechia.pmtiles`) replaces it until you delete the import.

### Getting more maps

On any computer with internet, download the `pmtiles` tool
(<https://github.com/protomaps/go-pmtiles/releases>) and cut the area you want from the
Protomaps world map — it only downloads that area:

    pmtiles extract https://build.protomaps.com/YYYYMMDD.pmtiles austria.pmtiles \
      --bbox=9.5,46.4,17.2,49.0 --maxzoom=12

- `YYYYMMDD`: a recent date (the daily builds are kept for about a week; try yesterday's).
  These maps are **Protomaps version 4** — what this box draws. A map made for another
  version is refused on import.
- `--bbox=west,south,east,north`: the area in degrees (find the numbers by hovering in the
  grid, or on <https://boundingbox.klokantech.com>, format "CSV").
- `--maxzoom`: how detailed. Rough sizes:

| Area | Max zoom | Shows | Size |
|---|---|---|---|
| Whole world | 5 | countries, capitals | 15 MB |
| Whole world | 6 | + big cities, main rivers | 45 MB |
| Europe | 7 | regions, larger towns | 57 MB |
| Central Europe | 9 | towns, main roads | 127 MB |
| Central Europe | 10 | more towns and roads | 340 MB |
| Czechia | 12 | villages, connecting roads | 250 MB |
| Czechia | 14 | every street and footpath | 925 MB |

Each extra zoom level makes a map roughly two to three times bigger. Copy the file to a
stick and import it.
