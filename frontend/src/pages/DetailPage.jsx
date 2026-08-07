import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Icon from '../components/Icon.jsx';
import LabelThumb from '../components/LabelThumb.jsx';
import { StatusBadge, CatTag } from '../components/Badges.jsx';
import Highlight from '../components/Highlight.jsx';
import { toPct } from '../components/ScoreMeter.jsx';
import { api } from '../lib/api.js';
import { track } from '../lib/analytics.js';
import { fmtDate, orderFaces } from '../lib/format.js';
import { useAsync } from '../hooks/useAsync.js';

function Field({ label, children, mono }) {
  return (
    <div className="d-field">
      <div className="d-label">{label}</div>
      <div className={'d-value' + (mono ? ' mono' : '')}>{children || '—'}</div>
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

// Label images are letterboxed by object-fit: contain inside a fixed 4/5 stage,
// so percentages of the image must be remapped onto the rendered image rect.
const STAGE_ASPECT = 4 / 5;

function boxStyle(item, img) {
  const b = item.box;
  const iw = img && img.widthPx;
  const ih = img && img.heightPx;
  let sx = 100;
  let sy = 100;
  let ox = 0;
  let oy = 0;
  if (iw && ih) {
    const ia = iw / ih;
    if (ia > STAGE_ASPECT) {
      sy = (STAGE_ASPECT / ia) * 100;
      oy = (100 - sy) / 2;
    } else {
      sx = (ia / STAGE_ASPECT) * 100;
      ox = (100 - sx) / 2;
    }
  }
  return {
    left: ox + (b.x * sx) / 100 + '%',
    top: oy + (b.y * sy) / 100 + '%',
    width: (b.w * sx) / 100 + '%',
    height: (b.h * sy) / 100 + '%',
  };
}

function BoundingBox({ item, img }) {
  return (
    <div className="bbox" style={boxStyle(item, img)}>
      <span className="bbox-tag">
        {String(item.type || '').replace(/_/g, ' ')}
        {item.conf != null ? ` · ${Math.round(item.conf * 100)}%` : ''}
      </span>
    </div>
  );
}

function Lightbox({ rec, faces, imagesByFace, face, setFace, hlItem, onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
      const i = faces.indexOf(face);
      if (e.key === 'ArrowRight') setFace(faces[(i + 1) % faces.length]);
      if (e.key === 'ArrowLeft') setFace(faces[(i + faces.length - 1) % faces.length]);
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [face, faces]); // eslint-disable-line react-hooks/exhaustive-deps

  const faceImages = imagesByFace[face] || [];
  const cur = (hlItem && faceImages.find((im) => im.fileName === hlItem.file)) || faceImages[0];
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-label="Full-size label image">
      <button className="lb-close" onClick={onClose} aria-label="Close">
        <Icon name="close" size={22} />
      </button>
      <div className="lb-body" onClick={(e) => e.stopPropagation()}>
        {faces.length > 1 && (
          <button
            className="lb-arrow"
            onClick={() => setFace(faces[(faces.indexOf(face) + faces.length - 1) % faces.length])}
            aria-label="Previous image"
          >
            <Icon name="chevLeft" size={26} />
          </button>
        )}
        <div className="lb-stage">
          <LabelThumb rec={rec} src={cur && cur.url} />
          {hlItem && hlItem.face === face && hasBox(hlItem) && <BoundingBox item={hlItem} img={cur} />}
          <div className="lb-cap">
            <b>{rec.brand}</b> — {face} label · TTB ID {rec.ttbId}
          </div>
        </div>
        {faces.length > 1 && (
          <button
            className="lb-arrow"
            onClick={() => setFace(faces[(faces.indexOf(face) + 1) % faces.length])}
            aria-label="Next image"
          >
            <Icon name="chevRight" size={26} />
          </button>
        )}
      </div>
      <div className="lb-thumbs" onClick={(e) => e.stopPropagation()}>
        {faces.map((f) => {
          const img = imagesByFace[f] && imagesByFace[f][0];
          return (
            <button key={f} className={'lv-thumb' + (face === f ? ' on' : '')} onClick={() => setFace(f)}>
              <LabelThumb rec={rec} src={img && img.url} />
              <span className="lv-cap">{f}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function DetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const q = (searchParams.get('q') || '').trim().toLowerCase();

  const detailState = useAsync((signal) => api.getCola(id, signal), [id]);
  const memberState = useAsync((signal) => api.similar(id, 8, signal, 'member'), [id]);
  const othersState = useAsync((signal) => api.similar(id, 8, signal, 'others'), [id]);
  const rec = detailState.data;

  const images = useMemo(() => (rec && rec.images) || [], [rec]);
  const items = useMemo(() => (rec && rec.imageItems) || [], [rec]);
  const imagesByFace = useMemo(() => {
    const m = {};
    images.forEach((img) => {
      const f = img.face || 'front';
      (m[f] = m[f] || []).push(img);
    });
    return m;
  }, [images]);
  const faces = useMemo(() => {
    // Server order: the API ranks images by visual interest, so the most
    // distinctive artwork leads rather than whichever face is nominally the front.
    const fs = Object.keys(imagesByFace);
    return fs.length ? fs : ['front'];
  }, [imagesByFace]);

  const [activeImg, setActiveImg] = useState('front');
  const [hlItem, setHlItem] = useState(null);
  const [lightbox, setLightbox] = useState(false);

  const matchedItems = useMemo(
    () => (q ? items.filter((it) => (it.text || '').toLowerCase().includes(q)) : []),
    [items, q]
  );

  // Group extracted text by image face, reading order within each group. Groups
  // follow the gallery so the text panel and the images agree on which face leads.
  const itemGroups = useMemo(() => {
    const byFace = new Map();
    items.forEach((it) => {
      const f = it.face || 'other';
      if (!byFace.has(f)) byFace.set(f, []);
      byFace.get(f).push(it);
    });
    const pos = (it, k) => (it.box && typeof it.box[k] === 'number' ? it.box[k] : Infinity);
    const ordered = [
      ...faces.filter((f) => byFace.has(f)),
      ...orderFaces([...byFace.keys()].filter((f) => !faces.includes(f))),
    ];
    return ordered.map((face) => ({
      face,
      items: [...byFace.get(face)].sort((a, b) => pos(a, 'y') - pos(b, 'y') || pos(a, 'x') - pos(b, 'x')),
    }));
  }, [items, faces]);

  useEffect(() => {
    const first = matchedItems.length ? matchedItems[0] : null;
    setHlItem(first);
    setActiveImg(first ? first.face : faces[0]);
  }, [id, q, faces]); // eslint-disable-line react-hooks/exhaustive-deps

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
  const activeFaceImages = imagesByFace[activeImg] || [];
  const currentImage =
    (hlItem && activeFaceImages.find((im) => im.fileName === hlItem.file)) || activeFaceImages[0];
  const onOpen = (rid) => navigate(`/cola/${rid}${q ? `?q=${encodeURIComponent(searchParams.get('q'))}` : ''}`);

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
            <button
              className="btn secondary sm"
              onClick={() => {
                track('print_clicked', {});
                window.print();
              }}
            >
              <Icon name="print" size={16} /> Print
            </button>
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

        <div className="detail-grid">
          {/* label images */}
          <div>
            <div className="panel label-viewer" data-tour="detail-images">
              <div className="lv-main">
                <div className="lv-stage" style={{ maxWidth: 360, margin: '0 auto', position: 'relative' }}>
                  <LabelThumb rec={rec} src={currentImage && currentImage.url} style={{ aspectRatio: '4/5' }} />
                  {hlItem && activeImg === hlItem.face && hasBox(hlItem) && (
                    <BoundingBox item={hlItem} img={currentImage} />
                  )}
                  <button className="lv-expand" onClick={() => { track('lightbox_opened', { face: activeImg }); setLightbox(true); }} title="View full size" aria-label="View full size">
                    <Icon name="expand" size={16} /> Full size
                  </button>
                </div>
              </div>
              <div className="lv-thumbs">
                {faces.map((f) => {
                  const img = imagesByFace[f] && imagesByFace[f][0];
                  return (
                    <button key={f} className={'lv-thumb' + (activeImg === f ? ' on' : '')} onClick={() => { track('label_face_switched', { face: f }); setActiveImg(f); }}>
                      <LabelThumb rec={rec} src={img && img.url} />
                      <span className="lv-cap">{f}</span>
                    </button>
                  );
                })}
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
              <h3 className="d-section">Label identity</h3>
              <div className="d-fields">
                <Field label="Brand name">{rec.brand}</Field>
                <Field label="Fanciful name">{rec.fanciful}</Field>
                <Field label="Class / Type">{rec.classType}</Field>
                <Field label="Class / Type code" mono>
                  {rec.classTypeCode}
                </Field>
                <Field label="Net contents">{rec.netContents}</Field>
                <Field label="Alcohol content">{rec.abv ? `${rec.abv} ALC/VOL` : null}</Field>
              </div>

              <h3 className="d-section">Origin &amp; status</h3>
              <div className="d-fields">
                <Field label="Source">{rec.originGroup}</Field>
                <Field label="Origin">{rec.originFlag ? rec.originFlag + ' ' : ''}{rec.origin}</Field>
                <Field label="Origin code" mono>
                  {rec.originCode}
                </Field>
                <Field label="Status">{rec.status}</Field>
                <Field label="For sale in">{rec.forSaleIn}</Field>
                <Field label="Formula" mono>
                  {rec.formula || 'Not required'}
                </Field>
                {rec.category === 'Wine' && (
                  <Field label="Grape varietal">
                    {rec.grapeVarietals && rec.grapeVarietals.length ? rec.grapeVarietals.join(', ') : '—'}
                  </Field>
                )}
                {rec.category === 'Wine' && <Field label="Appellation">{rec.appellation || '—'}</Field>}
              </div>

              <h3 className="d-section">Application &amp; permit</h3>
              <div className="d-fields">
                <Field label="Applicant / business">{rec.applicant}</Field>
                <Field label="Mailing address">{rec.mailingAddress}</Field>
                <Field label="Application type">{rec.applicationType}</Field>
                <Field label="Permit / plant number" mono>
                  {rec.permitId || rec.permit}
                </Field>
                <Field label="Serial number" mono>
                  {rec.serial}
                </Field>
                <Field label="Vendor code" mono>
                  {rec.vendorCode}
                </Field>
                <Field label="Received as">{rec.receivedDescription || rec.receivedCode}</Field>
                <Field label="Date approved">{fmtDate(rec.approvalDate)}</Field>
              </div>

              <h3 className="d-section">Submitter</h3>
              <div className="d-fields">
                <Field label="Name">{rec.submitter}</Field>
                <Field label="Submitter ID" mono>
                  {rec.submitterId}
                </Field>
                <Field label="Telephone" mono>
                  {rec.submitterPhone}
                </Field>
                <Field label="Fax" mono>
                  {rec.submitterFax}
                </Field>
              </div>

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
                          {[p.address, p.city, [p.state, p.postalCode].filter(Boolean).join(' '), p.country]
                            .filter(Boolean)
                            .join(', ') || '—'}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}

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
                <div className="muted" style={{ fontSize: 13, padding: '8px 0' }}>
                  No text has been extracted from this label's images yet.
                </div>
              ) : (
                <>
                  <p className="ocr-hint">
                    <Icon name="info" size={13} />
                    <span>Select any text below to highlight where it appears on the label image.</span>
                  </p>
                  <div className="ocr-groups">
                    {itemGroups.map((group) => (
                      <div className="ocr-group" key={group.face}>
                        <div className="ocr-group-head">
                          <span className="ocr-face-tag">{group.face}</span>
                          <span className="ocr-group-count">{group.items.length}</span>
                        </div>
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
                                    setActiveImg(it.face);
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
        {memberSimilar.length > 0 && (
          <section style={{ marginTop: 40 }}>
            <h2 style={{ fontSize: 20, marginBottom: 4 }}>Similar COLAs from this industry member</h2>
            <p className="muted" style={{ margin: '0 0 16px', fontSize: 14 }}>
              Visually similar approved labels filed under permit {rec.permit || '—'}.
            </p>
            <div className="recent-grid">
              {memberSimilar.map((r, i) => (
                <SimilarCard key={r.id} r={r} onOpen={onOpen} tourAnchor={i === 0 ? 'detail-similar' : undefined} />
              ))}
            </div>
          </section>
        )}

        {othersSimilar.length > 0 && (
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
          faces={faces}
          imagesByFace={imagesByFace}
          face={activeImg}
          setFace={setActiveImg}
          hlItem={hlItem}
          onClose={() => setLightbox(false)}
        />
      )}
    </div>
  );
}
