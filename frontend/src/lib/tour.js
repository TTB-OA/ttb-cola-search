// Step definitions for the product tour. `target` is a CSS selector resolved at
// runtime; `route` moves the app to the page a step lives on (a function when
// the path depends on a sample record). Steps flagged `requireTarget` are
// dropped when their element is missing; others fall back to a centered card.
const SEEN_KEY = 'ttb-cola:tour-seen:v1';

// One of these is typed into the search box during the `search` step, then
// carried into the results route so the results/facets steps show a real,
// filtered result set. All are broad enough to match plenty of approvals.
export const DEMO_QUERIES = [
  'cape may',
  'napa valley',
  'bourbon whiskey',
  'cabernet sauvignon',
  'brewing company',
  'india pale ale',
  'chardonnay',
  'single malt',
];

export function pickDemoQuery() {
  return DEMO_QUERIES[Math.floor(Math.random() * DEMO_QUERIES.length)];
}

export function resultsRoute(query) {
  return `/results?q=${encodeURIComponent(query)}&sort=approvalDate&status=Approved`;
}

// Pause before the sample query starts typing itself, so the step's card can be
// read first (ms).
export const DEMO_TYPING_DELAY_MS = 900;

export const TOUR_STEPS = [
  {
    id: 'welcome',
    route: '/',
    placement: 'center',
    title: 'Welcome to the Public COLA Registry',
    body:
      'Search every Certificate of Label Approval issued for wine, malt beverages, and distilled spirits — including the approved label artwork. Here is a quick look at what you can do.',
  },
  {
    id: 'search',
    route: '/',
    target: '[data-tour="search-box"]',
    placement: 'bottom',
    title: 'Start with one search box',
    body:
      'Brand, product name, applicant, permit, submitter, class/type, origin, and TTB ID are all searched at once — watch us try one. Results default to approved labels from the last three calendar years.',
  },
  {
    id: 'quick-filters',
    route: '/',
    target: '[data-tour="quick-filters"]',
    placement: 'bottom',
    requireTarget: true,
    title: 'Narrow by commodity',
    body: 'Limit results to wine, malt beverage, or distilled spirits before you search.',
  },
  {
    id: 'advanced',
    route: '/',
    target: '[data-tour="advanced-toggle"]',
    placement: 'left',
    requireTarget: true,
    title: 'Go deeper with advanced search',
    body:
      'Open advanced search for field-level control: TTB ID or serial number, permit number and permit holder location, varietal, qualifications, approval date range, and text found on the label itself.',
  },
  {
    id: 'image',
    route: '/',
    target: '[data-tour="image-tab"]',
    placement: 'bottom',
    requireTarget: true,
    title: 'Or search by artwork',
    body:
      'Upload a label image and we rank approved artwork by visual similarity — color palette, composition, and graphic elements. No image handy? The next tab lets you describe the label in plain language instead.',
  },
  {
    id: 'recent',
    route: '/',
    target: '[data-tour="recent"]',
    placement: 'top',
    requireTarget: true,
    title: 'Browse the newest approvals',
    body: 'Recently approved labels are always on the home page. Next, a look at a full result set.',
  },
  {
    id: 'results-facets',
    route: (ctx) => resultsRoute(ctx.query),
    target: '[data-tour="results-facets"]',
    placement: 'right',
    skipMobile: true,
    title: 'Refine without starting over',
    body:
      'Results are faceted by commodity, status, and source, with pick lists for origin and permit state. Counts update as you drill in, and every active filter becomes a chip you can remove individually.',
  },
  {
    id: 'results-views',
    route: (ctx) => resultsRoute(ctx.query),
    target: '[data-tour="results-views"]',
    placement: 'bottom',
    title: 'Sort and switch views',
    body:
      'Re-sort by relevance, newest approval, brand, or applicant, and switch between gallery, list, and table views. Your view preference is remembered.',
  },
  {
    id: 'detail-images',
    route: (ctx) => (ctx.colaId ? `/cola/${encodeURIComponent(ctx.colaId)}` : null),
    target: '[data-tour="detail-images"]',
    placement: 'right',
    title: 'Every approved label image',
    body:
      'Open a result to see the artwork exactly as approved — brand, back, neck, and keg collar faces included. Select a face to enlarge it, or open the full-size viewer.',
  },
  {
    id: 'detail-fields',
    route: (ctx) => (ctx.colaId ? `/cola/${encodeURIComponent(ctx.colaId)}` : null),
    target: '[data-tour="detail-fields"]',
    placement: 'left',
    title: 'The complete certificate record',
    body:
      'Label identity, origin and status, application and permit details, submitter contact information, every associated permit, and any qualifications TTB attached to the approval.',
  },
  {
    id: 'detail-ocr',
    route: (ctx) => (ctx.colaId ? `/cola/${encodeURIComponent(ctx.colaId)}` : null),
    target: '[data-tour="detail-ocr"]',
    placement: 'left',
    title: 'Text read from the label images',
    body:
      'Text detected on the artwork is listed here and can be searched from advanced search. Select a phrase to highlight exactly where it appears on the label.',
  },
  {
    id: 'detail-similar',
    route: (ctx) => (ctx.colaId ? `/cola/${encodeURIComponent(ctx.colaId)}` : null),
    target: '[data-tour="detail-similar"]',
    placement: 'right',
    title: 'Related approvals',
    body:
      'Each record links to similar COLAs from the same industry member and from other industry members — useful for comparing prior approvals and trade dress.',
  },
  {
    id: 'coverage',
    route: '/',
    target: '[data-tour="coverage-link"]',
    placement: 'bottom',
    requireTarget: true,
    title: 'One more thing: data coverage',
    body:
      'We are still backfilling historical COLA records and label images. Coverage shows what has loaded so far — by year — so you know how complete a search is.',
  },
  {
    id: 'replay',
    route: '/', // returns the user to the search page as the tour ends
    target: '[data-tour="tour-button"]',
    placement: 'bottom',
    requireTarget: true,
    title: "You're all set",
    body: 'You are back on the search page — start your own search, and replay this tour anytime from the Tour link in the header.',
  },
];

export function hasSeenTour() {
  try {
    return window.localStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return true; // storage blocked: don't nag on every visit
  }
}

export function markTourSeen() {
  try {
    window.localStorage.setItem(SEEN_KEY, '1');
  } catch {
    /* ignore */
  }
}
