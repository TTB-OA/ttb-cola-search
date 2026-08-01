/* ============================================================
   Search landing page
   ============================================================ */
const { useState: useStateS, useRef } = React;

const QUICK_CATS = window.COLA.CATEGORIES;

function ModeTabs({ mode, setMode }) {
  return (
    <div className="seg" role="tablist" style={{ marginBottom: 22 }}>
      <button className={mode === 'text' ? 'active' : ''} onClick={() => setMode('text')}>
        <Icon name="search" /> Text search
      </button>
      <button className={mode === 'image' ? 'active' : ''} onClick={() => setMode('image')}>
        <Icon name="image" /> Search by image
      </button>
    </div>
  );
}

/* ---------- Advanced fields ---------- */
function AdvancedFields({ draft, set }) {
  const C = window.COLA;
  return (
    <div className="adv-grid">
      <div className="field">
        <label>TTB ID or Serial number</label>
        <div className="hint">14-digit TTB ID, or applicant serial number</div>
        <input className="input mono" placeholder="e.g. 25040010011..." value={draft.ttbId} onChange={(e) => set('ttbId', e.target.value)} />
      </div>
      <div className="field">
        <label>Brand name</label>
        <div className="hint">Name marketed to consumers</div>
        <input className="input" placeholder="e.g. Cedar Hollow" value={draft.brand} onChange={(e) => set('brand', e.target.value)} />
      </div>
      <div className="field">
        <label>Product / Fanciful name</label>
        <div className="hint">Product-specific designation</div>
        <input className="input" placeholder="e.g. Estate Reserve" value={draft.fanciful} onChange={(e) => set('fanciful', e.target.value)} />
      </div>
      <div className="field">
        <label>Class / Type</label>
        <select className="select" value={draft.category} onChange={(e) => set('category', e.target.value)}>
          <option value="">All commodities</option>
          {C.CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="field">
        <label>Source</label>
        <select className="select" value={draft.source} onChange={(e) => { set('source', e.target.value); set('origin', ''); }}>
          <option value="">Domestic &amp; imported</option>
          {C.SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div className="field">
        <label>Origin — state or country</label>
        <select className="select" value={draft.origin} onChange={(e) => set('origin', e.target.value)}>
          <option value="">Any origin</option>
          {(draft.source !== 'Imported') && (
            <optgroup label="U.S. states &amp; territories">
              {C.DOMESTIC_ORIGINS.map((o) => <option key={o} value={o}>{o}</option>)}
            </optgroup>
          )}
          {(draft.source !== 'Domestic') && (
            <optgroup label="Countries">
              {C.IMPORTED_ORIGINS.map((o) => <option key={o} value={o}>{o}</option>)}
            </optgroup>
          )}
        </select>
      </div>
      <div className="field">
        <label>Status</label>
        <select className="select" value={draft.status} onChange={(e) => set('status', e.target.value)}>
          <option value="">Any status</option>
          {C.STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div className="field" style={{ gridColumn: 'span 1' }}>
        <label>Approval date — from</label>
        <input type="date" className="input" value={draft.dateFrom} onChange={(e) => set('dateFrom', e.target.value)} />
      </div>
      <div className="field">
        <label>Approval date — to</label>
        <input type="date" className="input" value={draft.dateTo} onChange={(e) => set('dateTo', e.target.value)} />
      </div>
    </div>
  );
}

/* ---------- Image search ---------- */
function ImageSearch({ draft, set, onSearch }) {
  const inputRef = useRef(null);
  const [drag, setDrag] = useStateS(false);

  function handleFile(file) {
    if (!file) return;
    const url = URL.createObjectURL(file);
    set('image', { name: file.name, url });
  }
  function onDrop(e) {
    e.preventDefault(); setDrag(false);
    handleFile(e.dataTransfer.files && e.dataTransfer.files[0]);
  }

  return (
    <div>
      <div
        className="dropzone"
        onClick={() => !draft.image && inputRef.current && inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        style={{ borderColor: drag ? 'var(--accent)' : '', background: drag ? 'var(--accent-lighter)' : '' }}
      >
        {!draft.image ? (
          <>
            <div className="dz-ico"><Icon name="upload" size={30} /></div>
            <div style={{ fontWeight: 700, fontSize: 17 }}>Drag a label image here, or <span style={{ color: 'var(--accent)' }}>browse files</span></div>
            <div className="muted" style={{ fontSize: 13.5, marginTop: 4 }}>JPG, PNG, or PDF up to 20&nbsp;MB. We match on color, layout, and imagery — text is optional.</div>
            <input ref={inputRef} type="file" accept="image/*,.pdf" hidden onChange={(e) => handleFile(e.target.files[0])} />
          </>
        ) : (
          <div className="row gap-16" style={{ width: '100%', justifyContent: 'center' }}>
            <div className="upload-preview"><Icon name="image" size={28} /></div>
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontWeight: 700 }}>{draft.image.name}</div>
              <div className="muted" style={{ fontSize: 13 }}>Ready to match</div>
              <button className="linkbtn" style={{ marginTop: 6 }} onClick={(e) => { e.stopPropagation(); set('image', null); }}>Remove &amp; choose another</button>
            </div>
          </div>
        )}
      </div>

      <div className="row gap-16 wrap-flex" style={{ marginTop: 18, alignItems: 'center' }}>
        <div className="field" style={{ margin: 0, minWidth: 220 }}>
          <span className="lbl">Restrict to commodity (optional)</span>
          <select className="select" value={draft.category} onChange={(e) => set('category', e.target.value)}>
            <option value="">All commodities</option>
            {window.COLA.CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div style={{ flex: 1 }}></div>
        <button className="btn lg" disabled={!draft.image} onClick={() => onSearch('image')}>
          <Icon name="sparkle" /> Find similar labels
        </button>
      </div>

      <div className="info-note" style={{ marginTop: 20 }}>
        <Icon name="info" size={18} />
        <div>Visual similarity search compares the dominant color palette, composition, and graphic elements of your image against approved label artwork. Results are ranked by a visual match score and are intended to surface potentially conflicting or similar trade dress.</div>
      </div>
    </div>
  );
}

/* ---------- Main search page ---------- */
function SearchPage({ initial, onSearch }) {
  const [draft, setDraft] = useStateS(initial);
  const [advanced, setAdvanced] = useStateS(initial.advanced || false);
  const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }));
  const recent = [...window.COLA.DATA].filter(d => d.status === 'Approved')
    .sort((a, b) => b.approvalDate.localeCompare(a.approvalDate)).slice(0, 6);

  function submit(mode) {
    onSearch({ ...draft, mode: mode || 'text', advanced });
  }

  return (
    <div>
      {/* hero */}
      <section className="hero">
        <div className="wrap">
          <div className="hero-inner">
            <span className="section-title" style={{ color: 'var(--accent)' }}>Certificate of Label Approval</span>
            <h1 className="hero-title">Search the public COLA registry</h1>
            <p className="hero-sub">Find approved alcohol beverage labels across wine, malt beverages, and distilled spirits. Search by any field, or upload a label image to find visually similar approvals.</p>

            <div className="panel search-card">
              <ModeTabs mode={draft.mode} setMode={(m) => set('mode', m)} />

              {draft.mode === 'text' ? (
                <>
                  <div className="field" style={{ margin: 0 }}>
                    <span className="lbl">Search all label records</span>
                    <div className="input-group">
                      <input
                        className="input"
                        style={{ fontSize: 17 }}
                        placeholder="Brand, fanciful name, TTB ID, applicant, origin…"
                        value={draft.text}
                        onChange={(e) => set('text', e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && submit('text')}
                      />
                      <button className="btn" onClick={() => submit('text')}><Icon name="search" /> Search</button>
                    </div>
                    <div className="hint" style={{ marginTop: 8 }}>One box searches across brand, product, applicant, class/type, origin, and TTB ID.</div>
                  </div>

                  <div className="row between" style={{ marginTop: 16 }}>
                    <div className="chips">
                      <span className="muted" style={{ fontSize: 13, fontWeight: 600, alignSelf: 'center' }}>Quick filter:</span>
                      {QUICK_CATS.map((c) => (
                        <button key={c} className={'qchip' + (draft.category === c ? ' on' : '')}
                          onClick={() => set('category', draft.category === c ? '' : c)}>{c}</button>
                      ))}
                    </div>
                    <button className="linkbtn" onClick={() => setAdvanced(!advanced)}>
                      <Icon name="sliders" size={16} /> {advanced ? 'Hide advanced search' : 'Advanced search'}
                    </button>
                  </div>

                  {advanced && (
                    <div className="adv-wrap">
                      <hr className="divider" style={{ margin: '20px 0' }} />
                      <AdvancedFields draft={draft} set={set} />
                      <div className="row between" style={{ marginTop: 4 }}>
                        <button className="linkbtn" onClick={() => setDraft({ ...initial, mode: 'text' })}>Clear all fields</button>
                        <button className="btn" onClick={() => submit('text')}><Icon name="search" /> Search registry</button>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <ImageSearch draft={draft} set={set} onSearch={submit} />
              )}
            </div>
          </div>
        </div>
      </section>

      {/* recent approvals */}
      <section className="wrap" style={{ marginTop: 44 }}>
        <div className="row between" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 20 }}>Recently approved</h2>
          <button className="linkbtn" onClick={() => onSearch({ ...initial, mode: 'text', sort: 'approvalDate' })}>
            Browse all approvals <Icon name="arrowRt" size={16} />
          </button>
        </div>
        <div className="recent-grid">
          {recent.map((r) => (
            <button key={r.id} className="recent-card" onClick={() => onSearch({ ...initial, openId: r.id })}>
              <LabelThumb rec={r} />
              <div className="recent-meta">
                <div className="row between gap-8">
                  <CatTag rec={r} />
                  <span className="muted mono" style={{ fontSize: 11 }}>{window.COLA.fmtDate(r.approvalDate)}</span>
                </div>
                <div style={{ fontWeight: 700, marginTop: 7 }}>{r.brand}</div>
                <div className="muted" style={{ fontSize: 13 }}>{r.fanciful}</div>
              </div>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

Object.assign(window, { SearchPage });
