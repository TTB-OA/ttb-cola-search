// MapLibre wrapper for the COLA map. Everything MapLibre-specific lives here so
// the pages stay declarative: they hand over data and a viewport, and get
// viewport changes and clicks back.
//
// The basemap is a single PMTiles archive read through the API by byte range,
// so there is no tile server and no per-tile metering. If it has not been
// provisioned the map still works — it just draws on an empty background.

import { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import { Protocol } from 'pmtiles';
import layers from 'protomaps-themes-base';
import { api } from '../lib/api.js';
import 'maplibre-gl/dist/maplibre-gl.css';

const SOURCE = 'protomaps';
const HEAT_SOURCE = 'cola-heat';
const HEAT_LAYER = 'cola-heat-layer';
const AREA_SOURCE = 'cola-area';
const AREA_FILL = 'cola-area-fill';
const AREA_LINE = 'cola-area-line';
// --blue-dark; MapLibre paint cannot read a CSS custom property.
const AREA_COLOR = '#1a4480';
const ATTRIBUTION = '<a href="https://openstreetmap.org">OpenStreetMap</a> via <a href="https://protomaps.com">Protomaps</a>';

// maplibre resolves pmtiles:// URLs through a global protocol handler, so this
// is registered once for the module rather than per map instance.
let protocolRegistered = false;
function registerProtocol() {
  if (protocolRegistered) return;
  maplibregl.addProtocol('pmtiles', new Protocol().tile);
  protocolRegistered = true;
}

// One probe per page load: a missing basemap is a deployment state, not a
// per-map condition, and MapLibre gives no usable error for it.
let basemapProbe = null;
function basemapAvailable() {
  if (!basemapProbe) {
    basemapProbe = fetch(api.basemapUrl(), { headers: { Range: 'bytes=0-15' } })
      .then((res) => res.ok)
      .catch(() => false);
  }
  return basemapProbe;
}

const BLANK_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#eef1f5' } }],
};

function basemapStyle() {
  return {
    version: 8,
    glyphs: `${api.basemapUrl().replace(/\/basemap$/, '')}/glyphs/{fontstack}/{range}.pbf`,
    sources: {
      [SOURCE]: {
        type: 'vector',
        url: `pmtiles://${new URL(api.basemapUrl(), window.location.origin).href}`,
        attribution: ATTRIBUTION,
      },
    },
    layers: layers(SOURCE, 'light', { lang: 'en' }),
  };
}

function toGeoJson(bins) {
  return {
    type: 'FeatureCollection',
    features: (bins || []).map((b) => ({
      type: 'Feature',
      properties: { count: b.count },
      geometry: { type: 'Point', coordinates: [b.lng, b.lat] },
    })),
  };
}

function areaGeoJson(area) {
  if (!area) return { type: 'FeatureCollection', features: [] };
  const { west, south, east, north } = area;
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
        },
      },
    ],
  };
}

// Counts across a viewport routinely span four orders of magnitude, so weight
// is taken from the log: a linear ramp would render everything outside the
// densest metro as blank.
function heatPaint(maxCount) {
  const top = Math.max(1, Math.log10(Math.max(1, maxCount)) + 1);
  return {
    'heatmap-weight': ['interpolate', ['linear'], ['log10', ['max', ['get', 'count'], 1]], 0, 0.15, top, 1],
    'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 0.8, 9, 2.2],
    // Server bins sit 11-23 CSS px apart depending on the zoom fraction, so the
    // radius has to stay well above that or the grid shows through as dots.
    'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 30, 10, 40, 16, 48],
    'heatmap-opacity': 0.82,
    'heatmap-color': [
      'interpolate',
      ['linear'],
      ['heatmap-density'],
      0, 'rgba(0,0,0,0)',
      0.15, 'rgba(120,168,214,0.55)',
      0.35, 'rgba(94,200,178,0.75)',
      0.6, 'rgba(243,199,94,0.85)',
      0.85, 'rgba(226,122,64,0.9)',
      1, 'rgba(190,52,52,0.95)',
    ],
  };
}

function markerElement(point, onSelect) {
  const el = document.createElement('button');
  el.type = 'button';
  el.className = 'map-pin';
  el.title = point.brand || point.id;
  el.setAttribute('aria-label', point.brand ? `${point.brand} label` : `COLA ${point.id}`);
  if (point.thumbUrl) {
    const img = document.createElement('img');
    img.src = point.thumbUrl;
    img.alt = '';
    img.loading = 'lazy';
    // A label that fails to load would otherwise leave a broken-image pin.
    img.onerror = () => el.classList.add('is-blank');
    el.appendChild(img);
  } else {
    el.classList.add('is-blank');
  }
  el.addEventListener('click', (e) => {
    e.stopPropagation();
    onSelect(point);
  });
  return el;
}

export default function MapView({
  mode = 'heat',
  bins,
  points,
  area,
  view,
  interactive = true,
  onViewportChange,
  onSelectArea,
  onSelectPoint,
  className = '',
}) {
  const holder = useRef(null);
  const map = useRef(null);
  const markers = useRef([]);
  const handlers = useRef({});
  const [ready, setReady] = useState(false);

  // Callbacks change on every render of the page; keeping them in a ref means
  // the map is built once instead of being torn down and rebuilt.
  handlers.current = { onViewportChange, onSelectArea, onSelectPoint };

  const initial = useMemo(() => view || { center: [-96, 38.5], zoom: 3.4 }, []);

  useEffect(() => {
    let cancelled = false;
    registerProtocol();

    basemapAvailable().then((ok) => {
      if (cancelled || !holder.current) return;
      const instance = new maplibregl.Map({
        container: holder.current,
        style: ok ? basemapStyle() : BLANK_STYLE,
        center: initial.center,
        zoom: initial.zoom,
        interactive,
        attributionControl: ok ? { compact: true } : false,
        // Wrapping duplicates every marker across copies of the world and makes
        // the reported viewport ambiguous.
        renderWorldCopies: false,
        maxZoom: 16,
      });
      map.current = instance;

      if (interactive) {
        instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
        instance.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), 'top-right');
      }

      let timer = null;
      const report = (m) => {
        const b = m.getBounds();
        handlers.current.onViewportChange?.({
          west: b.getWest(),
          south: b.getSouth(),
          east: b.getEast(),
          north: b.getNorth(),
          zoom: Math.round(m.getZoom()),
          center: m.getCenter(),
        });
      };

      instance.on('load', () => {
        instance.addSource(HEAT_SOURCE, { type: 'geojson', data: toGeoJson([]) });
        instance.addLayer({ id: HEAT_LAYER, type: 'heatmap', source: HEAT_SOURCE, paint: heatPaint(1) });

        instance.addSource(AREA_SOURCE, { type: 'geojson', data: areaGeoJson(null) });
        // Added after the heat layer so the box reads on top of the density it
        // is selecting; the fill is barely there so it does not tint the counts.
        instance.addLayer({
          id: AREA_FILL,
          type: 'fill',
          source: AREA_SOURCE,
          paint: { 'fill-color': AREA_COLOR, 'fill-opacity': 0.08 },
        });
        instance.addLayer({
          id: AREA_LINE,
          type: 'line',
          source: AREA_SOURCE,
          paint: { 'line-color': AREA_COLOR, 'line-width': 2, 'line-dasharray': [3, 2] },
        });

        setReady(true);
        report(instance);
      });

      instance.on('moveend', () => {
        // Panning fires a burst of these; refetching on each one would spend the
        // rate limit on viewports the user never stopped at.
        clearTimeout(timer);
        timer = setTimeout(() => report(instance), 250);
      });

      instance.on('click', (e) => {
        if (!handlers.current.onSelectArea) return;
        // Box a click into a small area rather than a point: the underlying data
        // is binned, so a bare coordinate would almost never hit anything.
        const span = 40 / 2 ** instance.getZoom() * 6;
        handlers.current.onSelectArea({
          west: e.lngLat.lng - span,
          south: e.lngLat.lat - span / 2,
          east: e.lngLat.lng + span,
          north: e.lngLat.lat + span / 2,
        });
      });
    });

    return () => {
      cancelled = true;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      map.current?.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive]);

  // Heat bins
  useEffect(() => {
    const instance = map.current;
    if (!instance || !ready) return;
    const source = instance.getSource(HEAT_SOURCE);
    if (!source) return;
    const active = mode === 'heat';
    source.setData(toGeoJson(active ? bins : []));
    instance.setLayoutProperty(HEAT_LAYER, 'visibility', active ? 'visible' : 'none');
    if (active && bins && bins.length) {
      const paint = heatPaint(Math.max(...bins.map((b) => b.count)));
      Object.entries(paint).forEach(([k, v]) => instance.setPaintProperty(HEAT_LAYER, k, v));
    }
  }, [bins, mode, ready]);

  // Selected area box
  useEffect(() => {
    const instance = map.current;
    if (!instance || !ready) return;
    instance.getSource(AREA_SOURCE)?.setData(areaGeoJson(area));
  }, [area?.west, area?.south, area?.east, area?.north, ready]);

  // Image pins
  useEffect(() => {
    const instance = map.current;
    if (!instance || !ready) return;
    markers.current.forEach((m) => m.remove());
    markers.current = [];
    if (mode !== 'image') return;
    (points || []).forEach((p) => {
      const marker = new maplibregl.Marker({ element: markerElement(p, (pt) => handlers.current.onSelectPoint?.(pt)) })
        .setLngLat([p.lng, p.lat])
        .addTo(instance);
      markers.current.push(marker);
    });
  }, [points, mode, ready]);

  // Programmatic recentring, for links that open the map at a known place.
  useEffect(() => {
    if (!map.current || !ready || !view) return;
    map.current.jumpTo({ center: view.center, zoom: view.zoom });
  }, [view?.center?.[0], view?.center?.[1], view?.zoom, ready]);

  return <div ref={holder} className={`map-canvas ${className}`} />;
}
