import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Icon from '../components/Icon.jsx';
import LabelThumb from '../components/LabelThumb.jsx';
import { StatusBadge, CatTag } from '../components/Badges.jsx';
import Highlight from '../components/Highlight.jsx';
import { toPct } from '../components/ScoreMeter.jsx';
import { api, toQuery } from '../lib/api.js';
import { track } from '../lib/analytics.js';
import { fmtDate, fmtPhone, orderFaces } from '../lib/format.js';
import { useAsync } from '../hooks/useAsync.js';
import { useDocumentTitle } from '../hooks/useDocumentTitle.js';

// Same reason as the map page: maplibre must not land in the main bundle just
// because a record might have coordinates.
const MapView = lazy(() => import('../components/MapView.jsx'));

const ROLE_LABELS = {
  primary_premise: 'Primary permit address',
  permit_premise: 'Permit address',
  product_origin: 'Product origin',
};

// A primary premise is also a permit premise, so the same address arrives under
// both roles. Ordering puts the primary first, so it is the one kept.
function dedupeLocations(points) {
  const seen = new Map();
  for (const p of points) {
    const who = p.permitId || p.sourceKey || p.permitName || '';
    const kind = p.role === 'product_origin' ? 'origin' : 'permit';
    const key = `${kind}|${who}|${p.lat.toFixed(5)}|${p.lng.toFixed(5)}`;
    if (!seen.has(key)) seen.set(key, p);
  }
  return [...seen.values()];
}

// The record's own coordinates, drawn as a locator. Deliberately not
// interactive: this answers "where is this", and the map page answers the rest.
function LocationPanel({ locations, status, origin }) {
  const points = useMemo(() => dedupeLocations(locations || []), [locations]);
  const [hoveredId, setHoveredId] = useState(null);
  const nameOf = (p) => (p.role === 'product_origin' ? origin || p.sourceKey : p.permitName || p.sourceKey);
  const locationClass = (p) =>
    p.role === 'primary_premise' ? 'is-primary' : p.role === 'product_origin' ? 'is-origin' : 'is-associated';
  const pins = useMemo(
    () =>
      points.map((p, i) => ({
        ...p,
        id: `loc-${i}`,
        index: i + 1,
        locationClass: locationClass(p),
        label: `${i + 1}. ${ROLE_LABELS[p.role] || p.role}${nameOf(p) ? ` — ${nameOf(p)}` : ''}`,
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [points, origin]
  );

  if (!points.length) {
    if (status === 'located') return null;
    return (
      <>
        <h3 className="d-section">Location</h3>
        <Notice
          title={
            status === 'no_match'
              ? 'This address could not be placed on a map.'
              : status === 'pending'
                ? 'This address is queued for geocoding.'
                : 'This address has not been geocoded.'
          }
        >
          {status === 'no_match'
            ? 'Geocoding ran but found no match for the permit address, so this record does not appear on the map.'
            : 'Coordinates are added by a separate process that has not reached this record yet.'}
        </Notice>
      </>
    );
  }

  const primary = points[0];
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  const view = {
    center: [primary.lng, primary.lat],
    zoom: 9,
    // A permit holder's premises can span several states, so a fixed zoom on the
    // first one would leave the rest off screen.
    bounds:
      points.length > 1
        ? [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)]
        : null,
  };
  return (
    <>
      <h3 className="d-section">Location</h3>
      <div className="d-minimap">
        <Suspense fallback={<div className="skel" style={{ height: '100%' }} />}>
          <MapView mode="locator" points={pins} view={view} interactive={false} highlightId={hoveredId} />
        </Suspense>
      </div>
      <div className="d-permits" style={{ marginTop: 10 }}>
        {pins.map((p) => (
          <div
            className={'d-permit is-locatable ' + p.locationClass + (hoveredId === p.id ? ' is-hovered' : '')}
            key={p.id}
            tabIndex={0}
            onMouseEnter={() => setHoveredId(p.id)}
            onMouseLeave={() => setHoveredId((cur) => (cur === p.id ? null : cur))}
            onFocus={() => setHoveredId(p.id)}
            onBlur={() => setHoveredId((cur) => (cur === p.id ? null : cur))}
          >
            <div style={{ fontWeight: 600 }}>
              <span className={'d-pin-no ' + p.locationClass}>{p.index}</span>
              {ROLE_LABELS[p.role] || p.role}
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              {nameOf(p) || '—'}
            </div>
          </div>
        ))}
      </div>
      <p className="an-note muted">
        Coordinates are approximated from the address on file.{' '}
        <Link to={`/map?lat=${primary.lat}&lng=${primary.lng}&zoom=9`}>See this area on the map</Link>
      </p>
    </>
  );
}

function permitAddress(p) {
  return (
    [p.address, p.city, [p.state, p.postalCode].filter(Boolean).join(' '), p.country]
      .filter(Boolean)
      .join(', ') || ''
  );
}

// Punctuation and spacing differ between the free-text mailing address and the
// permit's structured parts, so comparison happens on letters and digits only.
function addressKey(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function addressOnPermit(mailing, permits) {
  const key = addressKey(mailing);
  if (!key) return false;
  return (permits || []).some((p) => {
    const other = addressKey(permitAddress(p));
    return other && (other.includes(key) || key.includes(other));
  });
}

function isBlank(value) {
  return value == null || value === false || (typeof value === 'string' && !value.trim());
}

// Fields with nothing behind them are dropped rather than shown as an em dash,
// and a section that ends up with no fields at all disappears with them.
function FieldSection({ title, fields = [], children }) {
  const shown = fields.filter((f) => f && !isBlank(f.value));
  if (!shown.length && !children) return null;
  return (
    <>
      <h3 className="d-section">{title}</h3>
      {shown.length > 0 && (
        <div className="d-fields">
          {shown.map((f) => (
            <div className="d-field" key={f.label}>
              <div className="d-label">{f.label}</div>
              <div className={'d-value' + (f.mono ? ' mono' : '')}>{f.value}</div>
            </div>
          ))}
        </div>
      )}
      {children}
    </>
  );
}

function Notice({ tone, title, children }) {
  return (
    <div className={'d-notice' + (tone ? ' ' + tone : '')}>
      <Icon name="info" size={16} />
      <div>
        {title && <b>{title}</b>}
        <div>{children}</div>
      </div>
    </div>
  );
}

function SimilarCard({ r, onOpen, tourAnchor }) {
  return (
    <button className="recent-card" onClick={() => onOpen(r.id)} data-tour={tourAnchor || undefined}>
      <div style={{ position: 'relative' }}>
        <LabelThumb rec={r} />
        {r.score != null && (
          <span className="g-score">
            <Icon name="sparkle" size={12} />
            {toPct(r.score)}%
          </span>
        )}
      </div>
      <div className="recent-meta">
        <div className="row between gap-8">
          <CatTag rec={r} />
          <StatusBadge status={r.status} />
        </div>
        <div style={{ fontWeight: 700, marginTop: 7 }}>{r.brand}</div>
        <div className="muted" style={{ fontSize: 13 }}>
          {r.fanciful}
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
          {fmtDate(r.approvalDate)}
        </div>
      </div>
    </button>
  );
}

// Only render a bounding box when it carries usable percentage coordinates.
function hasBox(item) {
  const b = item && item.box;
  return b && ['x', 'y', 'w', 'h'].every((k) => typeof b[k] === 'number');
}

// Client rects come back post-transform, so divide them out to get the layout
// pixels the overlay is positioned in (the lightbox stage can be scaled).
function cssScale(el) {
  const t = getComputedStyle(el).transform;
  if (!t || t === 'none') return 1;
  return new DOMMatrixReadOnly(t).a || 1;
}

// The stage is not the image: the photo box adds padding and object-fit:
// contain letterboxes the artwork inside it. Measuring the rendered <img>
// keeps box percentages aligned without hard-coding those insets.
function useRenderedImageRect(stageRef, src) {
  const [rect, setRect] = useState(null);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;
    const el = stage.querySelector('img');
    if (!el) {
      setRect(null);
      return undefined;
    }

    const measure = () => {
      const stageBox = stage.getBoundingClientRect();
      const imgBox = el.getBoundingClientRect();
      const nw = el.naturalWidth;
      const nh = el.naturalHeight;
      if (!imgBox.width || !imgBox.height || !nw || !nh) {
        setRect(null);
        return;
      }
      const z = cssScale(stage);
      const boxW = imgBox.width / z;
      const boxH = imgBox.height / z;
      const scale = Math.min(boxW / nw, boxH / nh);
      const w = nw * scale;
      const h = nh * scale;
      setRect({
        left: (imgBox.left - stageBox.left) / z + (boxW - w) / 2,
        top: (imgBox.top - stageBox.top) / z + (boxH - h) / 2,
        width: w,
        height: h,
      });
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(stage);
    ro.observe(el);
    el.addEventListener('load', measure);
    return () => {
      ro.disconnect();
      el.removeEventListener('load', measure);
    };
  }, [stageRef, src]);

  return rect;
}

// The .bbox border is drawn inside the element (box-sizing: border-box), so
// grow the frame by its own width plus a pixel of clearance to keep the stroke
// off the text it is pointing at. Keep in sync with .bbox in pages.css.
const BBOX_BORDER = 2;
const BBOX_OUTSET = BBOX_BORDER + 1;

function BoundingBox({ item, stageRef, src }) {
  const rect = useRenderedImageRect(stageRef, src);
  if (!rect) return null;
  const b = item.box;
  const style = {
    left: rect.left + (b.x / 100) * rect.width - BBOX_OUTSET + 'px',
    top: rect.top + (b.y / 100) * rect.height - BBOX_OUTSET + 'px',
    width: (b.w / 100) * rect.width + BBOX_OUTSET * 2 + 'px',
    height: (b.h / 100) * rect.height + BBOX_OUTSET * 2 + 'px',
  };
  return (
    <div className="bbox" style={style}>
      <span className="bbox-tag">
        {String(item.type || '').replace(/_/g, ' ')}
        {item.conf != null ? ` · ${Math.round(item.conf * 100)}%` : ''}
      </span>
    </div>
  );
}

// Desktop has no pinch gesture, so the full-size view gets a click-to-zoom
// that pans with the cursor.
const LB_ZOOM = 2.6;

function Lightbox({ rec, views, file, setFile, hlItem, onClose }) {
  const [zoom, setZoom] = useState(null);
  const idx = Math.max(0, views.findIndex((v) => v.img.fileName === file));
  const step = (delta) => {
    if (!views.length) return;
    setFile(views[(idx + delta + views.length) % views.length].img.fileName);
  };
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowRight') step(1);
      if (e.key === 'ArrowLeft') step(-1);
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [file, views]); // eslint-disable-line react-hooks/exhaustive-deps

  // A new image means new artwork, so drop back to the fitted view.
  useEffect(() => setZoom(null), [file]);

  const view = views[idx];
  const cur = view && view.img;
  const stageRef = useRef(null);

  // Percentages are read off the untransformed stage so panning stays steady.
  const originFrom = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const clamp = (v) => Math.min(100, Math.max(0, v));
    return { x: clamp(((e.clientX - r.left) / r.width) * 100), y: clamp(((e.clientY - r.top) / r.height) * 100) };
  };

  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-label="Full-size label image">
      <button className="lb-close" onClick={onClose} aria-label="Close">
        <Icon name="close" size={22} />
      </button>
      <div className="lb-body" onClick={(e) => e.stopPropagation()}>
        {views.length > 1 && (
          <button className="lb-arrow" onClick={() => step(-1)} aria-label="Previous image">
            <Icon name="chevLeft" size={26} />
          </button>
        )}
        <div
          className={'lb-stage' + (zoom ? ' zoomed' : '')}
          onClick={(e) => setZoom(zoom ? null : originFrom(e))}
          onMouseMove={(e) => zoom && setZoom(originFrom(e))}
        >
          <div
            className="lb-zoom"
            ref={stageRef}
            style={zoom ? { transform: `scale(${LB_ZOOM})`, transformOrigin: `${zoom.x}% ${zoom.y}%` } : undefined}
          >
            <LabelThumb rec={rec} src={cur && cur.url} />
            {hlItem && cur && hlItem.file === cur.fileName && hasBox(hlItem) && (
              <BoundingBox item={hlItem} stageRef={stageRef} src={cur.url} />
            )}
          </div>
          <div className="lb-cap">
            <b>{rec.brand}</b> — {view ? view.caption : 'front'} label · TTB ID {rec.ttbId}
          </div>
        </div>
        {views.length > 1 && (
          <button className="lb-arrow" onClick={() => step(1)} aria-label="Next image">
            <Icon name="chevRight" size={26} />
          </button>
        )}
      </div>
      <div className="lb-thumbs" onClick={(e) => e.stopPropagation()}>
        {views.map((v) => (
          <button
            key={v.img.fileName}
            className={'lv-thumb' + (v === view ? ' on' : '')}
            onClick={() => setFile(v.img.fileName)}
          >
            <LabelThumb rec={rec} src={v.img.url} />
            <span className="lv-cap">{v.caption}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function DetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const q = (searchParams.get('q') || '').trim().toLowerCase();

  const detailState = useAsync((signal) => api.getCola(id, signal), [id], { cacheKey: `cola:${id}` });
  const memberState = useAsync((signal) => api.similar(id, 8, signal, 'member'), [id], {
    cacheKey: `similar:member:${id}`,
  });
  const othersState = useAsync((signal) => api.similar(id, 8, signal, 'others'), [id], {
    cacheKey: `similar:others:${id}`,
  });
  const rec = detailState.data;

  const brand = (rec && rec.brand ? rec.brand : '').trim();
  const fanciful = (rec && rec.fanciful ? rec.fanciful : '').trim();
  useDocumentTitle(
    rec
      ? [brand || fanciful || `TTB ID ${rec.ttbId || id}`, brand && fanciful ? `(${fanciful})` : '']
          .filter(Boolean)
          .join(' ')
      : detailState.loading
        ? null
        : 'Label not found'
  );

  const images = useMemo(() => (rec && rec.images) || [], [rec]);
  const items = useMemo(() => (rec && rec.imageItems) || [], [rec]);
  // One gallery entry per image. Several images usually share an img_type, so
  // keying the viewer on the face alone hid everything past the first of each.
  const views = useMemo(() => {
    const counts = {};
    images.forEach((img) => {
      const f = img.face || 'other';
      counts[f] = (counts[f] || 0) + 1;
    });
    const seen = {};
    return images.map((img) => {
      const f = img.face || 'other';
      seen[f] = (seen[f] || 0) + 1;
      return { img, face: f, caption: counts[f] > 1 ? `${f} ${seen[f]}` : f };
    });
  }, [images]);
  const faces = useMemo(() => {
    // Server order: the API ranks images by visual interest, so the most
    // distinctive artwork leads rather than whichever face is nominally the front.
    const fs = Array.from(new Set(views.map((v) => v.face)));
    return fs.length ? fs : ['front'];
  }, [views]);

  const [activeFile, setActiveFile] = useState(null);
  const [hlItem, setHlItem] = useState(null);
  const [lightbox, setLightbox] = useState(false);
  const mainStageRef = useRef(null);

  // Highlighted text names its own image; fall back to that image's face, then
  // to the lead image, so a stale or unmatched file name never blanks the stage.
  const fileForItem = (it) => {
    const match =
      (it && views.find((v) => v.img.fileName === it.file)) ||
      (it && views.find((v) => v.face === it.face)) ||
      views[0];
    return match ? match.img.fileName : null;
  };

  const matchedItems = useMemo(
    () => (q ? items.filter((it) => (it.text || '').toLowerCase().includes(q)) : []),
    [items, q]
  );

  // Group extracted text by image file, reading order within each group. Groups
  // follow the gallery so the text panel and the images agree on which image leads.
  const itemGroups = useMemo(() => {
    const byFile = new Map();
    items.forEach((it) => {
      const file = it.file || `face:${it.face || 'other'}`;
      if (!byFile.has(file)) byFile.set(file, []);
      byFile.get(file).push(it);
    });
    const pos = (it, k) => (it.box && typeof it.box[k] === 'number' ? it.box[k] : Infinity);
    const files = new Set(byFile.keys());
    const galleryFiles = views.map((v) => v.img.fileName).filter((file) => files.delete(file));
    const fallbackFiles = [...files];
    const fallbackFaces = orderFaces([...new Set(fallbackFiles.map((file) => byFile.get(file)[0].face || 'other'))]);
    const ordered = [
      ...galleryFiles,
      ...fallbackFiles.sort(
        (a, b) =>
          fallbackFaces.indexOf(byFile.get(a)[0].face || 'other') - fallbackFaces.indexOf(byFile.get(b)[0].face || 'other')
      ),
    ];
    return ordered.map((file) => {
      const groupItems = byFile.get(file);
      const image = images.find((img) => img.fileName === file);
      return {
        file: image ? image.fileName : groupItems[0].file,
        type: image?.imgType || groupItems[0].face || 'other',
        items: [...groupItems].sort((a, b) => pos(a, 'y') - pos(b, 'y') || pos(a, 'x') - pos(b, 'x')),
      };
    });
  }, [items, images, views]);

  useEffect(() => {
    const first = matchedItems.length ? matchedItems[0] : null;
    setHlItem(first);
    setActiveFile(fileForItem(first));
  }, [id, q, views]); // eslint-disable-line react-hooks/exhaustive-deps

  if (detailState.loading) {
    return (
      <div className="detail-page">
        <div className="wrap" style={{ padding: '48px 0' }}>
          <div className="skel" style={{ height: 28, width: '40%', marginBottom: 16 }}></div>
          <div className="skel" style={{ height: 320 }}></div>
        </div>
      </div>
    );
  }

  if (detailState.error || !rec) {
    return (
      <div className="detail-page">
        <div className="wrap" style={{ padding: '48px 0' }}>
          <div className="empty panel">
            <Icon name="info" size={34} className="muted" />
            <h3 style={{ marginTop: 12 }}>Label not found</h3>
            <p className="muted">
              {(detailState.error && detailState.error.message) || 'This COLA record could not be loaded.'}
            </p>
            <button className="btn secondary sm" onClick={() => navigate('/')}>
              Back to search
            </button>
          </div>
        </div>
      </div>
    );
  }

  const dropSelf = (list) => (list || []).filter((r) => String(r.id) !== String(rec.id));
  const memberSimilar = dropSelf(memberState.data);
  const othersSimilar = dropSelf(othersState.data);
  const proc = rec.processing || {};
  const activeView = views.find((v) => v.img.fileName === activeFile) || views[0];
  const currentImage = activeView && activeView.img;
  const showBox = !!(hlItem && currentImage && hlItem.file === currentImage.fileName && hasBox(hlItem));
  const onOpen = (rid) =>
    navigate(`/cola/${encodeURIComponent(rid)}${q ? `?q=${encodeURIComponent(searchParams.get('q'))}` : ''}`);
  const memberPermit = rec.permitId || rec.permit;

  return (
    <div className="detail-page">
      <div className="wrap">
        <nav className="crumbs">
          <button className="linkbtn" onClick={() => navigate(-1)}>
            <Icon name="chevLeft" size={16} /> Back to results
          </button>
          <span className="muted" style={{ margin: '0 8px' }}>
            /
          </span>
          <span className="muted">
            {rec.brand} — {rec.fanciful}
          </span>
        </nav>

        <div className="detail-head">
          <div>
            <div className="row gap-10" style={{ marginBottom: 10 }}>
              <CatTag rec={rec} />
              <StatusBadge status={rec.status} />
            </div>
            <h1 style={{ fontSize: 30 }}>{rec.brand}</h1>
            <div className="serif" style={{ fontSize: 18, fontStyle: 'italic', color: 'var(--base-darker)' }}>
              {rec.fanciful}
            </div>
            <div className="row gap-16 wrap-flex" style={{ marginTop: 12 }}>
              <span className="mono d-ttb">TTB ID {rec.ttbId}</span>
              <span className="muted">Approved {fmtDate(rec.approvalDate)}</span>
            </div>
          </div>
          <div className="row gap-8">
            {/* Reconstructed from registry data, unlike the TTB-hosted scan below. */}
            <a
              className="btn secondary sm"
              href={api.colaFormUrl(rec.id)}
              target="_blank"
              rel="noreferrer"
              onClick={() => track('form_viewed', {})}
            >
              <Icon name="print" size={16} /> View form 5100.31
            </a>
            {rec.formUrl && (
              // Leaves our origin, so this is the only place the download is visible.
              <a
                className="btn sm"
                href={rec.formUrl}
                target="_blank"
                rel="noreferrer"
                onClick={() => track('cola_form_downloaded', {})}
              >
                <Icon name="download" size={16} /> Download COLA
              </a>
            )}
          </div>
        </div>

        {!proc.detailLoaded && (
          <Notice tone="warn" title="Full record details have not been loaded for this COLA.">
            Only the fields published in TTB's COLA listing are shown below. The complete permit list,
            submitter contact information, qualifications and grape varietal data have not been
            retrieved yet.
          </Notice>
        )}

        <div className="detail-grid">
          {/* label images */}
          <div>
            <div className="panel label-viewer" data-tour="detail-images">
              <div className="lv-main">
                <div className="lv-stage" ref={mainStageRef} style={{ maxWidth: 360, margin: '0 auto', position: 'relative' }}>
                  <LabelThumb rec={rec} src={currentImage && currentImage.url} style={{ aspectRatio: '4/5' }} />
                  {showBox && (
                    <BoundingBox item={hlItem} stageRef={mainStageRef} src={currentImage.url} />
                  )}
                  <button className="lv-expand" onClick={() => { track('lightbox_opened', { face: activeView && activeView.face }); setLightbox(true); }} title="View full size" aria-label="View full size">
                    <Icon name="expand" size={16} /> Full size
                  </button>
                </div>
              </div>
              <div className="lv-thumbs">
                {views.map((v) => (
                  <button
                    key={v.img.fileName}
                    className={'lv-thumb' + (v === activeView ? ' on' : '')}
                    onClick={() => { track('label_face_switched', { face: v.face }); setActiveFile(v.img.fileName); }}
                  >
                    <LabelThumb rec={rec} src={v.img.url} />
                    <span className="lv-cap">{v.caption}</span>
                  </button>
                ))}
              </div>
              {images.length === 0 && (
                <div className="muted" style={{ fontSize: 12, textAlign: 'center', marginTop: 12 }}>
                  <Icon name="info" size={13} /> No label artwork is available for this record; a placeholder is shown.
                </div>
              )}
            </div>
          </div>

          {/* fields */}
          <div>
            <div className="panel d-panel" data-tour="detail-fields">
              <FieldSection
                title="Label identity"
                fields={[
                  { label: 'Brand name', value: rec.brand },
                  { label: 'Fanciful name', value: rec.fanciful },
                  { label: 'Class / Type', value: rec.classType || rec.classSub },
                  { label: 'Net contents', value: rec.netContents },
                  { label: 'Alcohol content', value: rec.abv ? `${rec.abv} ALC/VOL` : null },
                ]}
              />

              <FieldSection
                title="Origin & status"
                fields={[
                  { label: 'Source', value: rec.originGroup },
                  {
                    label: 'Origin',
                    value: rec.origin ? `${rec.originFlag ? rec.originFlag + ' ' : ''}${rec.origin}` : null,
                  },
                  { label: 'Status', value: rec.status },
                  { label: 'For sale in', value: rec.forSaleIn },
                  // "Not required" is only a fact once the detail pass has run.
                  { label: 'Formula', value: rec.formula || (proc.detailLoaded ? 'Not required' : null), mono: true },
                  {
                    label: 'Grape varietal',
                    value: rec.grapeVarietals && rec.grapeVarietals.length ? rec.grapeVarietals.join(', ') : null,
                  },
                  { label: 'Appellation', value: rec.appellation },
                ]}
              />

              <FieldSection
                title="Application & permit"
                fields={[
                  { label: 'Applicant / business', value: rec.applicant },
                  // Dropped when the permit list below already shows the same address.
                  {
                    label: 'Mailing address',
                    value: addressOnPermit(rec.mailingAddress, rec.permits) ? null : rec.mailingAddress,
                  },
                  { label: 'Application type', value: rec.applicationType },
                  // Redundant with the permit list below, which carries the same
                  // number plus the name and address.
                  {
                    label: 'Permit / plant number',
                    value: rec.permits && rec.permits.length ? null : rec.permitId || rec.permit,
                    mono: true,
                  },
                  { label: 'Serial number', value: rec.serial, mono: true },
                  { label: 'Vendor code', value: rec.vendorCode, mono: true },
                  { label: 'Received as', value: rec.receivedDescription },
                  { label: 'Date approved', value: fmtDate(rec.approvalDate) },
                ]}
              />

              <FieldSection
                title="Submitter"
                fields={[
                  { label: 'Name', value: rec.submitter },
                  { label: 'Submitter ID', value: rec.submitterId, mono: true },
                  { label: 'Telephone', value: rec.submitterPhone && fmtPhone(rec.submitterPhone), mono: true },
                  { label: 'Fax', value: rec.submitterFax && fmtPhone(rec.submitterFax), mono: true },
                ]}
              />

              {rec.permits && rec.permits.length > 0 && (
                <>
                  <h3 className="d-section">
                    Permits {rec.permits.length > 1 ? `(${rec.permits.length})` : ''}
                  </h3>
                  <div className="d-permits">
                    {rec.permits.map((p, i) => (
                      <div className="d-permit" key={p.permitId || i}>
                        <div className="row gap-8" style={{ alignItems: 'baseline' }}>
                          <span className="mono" style={{ fontWeight: 700 }}>
                            {p.permitId || '—'}
                          </span>
                          {p.primary && <span className="chip static">Primary</span>}
                        </div>
                        <div style={{ fontWeight: 600 }}>{p.name}</div>
                        <div className="muted" style={{ fontSize: 13 }}>
                          {permitAddress(p) || '—'}
                        </div>
                        {p.permitId && (
                          <a
                            className="linkbtn"
                            href={`/results${toQuery({ permit: p.permitId })}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View permit results <Icon name="external" size={14} />
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}

              <LocationPanel locations={rec.locations} status={proc.geocoding} origin={rec.origin} />

              {rec.qualificationItems && rec.qualificationItems.length > 0 ? (
                <>
                  <h3 className="d-section">Qualifications</h3>
                  <ul className="d-qual-list">
                    {rec.qualificationItems.map((qi, i) => (
                      <li key={qi.id ?? i}>
                        {qi.text}
                        {qi.comment && <div className="muted" style={{ fontSize: 13 }}>{qi.comment}</div>}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                rec.qualifications && (
                  <>
                    <h3 className="d-section">Qualifications</h3>
                    <div className="d-qual">{rec.qualifications}</div>
                  </>
                )
              )}
            </div>

            {/* extracted label text */}
            <div className="panel d-panel" style={{ marginTop: 20 }} data-tour="detail-ocr">
              <div className="row between" style={{ marginBottom: 4 }}>
                <h3 className="d-section" style={{ margin: 0, border: 0, paddingBottom: 4 }}>
                  Text detected on label images
                </h3>
                {hlItem && (
                  <button className="linkbtn" onClick={() => setHlItem(null)}>
                    Clear highlight
                  </button>
                )}
              </div>
              {q && matchedItems.length > 0 && (
                <div className="ocr-matchnote">
                  <Icon name="search" size={13} />
                  <span>
                    Your search “{searchParams.get('q')}” matched{' '}
                    {matchedItems.length === 1 ? 'this text' : matchedItems.length + ' items'} on the label — highlighted
                    at left.
                  </span>
                </div>
              )}
              {items.length === 0 ? (
                !proc.imagesLoaded ? (
                  <Notice>
                    No label images have been retrieved for this record, so there is nothing to read
                    text from.
                  </Notice>
                ) : !proc.textAnalyzed ? (
                  <Notice title="Text extraction has not been run on this label.">
                    These images have not yet been processed by document intelligence, so no text,
                    highlights or label-text search results are available for this COLA.
                  </Notice>
                ) : (
                  <Notice title="Text extraction ran but found no readable text.">
                    Document intelligence processed this label's images and returned no text.
                  </Notice>
                )
              ) : (
                <>
                  <p className="ocr-hint">
                    <Icon name="info" size={13} />
                    <span>Select any text below to highlight where it appears on the label image.</span>
                  </p>
                  <div className="ocr-groups">
                    {itemGroups.map((group) => (
                      <div className="ocr-group" key={group.file || group.type}>
                        <h4 className="ocr-group-head">
                          <span>{group.type}</span>
                          {group.file && <span className="ocr-file-name mono">{group.file}</span>}
                          <span className="ocr-group-count">{group.items.length} text items</span>
                        </h4>
                        <div className="ocr-flow">
                          {group.items.map((it, i) => {
                            const isMatch = q && (it.text || '').toLowerCase().includes(q);
                            const on = hlItem === it;
                            return (
                              <button
                                key={i}
                                className={'ocr-chip' + (on ? ' on' : '') + (isMatch ? ' hit' : '')}
                                title={it.conf != null ? `${Math.round(it.conf * 100)}% confidence` : undefined}
                                onClick={() => {
                                  track('ocr_chip_clicked', { on: !on, face: it.face });
                                  if (on) {
                                    setHlItem(null);
                                  } else {
                                    setHlItem(it);
                                    setActiveFile(fileForItem(it));
                                  }
                                }}
                              >
                                {isMatch ? <Highlight text={it.text} q={searchParams.get('q')} /> : it.text}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        {/* similar labels */}
        {!proc.embedded && (
          <section style={{ marginTop: 40 }}>
            <h2 style={{ fontSize: 20, marginBottom: 4 }} data-tour="detail-similar">
              Similar COLAs
            </h2>
            <Notice title="Visual similarity has not been computed for this label.">
              {proc.imagesLoaded
                ? "This record's images have not been converted into image embeddings yet, so visually similar COLAs from this or any other industry member cannot be shown."
                : 'No label images have been retrieved for this record, so there is nothing to compare against other COLAs.'}
            </Notice>
          </section>
        )}

        {proc.embedded && memberSimilar.length > 0 && (
          <section style={{ marginTop: 40 }}>
            <h2 style={{ fontSize: 20, marginBottom: 4 }}>Similar COLAs from this industry member</h2>
            <p className="muted" style={{ margin: '0 0 16px', fontSize: 14 }}>
              Visually similar approved labels filed under permit {memberPermit || '—'}.
            </p>
            <div className="recent-grid">
              {memberSimilar.map((r, i) => (
                <SimilarCard key={r.id} r={r} onOpen={onOpen} tourAnchor={i === 0 ? 'detail-similar' : undefined} />
              ))}
            </div>
          </section>
        )}

        {proc.embedded && othersSimilar.length > 0 && (
          <section style={{ marginTop: 40 }}>
            <h2 style={{ fontSize: 20, marginBottom: 4 }}>Similar COLAs from other industry members</h2>
            <p className="muted" style={{ margin: '0 0 16px', fontSize: 14 }}>
              Visually similar approved labels from other permit holders — useful for trade-dress comparison.
            </p>
            <div className="recent-grid">
              {othersSimilar.map((r, i) => (
                <SimilarCard
                  key={r.id}
                  r={r}
                  onOpen={onOpen}
                  tourAnchor={i === 0 && memberSimilar.length === 0 ? 'detail-similar' : undefined}
                />
              ))}
            </div>
          </section>
        )}
      </div>

      {lightbox && (
        <Lightbox
          rec={rec}
          views={views}
          file={currentImage && currentImage.fileName}
          setFile={setActiveFile}
          hlItem={hlItem}
          onClose={() => setLightbox(false)}
        />
      )}
    </div>
  );
}
