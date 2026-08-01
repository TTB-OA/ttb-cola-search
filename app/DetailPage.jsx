/* ============================================================
   COLA detail page
   ============================================================ */
function Field({ label, children, mono }) {
  return (
    <div className="d-field">
      <div className="d-label">{label}</div>
      <div className={'d-value' + (mono ? ' mono' : '')}>{children || '—'}</div>
    </div>
  );
}

function SimilarCard({ r, onOpen, score }) {
  return (
    <button className="recent-card" onClick={() => onOpen(r.id)}>
      <div style={{ position: 'relative' }}>
        <LabelThumb rec={r} />
        <span className="g-score"><Icon name="sparkle" size={12} />{score}%</span>
      </div>
      <div className="recent-meta">
        <div className="row between gap-8"><CatTag rec={r} /><StatusBadge status={r.status} /></div>
        <div style={{ fontWeight: 700, marginTop: 7 }}>{r.brand}</div>
        <div className="muted" style={{ fontSize: 13 }}>{r.fanciful}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{window.COLA.fmtDate(r.approvalDate)}</div>
      </div>
    </button>
  );
}

function SimilarSection({ title, sub, rows, rec, onOpen }) {
  if (!rows.length) return null;
  return (
    <section style={{ marginTop: 40 }}>
      <h2 style={{ fontSize: 20, marginBottom: 4 }}>{title}</h2>
      <p className="muted" style={{ margin: '0 0 16px', fontSize: 14 }}>{sub}</p>
      <div className="recent-grid">
        {rows.map((r) => <SimilarCard key={r.id} r={r} onOpen={onOpen} score={window.COLA.visualScore(r, rec.id)} />)}
      </div>
    </section>
  );
}

function Lightbox({ rec, face, setFace, hlItem, onClose }) {
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
      const faces = ['front', 'back', 'neck'];
      const i = faces.indexOf(face);
      if (e.key === 'ArrowRight') setFace(faces[(i + 1) % 3]);
      if (e.key === 'ArrowLeft') setFace(faces[(i + 2) % 3]);
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = ''; };
  }, [face]);
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-label="Full-size label image">
      <button className="lb-close" onClick={onClose} aria-label="Close"><Icon name="close" size={22} /></button>
      <div className="lb-body" onClick={(e) => e.stopPropagation()}>
        <button className="lb-arrow" onClick={() => setFace(['front','back','neck'][(['front','back','neck'].indexOf(face) + 2) % 3])} aria-label="Previous image"><Icon name="chevLeft" size={26} /></button>
        <div className="lb-stage">
          <LabelThumb rec={rec} />
          {hlItem && hlItem.face === face && (
            <div className="bbox" style={{ left: hlItem.box.x + '%', top: hlItem.box.y + '%', width: hlItem.box.w + '%', height: hlItem.box.h + '%' }}>
              <span className="bbox-tag">{hlItem.type.replace(/_/g, ' ')} · {Math.round(hlItem.conf * 100)}%</span>
            </div>
          )}
          <div className="lb-cap"><b>{rec.brand}</b> — {face} label · TTB ID {rec.ttbId}</div>
        </div>
        <button className="lb-arrow" onClick={() => setFace(['front','back','neck'][(['front','back','neck'].indexOf(face) + 1) % 3])} aria-label="Next image"><Icon name="chevRight" size={26} /></button>
      </div>
      <div className="lb-thumbs" onClick={(e) => e.stopPropagation()}>
        {['front','back','neck'].map((f) => (
          <button key={f} className={'lv-thumb' + (face === f ? ' on' : '')} onClick={() => setFace(f)}>
            <LabelThumb rec={rec} /><span className="lv-cap">{f}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function DetailPage({ rec, onBack, onOpen, searchQuery }) {
  const [activeImg, setActiveImg] = React.useState('front');
  const [hlItem, setHlItem] = React.useState(null);
  const [lightbox, setLightbox] = React.useState(false);
  const C = window.COLA;
  const q = (searchQuery || '').trim().toLowerCase();
  const items = (rec && rec.imageItems) || [];
  const matchedItems = q ? items.filter((it) => it.text.toLowerCase().includes(q)) : [];
  React.useEffect(() => {
    const first = matchedItems.length ? matchedItems[0] : null;
    setHlItem(first);
    setActiveImg(first ? first.face : 'front');
  }, [rec && rec.id, q]);
  if (!rec) return null;
  const byScore = (a, b) => C.visualScore(b, rec.id) - C.visualScore(a, rec.id);
  const sameMember = C.DATA.filter((r) => r.id !== rec.id && r.applicant === rec.applicant).sort(byScore).slice(0, 6);
  const otherMembers = C.DATA.filter((r) => r.id !== rec.id && r.applicant !== rec.applicant && r.category === rec.category)
    .sort(byScore).slice(0, 6);
  const faces = ['front', 'back', 'neck'];

  return (
    <div className="detail-page">
      <div className="wrap">
        <nav className="crumbs">
          <button className="linkbtn" onClick={onBack}><Icon name="chevLeft" size={16} /> Back to results</button>
          <span className="muted" style={{ margin: '0 8px' }}>/</span>
          <span className="muted">{rec.brand} — {rec.fanciful}</span>
        </nav>

        <div className="detail-head">
          <div>
            <div className="row gap-10" style={{ marginBottom: 10 }}><CatTag rec={rec} /><StatusBadge status={rec.status} /></div>
            <h1 style={{ fontSize: 30 }}>{rec.brand}</h1>
            <div className="serif" style={{ fontSize: 18, fontStyle: 'italic', color: 'var(--base-darker)' }}>{rec.fanciful}</div>
            <div className="row gap-16 wrap-flex" style={{ marginTop: 12 }}>
              <span className="mono d-ttb">TTB ID {rec.ttbId}</span>
              <span className="muted">Approved {C.fmtDate(rec.approvalDate)}</span>
            </div>
          </div>
          <div className="row gap-8">
            <button className="btn secondary sm" onClick={() => window.print()}><Icon name="print" size={16} /> Print</button>
            <button className="btn sm"><Icon name="download" size={16} /> Download COLA</button>
          </div>
        </div>

        <div className="detail-grid">
          {/* label images */}
          <div>
            <div className="panel label-viewer">
              <div className="lv-main">
                <div className="lv-stage" style={{ maxWidth: 360, margin: '0 auto', position: 'relative' }}>
                  <LabelThumb rec={rec} style={{ aspectRatio: '4/5' }} />
                  {hlItem && activeImg === hlItem.face && (
                    <div className="bbox" style={{ left: hlItem.box.x + '%', top: hlItem.box.y + '%', width: hlItem.box.w + '%', height: hlItem.box.h + '%' }}>
                      <span className="bbox-tag">{hlItem.type.replace(/_/g, ' ')} · {Math.round(hlItem.conf * 100)}%</span>
                    </div>
                  )}
                  <button className="lv-expand" onClick={() => setLightbox(true)} title="View full size" aria-label="View full size">
                    <Icon name="expand" size={16} /> Full size
                  </button>
                </div>
              </div>
              <div className="lv-thumbs">
                {faces.map((f) => (
                  <button key={f} className={'lv-thumb' + (activeImg === f ? ' on' : '')} onClick={() => setActiveImg(f)}>
                    <LabelThumb rec={rec} />
                    <span className="lv-cap">{f}</span>
                  </button>
                ))}
              </div>
              <div className="muted" style={{ fontSize: 12, textAlign: 'center', marginTop: 12 }}>
                <Icon name="info" size={13} /> Label artwork shown as a representative placeholder in this prototype.
              </div>
            </div>
          </div>

          {/* fields */}
          <div>
            <div className="panel d-panel">
              <h3 className="d-section">Label identity</h3>
              <div className="d-fields">
                <Field label="Brand name">{rec.brand}</Field>
                <Field label="Fanciful name">{rec.fanciful}</Field>
                <Field label="Class / Type">{rec.classType}</Field>
                <Field label="Class / Type code" mono>{rec.classTypeCode}</Field>
                <Field label="Net contents">{rec.netContents}</Field>
                <Field label="Alcohol content">{rec.abv} ALC/VOL</Field>
              </div>

              <h3 className="d-section">Origin &amp; status</h3>
              <div className="d-fields">
                <Field label="Source">{rec.originGroup}</Field>
                <Field label="Origin">{rec.origin}</Field>
                <Field label="Origin code" mono>{rec.originCode}</Field>
                <Field label="Status">{rec.status}</Field>
                <Field label="For sale in">{rec.forSaleIn}</Field>
                <Field label="Formula" mono>{rec.formula || 'Not required'}</Field>
                {rec.category === 'Wine' && <Field label="Grape varietal">{rec.grapeVarietals && rec.grapeVarietals.length ? rec.grapeVarietals.join(', ') : '—'}</Field>}
                {rec.category === 'Wine' && <Field label="Appellation">{rec.appellation || '—'}</Field>}
              </div>

              <h3 className="d-section">Application &amp; permit</h3>
              <div className="d-fields">
                <Field label="Applicant / business">{rec.applicant}</Field>
                <Field label="Mailing address">{rec.mailingAddress}</Field>
                <Field label="Application type">{rec.applicationType}</Field>
                <Field label="Permit / plant number" mono>{rec.permit}</Field>
                <Field label="Serial number" mono>{rec.serial}</Field>
                <Field label="Vendor code" mono>{rec.vendorCode}</Field>
                <Field label="Date received">{C.fmtDate(rec.receivedDate)}</Field>
                <Field label="Date approved">{C.fmtDate(rec.approvalDate)}</Field>
              </div>

              {rec.qualifications && (
                <>
                  <h3 className="d-section">Qualifications</h3>
                  <div className="d-qual">{rec.qualifications}</div>
                </>
              )}
            </div>

            {/* extracted label text (image_analysis_items) */}
            <div className="panel d-panel" style={{ marginTop: 20 }}>
              <div className="row between" style={{ marginBottom: 4 }}>
                <h3 className="d-section" style={{ margin: 0, border: 0, paddingBottom: 4 }}>Text detected on label images</h3>
                {hlItem && <button className="linkbtn" onClick={() => setHlItem(null)}>Clear highlight</button>}
              </div>
              {q && matchedItems.length > 0 && (
                <div className="ocr-matchnote"><Icon name="search" size={13} /><span>Your search “{searchQuery}” matched {matchedItems.length === 1 ? 'this text' : matchedItems.length + ' items'} on the label — highlighted at left.</span></div>
              )}
              <div className="ocr-list">
                {items.map((it, i) => {
                  const isMatch = q && it.text.toLowerCase().includes(q);
                  const on = hlItem === it;
                  return (
                    <button key={i} className={'ocr-row' + (on ? ' on' : '') + (isMatch ? ' hit' : '')} onClick={() => { if (on) { setHlItem(null); } else { setHlItem(it); setActiveImg(it.face); } }}>
                      <span className="ocr-face-tag">{it.face}</span>
                      <span className="ocr-type">{it.type.replace(/_/g, ' ')}</span>
                      <span className="ocr-text">{isMatch ? <Highlight text={it.text} q={searchQuery} /> : it.text}</span>
                      <span className="ocr-conf mono">{Math.round(it.conf * 100)}%</span>
                    </button>
                  );
                })}
              </div>
              <div className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>Extracted by ttb-ocr-v2 · select a row to locate it on the label image at left.</div>
            </div>
          </div>
        </div>

        {/* similar labels */}
        <SimilarSection
          title={'Similar labels from ' + rec.applicant.split(',')[0]}
          sub="Other approvals held by this industry member, ranked by visual similarity to this label."
          rows={sameMember} rec={rec} onOpen={onOpen} />
        <SimilarSection
          title="Similar labels from other industry members"
          sub="Visually similar approved labels held by other permittees — useful for trade-dress comparison."
          rows={otherMembers} rec={rec} onOpen={onOpen} />
      </div>
      {lightbox && <Lightbox rec={rec} face={activeImg} setFace={setActiveImg} hlItem={hlItem} onClose={() => setLightbox(false)} />}
    </div>
  );
}

Object.assign(window, { DetailPage });
