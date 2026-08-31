// Small presentation helpers shared across pages/components.

// Parse a bare YYYY-MM-DD as a local calendar date; Date() reads it as UTC,
// which slips back a day west of Greenwich.
function parseDate(iso) {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso).trim());
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

// Format an ISO date (or date-time) into a short US date, or an em dash.
export function fmtDate(iso) {
  const d = parseDate(iso);
  if (!d) return '—';
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

// Same, but with the month spelled out.
export function fmtDateLong(iso) {
  const d = parseDate(iso);
  if (!d) return '—';
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}

// Short date plus clock time, for stamps where the time of day matters.
export function fmtDateTime(iso) {
  const d = parseDate(iso);
  if (!d) return '—';
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

// Format a North American number; anything else is passed through as-is.
export function fmtPhone(value) {
  const text = String(value ?? '').trim();
  let digits = text.replace(/\D/g, '');
  if (digits.length === 11 && digits.startsWith('1')) digits = digits.slice(1);
  if (digits.length === 10) return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  if (digits.length === 7) return `${digits.slice(0, 3)}-${digits.slice(3)}`;
  return text;
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
  // Ids are text, so hash the characters rather than coercing to a number.
  const id = String(rec.id || '');
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) hash = (hash * 31 + id.charCodeAt(i)) % 100000;
  const idx = hash % set.length;
  return set[idx];
}

// Label faces display brand/keg-collar first, then back, then everything else.
// `face` is a lowercased img_type, and "brand (front) or keg collar" is a single
// stored value, so match on substrings rather than equality.
export function faceRank(face) {
  const f = (face || '').toLowerCase();
  if (f.includes('front') || f.includes('keg')) return 0;
  if (f.includes('back')) return 1;
  return 2;
}

export function orderFaces(faces) {
  const uniq = Array.from(new Set(faces.filter(Boolean)));
  return uniq.sort((a, b) => faceRank(a) - faceRank(b) || a.localeCompare(b));
}
