import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Icon from '../components/Icon.jsx';
import LabelThumb from '../components/LabelThumb.jsx';
import { StatusBadge, CatTag } from '../components/Badges.jsx';
import Highlight from '../components/Highlight.jsx';
import ScoreMeter, { toPct } from '../components/ScoreMeter.jsx';
import { api } from '../lib/api.js';
import { fmtDate } from '../lib/format.js';
import { clearPendingImageSearch, readPendingImageSearch } from '../lib/imageSearchStore.js';
import { track } from '../lib/analytics.js';
import { useAsync } from '../hooks/useAsync.js';
import { useDocumentTitle } from '../hooks/useDocumentTitle.js';
import { useIsMobile } from '../hooks/useIsMobile.js';

const PAGE_SIZE = 24;

// URL params that are search filters (as opposed to view/paging state).
const FILTER_KEYS = [
  'q',
  'ttbId',
  'brand',
  'fanciful',
  'applicant',
  'business',
  'permit',
  'permitName',
  'permitCity',
  'permitState',
  'submitter',
  'varietal',
  'qualification',
  'labelText',
  'commodity',
  'classType',
  'receivedBy',
  'source',
  'origin',
  'status',
  'dateFrom',
  'dateTo',
];

// Map a facet group name to the single-value URL/API param it controls.
const FACET_PARAM = {
  commodity: 'commodity',
  source: 'source',
  origin: 'origin',
  status: 'status',
  permitState: 'permitState',
};

function paramsToObject(sp) {
  const o = {};
  for (const [k, v] of sp.entries()) o[k] = v;
  return o;
}

// Keeps a long describe prompt from overrunning the browser tab title.
function clip(value, max = 60) {
  const s = String(value).trim();
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

/* ---------- facet group ---------- */
function FacetGroup({ title, buckets, selected, onSelect }) {
  if (!buckets || !buckets.length) return null;
  return (
    <div className="facet">
      <div className="facet-title">{title}</div>
      {buckets.map((b) => (
        <label className="checkrow" key={b.value}>
          <input type="checkbox" checked={selected === b.value} onChange={() => onSelect(b.value)} />
          <span>{b.value}</span>
          <span className="count">{b.count}</span>
        </label>
      ))}
    </div>
  );
}

/* ---------- facet pick list ---------- */
// Origin and permit state can each return 50+ buckets, too many for checkboxes
// in a 250px rail.
function FacetSelect({ title, buckets, selected, allLabel, onChange }) {
  const list = buckets || [];
  if (!list.length && !selected) return null;
  // A selected value can drop out of the buckets once other filters narrow the
  // set; keep it listed so the control never misreports itself as unfiltered.
  const options = selected && !list.some((b) => b.value === selected) ? [{ value: selected, count: 0 }, ...list] : list;
  const sorted = [...options].sort((a, b) => a.value.localeCompare(b.value));
  return (
    <div className="facet">
      <div className="facet-title">{title}</div>
      <select className="select facet-select" aria-label={title} value={selected || ''} onChange={(e) => onChange(e.target.value)}>
        <option value="">{allLabel}</option>
        {sorted.map((b) => (
          <option key={b.value} value={b.value}>
            {b.count ? `${b.value} (${b.count.toLocaleString()})` : b.value}
          </option>
        ))}
      </select>
    </div>
  );
}

// Cross-modal scores are compressed into a narrow band, so describe mode ranks
// results rather than claiming a match percentage the numbers can't support.
function RankBadge({ n }) {
  return <span className="rank-badge mono">#{n}</span>;
}

/* ---------- views ---------- */
function GalleryView({ rows, criteria, isVector, showRank, onOpen }) {
  return (
    <div className="gallery-grid">
      {rows.map((r, i) => (
        <button key={r.id} className="g-card" onClick={() => onOpen(r.id, i)}>
          <div className="g-thumb">
            <LabelThumb rec={r} />
            {showRank ? (
              <span className="g-score">#{i + 1}</span>
            ) : (
              isVector && r.score != null && (
                <span className="g-score">
                  <Icon name="sparkle" size={12} />
                  {toPct(r.score)}%
                </span>
              )
            )}
          </div>
          <div className="g-body">
            <div className="row between gap-8">
              <CatTag rec={r} />
              <StatusBadge status={r.status} />
            </div>
            <div className="g-brand">
              <Highlight text={r.brand} q={criteria.brand || criteria.q} />
            </div>
            <div className="g-fanciful">
              <Highlight text={r.fanciful} q={criteria.fanciful || criteria.q} />
            </div>
            <div className="g-meta mono">{r.ttbId}</div>
            <div className="g-meta">
              {r.originFlag ? r.originFlag + ' ' : ''}{r.origin} · {fmtDate(r.approvalDate)}
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}

function ListView({ rows, criteria, isVector, showRank, onOpen }) {
  return (
    <div className="list-view">
      {rows.map((r, i) => (
        <button key={r.id} className="l-row" onClick={() => onOpen(r.id, i)}>
          <div className="l-thumb">
            <LabelThumb rec={r} />
          </div>
          <div className="l-main">
            <div className="row gap-8" style={{ marginBottom: 4 }}>
              <CatTag rec={r} />
              <span className="muted mono" style={{ fontSize: 12 }}>
                {r.classType}
              </span>
            </div>
            <div className="l-brand">
              <Highlight text={r.brand} q={criteria.brand || criteria.q} /> <span className="l-fanciful">{r.fanciful}</span>
            </div>
            <div className="l-meta">
              <span className="mono">{r.ttbId}</span>
              <span>{r.originFlag ? r.originFlag + ' ' : ''}{r.origin}</span>
              <span>
                <Highlight text={r.applicant} q={criteria.applicant || criteria.permitName || criteria.q} />
              </span>
              {r.permitId && <span className="mono">{r.permitId}</span>}
              {r.permitState && (
                <span>
                  {r.permitCity ? r.permitCity + ', ' : ''}
                  {r.permitState}
                </span>
              )}
            </div>
          </div>
          <div className="l-side">
            {showRank ? <RankBadge n={i + 1} /> : isVector && r.score != null ? <ScoreMeter score={r.score} /> : <StatusBadge status={r.status} />}
            <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
              Approved {fmtDate(r.approvalDate)}
            </div>
            <span className="linkbtn" style={{ marginTop: 8 }}>
              View COLA <Icon name="chevRight" size={14} />
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}

function TableView({ rows, criteria, isVector, showRank, onOpen }) {
  return (
    <div className="table-wrap panel">
      <table className="data-table">
        <thead>
          <tr>
            <th style={{ width: 52 }}></th>
            <th>Brand / Fanciful</th>
            <th>Class / Type</th>
            <th>Applicant / Permit</th>
            <th>Origin</th>
            <th>TTB ID</th>
            <th>Approved</th>
              <th>{showRank ? 'Rank' : isVector ? 'Match' : 'Status'}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id} onClick={() => onOpen(r.id, i)}>
              <td>
                <div className="t-thumb">
                  <LabelThumb rec={r} />
                </div>
              </td>
              <td>
                <div style={{ fontWeight: 700 }}>
                  <Highlight text={r.brand} q={criteria.brand || criteria.q} />
                </div>
                <div className="muted" style={{ fontSize: 12.5 }}>
                  {r.fanciful}
                </div>
              </td>
              <td>
                <CatTag rec={r} />
                <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
                  {r.classSub}
                </div>
              </td>
              <td>
                <div>
                  <Highlight text={r.applicant} q={criteria.applicant || criteria.permitName || criteria.q} />
                </div>
                <div className="muted mono" style={{ fontSize: 12, marginTop: 3 }}>
                  {[r.permitId, r.permitState].filter(Boolean).join(' · ')}
                </div>
              </td>
              <td>{r.originFlag ? r.originFlag + ' ' : ''}{r.origin}</td>
              <td className="mono" style={{ fontSize: 12.5 }}>
                {r.ttbId}
              </td>
              <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(r.approvalDate)}</td>
              <td>{showRank ? <RankBadge n={i + 1} /> : isVector && r.score != null ? <ScoreMeter score={r.score} compact /> : <StatusBadge status={r.status} />}</td>
              <td>
                <Icon name="chevRight" size={16} className="muted" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- active filter chips ---------- */
const CHIP_LABELS = {
  q: null,
  ttbId: 'TTB/Serial',
  brand: 'Brand',
  fanciful: 'Product',
  applicant: 'Applicant',
  business: 'Business or permit',
  permit: 'Permit',
  permitName: 'Permit holder',
  permitCity: 'Permit city',
  permitState: 'Permit state',
  submitter: 'Submitter',
  varietal: 'Varietal',
  qualification: 'Qualification',
  labelText: 'Label text',
  commodity: 'Commodity',
  classType: 'Class/Type',
  receivedBy: 'Received by',
  source: 'Source',
  origin: 'Origin',
  status: 'Status',
  dateFrom: 'From',
  dateTo: 'To',
};

function ActiveChips({ criteria, onClearKey }) {
  const items = FILTER_KEYS.filter((k) => criteria[k]).map((k) => ({
    k,
    label: k === 'q' ? `“${criteria[k]}”` : `${CHIP_LABELS[k]}: ${criteria[k]}`,
  }));
  if (!items.length) return null;
  return (
    <div className="chips" style={{ marginTop: 12 }}>
      {items.map((it) => (
        <span className="chip" key={it.k}>
          {it.label}
          <button onClick={() => onClearKey(it.k)} aria-label="Remove">
            <Icon name="close" size={12} />
          </button>
        </span>
      ))}
    </div>
  );
}

/* ---------- main ---------- */
export default function ResultsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const isMobile = useIsMobile();
  const criteria = paramsToObject(searchParams);
  const mode = criteria.mode || 'text';
  const isImg = mode === 'image';
  const isDescribe = mode === 'describe';
  // Both are ANN searches over label vectors: scored, unfaceted, unpaged.
  const isVector = isImg || isDescribe;
  const page = Math.max(1, parseInt(criteria.page || '1', 10) || 1);

  // Name the tab after whichever filter the user most likely typed: FILTER_KEYS
  // is ordered from the broadest query down to the narrower fields.
  const titleTerm = (() => {
    const key = FILTER_KEYS.find((k) => criteria[k]);
    return key ? clip(criteria[key]) : '';
  })();
  useDocumentTitle(
    isImg
      ? 'Image search results'
      : isDescribe
        ? titleTerm
          ? `Artwork search: \u201C${titleTerm}\u201D`
          : 'Artwork search results'
        : titleTerm
          ? `Search: \u201C${titleTerm}\u201D`
          : 'Search results'
  );

  const [view, setViewState] = useState(() => localStorage.getItem('cola.view') || (window.matchMedia('(max-width: 720px)').matches ? 'list' : 'gallery'));

  // Default to compact list on mobile only when no explicit user preference is stored.
  useEffect(() => {
    if (isMobile && !localStorage.getItem('cola.view')) {
      setViewState('list');
    }
  }, [isMobile]);
  const setView = (v) => {
    setViewState(v);
    localStorage.setItem('cola.view', v);
    track('view_mode_changed', { view: v, mode });
  };

  // Image-search payload was stashed by the search form (a File can't ride in a URL).
  const [pending] = useState(() => {
    if (!isImg) return null;
    const stashed = readPendingImageSearch();
    // No file means a deep link, refresh or back-nav dropped it — a dead end
    // the server cannot see, since no request is ever made.
    if (!stashed || !stashed.file) track('image_search_state_lost', {});
    return stashed;
  });

  // Held in state now, so drop the module-level reference: otherwise a later
  // visit to /results?mode=image would re-run this stale search.
  useEffect(() => {
    clearPendingImageSearch();
  }, []);

  // Build the text-search query object passed to the API.
  const textParams = useMemo(() => {
    const p = { pageSize: PAGE_SIZE, page, facets: true };
    FILTER_KEYS.forEach((k) => {
      if (criteria[k]) p[k] = criteria[k];
    });
    if (criteria.allDates) p.allDates = true;
    if (criteria.sort) p.sort = criteria.sort;
    return p;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.toString()]);

  const textState = useAsync((signal) => api.searchColas(textParams, signal), [searchParams.toString()], {
    skip: isVector,
    cacheKey: `text:${searchParams.toString()}`,
  });

  const imageState = useAsync(
    (signal) => api.searchByImage({ file: pending.file, commodity: criteria.commodity, limit: PAGE_SIZE }, signal),
    [searchParams.toString()],
    { skip: !isImg || !pending || !pending.file }
  );

  const describeState = useAsync(
    (signal) => api.searchByDescription({ q: criteria.q, commodity: criteria.commodity, limit: PAGE_SIZE }, signal),
    [searchParams.toString()],
    { skip: !isDescribe, cacheKey: `describe:${searchParams.toString()}` }
  );

  const state = isImg ? imageState : isDescribe ? describeState : textState;
  const data = state.data;
  const loading = isImg ? (pending && pending.file ? state.loading : false) : state.loading;
  const rows = (data && data.items) || [];
  // `q` is the artwork description in describe mode, so highlighting it against
  // brand and applicant text would just be noise.
  const highlightCriteria = isDescribe ? { ...criteria, q: '' } : criteria;
  const total = data ? data.total : 0;
  const totalCapped = Boolean(data && data.totalIsCapped);
  const facets = (data && data.facets) || null;
  // The API refuses pages past 500; don't offer links the server will reject.
  const pageCount = Math.min(500, Math.max(1, Math.ceil((total || 0) / PAGE_SIZE)));

  function patchParams(mutator) {
    const next = paramsToObject(searchParams);
    mutator(next);
    setSearchParams(next);
  }

  function selectFacet(group, value) {
    patchParams((p) => {
      const key = FACET_PARAM[group];
      if (p[key] === value) delete p[key];
      else p[key] = value;
      delete p.page;
    });
  }

  // Pick lists set outright rather than toggling: '' is the "all" option.
  function setFacet(group, value) {
    patchParams((p) => {
      const key = FACET_PARAM[group];
      if (value) p[key] = value;
      else delete p[key];
      delete p.page;
    });
  }

  function clearKey(k) {
    patchParams((p) => {
      delete p[k];
      delete p.page;
      // With no bound left the API re-applies its default three-year window, so
      // removing the last date chip has to say "search everything" explicitly.
      if ((k === 'dateFrom' || k === 'dateTo') && !p.dateFrom && !p.dateTo) p.allDates = '1';
    });
  }

  function setSort(sort) {
    patchParams((p) => {
      if (sort === 'relevance') delete p.sort;
      else p.sort = sort;
      delete p.page;
    });
  }

  function goPage(n) {
    patchParams((p) => {
      if (n <= 1) delete p.page;
      else p.page = String(n);
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  const activeFacet = (group) => criteria[FACET_PARAM[group]] || null;
  const hasActiveFacets = Object.values(FACET_PARAM).some((k) => criteria[k]);
  const View = view === 'gallery' ? GalleryView : view === 'list' ? ListView : TableView;
  // Carry the search term so the detail page can highlight matching label text.
  const onOpen = (id, rank) => {
    const term = isDescribe ? '' : (criteria.q || '').trim();
    track('result_clicked', {
      rank: typeof rank === 'number' ? (page - 1) * PAGE_SIZE + rank + 1 : -1,
      view,
      mode,
    });
    navigate(`/cola/${encodeURIComponent(id)}${term ? `?q=${encodeURIComponent(term)}` : ''}`);
  };

  // Image mode with no stashed file (e.g. deep link / refresh): prompt to restart.
  if (isImg && (!pending || !pending.file)) {
    return (
      <div className="results-page">
        <div className="results-bar">
          <div className="wrap">
            <button className="linkbtn" onClick={() => navigate('/')}>
              <Icon name="chevLeft" size={16} /> New search
            </button>
          </div>
        </div>
        <div className="wrap" style={{ padding: '48px 0' }}>
          <div className="empty panel">
            <Icon name="image" size={34} className="muted" />
            <h3 style={{ marginTop: 12 }}>Upload an image to search</h3>
            <p className="muted">Image results can't be reopened from a link. Start a new image search to find similar labels.</p>
            <button className="btn secondary sm" onClick={() => navigate('/')}>
              Go to image search
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="results-page">
      <div className="results-bar">
        <div className="wrap">
          <button className="linkbtn" onClick={() => navigate('/')}>
            <Icon name="chevLeft" size={16} /> Modify search
          </button>
          {isImg ? (
            <div className="img-query">
              <div className="iq-thumb">
                {pending.url ? <img src={pending.url} alt="Query" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <Icon name="image" size={22} />}
              </div>
              <div>
                <div style={{ fontWeight: 700 }}>Visual similarity results</div>
                <div className="muted" style={{ fontSize: 13 }}>
                  {pending.name || 'uploaded-label.jpg'} · ranked by match score
                </div>
              </div>
            </div>
          ) : isDescribe ? (
            <div className="img-query">
              <div className="iq-thumb">
                <Icon name="sparkle" size={22} />
              </div>
              <div>
                <div style={{ fontWeight: 700 }}>Labels matching your description</div>
                <div className="muted" style={{ fontSize: 13 }}>
                  “{criteria.q}” · closest artwork first
                </div>
              </div>
            </div>
          ) : (
            <ActiveChips criteria={criteria} onClearKey={clearKey} />
          )}
        </div>
      </div>

      <div className={`wrap results-layout${isVector ? ' no-facets' : ''}`}>
        {!isVector && (
          <aside className="facets panel" data-tour="results-facets">
            <div className="row between" style={{ marginBottom: 6 }}>
              <div className="section-title">Refine results</div>
              {hasActiveFacets && (
                <button
                  className="linkbtn"
                  onClick={() =>
                    patchParams((p) => {
                      Object.values(FACET_PARAM).forEach((k) => delete p[k]);
                      delete p.page;
                    })
                  }
                >
                  Reset
                </button>
              )}
            </div>
            {facets ? (
              <>
                <FacetGroup title="Commodity" buckets={facets.commodity} selected={activeFacet('commodity')} onSelect={(v) => selectFacet('commodity', v)} />
                <FacetGroup title="Status" buckets={facets.status} selected={activeFacet('status')} onSelect={(v) => selectFacet('status', v)} />
                <FacetGroup title="Source" buckets={facets.source} selected={activeFacet('source')} onSelect={(v) => selectFacet('source', v)} />
                <FacetSelect
                  title="Origin"
                  buckets={facets.origin}
                  selected={activeFacet('origin')}
                  allLabel="All origins"
                  onChange={(v) => setFacet('origin', v)}
                />
                <FacetSelect
                  title="Permit state"
                  buckets={facets.permitState}
                  selected={activeFacet('permitState')}
                  allLabel="All permit states"
                  onChange={(v) => setFacet('permitState', v)}
                />
              </>
            ) : (
              <div className="muted" style={{ fontSize: 13 }}>Loading filters…</div>
            )}
          </aside>
        )}

        <div className="results-main">
          <div className="results-toolbar">
            <div>
              <div style={{ fontSize: 22, fontWeight: 800 }}>
                {loading ? 'Searching…' : (
                  <>
                    {total.toLocaleString()}{totalCapped ? '+' : ''}{' '}
                    {total === 1 ? 'result' : 'results'}
                  </>
                )}
              </div>
              {!loading && (
                <div className="muted" style={{ fontSize: 13.5 }}>
                  {isVector ? 'Similar labels in the registry' : 'Matching certificates of label approval'}
                </div>
              )}
            </div>
            <div className="row gap-16 wrap-flex" data-tour="results-views">
              {!isVector && (
                <div className="row gap-8">
                  <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>
                    Sort
                  </span>
                  <select
                    className="select"
                    style={{ height: 38, width: 'auto', fontSize: 14 }}
                    value={criteria.sort || 'relevance'}
                    onChange={(e) => setSort(e.target.value)}
                  >
                    <option value="relevance">Relevance</option>
                    <option value="approvalDate">Newest approval</option>
                    <option value="brand">Brand (A–Z)</option>
                    <option value="applicant">Applicant (A–Z)</option>
                  </select>
                </div>
              )}
              <div className="seg">
                <button className={view === 'gallery' ? 'active' : ''} onClick={() => setView('gallery')} title="Gallery">
                  <Icon name="grid" />
                </button>
                <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')} title="List">
                  <Icon name="list" />
                </button>
                <button className={view === 'table' ? 'active' : ''} onClick={() => setView('table')} title="Table">
                  <Icon name="table" />
                </button>
              </div>
            </div>
          </div>

          {state.error ? (
            <div className="empty panel">
              <Icon name="info" size={34} className="muted" />
              <h3 style={{ marginTop: 12 }}>Something went wrong</h3>
              <p className="muted">{state.error.message || 'The search could not be completed.'}</p>
              <button className="btn secondary sm" onClick={() => navigate('/')}>
                Back to search
              </button>
            </div>
          ) : loading ? (
            <div className="gallery-grid">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="g-card">
                  <div className="skel" style={{ aspectRatio: '4/5' }}></div>
                  <div className="g-body">
                    <div className="skel" style={{ height: 14, width: '60%', marginBottom: 8 }}></div>
                    <div className="skel" style={{ height: 12, width: '90%' }}></div>
                  </div>
                </div>
              ))}
            </div>
          ) : rows.length === 0 ? (
            <div className="empty panel">
              <Icon name="search" size={34} className="muted" />
              <h3 style={{ marginTop: 12 }}>No matching labels</h3>
              <p className="muted">
                {isDescribe
                  ? 'Try describing colors, shapes, and motifs rather than naming a brand.'
                  : 'Try removing a filter or broadening your search terms.'}
              </p>
              <button className="btn secondary sm" onClick={() => navigate('/')}>
                Modify search
              </button>
            </div>
          ) : (
            <>
              <View rows={rows} criteria={highlightCriteria} isVector={isVector} showRank={isDescribe} onOpen={onOpen} />
              {!isVector && pageCount > 1 && (
                <div className="row between" style={{ marginTop: 24, alignItems: 'center' }}>
                  <button className="btn secondary sm" disabled={page <= 1} onClick={() => goPage(page - 1)}>
                    <Icon name="chevLeft" size={16} /> Previous
                  </button>
                  <span className="muted" style={{ fontSize: 13.5 }}>
                    Page {page} of {pageCount}
                  </span>
                  <button className="btn secondary sm" disabled={page >= pageCount} onClick={() => goPage(page + 1)}>
                    Next <Icon name="chevRight" size={16} />
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
