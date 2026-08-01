// Small presentation helpers shared across pages/components.

// Format an ISO date (or date-time) into a short US date, or an em dash.
export function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

// Map a commodity/category label to the CSS tag class used by styles.css.
export function tagClass(category) {
  switch ((category || '').toLowerCase()) {
    case 'wine':
      return 'wine';
    case 'malt beverage':
    case 'beer':
      return 'beer';
    case 'distilled spirits':
    case 'spirits':
      return 'spirits';
    case 'cider':
      return 'cider';
    default:
      return 'wine';
  }
}

// Deterministic placeholder palette for procedural label thumbnails, keyed by
// category with a small per-record variation so cards don't all look identical.
const PALETTES = {
  wine: [
    { bg: '#f4ecec', ink: '#7a2348' },
    { bg: '#efe7ee', ink: '#5b2b52' },
    { bg: '#f6eee6', ink: '#6e3b1f' },
  ],
  beer: [
    { bg: '#f7f0dc', ink: '#7a5a12' },
    { bg: '#f3ecd6', ink: '#5f4a13' },
  ],
  spirits: [
    { bg: '#e9eff4', ink: '#1a4d6e' },
    { bg: '#eceef1', ink: '#26333f' },
  ],
  cider: [{ bg: '#eef4e6', ink: '#3d6321' }],
};

export function placeholderStyle(rec) {
  const key = tagClass(rec.category);
  const set = PALETTES[key] || PALETTES.wine;
  const idx = Math.abs(Number(rec.id) || 0) % set.length;
  return set[idx];
}

// Faces we cycle through in the label viewer, in preferred display order.
export const FACE_ORDER = ['front', 'back', 'neck', 'other'];

export function orderFaces(faces) {
  const uniq = Array.from(new Set(faces.filter(Boolean)));
  return uniq.sort((a, b) => {
    const ia = FACE_ORDER.indexOf(a);
    const ib = FACE_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
}
