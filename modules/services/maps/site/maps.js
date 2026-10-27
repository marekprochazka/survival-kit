// survival-kit maps page: every .pmtiles map on the box (built-in + imported) drawn with
// MapLibre and the Protomaps style; where maps overlap, the more detailed one is shown
// (geo.js `yields`). Everything is local: style, fonts, icons and the map files.
import * as maplibregl from "./vendor/maplibre/maplibre-gl.mjs";
import { yields, haversine, formatDistance, gridStep, gridLines } from "./geo.js";

const base = `${location.origin}/`;
const CZECHIA = [12.0, 48.5, 18.9, 51.1]; // start view
// a fresh one each time: MapLibre hands tile bytes to its worker, which empties the buffer
const empty = () => new Uint8Array(0);
const NOTHING = { type: "FeatureCollection", features: [] };
const FONT = ["Noto Sans Regular"];
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
const flavor = dark ? "dark" : "light";
const ATTRIBUTION = "© OpenStreetMap contributors · Protomaps · MapLibre";

// nginx JSON listing → .pmtiles file names; an unreachable folder counts as empty
async function list(dir) {
  try {
    const r = await fetch(`${base}${dir}/`);
    if (!r.ok) return [];
    return (await r.json())
      .filter((e) => e.type === "file" && e.name.endsWith(".pmtiles"))
      .map((e) => e.name);
  } catch {
    return [];
  }
}

// all maps, coarse first (drawn below); an import replaces a built-in of the same name
async function loadMaps() {
  const [builtin, imported] = await Promise.all([list("builtin"), list("imported")]);
  const urls = new Map(builtin.map((n) => [n, `${base}builtin/${encodeURIComponent(n)}`]));
  for (const n of imported) urls.set(n, `${base}imported/${encodeURIComponent(n)}`);
  const maps = [];
  for (const [file, url] of urls) {
    const archive = new pmtiles.PMTiles(url);
    try {
      const h = await archive.getHeader();
      maps.push({
        name: file.replace(/\.pmtiles$/, ""),
        archive,
        minZoom: h.minZoom,
        maxZoom: h.maxZoom,
        bounds: [h.minLon, h.minLat, h.maxLon, h.maxLat],
      });
    } catch (e) {
      console.warn(`map ${file} can't be read`, e); // one broken file must not blank the page
    }
  }
  return maps.sort((a, b) => a.maxZoom - b.maxZoom);
}

// deck://<map>/<z>/<x>/<y> → that map's tile, or nothing where a more detailed map takes over
function tiles(maps) {
  const byName = new Map(maps.map((m) => [m.name, m]));
  return async (params, abort) => {
    const [, name, z, x, y] = params.url.match(/^deck:\/\/(.+)\/(\d+)\/(\d+)\/(\d+)$/);
    const map = byName.get(name);
    if (yields(map, maps, +z, +x, +y)) return { data: empty() };
    const tile = await map.archive.getZxy(+z, +x, +y, abort.signal);
    return { data: tile ? tile.data : empty() };
  };
}

// one source + one copy of the Protomaps layers per map, English names where they exist;
// source ids are "map:<name>", so an imported grid.pmtiles can't clash with the page's own
function style(maps) {
  const sources = {};
  let layers = [];
  for (const m of maps) {
    sources[`map:${m.name}`] = {
      type: "vector",
      tiles: [`deck://${m.name}/{z}/{x}/{y}`],
      minzoom: m.minZoom,
      maxzoom: m.maxZoom, // deeper zooms stretch this map's last level (no gray)
      bounds: m.bounds,
    };
    const own = basemaps
      .layers(`map:${m.name}`, basemaps.namedFlavor(flavor), { lang: "en" })
      .filter((l) => l.type !== "background" || layers.length === 0); // one background
    layers = layers.concat(own.map((l) => ({ ...l, id: `${m.name}:${l.id}` })));
  }
  return {
    version: 8,
    glyphs: `${base}fonts/{fontstack}/{range}.pbf`,
    sprite: `${base}sprites/v4/${flavor}`,
    sources,
    layers,
  };
}

// a group of text buttons in MapLibre's control style
class Tools {
  constructor(buttons) {
    this.buttons = buttons;
  }
  onAdd() {
    this.el = document.createElement("div");
    this.el.className = "maplibregl-ctrl maplibregl-ctrl-group tools";
    for (const [label, onClick] of this.buttons) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", () => b.setAttribute("aria-pressed", String(onClick())));
      this.el.append(b);
    }
    return this.el;
  }
  onRemove() {
    this.el.remove();
  }
}

function start(maps) {
  maplibregl.addProtocol("deck", tiles(maps));
  const map = new maplibregl.Map({
    container: "map",
    style: style(maps),
    bounds: CZECHIA,
    maxZoom: Math.max(...maps.map((m) => m.maxZoom)) + 2,
    hash: true, // the view is kept in the address: a reload (e.g. after an import) stays put
    attributionControl: false,
  });
  map.dragRotate.disable(); // north stays up: simpler to read, ruler and grid stay straight
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  map.addControl(new maplibregl.ScaleControl({ unit: "metric", maxWidth: 150 }), "bottom-left");
  map.addControl(
    new maplibregl.AttributionControl({ compact: false, customAttribution: ATTRIBUTION }),
  );

  // ruler: each click adds a point; legs and total in the box, running total at each point
  const panel = document.getElementById("ruler");
  const text = document.getElementById("ruler-text");
  let measuring = false;
  let points = [];
  const drawRuler = () => {
    let total = 0;
    const legs = [];
    const features = points.map((p, i) => {
      if (i > 0) {
        const leg = haversine(points[i - 1], p);
        legs.push(formatDistance(leg));
        total += leg;
      }
      return {
        type: "Feature",
        properties: { label: i ? formatDistance(total) : "" },
        geometry: { type: "Point", coordinates: p },
      };
    });
    if (points.length > 1)
      features.push({
        type: "Feature",
        properties: {},
        geometry: { type: "LineString", coordinates: points },
      });
    map.getSource("ruler").setData({ type: "FeatureCollection", features });
    text.textContent = legs.length
      ? `Total ${formatDistance(total)}` + (legs.length > 1 ? ` (legs: ${legs.join(", ")})` : "")
      : "Click on the map to measure.";
  };
  const toggleRuler = () => {
    measuring = !measuring;
    panel.hidden = !measuring;
    map.getCanvas().style.cursor = measuring ? "crosshair" : "";
    points = [];
    drawRuler();
    return measuring;
  };
  document.getElementById("ruler-clear").addEventListener("click", () => {
    points = [];
    drawRuler();
  });
  map.on("click", (e) => {
    if (!measuring) return;
    points.push([e.lngLat.lng, e.lngLat.lat]);
    drawRuler();
  });

  // grid: lat/lon lines with labels, spacing by zoom, redrawn after each move
  let grid = false;
  const drawGrid = () => {
    if (!grid) return map.getSource("grid").setData(NOTHING);
    const b = map.getBounds();
    const view = [b.getWest(), Math.max(b.getSouth(), -85), b.getEast(), Math.min(b.getNorth(), 85)];
    map.getSource("grid").setData(gridLines(view, gridStep(map.getZoom())));
  };
  const toggleGrid = () => {
    grid = !grid;
    drawGrid();
    return grid;
  };
  map.on("moveend", () => grid && drawGrid());

  map.on("load", () => {
    const ink = dark ? "#e4e9e6" : "#1d2420";
    const halo = dark ? "#121614" : "#ffffff";
    map.addSource("grid", { type: "geojson", data: NOTHING });
    map.addSource("ruler", { type: "geojson", data: NOTHING });
    map.addLayer({
      id: "grid-lines",
      type: "line",
      source: "grid",
      paint: { "line-color": ink, "line-opacity": 0.35, "line-width": 1 },
    });
    map.addLayer({
      id: "grid-labels",
      type: "symbol",
      source: "grid",
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": 400,
        "text-field": ["get", "label"],
        "text-font": FONT,
        "text-size": 11,
      },
      paint: { "text-color": ink, "text-halo-color": halo, "text-halo-width": 1.5 },
    });
    map.addLayer({
      id: "ruler-line",
      type: "line",
      source: "ruler",
      filter: ["==", "$type", "LineString"],
      paint: { "line-color": "#c0392b", "line-width": 3, "line-dasharray": [2, 1] },
    });
    map.addLayer({
      id: "ruler-points",
      type: "circle",
      source: "ruler",
      filter: ["==", "$type", "Point"],
      paint: {
        "circle-radius": 5,
        "circle-color": "#c0392b",
        "circle-stroke-color": halo,
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "ruler-labels",
      type: "symbol",
      source: "ruler",
      filter: ["==", "$type", "Point"],
      layout: {
        "text-field": ["get", "label"],
        "text-font": FONT,
        "text-size": 13,
        "text-offset": [0, -1.2],
        "text-allow-overlap": true,
      },
      paint: { "text-color": "#c0392b", "text-halo-color": halo, "text-halo-width": 2 },
    });
    map.addControl(
      new Tools([
        ["Ruler", toggleRuler],
        ["Grid", toggleGrid],
      ]),
    );
  });
  addEventListener(
    "keydown",
    (e) => e.key === "Escape" && measuring && document.querySelector(".tools button").click(),
  );
}

const maps = await loadMaps();
if (maps.length) {
  start(maps);
} else {
  const notice = document.getElementById("notice");
  const content = `https://${location.host.replace(/^maps\./, "content.")}/`;
  notice.hidden = false;
  notice.innerHTML = `No maps installed — import one on the <a href="${content}">Content</a> page.`;
}
