import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Icon from '../components/Icon.jsx';
import LabelThumb from '../components/LabelThumb.jsx';
import { CatTag } from '../components/Badges.jsx';
import { api, toQuery } from '../lib/api.js';
import { fmtDate } from '../lib/format.js';
import { setPendingImageSearch } from '../lib/imageSearchStore.js';
import { useAsync } from '../hooks/useAsync.js';

const EMPTY = {
  text: '',
  ttbId: '',
  brand: '',
  fanciful: '',
  commodity: '',
  source: '',
  origin: '',
  status: '',
  dateFrom: '',
  dateTo: '',
  mode: 'text',
  image: null,
  sort: 'relevance',
};

// Turn the form draft into the API/URL query object (camelCase matches the API).
function draftToParams(draft) {
  const p = {};
  if (draft.text) p.q = draft.text;
  if (draft.ttbId) p.ttbId = draft.ttbId;
  if (draft.brand) p.brand = draft.brand;
  if (draft.fanciful) p.fanciful = draft.fanciful;
  if (draft.commodity) p.commodity = draft.commodity;
  if (draft.source) p.source = draft.source;
  if (draft.origin) p.origin = draft.origin;
  if (draft.status) p.status = draft.status;
  if (draft.dateFrom) p.dateFrom = draft.dateFrom;
  if (draft.dateTo) p.dateTo = draft.dateTo;
  if (draft.sort && draft.sort !== 'relevance') p.sort = draft.sort;
  return p;
}

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

function AdvancedFields({ draft, set, refData }) {
  const categories = refData.categories || [];
  const sources = refData.sources || [];
  const domestic = refData.domesticOrigins || [];
  const imported = refData.importedOrigins || [];
  const statuses = refData.statuses || [];
  return (
    <div className="adv-grid">
      <div className="field">
        <label>TTB ID or Serial number</label>
        <div className="hint">14-digit TTB ID, or applicant serial number</div>
        <input
          className="input mono"
          placeholder="e.g. 25040010011..."
          value={draft.ttbId}
          onChange={(e) => set('ttbId', e.target.value)}
        />
      </div>
      <div className="field">
        <label>Brand name</label>
        <div className="hint">Name marketed to consumers</div>
        <input
          className="input"
          placeholder="e.g. Cedar Hollow"
          value={draft.brand}
          onChange={(e) => set('brand', e.target.value)}
        />
      </div>
      <div className="field">
        <label>Product / Fanciful name</label>
        <div className="hint">Product-specific designation</div>
        <input
          className="input"
          placeholder="e.g. Estate Reserve"
          value={draft.fanciful}
          onChange={(e) => set('fanciful', e.target.value)}
        />
      </div>
      <div className="field">
        <label>Class / Type</label>
        <select className="select" value={draft.commodity} onChange={(e) => set('commodity', e.target.value)}>
          <option value="">All commodities</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>Source</label>
        <select
          className="select"
          value={draft.source}
          onChange={(e) => {
            set('source', e.target.value);
            set('origin', '');
          }}
        >
          <option value="">Domestic &amp; imported</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>Origin — state or country</label>
        <select className="select" value={draft.origin} onChange={(e) => set('origin', e.target.value)}>
          <option value="">Any origin</option>
          {draft.source !== 'Imported' && (
            <optgroup label="U.S. states &amp; territories">
              {domestic.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </optgroup>
          )}
          {draft.source !== 'Domestic' && (
            <optgroup label="Countries">
              {imported.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </div>
      <div className="field">
        <label>Status</label>
        <select className="select" value={draft.status} onChange={(e) => set('status', e.target.value)}>
          <option value="">Any status</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
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

function ImageSearch({ draft, set, refData, onSubmit }) {
  const inputRef = useRef(null);
  const [drag, setDrag] = useState(false);
  const categories = refData.categories || [];

  function handleFile(file) {
    if (!file) return;
    const url = URL.createObjectURL(file);
    set('image', { name: file.name, url, file });
  }
  function onDrop(e) {
    e.preventDefault();
    setDrag(false);
    handleFile(e.dataTransfer.files && e.dataTransfer.files[0]);
  }

  return (
    <div>
      <div
        className="dropzone"
        onClick={() => !draft.image && inputRef.current && inputRef.current.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        style={{ borderColor: drag ? 'var(--accent)' : '', background: drag ? 'var(--accent-lighter)' : '' }}
      >
        {!draft.image ? (
          <>
            <div className="dz-ico">
              <Icon name="upload" size={30} />
            </div>
            <div style={{ fontWeight: 700, fontSize: 17 }}>
              Drag a label image here, or <span style={{ color: 'var(--accent)' }}>browse files</span>
            </div>
            <div className="muted" style={{ fontSize: 13.5, marginTop: 4 }}>
              JPG, PNG, or PDF up to 20&nbsp;MB. We match on color, layout, and imagery — text is optional.
            </div>
            <input
              ref={inputRef}
              type="file"
              accept="image/*,.pdf"
              hidden
              onChange={(e) => handleFile(e.target.files[0])}
            />
          </>
        ) : (
          <div className="row gap-16" style={{ width: '100%', justifyContent: 'center' }}>
            <div className="upload-preview">
              <img src={draft.image.url} alt="Upload preview" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 6 }} />
            </div>
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontWeight: 700 }}>{draft.image.name}</div>
              <div className="muted" style={{ fontSize: 13 }}>Ready to match</div>
              <button
                className="linkbtn"
                style={{ marginTop: 6 }}
                onClick={(e) => {
                  e.stopPropagation();
                  set('image', null);
                }}
              >
                Remove &amp; choose another
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="row gap-16 wrap-flex" style={{ marginTop: 18, alignItems: 'center' }}>
        <div className="field" style={{ margin: 0, minWidth: 220 }}>
          <span className="lbl">Restrict to commodity (optional)</span>
          <select className="select" value={draft.commodity} onChange={(e) => set('commodity', e.target.value)}>
            <option value="">All commodities</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div style={{ flex: 1 }}></div>
        <button className="btn lg" disabled={!draft.image} onClick={onSubmit}>
          <Icon name="sparkle" /> Find similar labels
        </button>
      </div>

      <div className="info-note" style={{ marginTop: 20 }}>
        <Icon name="info" size={18} />
        <div>
          Visual similarity search compares the dominant color palette, composition, and graphic elements of your image
          against approved label artwork. Results are ranked by a visual match score and are intended to surface
          potentially conflicting or similar trade dress.
        </div>
      </div>
    </div>
  );
}

export default function SearchPage() {
  const navigate = useNavigate();
  const [draft, setDraft] = useState(EMPTY);
  const [advanced, setAdvanced] = useState(false);
  const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }));

  const refState = useAsync((signal) => api.reference(signal), []);
  const ref = refState.data || {};
  const categories = ref.categories || [];

  const recentState = useAsync(
    (signal) => api.searchColas({ sort: 'approvalDate', pageSize: 6, facets: false }, signal),
    []
  );
  const recent = (recentState.data && recentState.data.items) || [];

  function submitText() {
    navigate({ pathname: '/results', search: toQuery(draftToParams({ ...draft, mode: 'text' })) });
  }

  function submitImage() {
    if (!draft.image) return;
    setPendingImageSearch({ file: draft.image.file, name: draft.image.name, url: draft.image.url, commodity: draft.commodity });
    navigate({ pathname: '/results', search: toQuery({ mode: 'image', commodity: draft.commodity }) });
  }

  return (
    <div>
      <section className="hero">
        <div className="wrap">
          <div className="hero-inner">
            <span className="section-title" style={{ color: 'var(--accent)' }}>
              Certificate of Label Approval
            </span>
            <h1 className="hero-title">Search the public COLA registry</h1>
            <p className="hero-sub">
              Find approved alcohol beverage labels across wine, malt beverages, and distilled spirits. Search by any
              field, or upload a label image to find visually similar approvals.
            </p>

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
                        onKeyDown={(e) => e.key === 'Enter' && submitText()}
                      />
                      <button className="btn" onClick={submitText}>
                        <Icon name="search" /> Search
                      </button>
                    </div>
                    <div className="hint" style={{ marginTop: 8 }}>
                      One box searches across brand, product, applicant, class/type, origin, and TTB ID.
                    </div>
                  </div>

                  <div className="row between" style={{ marginTop: 16 }}>
                    <div className="chips">
                      <span className="muted" style={{ fontSize: 13, fontWeight: 600, alignSelf: 'center' }}>
                        Quick filter:
                      </span>
                      {categories.map((c) => (
                        <button
                          key={c}
                          className={'qchip' + (draft.commodity === c ? ' on' : '')}
                          onClick={() => set('commodity', draft.commodity === c ? '' : c)}
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                    <button className="linkbtn" onClick={() => setAdvanced(!advanced)}>
                      <Icon name="sliders" size={16} /> {advanced ? 'Hide advanced search' : 'Advanced search'}
                    </button>
                  </div>

                  {advanced && (
                    <div className="adv-wrap">
                      <hr className="divider" style={{ margin: '20px 0' }} />
                      <AdvancedFields draft={draft} set={set} refData={ref} />
                      <div className="row between" style={{ marginTop: 4 }}>
                        <button className="linkbtn" onClick={() => setDraft({ ...EMPTY, mode: 'text' })}>
                          Clear all fields
                        </button>
                        <button className="btn" onClick={submitText}>
                          <Icon name="search" /> Search registry
                        </button>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <ImageSearch draft={draft} set={set} refData={ref} onSubmit={submitImage} />
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="wrap" style={{ marginTop: 44 }}>
        <div className="row between" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 20 }}>Recently approved</h2>
          <button className="linkbtn" onClick={() => navigate({ pathname: '/results', search: toQuery({ sort: 'approvalDate' }) })}>
            Browse all approvals <Icon name="arrowRt" size={16} />
          </button>
        </div>
        <div className="recent-grid">
          {recent.map((r) => (
            <button key={r.id} className="recent-card" onClick={() => navigate(`/cola/${r.id}`)}>
              <LabelThumb rec={r} />
              <div className="recent-meta">
                <div className="row between gap-8">
                  <CatTag rec={r} />
                  <span className="muted mono" style={{ fontSize: 11 }}>
                    {fmtDate(r.approvalDate)}
                  </span>
                </div>
                <div style={{ fontWeight: 700, marginTop: 7 }}>{r.brand}</div>
                <div className="muted" style={{ fontSize: 13 }}>
                  {r.fanciful}
                </div>
              </div>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
