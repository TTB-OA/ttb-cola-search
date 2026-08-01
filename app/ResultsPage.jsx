/* ============================================================
   Results page — Gallery / List / Table views + facets
   ============================================================ */
const { useState: useStateR, useMemo, useEffect: useEffectR } = React;

/* ---------- filtering ---------- */
function runSearch(criteria, facets) {
  const D = window.COLA.DATA;
  const q = (criteria.text || '').trim().toLowerCase();
  let out = D.filter((r) => {
    if (criteria.mode === 'image') {
      if (criteria.category && r.category !== criteria.category) return false;
      return true;
    }
    if (q) {
      const hay = [r.brand, r.fanciful, r.applicant, r.classType, r.classSub, r.origin, r.ttbId, r.serial, r.category]
        .join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (criteria.ttbId && !(r.ttbId + ' ' + r.serial).toLowerCase().includes(criteria.ttbId.toLowerCase())) return false;
    if (criteria.brand && !r.brand.toLowerCase().includes(criteria.brand.toLowerCase())) return false;
    if (criteria.fanciful && !r.fanciful.toLowerCase().includes(criteria.fanciful.toLowerCase())) return false;
    if (criteria.category && r.category !== criteria.category) return false;
    if (criteria.source && r.originGroup !== criteria.source) return false;
    if (criteria.origin && r.origin !== criteria.origin) return false;
    if (criteria.status && r.status !== criteria.status) return false;
    if (criteria.dateFrom && r.approvalDate < criteria.dateFrom) return false;
    if (criteria.dateTo && r.approvalDate > criteria.dateTo) return false;
    return true;
  });
  // facet refinement
  if (facets.cats.length) out = out.filter((r) => facets.cats.includes(r.category));
  if (facets.sources.length) out = out.filter((r) => facets.sources.includes(r.originGroup));
  if (facets.origins.length) out = out.filter((r) => facets.origins.includes(r.origin));
  if (facets.statuses.length) out = out.filter((r) => facets.statuses.includes(r.status));

  if (criteria.mode === 'image') {
    out = out.map((r) => ({ ...r, score: window.COLA.visualScore(r, 7) })).sort((a, b) => b.score - a.score);
  } else if (criteria.sort === 'approvalDate') {
    out = [...out].sort((a, b) => b.approvalDate.localeCompare(a.approvalDate));
  } else if (criteria.sort === 'brand') {
    out = [...out].sort((a, b) => a.brand.localeCompare(b.brand));
  }
  return out;
}

/* ---------- facet group ---------- */
function FacetGroup({ title, options, selected, onToggle, counts }) {
  return (
    <div className="facet">
      <div className="facet-title">{title}</div>
      {options.map((o) => (
        <label className="checkrow" key={o}>
          <input type="checkbox" checked={selected.includes(o)} onChange={() => onToggle(o)} />
          <span>{o}</span>
          <span className="count">{counts[o] || 0}</span>
        </label>
      ))}
    </div>
  );
}

/* ---------- score meter ---------- */
function ScoreMeter({ score, compact }) {
  const hue = score >= 88 ? 'var(--green)' : score >= 75 ? 'var(--gold-dark)' : 'var(--base)';
  if (compact) return <span className="score-pill" style={{ color: hue }}><b>{score}%</b></span>;
  return (
    <div className="score">
      <div className="score-row"><Icon name="sparkle" size={14} /> <b>{score}%</b> visual match</div>
      <div className="score-bar"><span style={{ width: score + '%', background: hue }}></span></div>
    </div>
  );
}

const MATCH_TAGS = ['Color palette', 'Layout', 'Typography', 'Imagery'];
function matchChips(rec) {
  const n = 2 + (rec.id % 3);
  return MATCH_TAGS.slice(0, n);
}

/* ---------- views ---------- */
function GalleryView({ rows, criteria, onOpen }) {
  const isImg = criteria.mode === 'image';
  return (
    <div className="gallery-grid">
      {rows.map((r) => (
        <button key={r.id} className="g-card" onClick={() => onOpen(r.id)}>
          <div className="g-thumb"><LabelThumb rec={r} />{isImg && <span className="g-score"><Icon name="sparkle" size={12} />{r.score}%</span>}</div>
          <div className="g-body">
            <div className="row between gap-8"><CatTag rec={r} /><StatusBadge status={r.status} /></div>
            <div className="g-brand"><Highlight text={r.brand} q={criteria.brand || criteria.text} /></div>
            <div className="g-fanciful"><Highlight text={r.fanciful} q={criteria.fanciful || criteria.text} /></div>
            <div className="g-meta mono">{r.ttbId}</div>
            <div className="g-meta">{r.origin} · {window.COLA.fmtDate(r.approvalDate)}</div>
            {isImg && <div className="chips" style={{ marginTop: 8 }}>{matchChips(r).map((m) => <span key={m} className="mchip">{m}</span>)}</div>}
          </div>
        </button>
      ))}
    </div>
  );
}

function ListView({ rows, criteria, onOpen }) {
  const isImg = criteria.mode === 'image';
  return (
    <div className="list-view">
      {rows.map((r) => (
        <button key={r.id} className="l-row" onClick={() => onOpen(r.id)}>
          <div className="l-thumb"><LabelThumb rec={r} /></div>
          <div className="l-main">
            <div className="row gap-8" style={{ marginBottom: 4 }}><CatTag rec={r} /><span className="muted mono" style={{ fontSize: 12 }}>{r.classType}</span></div>
            <div className="l-brand"><Highlight text={r.brand} q={criteria.brand || criteria.text} /> <span className="l-fanciful">{r.fanciful}</span></div>
            <div className="l-meta">
              <span className="mono">{r.ttbId}</span>
              <span>{r.origin}</span>
              <span>{r.applicant}</span>
            </div>
            {isImg && <div className="chips" style={{ marginTop: 8 }}>{matchChips(r).map((m) => <span key={m} className="mchip">{m}</span>)}</div>}
          </div>
          <div className="l-side">
            {isImg ? <ScoreMeter score={r.score} /> : <StatusBadge status={r.status} />}
            <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>Approved {window.COLA.fmtDate(r.approvalDate)}</div>
            <span className="linkbtn" style={{ marginTop: 8 }}>View COLA <Icon name="chevRight" size={14} /></span>
          </div>
        </button>
      ))}
    </div>
  );
}

function TableView({ rows, criteria, onOpen }) {
  const isImg = criteria.mode === 'image';
  return (
    <div className="table-wrap panel">
      <table className="data-table">
        <thead>
          <tr>
            <th style={{ width: 52 }}></th>
            <th>Brand / Fanciful</th>
            <th>Class / Type</th>
            <th>Origin</th>
            <th>TTB ID</th>
            <th>Approved</th>
            <th>{isImg ? 'Match' : 'Status'}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} onClick={() => onOpen(r.id)}>
              <td><div className="t-thumb"><LabelThumb rec={r} /></div></td>
              <td><div style={{ fontWeight: 700 }}><Highlight text={r.brand} q={criteria.brand || criteria.text} /></div><div className="muted" style={{ fontSize: 12.5 }}>{r.fanciful}</div></td>
              <td><CatTag rec={r} /><div className="muted" style={{ fontSize: 12, marginTop: 3 }}>{r.classSub}</div></td>
              <td>{r.origin}</td>
              <td className="mono" style={{ fontSize: 12.5 }}>{r.ttbId}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{window.COLA.fmtDate(r.approvalDate)}</td>
              <td>{isImg ? <ScoreMeter score={r.score} compact /> : <StatusBadge status={r.status} />}</td>
              <td><Icon name="chevRight" size={16} className="muted" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- active filter chips ---------- */
function ActiveChips({ criteria, onClearKey }) {
  const items = [];
  const push = (k, label) => { if (criteria[k]) items.push({ k, label: label + ': ' + criteria[k] }); };
  if (criteria.text) items.push({ k: 'text', label: '“' + criteria.text + '”' });
  push('ttbId', 'TTB/Serial'); push('brand', 'Brand'); push('fanciful', 'Product');
  push('category', 'Commodity'); push('source', 'Source'); push('origin', 'Origin'); push('status', 'Status');
  if (criteria.dateFrom) items.push({ k: 'dateFrom', label: 'From ' + criteria.dateFrom });
  if (criteria.dateTo) items.push({ k: 'dateTo', label: 'To ' + criteria.dateTo });
  if (!items.length) return null;
  return (
    <div className="chips" style={{ marginTop: 12 }}>
      {items.map((it) => (
        <span className="chip" key={it.k}>{it.label}<button onClick={() => onClearKey(it.k)} aria-label="Remove"><Icon name="close" size={12} /></button></span>
      ))}
    </div>
  );
}

/* ---------- main ---------- */
function ResultsPage({ criteria, onOpen, onEditSearch, onUpdateCriteria, view, setView, showScores }) {
  const [facets, setFacets] = useStateR({ cats: [], sources: [], origins: [], statuses: [] });
  const [loading, setLoading] = useStateR(true);

  useEffectR(() => {
    setLoading(true);
    const t = setTimeout(() => setLoading(false), criteria.mode === 'image' ? 850 : 420);
    return () => clearTimeout(t);
  }, [JSON.stringify(criteria)]);

  const rows = useMemo(() => runSearch(criteria, facets), [JSON.stringify(criteria), JSON.stringify(facets)]);
  const base = useMemo(() => runSearch({ ...criteria }, { cats: [], sources: [], origins: [], statuses: [] }), [JSON.stringify(criteria)]);

  const counts = useMemo(() => {
    const c = { cat: {}, source: {}, origin: {}, status: {} };
    base.forEach((r) => {
      c.cat[r.category] = (c.cat[r.category] || 0) + 1;
      c.source[r.originGroup] = (c.source[r.originGroup] || 0) + 1;
      c.origin[r.origin] = (c.origin[r.origin] || 0) + 1;
      c.status[r.status] = (c.status[r.status] || 0) + 1;
    });
    return c;
  }, [base]);

  const toggle = (group, val) => setFacets((f) => {
    const arr = f[group];
    return { ...f, [group]: arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val] };
  });

  const isImg = criteria.mode === 'image';
  const View = view === 'gallery' ? GalleryView : view === 'list' ? ListView : TableView;
  const showImg = isImg && showScores;

  const originOpts = Object.keys(counts.origin).sort();
  const domOpts = window.COLA.DOMESTIC_ORIGINS.filter((o) => counts.origin[o]);
  const impOpts = window.COLA.IMPORTED_ORIGINS.filter((o) => counts.origin[o]);
  const showDom = !facets.sources.length || facets.sources.includes('Domestic');
  const showImp = !facets.sources.length || facets.sources.includes('Imported');

  return (
    <div className="results-page">
      {/* sub header */}
      <div className="results-bar">
        <div className="wrap">
          <button className="linkbtn" onClick={onEditSearch}><Icon name="chevLeft" size={16} /> Modify search</button>
          {isImg ? (
            <div className="img-query">
              <div className="iq-thumb"><Icon name="image" size={22} /></div>
              <div>
                <div style={{ fontWeight: 700 }}>Visual similarity results</div>
                <div className="muted" style={{ fontSize: 13 }}>{criteria.image ? criteria.image.name : 'uploaded-label.jpg'} · ranked by match score</div>
              </div>
            </div>
          ) : (
            <ActiveChips criteria={criteria} onClearKey={(k) => onUpdateCriteria({ ...criteria, [k]: '' })} />
          )}
        </div>
      </div>

      <div className="wrap results-layout">
        {/* facets */}
        <aside className="facets panel">
          <div className="row between" style={{ marginBottom: 6 }}>
            <div className="section-title">Refine results</div>
            {(facets.cats.length || facets.sources.length || facets.origins.length || facets.statuses.length) ?
              <button className="linkbtn" onClick={() => setFacets({ cats: [], sources: [], origins: [], statuses: [] })}>Reset</button> : null}
          </div>
          <FacetGroup title="Commodity" options={window.COLA.CATEGORIES} selected={facets.cats} onToggle={(v) => toggle('cats', v)} counts={counts.cat} />
          <hr className="divider" />
          <FacetGroup title="Status" options={window.COLA.STATUSES} selected={facets.statuses} onToggle={(v) => toggle('statuses', v)} counts={counts.status} />
          <hr className="divider" />
          <FacetGroup title="Source" options={window.COLA.SOURCES} selected={facets.sources} onToggle={(v) => toggle('sources', v)} counts={counts.source} />
          {showDom && domOpts.length > 0 && (
            <div className="facet facet-sub">
              <div className="facet-subtitle">U.S. states &amp; territories</div>
              {domOpts.map((o) => (
                <label className="checkrow" key={o}>
                  <input type="checkbox" checked={facets.origins.includes(o)} onChange={() => toggle('origins', o)} />
                  <span>{o}</span><span className="count">{counts.origin[o] || 0}</span>
                </label>
              ))}
            </div>
          )}
          {showImp && impOpts.length > 0 && (
            <div className="facet facet-sub">
              <div className="facet-subtitle">Countries</div>
              {impOpts.map((o) => (
                <label className="checkrow" key={o}>
                  <input type="checkbox" checked={facets.origins.includes(o)} onChange={() => toggle('origins', o)} />
                  <span>{o}</span><span className="count">{counts.origin[o] || 0}</span>
                </label>
              ))}
            </div>
          )}
        </aside>

        {/* main */}
        <div className="results-main">
          <div className="results-toolbar">
            <div>
              <div style={{ fontSize: 22, fontWeight: 800 }}>
                {loading ? 'Searching…' : <>{rows.length} {rows.length === 1 ? 'result' : 'results'}</>}
              </div>
              {!loading && <div className="muted" style={{ fontSize: 13.5 }}>{isImg ? 'Similar labels in the registry' : 'Matching certificates of label approval'}</div>}
            </div>
            <div className="row gap-16 wrap-flex">
              {!isImg && (
                <div className="row gap-8">
                  <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>Sort</span>
                  <select className="select" style={{ height: 38, width: 'auto', fontSize: 14 }}
                    value={criteria.sort || 'relevance'} onChange={(e) => onUpdateCriteria({ ...criteria, sort: e.target.value })}>
                    <option value="relevance">Relevance</option>
                    <option value="approvalDate">Newest approval</option>
                    <option value="brand">Brand (A–Z)</option>
                  </select>
                </div>
              )}
              <div className="seg">
                <button className={view === 'gallery' ? 'active' : ''} onClick={() => setView('gallery')} title="Gallery"><Icon name="grid" /></button>
                <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')} title="List"><Icon name="list" /></button>
                <button className={view === 'table' ? 'active' : ''} onClick={() => setView('table')} title="Table"><Icon name="table" /></button>
              </div>
            </div>
          </div>

          {loading ? (
            <div className="gallery-grid">
              {Array.from({ length: 6 }).map((_, i) => <div key={i} className="g-card"><div className="skel" style={{ aspectRatio: '4/5' }}></div><div className="g-body"><div className="skel" style={{ height: 14, width: '60%', marginBottom: 8 }}></div><div className="skel" style={{ height: 12, width: '90%' }}></div></div></div>)}
            </div>
          ) : rows.length === 0 ? (
            <div className="empty panel">
              <Icon name="search" size={34} className="muted" />
              <h3 style={{ marginTop: 12 }}>No matching labels</h3>
              <p className="muted">Try removing a filter or broadening your search terms.</p>
              <button className="btn secondary sm" onClick={onEditSearch}>Modify search</button>
            </div>
          ) : (
            <View rows={rows} criteria={{ ...criteria, mode: showImg ? 'image' : criteria.mode }} onOpen={onOpen} />
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ResultsPage });
