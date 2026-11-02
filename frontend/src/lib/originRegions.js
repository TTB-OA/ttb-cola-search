// Outlines for product origins. An origin is a U.S. state or a country, and its
// coordinates are only a representative centroid, so a pin on it suggests a
// precision the record does not have. Drawing the whole area says what is
// actually known.
//
// The boundaries are static Natural Earth / Census cartographic data shipped as
// TopoJSON. This module is imported dynamically so the ~750KB of country shapes
// only load on a record that has an origin to draw.

import { feature } from 'topojson-client';
import countriesTopo from 'world-atlas/countries-50m.json';
import statesTopo from 'us-atlas/states-10m.json';

// Natural Earth abbreviates long names ("Dominican Rep.", "St. Kitts and
// Nevis"), so both sides are expanded to the same spelling before comparing.
const ABBREVIATIONS = [
  [/\brep\b/g, 'republic'],
  [/\bdem\b/g, 'democratic'],
  [/\bis\b/g, 'islands'],
  [/\bi\b/g, 'island'],
  [/\bst\b/g, 'saint'],
  [/\bsts\b/g, 'saints'],
  [/\bherz\b/g, 'herzegovina'],
  [/\bbarb\b/g, 'barbuda'],
  [/\bgren\b/g, 'grenadines'],
  [/\bvin\b/g, 'vincent'],
  [/\beq\b/g, 'equatorial'],
  [/\bn\b/g, 'north'],
  [/\bs\b/g, 'south'],
  [/\bw\b/g, 'western'],
  [/\bfr\b/g, 'french'],
  [/\bbr\b/g, 'british'],
  [/\bter\b/g, 'territory'],
  [/\b(the|of|and)\b/g, ' '],
];

// Names that differ by more than an abbreviation. Keys and values are both
// normalised spellings.
const ALIASES = {
  'united states america': 'united states',
  usa: 'united states',
  'czech republic': 'czechia',
  'ivory coast': 'cote d ivoire',
  'republic korea': 'south korea',
  'korea south': 'south korea',
  'korea republic': 'south korea',
  'north macedonia': 'macedonia',
  'great britain': 'united kingdom',
  'faroe islands': 'faeroe islands',
  'democratic republic congo': 'congo democratic republic',
  'congo democratic republic': 'congo democratic republic',
  'russian federation': 'russia',
  'viet nam': 'vietnam',
  'holland': 'netherlands',
  'swaziland': 'eswatini',
  'burma': 'myanmar',
};

function normalize(name) {
  let s = String(name || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ');
  for (const [re, to] of ABBREVIATIONS) s = s.replace(re, to);
  s = s.replace(/\s+/g, ' ').trim();
  return ALIASES[s] || s;
}

function index(collection) {
  const byName = new Map();
  for (const f of collection.features) {
    if (f.geometry) byName.set(normalize(f.properties?.name), f);
  }
  return byName;
}

const states = feature(statesTopo, statesTopo.objects.states);
const countries = feature(countriesTopo, countriesTopo.objects.countries);
const stateByName = index(states);
const countryByName = index(countries);

function polygonsOf(geometry) {
  if (!geometry) return [];
  if (geometry.type === 'Polygon') return [geometry.coordinates];
  if (geometry.type === 'MultiPolygon') return geometry.coordinates;
  return [];
}

function ringContains(ring, lng, lat) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function polygonContains(polygon, lng, lat) {
  if (!ringContains(polygon[0], lng, lat)) return false;
  for (let h = 1; h < polygon.length; h++) if (ringContains(polygon[h], lng, lat)) return false;
  return true;
}

function bboxOf(polygons) {
  let w = Infinity;
  let s = Infinity;
  let e = -Infinity;
  let n = -Infinity;
  for (const poly of polygons) {
    for (const [x, y] of poly[0]) {
      if (x < w) w = x;
      if (x > e) e = x;
      if (y < s) s = y;
      if (y > n) n = y;
    }
  }
  return [w, s, e, n];
}

function bboxArea([w, s, e, n]) {
  return (e - w) * (n - s);
}

// The area a viewport should frame. A country's full extent can be useless for
// that: France's includes French Guiana, the United States' Guam, and anything
// touching the antimeridian spans the globe. So the frame is the part holding
// the centroid (or the largest part) plus whatever lies close to it, which keeps
// Sicily with Italy and Hokkaido with Japan but leaves overseas territories out.
function frameOf(polygons, lng, lat) {
  const boxes = polygons.map((p) => bboxOf([p]));
  let main = polygons.findIndex((p) => polygonContains(p, lng, lat));
  if (main < 0) {
    main = 0;
    boxes.forEach((b, i) => {
      if (bboxArea(b) > bboxArea(boxes[main])) main = i;
    });
  }
  const [mw, ms, me, mn] = boxes[main];
  const reach = Math.max(2, me - mw, mn - ms);
  const near = [mw - reach, ms - reach, me + reach, mn + reach];
  const frame = [mw, ms, me, mn];
  boxes.forEach(([w, s, e, n]) => {
    if (e < near[0] || w > near[2] || n < near[1] || s > near[3]) return;
    // Still guards against a part that wraps the antimeridian.
    if (Math.max(e, frame[2]) - Math.min(w, frame[0]) > 180) return;
    frame[0] = Math.min(frame[0], w);
    frame[1] = Math.min(frame[1], s);
    frame[2] = Math.max(frame[2], e);
    frame[3] = Math.max(frame[3], n);
  });
  return frame;
}

function region(geometry, name, lng, lat) {
  const polygons = polygonsOf(geometry);
  if (!polygons.length) return null;
  return { name, geometry, bounds: frameOf(polygons, lng, lat) };
}

// How far (in degrees) a centroid may sit outside a named shape's outline and
// still confirm the name: curated centroids of small or coastal places can land
// just offshore.
const NEAR_DEG = 1;

function nearFeature(f, lng, lat) {
  return polygonsOf(f.geometry).some((p) => {
    if (polygonContains(p, lng, lat)) return true;
    const [w, s, e, n] = bboxOf([p]);
    return lng >= w - NEAR_DEG && lng <= e + NEAR_DEG && lat >= s - NEAR_DEG && lat <= n + NEAR_DEG;
  });
}

function largestPolygon(polygons) {
  let best = polygons[0];
  for (const p of polygons) if (bboxArea(bboxOf([p])) > bboxArea(bboxOf([best]))) best = p;
  return best;
}

// Resolves an origin to the area it names. Names are tried first, states
// before countries, and a name only counts when the centroid lies on or near
// the shape it names: "Georgia" is both a U.S. state and a country, and the
// centroid is what tells them apart.
//
// Failing a name, the centroid's position is used, but only when it lands on a
// detached part of a country: an origin such as Martinique is drawn by Natural
// Earth as an island of France, and outlining that island is right. A centroid
// on a country's main landmass says nothing about what the origin is, since a
// region ("Scotland" lands on Great Britain) or a group of countries ("European
// Union" lands on Germany) would outline the wrong area. Those keep their pin.
//
// States are never matched by position alone, since a multi-state or
// nationwide origin would have its centroid land in whatever state is central.
export function resolveOriginRegion({ names, lng, lat }) {
  const keys = (names || []).filter(Boolean).map(normalize);
  const located = Number.isFinite(lng) && Number.isFinite(lat);
  const fits = (f) => f && (!located || nearFeature(f, lng, lat));
  for (const byName of [stateByName, countryByName]) {
    for (const key of keys) {
      const f = byName.get(key);
      if (fits(f)) return region(f.geometry, f.properties.name, lng, lat);
    }
  }
  if (!located) return null;
  for (const f of countries.features) {
    const polygons = polygonsOf(f.geometry);
    const hit = polygons.find((p) => polygonContains(p, lng, lat));
    if (!hit) continue;
    if (polygons.length < 2 || hit === largestPolygon(polygons)) return null;
    return region({ type: 'Polygon', coordinates: hit }, f.properties.name, lng, lat);
  }
  return null;
}
