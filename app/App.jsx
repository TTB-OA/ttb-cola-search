/* ============================================================
   App root — routing, state, tweaks
   ============================================================ */
const { useState: useStateA, useEffect: useEffectA } = React;

const ACCENTS = {
  'Federal blue': ['#005ea2', '#1a4480', '#162e51', '#d9e8f6', '#e8f0f7'],
  'Pine green':   ['#2e7d4f', '#1e5a38', '#143f27', '#dcefe2', '#e9f4ed'],
  'Navy':         ['#1b3a6b', '#142d54', '#0e2040', '#dbe4f2', '#e8eef7'],
  'Bordeaux':     ['#8a2540', '#6c1c32', '#4d1424', '#f3dde3', '#f7e9ee']
};

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "Federal blue",
  "density": "regular",
  "showScores": true,
  "defaultView": "gallery"
}/*EDITMODE-END*/;

const EMPTY = {
  text: '', ttbId: '', brand: '', fanciful: '', category: '', source: '', origin: '', status: '',
  dateFrom: '', dateTo: '', mode: 'text', image: null, sort: 'relevance', advanced: false
};

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [page, setPage] = useStateA('search');
  const [criteria, setCriteria] = useStateA({ ...EMPTY });
  const [recId, setRecId] = useStateA(null);
  const [view, setViewState] = useStateA(() => localStorage.getItem('cola.view') || t.defaultView || 'gallery');

  const setView = (v) => { setViewState(v); localStorage.setItem('cola.view', v); };

  // apply accent tweak -> CSS vars
  useEffectA(() => {
    const a = ACCENTS[t.accent] || ACCENTS['Federal blue'];
    const r = document.documentElement.style;
    r.setProperty('--accent', a[0]);
    r.setProperty('--accent-dark', a[1]);
    r.setProperty('--accent-darker', a[2]);
    r.setProperty('--accent-light', a[3]);
    r.setProperty('--accent-lighter', a[4]);
  }, [t.accent]);

  function go(p) { setPage(p); window.scrollTo({ top: 0 }); }

  function handleSearch(c) {
    if (c.openId) { setRecId(c.openId); go('detail'); return; }
    setCriteria(c);
    go('results');
  }
  function openRec(id) { setRecId(id); go('detail'); }
  const currentRec = window.COLA.DATA.find((r) => r.id === recId);

  return (
    <div className="app-shell" data-density={t.density}>
      <GovBanner />
      <Header nav={page === 'search' ? 'search' : 'search'} onNav={(p) => { if (p === 'search') { setCriteria({ ...EMPTY }); go('search'); } }} />

      <main className="app-main">
        {page === 'search' && <SearchPage initial={criteria.mode ? criteria : { ...EMPTY }} onSearch={handleSearch} />}
        {page === 'results' && (
          <ResultsPage
            criteria={criteria}
            onOpen={openRec}
            onEditSearch={() => go('search')}
            onUpdateCriteria={setCriteria}
            view={view}
            setView={setView}
            showScores={t.showScores}
          />
        )}
        {page === 'detail' && <DetailPage rec={currentRec} onBack={() => go(criteria.mode ? 'results' : 'results')} onOpen={openRec} searchQuery={criteria.mode === 'text' ? criteria.text : ''} />}
      </main>

      <Footer />

      <TweaksPanel>
        <TweakSection label="Appearance" />
        <TweakSelect label="Accent" value={t.accent} options={Object.keys(ACCENTS)} onChange={(v) => setTweak('accent', v)} />
        <TweakRadio label="Result density" value={t.density} options={['compact', 'regular', 'comfy']} onChange={(v) => setTweak('density', v)} />
        <TweakSection label="Results" />
        <TweakSelect label="Default layout" value={t.defaultView} options={['gallery', 'list', 'table']} onChange={(v) => { setTweak('defaultView', v); setView(v); }} />
        <TweakToggle label="Show visual-match scores" value={t.showScores} onChange={(v) => setTweak('showScores', v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
