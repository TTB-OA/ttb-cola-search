/* ============================================================
   Shared components — exported to window for cross-file use
   ============================================================ */
const { useState, useEffect, useRef } = React;

/* ---------- Icons (simple, USWDS-flavored) ---------- */
const Icon = ({ name, className = '', size }) => {
  const s = size || 20;
  const p = { width: s, height: s, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', className: 'ico ' + className };
  const paths = {
    search:   <><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></>,
    close:    <><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></>,
    chevDown: <polyline points="6 9 12 15 18 9" />,
    chevRight:<polyline points="9 6 15 12 9 18" />,
    chevLeft: <polyline points="15 6 9 12 15 18" />,
    grid:     <><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /></>,
    list:     <><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3.5" y1="6" x2="3.6" y2="6" /><line x1="3.5" y1="12" x2="3.6" y2="12" /><line x1="3.5" y1="18" x2="3.6" y2="18" /></>,
    table:    <><rect x="3" y="4" width="18" height="16" rx="1" /><line x1="3" y1="10" x2="21" y2="10" /><line x1="9" y1="10" x2="9" y2="20" /></>,
    upload:   <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></>,
    image:    <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></>,
    filter:   <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />,
    sliders:  <><line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" /><line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" /><line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" /><line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="17" y1="16" x2="23" y2="16" /></>,
    calendar: <><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></>,
    external: <><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></>,
    download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></>,
    check:    <polyline points="20 6 9 17 4 12" />,
    info:     <><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></>,
    print:    <><polyline points="6 9 6 2 18 2 18 9" /><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" /><rect x="6" y="14" width="12" height="8" /></>,
    star:     <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />,
    sparkle:  <><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" /><path d="M19 3v3M21.5 4.5h-3" /></>,
    swap:     <><polyline points="17 1 21 5 17 9" /><path d="M3 11V9a4 4 0 0 1 4-4h14" /><polyline points="7 23 3 19 7 15" /><path d="M21 13v2a4 4 0 0 1-4 4H3" /></>,
    arrowRt:  <><line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" /></>,
    drop:     <path d="M12 2.5S6 9 6 14a6 6 0 0 0 12 0c0-5-6-11.5-6-11.5z" />,
    expand:   <><polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" /><line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" /></>,
    loader:   <><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.9" y1="4.9" x2="7.8" y2="7.8"/><line x1="16.2" y1="16.2" x2="19.1" y2="19.1"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.9" y1="19.1" x2="7.8" y2="16.2"/><line x1="16.2" y1="7.8" x2="19.1" y2="4.9"/></>
  };
  return <svg {...p}>{paths[name]}</svg>;
};

/* ---------- Government banner ---------- */
const GovBanner = () => {
  const [open, setOpen] = useState(false);
  return (
    <div className="gov-banner">
      <div className="wrap">
        <span className="flag" aria-hidden="true"></span>
        <span className="banner-text">An official website of the United States government</span>
        <button onClick={() => setOpen(!open)}>Here's how you know {open ? '▲' : '▾'}</button>
      </div>
      {open && (
        <div className="wrap" style={{ paddingBottom: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, maxWidth: 980 }}>
          <div className="row gap-10" style={{ alignItems: 'flex-start' }}>
            <Icon name="info" size={22} className="" />
            <div><b>Official websites use .gov</b><div className="muted" style={{ fontSize: 12.5 }}>A <b>.gov</b> website belongs to an official government organization in the United States.</div></div>
          </div>
          <div className="row gap-10" style={{ alignItems: 'flex-start' }}>
            <Icon name="check" size={22} />
            <div><b>Secure .gov websites use HTTPS</b><div className="muted" style={{ fontSize: 12.5 }}>A lock means you've safely connected to the .gov website.</div></div>
          </div>
        </div>
      )}
    </div>
  );
};

/* ---------- Site header ---------- */
const Header = ({ nav, onNav }) => (
  <header className="site-header">
    <div className="wrap">
      <a className="brand" href="#" onClick={(e) => { e.preventDefault(); onNav('search'); }}>
        <img className="seal-img" src="resources/US-AlcoholAndTobaccoTaxAndTradeBureau-Seal.svg" alt="TTB seal" />
        <span className="brand-text">
          <span className="agency">Alcohol &amp; Tobacco Tax and Trade Bureau</span>
          <span className="product">Public COLA <b>Registry</b></span>
        </span>
      </a>
      <nav className="header-nav">
        <a href="#" className={nav === 'search' ? 'active' : ''} onClick={(e) => { e.preventDefault(); onNav('search'); }}>Search</a>
        <a href="#" onClick={(e) => e.preventDefault()}>Public Guidance</a>
        <a href="#" onClick={(e) => e.preventDefault()}>About COLAs</a>
        <a href="#" onClick={(e) => e.preventDefault()}>Help</a>
        <a href="#" onClick={(e) => e.preventDefault()} className="row gap-6">Permits Online <Icon name="external" size={14} /></a>
      </nav>
    </div>
  </header>
);

/* ---------- Footer ---------- */
const Footer = () => (
  <footer className="site-footer">
    <div className="wrap">
      <div className="foot-brand">
        <img className="seal-img" style={{ width: 52, height: 52 }} src="resources/US-AlcoholAndTobaccoTaxAndTradeBureau-Seal.svg" alt="TTB seal" />
        <div>
          <div style={{ fontWeight: 800, color: '#fff', fontSize: 16 }}>Alcohol &amp; Tobacco Tax and Trade Bureau</div>
          <div className="foot-note">Public Certificate of Label Approval (COLA) Registry. This is a design prototype using fictional records for demonstration.</div>
        </div>
      </div>
      <div>
        <h4>Registry</h4>
        <a href="#" onClick={(e)=>e.preventDefault()}>Basic search</a>
        <a href="#" onClick={(e)=>e.preventDefault()}>Advanced search</a>
        <a href="#" onClick={(e)=>e.preventDefault()}>Search by image</a>
      </div>
      <div>
        <h4>Resources</h4>
        <a href="#" onClick={(e)=>e.preventDefault()}>Labeling resources</a>
        <a href="#" onClick={(e)=>e.preventDefault()}>Class/Type codes</a>
        <a href="#" onClick={(e)=>e.preventDefault()}>Origin codes</a>
      </div>
      <div>
        <h4>Agency</h4>
        <a href="#" onClick={(e)=>e.preventDefault()}>TTB.gov</a>
        <a href="#" onClick={(e)=>e.preventDefault()}>Contact</a>
        <a href="#" onClick={(e)=>e.preventDefault()}>Accessibility (508)</a>
      </div>
    </div>
  </footer>
);

/* ---------- Status badge ---------- */
const StatusBadge = ({ status }) => {
  const map = { Approved: 'approved', Pending: 'pending', Revoked: 'revoked', Expired: 'expired' };
  return <span className={'badge ' + (map[status] || 'expired')}><span className="dot"></span>{status}</span>;
};

const CatTag = ({ rec }) => <span className={'tag ' + rec.tagClass}>{rec.category}</span>;

/* ---------- Procedural label thumbnail ---------- */
const LabelThumb = ({ rec, style }) => {
  const lt = { '--lt-bg': rec.bg, '--lt-ink': rec.ink };
  const kicker = rec.classSub || rec.category;
  return (
    <div className={'label-thumb style-' + rec.labelStyle} style={{ ...lt, ...(style || {}) }} aria-label={rec.brand + ' label'}>
      <div className="lt-inner">
        <div className="lt-kicker">{kicker}</div>
        <div className="lt-brand">{rec.brand}</div>
        {rec.labelStyle !== 'minimal' && <div className="lt-rule"></div>}
        <div className="lt-fanciful">{rec.fanciful}</div>
        <div className="lt-foot">{rec.origin}</div>
        <div className="lt-abv">{rec.netContents} · {rec.abv} ALC/VOL</div>
      </div>
    </div>
  );
};

/* ---------- Highlight matched text ---------- */
const Highlight = ({ text, q }) => {
  if (!q) return <>{text}</>;
  const idx = String(text).toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return <>{text}</>;
  return (
    <>{text.slice(0, idx)}<mark style={{ background: 'var(--gold)', padding: '0 2px', borderRadius: 2 }}>{text.slice(idx, idx + q.length)}</mark>{text.slice(idx + q.length)}</>
  );
};

Object.assign(window, { Icon, GovBanner, Header, Footer, StatusBadge, CatTag, LabelThumb, Highlight });
