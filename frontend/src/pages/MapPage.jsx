// Where COLAs come from, geographically. Two readings of the same data: a heat
// surface for density, and label thumbnails for what is actually there.
//
// The viewport is the query. Everything else — mode, role, filters — is URL
// state so a view can be linked, and the map refetches whenever the user stops
// moving.

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import Icon from '../components/Icon.jsx';
import Combobox, { matchOptions } from '../components/Combobox.jsx';
import { CatTag, StatusBadge } from '../components/Badges.jsx';
import { api } from '../lib/api.js';
import { track } from '../lib/analytics.js';
import { fmtDate } from '../lib/format.js';
import { useAsync } from '../hooks/useAsync.js';
import { useDocumentTitle } from '../hooks/useDocumentTitle.js';

// maplibre is by far the largest thing this site loads; keeping it out of the
// main bundle means the search page is unaffected by the map existing.
const MapView = lazy(() => import('../components/MapView.jsx'));

const FILTER_KEYS = ['commodity', 'source', 'origin', 'classType', 'varietal', 'dateFrom', 'dateTo'];

const MODES = [
  { key: 'heat', label: 'Heat', icon: 'layers', hint: 'Density of approvals' },
  { key: 'image', label: 'Labels', icon: 'image', hint: 'Individual label images' },
];

// A COLA has a permit address and a product origin, and they are often nowhere
// near each other. Which one is plotted changes what the map means, so it is a
// first-class control rather than a filter.
const ROLES = [
  { key: 'primary_premise', label: 'Permit address', hint: 'Where the applicant is licensed' },
  { key: 'product_origin', label: 'Product origin', hint: 'Where the product is stated to come from' },
];

const num = (n) => Number(n || 0).toLocaleString();

const CHIP_LABELS = {
  commodity: 'Commodity',
  source: 'Source',
  origin: 'Origin',
  classType: 'Class/Type',
  varietal: 'Varietal',
  dateFrom: 'From',
  dateTo: 'To',
};

function paramsToObject(sp) {
  const o = {};
  for (const [k, v] of sp.entries()) o[k] = v;
  return o;
}

/* ---------- controls ---------- */
function Segmented({ options, value, onChange, label }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          className={value === o.key ? 'active' : ''}
          title={o.hint}
          aria-pressed={value === o.key}
          onClick={() => onChange(o.key)}
        >
          {o.icon ? <Icon name={o.icon} size={14} /> : null}
          {o.label}
        </button>
      ))}
    </div>
  );
}

function FilterSelect({ label, name, value, options, onChange }) {
  const list = options || [];
  if (!list.length && !value) return null;
  // A value can survive in the URL after the reference list changes; keep it
  // listed so the control never misreports itself as unfiltered.
  const all = value && !list.includes(value) ? [value, ...list] : list;
  return (
    <label className="map-filter">
      <span className="d-label">{label}</span>
      <select className="select" value={value || ''} onChange={(e) => onChange(name, e.target.value)}>
        <option value="">All</option>
        {all.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function ActiveChips({ criteria, onClear }) {
  const items = FILTER_KEYS.filter((k) => criteria[k]);
  if (!items.length) return null;
  return (
    <div className="chips map-chips">
      {items.map((k) => (
        <span className="chip" key={k}>
          {CHIP_LABELS[k]}: {criteria[k]}
          <button onClick={() => onClear(k)} aria-label={`Remove ${CHIP_LABELS[k]} filter`}>
            <Icon name="close" size={12} />
          </button>
        </span>
      ))}
    </div>
  );
}

/* ---------- area drill-in ---------- */
function Breakdown({ title, buckets, total }) {
  if (!buckets || !buckets.length) return null;
  return (
    <div className="map-breakdown">
      <div className="d-label">{title}</div>
      {buckets.slice(0, 5).map((b) => (
        <div className="map-bar" key={b.value}>
          <span className="map-bar-label">{b.value}</span>
          <span className="map-bar-track">
            <span style={{ width: `${total > 0 ? (b.count / total) * 100 : 0}%` }} />
          </span>
          <span className="map-bar-count mono">{num(b.count)}</span>
        </div>
      ))}
    </div>
  );
}

function AreaPanel({ state, onClose }) {
  const { data, loading, error } = state;
  return (
    <aside className="map-panel panel" aria-label="Selected area">
      <div className="row between">
        <div className="section-title">Selected area</div>
        <button className="linkbtn" onClick={onClose} aria-label="Close area summary">
          <Icon name="close" size={16} />
        </button>
      </div>

      {loading ? (
        <div className="skel" style={{ height: 180, marginTop: 12 }} />
      ) : error ? (
        <p className="muted an-note">This area could not be summarised. Try again in a moment.</p>
      ) : !data || !data.total ? (
        <p className="muted an-note">No geocoded COLAs fall inside this part of the map.</p>
      ) : (
        <>
          <div className="map-total">
            <strong>{data.totalIsCapped ? `${num(data.total)}+` : num(data.total)}</strong>
            <span className="muted"> approvals here</span>
          </div>

          <Breakdown title="Commodity" buckets={data.commodity} total={data.total} />
          <Breakdown title="Source" buckets={data.source} total={data.total} />
          <Breakdown title="Origin" buckets={data.origin} total={data.total} />

          <div className="d-label" style={{ marginTop: 14 }}>Records</div>
          <div className="map-items">
            {(data.items || []).map((r) => (
              <Link className="map-item" key={r.id} to={`/cola/${encodeURIComponent(r.id)}`}>
                <div className="map-item-main">
                  <div className="map-item-brand">{r.brand || r.ttbId}</div>
                  <div className="map-item-meta muted">
                    <span className="mono">{r.ttbId}</span>
                    {r.origin ? <span> · {r.origin}</span> : null}
                    {r.approvalDate ? <span> · {fmtDate(r.approvalDate)}</span> : null}
                  </div>
                  <div className="row gap-8" style={{ marginTop: 4 }}>
                    <CatTag rec={r} />
                    <StatusBadge status={r.status} />
                  </div>
                </div>
                <Icon name="chevRight" size={16} className="muted" />
              </Link>
            ))}
          </div>
          {data.totalIsCapped || (data.items || []).length < data.total ? (
            <p className="muted an-note">
              Showing the most recent {num((data.items || []).length)}. Zoom in to narrow the area.
            </p>
          ) : null}
        </>
      )}
    </aside>
  );
}

/* ---------- main ---------- */
export default function MapPage() {
  useDocumentTitle('Map');
  const [searchParams, setSearchParams] = useSearchParams();
  const criteria = paramsToObject(searchParams);

  const mode = criteria.mode === 'image' ? 'image' : 'heat';
  const role = ROLES.some((r) => r.key === criteria.role) ? criteria.role : 'primary_premise';

  const [viewport, setViewport] = useState(null);
  const [area, setArea] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const lastMode = useRef(mode);

  // Deep links can name a starting place; after that the map owns its own view.
  const initialView = useMemo(() => {
    const lat = parseFloat(criteria.lat);
    const lng = parseFloat(criteria.lng);
    if (Number.isNaN(lat) || Number.isNaN(lng)) return undefined;
    return { center: [lng, lat], zoom: parseFloat(criteria.zoom) || 9 };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filters = useMemo(() => {
    const p = {};
    FILTER_KEYS.forEach((k) => {
      if (criteria[k]) p[k] = criteria[k];
    });
    return p;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.toString()]);

  const filterKey = JSON.stringify(filters);
  const viewKey = viewport
    ? [viewport.west, viewport.south, viewport.east, viewport.north, viewport.zoom].map((n) => n.toFixed(3)).join(',')
    : '';

  const reference = useAsync((signal) => api.reference(signal), [], { cacheKey: 'reference' });

  const pointsState = useAsync(
    (signal) => api.mapPoints({ ...viewport, center: undefined, mode, role, ...filters }, signal),
    [viewKey, mode, role, filterKey],
    { skip: !viewport }
  );

  const areaState = useAsync(
    (signal) => api.mapArea({ ...area, role, ...filters }, signal),
    [area ? JSON.stringify(area) : '', role, filterKey],
    { skip: !area }
  );

  // A 503 here means the geocoded surface has not been built for this
  // deployment. That is a different message from "nothing in view".
  useEffect(() => {
    if (pointsState.error?.status === 503) setUnavailable(true);
    else if (pointsState.data) setUnavailable(false);
  }, [pointsState.error, pointsState.data]);

  useEffect(() => {
    if (lastMode.current !== mode) {
      track('map_mode_changed', { mode, role });
      lastMode.current = mode;
    }
  }, [mode, role]);

  function patch(mutator) {
    const next = paramsToObject(searchParams);
    mutator(next);
    setSearchParams(next, { replace: true });
  }

  const setMode = (next) => patch((p) => { p.mode = next; });
  const setRole = (next) => {
    track('map_role_changed', { role: next, mode });
    patch((p) => { p.role = next; });
  };
  const setFilter = (name, value) =>
    patch((p) => {
      if (value) p[name] = value;
      else delete p[name];
    });

  const onViewportChange = useCallback((v) => setViewport(v), []);

  const onSelectArea = useCallback(
    (box) => {
      track('map_area_opened', { mode });
      setArea(box);
    },
    [mode]
  );

  const onSelectPoint = useCallback(
    (point) => {
      track('map_marker_clicked', { mode });
      // A single label is a small box around itself, so the panel is the same
      // component whether the user clicked a pin or empty space.
      setArea({ west: point.lng - 0.02, south: point.lat - 0.02, east: point.lng + 0.02, north: point.lat + 0.02 });
    },
    [mode]
  );

  const data = pointsState.data;
  const total = data?.total || 0;
  const facets = reference.data || {};
  // Domestic and imported origins are separate lists upstream; the map filters
  // on the single origin column, so they are one control here.
  const origins = useMemo(
    () => [...(facets.domesticOrigins || []), ...(facets.importedOrigins || [])].sort((a, b) => a.localeCompare(b)),
    [facets.domesticOrigins, facets.importedOrigins]
  );
  // The map surface only recently gained a varietal column; where it is absent
  // the API rejects the filter, so the control is not offered at all.
  const varietalReady = Boolean(data?.varietalAvailable);
  const varietalOptions = useMemo(
    () => matchOptions(facets.varietals || [], criteria.varietal || ''),
    [facets.varietals, criteria.varietal]
  );

  return (
    <div className="map-page">
      <div className="map-bar">
        <div className="wrap">
          <div className="map-controls">
            <Segmented options={MODES} value={mode} onChange={setMode} label="Map mode" />
            <Segmented options={ROLES} value={role} onChange={setRole} label="Location plotted" />

            <FilterSelect label="Commodity" name="commodity" value={criteria.commodity} options={facets.categories} onChange={setFilter} />
            <FilterSelect label="Source" name="source" value={criteria.source} options={facets.sources} onChange={setFilter} />
            <FilterSelect label="Origin" name="origin" value={criteria.origin} options={origins} onChange={setFilter} />

            {varietalReady ? (
              <label className="map-filter map-filter-wide">
                <span className="d-label">Varietal</span>
                <Combobox
                  ariaLabel="Grape varietal"
                  placeholder="Any varietal"
                  value={criteria.varietal || ''}
                  onChange={(v) => setFilter('varietal', v)}
                  options={varietalOptions}
                  emptyText="No matching varietal"
                />
              </label>
            ) : null}

            <label className="map-filter">
              <span className="d-label">Approved from</span>
              <input className="input" type="date" value={criteria.dateFrom || ''} onChange={(e) => setFilter('dateFrom', e.target.value)} />
            </label>
            <label className="map-filter">
              <span className="d-label">to</span>
              <input className="input" type="date" value={criteria.dateTo || ''} onChange={(e) => setFilter('dateTo', e.target.value)} />
            </label>
          </div>

          <div className="map-status">
            <ActiveChips criteria={criteria} onClear={(k) => setFilter(k, '')} />
            <span className="muted map-count">
              {pointsState.loading
                ? 'Loading…'
                : unavailable
                  ? ''
                  : `${data?.totalIsCapped ? `${num(total)}+` : num(total)} in view`}
            </span>
          </div>
        </div>
      </div>

      <div className={`map-stage${area ? ' has-panel' : ''}`} data-tour="map-stage">
        <Suspense fallback={<div className="skel map-canvas" />}>
          <MapView
            mode={mode}
            bins={data?.bins}
            points={data?.points}
            view={initialView}
            onViewportChange={onViewportChange}
            onSelectArea={onSelectArea}
            onSelectPoint={onSelectPoint}
          />
        </Suspense>

        {unavailable ? (
          <div className="map-overlay panel">
            <Icon name="pin" size={28} className="muted" />
            <h3>Locations are not available yet</h3>
            <p className="muted">
              Permit and origin addresses have not been geocoded for this deployment, so there is
              nothing to plot. Coverage will show the geocoding progress once it starts.
            </p>
            <Link className="btn secondary sm" to="/coverage">View coverage</Link>
          </div>
        ) : !pointsState.loading && viewport && total === 0 ? (
          <div className="map-overlay panel">
            <h3>Nothing in view</h3>
            <p className="muted">No geocoded approvals match these filters here. Zoom out or clear a filter.</p>
          </div>
        ) : null}

        {area ? <AreaPanel state={areaState} onClose={() => setArea(null)} /> : null}
      </div>

      <p className="wrap muted an-note map-note">
        Only COLAs whose {role === 'product_origin' ? 'stated origin' : 'permit address'} has been
        geocoded appear here, and a geocode is an approximation of an address, not a production
        site. {mode === 'image' ? 'Label mode shows the most recent approvals in view, not all of them.' : ''}
      </p>
    </div>
  );
}
