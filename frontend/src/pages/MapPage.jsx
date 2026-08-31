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
import { useIsMobile } from '../hooks/useIsMobile.js';

// maplibre is by far the largest thing this site loads; keeping it out of the
// main bundle means the search page is unaffected by the map existing.
const MapView = lazy(() => import('../components/MapView.jsx'));

const FILTER_KEYS = ['commodity', 'source', 'origin', 'classType', 'varietal', 'dateFrom', 'dateTo'];

const MODES = [
  { key: 'heat', label: 'Heat', icon: 'layers', hint: 'Density of approvals' },
  { key: 'image', label: 'Labels', icon: 'image', hint: 'Individual label images' },
];

// Two segmented controls plus a filter button do not fit across a phone, so the
// long forms collapse to a word that still distinguishes the two choices.
const SHORT = { primary_premise: 'Permit', product_origin: 'Origin' };

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
function Segmented({ options, value, onChange, label, short }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          className={value === o.key ? 'active' : ''}
          title={o.hint}
          aria-pressed={value === o.key}
          aria-label={o.label}
          onClick={() => onChange(o.key)}
        >
          {o.icon ? <Icon name={o.icon} size={14} /> : null}
          {short && SHORT[o.key] ? SHORT[o.key] : o.label}
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
function Bar({ label, count, total, className }) {
  return (
    <div className={className ? `map-bar ${className}` : 'map-bar'}>
      <span className="map-bar-label">{label}</span>
      <span className="map-bar-track">
        <span style={{ width: `${total > 0 ? (count / total) * 100 : 0}%` }} />
      </span>
      <span className="map-bar-count mono">{num(count)}</span>
    </div>
  );
}

function Breakdown({ title, buckets, total }) {
  if (!buckets || !buckets.length) return null;
  return (
    <div className="map-breakdown">
      <div className="d-label">{title}</div>
      {buckets.slice(0, 5).map((b) => (
        <Bar key={b.value} label={b.value} count={b.count} total={total} />
      ))}
    </div>
  );
}

// Origins are only comparable inside their own source, so each child bar is
// scaled to its group rather than to the area.
function SourceBreakdown({ groups, total }) {
  if (!groups || !groups.length) return null;
  return (
    <div className="map-breakdown">
      <div className="d-label">Source &amp; origin</div>
      {groups.map((g) => (
        <div className="map-group" key={g.value}>
          <Bar label={g.value} count={g.count} total={total} className="map-bar-head" />
          {(g.children || []).slice(0, 5).map((c) => (
            <Bar
              key={c.value}
              label={c.value}
              count={c.count}
              total={g.count}
              className="map-bar-child"
            />
          ))}
        </div>
      ))}
    </div>
  );
}

// A permit takes the position of its most recent COLA, so the grouped list
// keeps the recency order of the page it was built from.
function groupByPermit(items) {
  const groups = [];
  const seen = new Map();
  for (const r of items || []) {
    const key = r.permitId || r.permit || '';
    let group = seen.get(key);
    if (!group) {
      group = { key, code: r.permitId || r.permit, name: r.permitName, items: [] };
      seen.set(key, group);
      groups.push(group);
    }
    group.items.push(r);
  }
  return groups;
}

// On a phone the sheet and the map compete for the same screen, and which one
// matters changes minute to minute, so its height is dragged rather than fixed.
// Fractions of the viewport, smallest first.
const SHEET_SNAPS = [0.28, 0.5, 0.85];
const SHEET_MIN = 0.14;
const SHEET_MAX = 0.9;

const vh = (fraction) => Math.round(window.innerHeight * fraction);
const clampSheet = (px) => Math.min(Math.max(px, vh(SHEET_MIN)), vh(SHEET_MAX));
const snapSheet = (px) =>
  SHEET_SNAPS.map(vh).reduce((best, p) => (Math.abs(p - px) < Math.abs(best - px) ? p : best));

function useSheetResize(enabled) {
  const panelRef = useRef(null);
  const drag = useRef(null);
  const [height, setHeight] = useState(null);

  useEffect(() => {
    setHeight(enabled ? vh(SHEET_SNAPS[1]) : null);
  }, [enabled]);

  // The browser toolbar collapsing counts as a resize, so a height set against
  // the old viewport has to be pulled back into range.
  useEffect(() => {
    if (!enabled) return undefined;
    const onResize = () => setHeight((h) => (h == null ? h : clampSheet(h)));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [enabled]);

  const onPointerDown = (e) => {
    if (!enabled || !panelRef.current) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { y: e.clientY, from: panelRef.current.getBoundingClientRect().height, moved: false };
  };

  const onPointerMove = (e) => {
    if (!drag.current) return;
    const delta = drag.current.y - e.clientY;
    if (Math.abs(delta) > 4) drag.current.moved = true;
    setHeight(clampSheet(drag.current.from + delta));
  };

  const onPointerUp = () => {
    if (!drag.current) return;
    const { moved } = drag.current;
    drag.current = null;
    // A tap is not a drag: cycle through the snap points so the handle still
    // does something obvious for anyone who does not think to drag it.
    setHeight((h) => {
      if (moved) return snapSheet(h);
      const stops = SHEET_SNAPS.map(vh);
      const next = stops.find((p) => p > h + 8);
      return next ?? stops[0];
    });
  };

  const onKeyDown = (e) => {
    const step = vh(0.08);
    if (e.key === 'ArrowUp') setHeight((h) => clampSheet(h + step));
    else if (e.key === 'ArrowDown') setHeight((h) => clampSheet(h - step));
    else if (e.key === 'Home') setHeight(vh(SHEET_MAX));
    else if (e.key === 'End') setHeight(vh(SHEET_MIN));
    else return;
    e.preventDefault();
  };

  const pct = height ? Math.round((height / window.innerHeight) * 100) : 50;

  return {
    panelRef,
    style: height ? { height: `${height}px`, maxHeight: 'none' } : undefined,
    handleProps: {
      role: 'separator',
      'aria-orientation': 'horizontal',
      'aria-label': 'Resize selected area panel',
      'aria-valuemin': Math.round(SHEET_MIN * 100),
      'aria-valuemax': Math.round(SHEET_MAX * 100),
      'aria-valuenow': pct,
      'aria-valuetext': `${pct}% of the screen`,
      tabIndex: enabled ? 0 : -1,
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: onPointerUp,
      onKeyDown,
    },
  };
}

function AreaPanel({ state, onClose, isMobile }) {
  const { data, loading, error } = state;
  const { panelRef, style, handleProps } = useSheetResize(isMobile);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <aside className="map-panel panel" aria-label="Selected area" ref={panelRef} style={style}>
      <div className="map-sheet-grab" {...handleProps} />
      {/* Sticky so the way out stays reachable however far the list is scrolled. */}
      <div className="map-panel-head">
        <div className="section-title">Selected area</div>
        <button type="button" className="btn secondary sm map-clear" onClick={onClose}>
          <Icon name="close" size={14} />
          Clear selection
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
          <SourceBreakdown groups={data.source} total={data.total} />

          <div className="d-label" style={{ marginTop: 14 }}>Records</div>
          <div className="map-groups">
            {groupByPermit(data.items).map((g) => (
              <div className="map-permit" key={g.key}>
                <div className="map-permit-head">
                  {g.code ? <span className="mono map-permit-code">{g.code}</span> : null}
                  <span className="map-permit-name">{g.name || (g.code ? '' : 'Permit not recorded')}</span>
                  <span className="map-permit-count mono">{num(g.items.length)}</span>
                </div>
                {g.items.map((r) => (
                  <Link className="map-item" key={r.id} to={`/cola/${encodeURIComponent(r.id)}`}>
                    <div className="map-item-main">
                      {/* Ellipsised to keep the row on one line, so the full name needs a tooltip. */}
                      <div className="map-item-brand" title={r.brand || r.ttbId}>{r.brand || r.ttbId}</div>
                      {r.approvalDate ? <div className="map-item-meta muted">{fmtDate(r.approvalDate)}</div> : null}
                    </div>
                    {r.status && r.status !== 'Approved' ? <StatusBadge status={r.status} /> : null}
                    <CatTag rec={r} />
                  </Link>
                ))}
              </div>
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
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const lastMode = useRef(mode);
  const stageRef = useRef(null);
  const isMobile = useIsMobile();

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

  useEffect(() => {
    if (!filtersOpen) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') setFiltersOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [filtersOpen]);

  // The area sheet covers the lower half of the screen, so on a phone the map
  // has to come up out of the document first or there is nothing left to see.
  useEffect(() => {
    if (area && isMobile && stageRef.current) {
      stageRef.current.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }, [area, isMobile]);

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

  const clearArea = useCallback(() => setArea(null), []);

  const onSelectArea = useCallback(
    (box) => {
      track('map_area_opened', { mode });
      setFiltersOpen(false);
      setArea(box);
    },
    [mode]
  );

  const onSelectPoint = useCallback(
    (point) => {
      track('map_marker_clicked', { mode });
      setFiltersOpen(false);
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
  const activeFilters = FILTER_KEYS.filter((k) => criteria[k]).length;

  return (
    <div className="map-page">
      <div className="map-toolbar">
        <div className="wrap">
          <div className="map-toolbar-top">
            <Segmented options={MODES} value={mode} onChange={setMode} label="Map mode" short={isMobile} />
            <Segmented options={ROLES} value={role} onChange={setRole} label="Location plotted" short={isMobile} />
            <button
              type="button"
              className="btn secondary sm map-filters-toggle"
              aria-expanded={filtersOpen}
              aria-controls="map-filters"
              onClick={() => setFiltersOpen((open) => !open)}
            >
              <Icon name="filter" size={14} />
              Filters
              {activeFilters ? <span className="map-filter-count">{activeFilters}</span> : null}
            </button>
          </div>

          {filtersOpen ? (
            <button
              type="button"
              className="map-backdrop"
              aria-label="Close filters"
              onClick={() => setFiltersOpen(false)}
            />
          ) : null}

          <div id="map-filters" className={`map-filters${filtersOpen ? ' is-open' : ''}`}>
            <div className="map-sheet-grab" aria-hidden="true" />
            <div className="map-sheet-head">
              <div className="section-title">Filters</div>
              <button type="button" className="btn secondary sm" onClick={() => setFiltersOpen(false)}>
                Done
              </button>
            </div>
            <div className="map-controls">
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

      <div className={`map-stage${area ? ' has-panel' : ''}`} data-tour="map-stage" ref={stageRef}>
        <Suspense fallback={<div className="skel map-canvas" />}>
          <MapView
            mode={mode}
            bins={data?.bins}
            points={data?.points}
            area={area}
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

        {area ? <AreaPanel state={areaState} onClose={clearArea} isMobile={isMobile} /> : null}
      </div>

      <p className="wrap muted an-note map-note">
        Only COLAs whose {role === 'product_origin' ? 'stated origin' : 'permit address'} has been
        geocoded appear here, and a geocode is an approximation of an address, not a production
        site. {mode === 'image' ? 'Label mode shows the most recent approvals in view, not all of them.' : ''}
      </p>
    </div>
  );
}
