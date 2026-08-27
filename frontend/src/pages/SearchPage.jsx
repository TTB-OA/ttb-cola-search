import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Icon from '../components/Icon.jsx';
import LabelThumb from '../components/LabelThumb.jsx';
import Combobox, { matchOptions } from '../components/Combobox.jsx';
import { CatTag } from '../components/Badges.jsx';
import { useTour } from '../components/Tour.jsx';
import { api, toQuery } from '../lib/api.js';
import { track } from '../lib/analytics.js';
import { fmtDate, fmtDateLong } from '../lib/format.js';
import { setPendingImageSearch } from '../lib/imageSearchStore.js';
import { useAsync } from '../hooks/useAsync.js';
import { useDocumentTitle } from '../hooks/useDocumentTitle.js';
import { useIsMobile } from '../hooks/useIsMobile.js';
import { usePermitSuggest } from '../hooks/usePermitSuggest.js';

function defaultDateFrom() {
  return `${new Date().getFullYear() - 2}-01-01`;
}

const EMPTY = {
  text: '',
  ttbId: '',
  brand: '',
  fanciful: '',
  applicant: '',
  business: '',
  permit: '',
  permitName: '',
  permitState: '',
  permitCity: '',
  submitter: '',
  varietal: '',
  qualification: '',
  labelText: '',
  commodity: '',
  classType: '',
  receivedBy: '',
  source: '',
  origin: '',
  status: 'Approved',
  dateFrom: defaultDateFrom(),
  dateTo: '',
  mode: 'text',
  image: null,
  description: '',
  sort: 'relevance',
};

// Draft keys that map 1:1 onto API/URL query params.
const PASSTHROUGH_KEYS = [
  'ttbId',
  'brand',
  'fanciful',
  'applicant',
  'business',
  'permit',
  'permitName',
  'permitState',
  'permitCity',
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

// Turn the form draft into the API/URL query object (camelCase matches the API).
function draftToParams(draft) {
  const p = {};
  if (draft.text) p.q = draft.text;
  PASSTHROUGH_KEYS.forEach((k) => {
    if (draft[k]) p[k] = draft[k];
  });
  if (draft.sort && draft.sort !== 'relevance') p.sort = draft.sort;
  return p;
}

const MODES = [
  { id: 'text', icon: 'search', label: 'Text search' },
  { id: 'image', icon: 'image', label: 'Search by image', tour: 'image-tab' },
  { id: 'describe', icon: 'sparkle', label: 'Describe a label', tour: 'describe-tab' },
];

function ModeTabs({ mode, setMode }) {
  return (
    <div className="seg" role="tablist" style={{ marginBottom: 22 }}>
      {MODES.map((m) => (
        <button
          key={m.id}
          className={mode === m.id ? 'active' : ''}
          onClick={() => setMode(m.id)}
          data-tour={m.tour}
        >
          <Icon name={m.icon} /> {m.label}
        </button>
      ))}
    </div>
  );
}

function permitLine(p) {
  return [p.city ? `${p.city}, ${p.state || ''}`.replace(/,\s*$/, '') : p.state, p.colaCount ? `${p.colaCount.toLocaleString()} COLAs` : '']
    .filter(Boolean)
    .join(' · ');
}

function AdvancedFields({ draft, set, refData }) {
  const sources = refData.sources || [];
  const domestic = refData.domesticOrigins || [];
  const imported = refData.importedOrigins || [];
  const statuses = refData.statuses || [];
  const permitStates = refData.permitStates || [];
  const classTypes = refData.classTypes || [];
  const receivedTypes = refData.receivedTypes || [];
  const varietals = refData.varietals || [];

  const classTypeOptions = useMemo(() => matchOptions(classTypes, draft.classType), [classTypes, draft.classType]);
  const varietalOptions = useMemo(() => matchOptions(varietals, draft.varietal), [varietals, draft.varietal]);

  const business = usePermitSuggest(draft.business, (p) => ({
    value: p.name || p.permitId,
    label: p.name || p.permitId,
    hint: [p.permitId, permitLine(p)].filter(Boolean).join(' · '),
  }));

  // Picking a suggestion swaps the typed name for the permit number, which is
  // unambiguous and finds every COLA on that permit — including the ones where
  // it isn't the primary permit. One field, so no second filter to AND against.
  function pickBusiness(opt) {
    set('business', opt.permit.permitId);
  }

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
      <div className="field adv-wide">
        <label>Class / Type</label>
        <div className="hint">Specific class/type on the application — use the quick filters for a whole commodity</div>
        <Combobox
          ariaLabel="Class / Type"
          placeholder="Start typing, e.g. TABLE RED WINE"
          value={draft.classType}
          onChange={(v) => set('classType', v)}
          options={classTypeOptions}
          emptyText="No matching class/type"
        />
      </div>
      <div className="field adv-wide">
        <label>Received by</label>
        <div className="hint">How TTB received the application</div>
        <select className="select" value={draft.receivedBy} onChange={(e) => set('receivedBy', e.target.value)}>
          <option value="">Any submission method</option>
          {receivedTypes.map((r) => (
            <option key={r} value={r}>
              {r}
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

      <div className="field adv-span">
        <div className="adv-subhead">Applicant, permit &amp; submitter</div>
      </div>
      <div className="field adv-wide">
        <label>Business or permit</label>
        <div className="hint">
          Applicant, permit holder, or a permit/plant number — pick a suggestion to search every COLA on that permit
        </div>
        <Combobox
          ariaLabel="Business or permit"
          placeholder="e.g. Cedar Hollow Winery, or BWN-CA-1234"
          value={draft.business}
          onChange={(v) => set('business', v)}
          onPick={pickBusiness}
          options={business.options}
          loading={business.loading}
          emptyText="No matching business or permit"
        />
      </div>
      <div className="field">
        <label>Permit city</label>
        <input
          className="input"
          placeholder="e.g. Napa"
          value={draft.permitCity}
          onChange={(e) => set('permitCity', e.target.value)}
        />
      </div>
      <div className="field">
        <label>Permit state</label>
        <select className="select" value={draft.permitState} onChange={(e) => set('permitState', e.target.value)}>
          <option value="">Any state</option>
          {permitStates.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>Submitter</label>
        <div className="hint">Name or submitter ID on the application</div>
        <input
          className="input"
          placeholder="e.g. Jordan Reyes"
          value={draft.submitter}
          onChange={(e) => set('submitter', e.target.value)}
        />
      </div>

      <div className="field adv-span">
        <div className="adv-subhead">Product detail &amp; label text</div>
      </div>
      <div className="field">
        <label>Grape varietal</label>
        <div className="hint">Any varietal declared on the application</div>
        <Combobox
          ariaLabel="Grape varietal"
          placeholder="e.g. Cabernet Sauvignon"
          value={draft.varietal}
          onChange={(v) => set('varietal', v)}
          options={varietalOptions}
          emptyText="No matching varietal"
        />
      </div>
      <div className="field">
        <label>Qualification text</label>
        <div className="hint">Conditions recorded on the approval</div>
        <input
          className="input"
          placeholder="e.g. alcohol content"
          value={draft.qualification}
          onChange={(e) => set('qualification', e.target.value)}
        />
      </div>
      <div className="field">
        <label>Text on the label</label>
        <div className="hint">Limits results to text recognized on the label artwork</div>
        <input
          className="input"
          placeholder="e.g. estate bottled"
          value={draft.labelText}
          onChange={(e) => set('labelText', e.target.value)}
        />
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
                  track('image_search_abandoned', {});
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
          against approved label artwork. Results are ranked by a visual match score.
        </div>
      </div>
    </div>
  );
}

const DESCRIBE_MIN = 3;

const DESCRIBE_PLACEHOLDERS = [
  'a gold eagle crest above art-deco lettering on a deep green background',
  'hand-drawn mountain range in muted blues with serif lettering',
  'black label with gold foil script and a wax-seal emblem',
  'watercolor botanical illustration with a thin gold border',
];

function DescribeSearch({ draft, set, refData, onSubmit }) {
  const categories = refData.categories || [];
  const ready = draft.description.trim().length >= DESCRIBE_MIN;
  const placeholder = useMemo(
    () => DESCRIBE_PLACEHOLDERS[Math.floor(Math.random() * DESCRIBE_PLACEHOLDERS.length)],
    [],
  );

  return (
    <div>
      <div className="field" style={{ margin: 0 }}>
        <span className="lbl">Describe the label artwork</span>
        <textarea
          className="input"
          rows={3}
          style={{ resize: 'vertical' }}
          placeholder={placeholder}
          value={draft.description}
          onChange={(e) => set('description', e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== 'Enter' || e.shiftKey) return; // Shift+Enter still adds a line break
            e.preventDefault();
            if (ready) onSubmit();
          }}
        />
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
        <button className="btn lg" disabled={!ready} onClick={onSubmit}>
          <Icon name="sparkle" /> Find matching labels
        </button>
      </div>

      <div className="info-note" style={{ marginTop: 20 }}>
        <Icon name="info" size={18} />
        <div>
          Your description is matched against label artwork, not label wording. Describing colors, shapes, and motifs
          works better than naming a brand. To search the text printed on a label, use Text search instead.
        </div>
      </div>
    </div>
  );
}

export default function SearchPage() {
  useDocumentTitle(null);
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [draft, setDraft] = useState(EMPTY);
  const [advanced, setAdvanced] = useState(false);
  const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }));

  const refState = useAsync((signal) => api.reference(signal), [], { cacheKey: 'reference' });
  const ref = refState.data || {};
  const categories = ref.categories || [];

  const recentState = useAsync(
    (signal) => api.searchColas({ sort: 'approvalDate', status: 'Approved', pageSize: 6, facets: false }, signal),
    [],
    { cacheKey: 'recent' }
  );
  const recent = (recentState.data && recentState.data.items) || [];

  // The tour types a sample query into the box, and clears it when it ends.
  const { demoText } = useTour();
  useEffect(() => {
    setDraft((d) => (d.text === demoText ? d : { ...d, text: demoText }));
  }, [demoText]);

  function submitText() {
    navigate({ pathname: '/results', search: toQuery(draftToParams({ ...draft, mode: 'text' })) });
  }

  function submitImage() {
    if (!draft.image) return;
    setPendingImageSearch({ file: draft.image.file, name: draft.image.name, url: draft.image.url, commodity: draft.commodity });
    navigate({ pathname: '/results', search: toQuery({ mode: 'image', commodity: draft.commodity }) });
  }

  function submitDescribe() {
    const q = draft.description.trim();
    if (q.length < DESCRIBE_MIN) return;
    track('describe_search_submitted', { length: q.length, commodity: draft.commodity || null });
    navigate({ pathname: '/results', search: toQuery({ mode: 'describe', q, commodity: draft.commodity }) });
  }

  return (
    <div>
      <section className="hero">
        <div className="wrap">
          <div className="hero-inner">
            <span className="section-title" style={{ color: 'var(--accent)' }}>
              Certificate of Label Approval
            </span>
            <h1 className="hero-title">Search the TTB COLA Registry</h1>
            <p className="hero-sub">
              Find approved alcohol beverage labels across wine, malt beverages, and distilled spirits. Search by any
              field, upload a label image, or describe the artwork you have in mind.
            </p>

            <div className="panel search-card">
              <ModeTabs mode={draft.mode} setMode={(m) => set('mode', m)} />

              {draft.mode === 'text' ? (
                <>
                  <div className="field" style={{ margin: 0 }}>
                    <span className="lbl">Search all label records</span>
                    <div className="input-group" data-tour="search-box">
                      <input
                        className="input"
                        style={{ fontSize: 17 }}
                        placeholder="Brand, fanciful name, TTB ID, applicant, permit, text on the label…"
                        value={draft.text}
                        onChange={(e) => set('text', e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && submitText()}
                      />
                      <button className="btn" onClick={submitText}>
                        <Icon name="search" /> Search
                      </button>
                    </div>
                    <div className="hint" style={{ marginTop: 8 }}>
                      Search across brand, product, applicant, permit, submitter, class/type, origin, and TTB ID, plus
                      text recognized on the label artwork. Records matching a field are listed first.
                    </div>
                    <div className="hint" style={{ marginTop: 6 }}>
                      Defaults to COLAs approved after {fmtDateLong(defaultDateFrom())} (last three calendar years). Expand in Advanced search.
                    </div>
                  </div>

                  <div className="row between" style={{ marginTop: 16 }}>
                    <div className="chips" data-tour="quick-filters">
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
                    <button
                      className="linkbtn"
                      data-tour="advanced-toggle"
                      onClick={() => {
                        track('advanced_panel_toggled', { open: !advanced });
                        setAdvanced(!advanced);
                      }}
                    >
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
              ) : draft.mode === 'image' ? (
                <ImageSearch draft={draft} set={set} refData={ref} onSubmit={submitImage} />
              ) : (
                <DescribeSearch draft={draft} set={set} refData={ref} onSubmit={submitDescribe} />
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="wrap" style={{ marginTop: 44 }}>
        <div className="row between" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 20 }}>Recently approved</h2>
          <button className="linkbtn" onClick={() => navigate({ pathname: '/results', search: toQuery({ sort: 'approvalDate', status: 'Approved' }) })}>
            Browse all approvals <Icon name="arrowRt" size={16} />
          </button>
        </div>
        {recentState.loading && <div className="muted">Loading recent approvals...</div>}
        {recentState.error && !recentState.loading && (
          <div className="info-note">
            <Icon name="info" size={18} />
            <div>Recent approvals are temporarily unavailable. Try reloading the page.</div>
          </div>
        )}
        <div className={'recent-grid' + (isMobile ? ' compact' : '')} data-tour="recent">
          {recent.map((r) => (
            <button key={r.id} className={'recent-card' + (isMobile ? ' compact' : '')} onClick={() => navigate(`/cola/${encodeURIComponent(r.id)}`)}>
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
