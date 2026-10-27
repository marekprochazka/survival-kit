// Map maths for the maps page — no DOM, no MapLibre.

const R = 6371008.8; // mean Earth radius in metres

// [west, south, east, north] in degrees of tile z/x/y (Web Mercator, like MapLibre)
export function tileBounds(z, x, y) {
  const n = 2 ** z;
  const lon = (i) => (i / n) * 360 - 180;
  const lat = (j) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * j) / n))) * 180) / Math.PI;
  return [lon(x), lat(y + 1), lon(x + 1), lat(y)];
}

// tile entirely inside bounds [w, s, e, n]
export function covers(b, z, x, y) {
  const [w, s, e, n] = tileBounds(z, x, y);
  return w >= b[0] && s >= b[1] && e <= b[2] && n <= b[3];
}

// tile touches bounds at all
export function intersects(b, z, x, y) {
  const [w, s, e, n] = tileBounds(z, x, y);
  return w < b[2] && e > b[0] && s < b[3] && n > b[1];
}

// Should `map` hand tile z/x/y to a more detailed map (and draw nothing there)?
// Maps cut with `pmtiles extract` hold *whole* tiles wherever they touch their area, so
// below map's own max zoom (the browser shows both maps at that same zoom) touching is
// enough. At map's max zoom the tile may be stretched far deeper, where the detailed map
// only has its own area — then it must lie fully inside, or we'd leave a gap.
export function yields(map, maps, z, x, y) {
  return maps.some(
    (o) =>
      o.maxZoom > map.maxZoom &&
      z >= o.minZoom &&
      (z < map.maxZoom ? intersects(o.bounds, z, x, y) : covers(o.bounds, z, x, y)),
  );
}

// great-circle distance in metres between [lon, lat] points
export function haversine([lon1, lat1], [lon2, lat2]) {
  const rad = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// "850 m" (under 1 km, to 10 m), "12.4 km" (under 100 km), "250 km"
export function formatDistance(m) {
  if (m < 1000) return `${Math.round(m / 10) * 10} m`;
  if (m < 100000) return `${(m / 1000).toFixed(1)} km`;
  return `${Math.round(m / 1000)} km`;
}

// grid spacing in degrees for a zoom level
export function gridStep(zoom) {
  if (zoom < 4) return 10;
  if (zoom < 6) return 5;
  if (zoom < 8) return 1;
  if (zoom < 10) return 0.5;
  if (zoom < 12) return 0.1;
  return 0.05;
}

// GeoJSON lines every `step` degrees across view [w, s, e, n], each labelled ("50.1°N")
export function gridLines([w, s, e, n], step) {
  const round = (v) => +v.toFixed(6); // 0.1 * 3 → 0.3, not 0.30000000000000004
  const features = [];
  for (let lon = Math.ceil(w / step) * step; lon <= e; lon += step) {
    const v = round(lon);
    features.push(line([[v, s], [v, n]], `${Math.abs(v)}°${v < 0 ? "W" : "E"}`));
  }
  for (let lat = Math.ceil(s / step) * step; lat <= n; lat += step) {
    const v = round(lat);
    features.push(line([[w, v], [e, v]], `${Math.abs(v)}°${v < 0 ? "S" : "N"}`));
  }
  return { type: "FeatureCollection", features };
}

const line = (coordinates, label) => ({
  type: "Feature",
  properties: { label },
  geometry: { type: "LineString", coordinates },
});
