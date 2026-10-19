import { termsPattern } from '../lib/queryTerms.js';

// `q` is a literal string or an array of terms (see queryTerms); every occurrence is marked.
export default function Highlight({ text, q }) {
  const str = text == null ? '' : String(text);
  const re = termsPattern(q);
  if (!re) return <>{str}</>;
  const parts = str.split(re);
  if (parts.length < 2) return <>{str}</>;
  return (
    <>
      {parts.map((part, i) =>
        i % 2 ? (
          <mark key={i} style={{ background: 'var(--gold)', padding: '0 2px', borderRadius: 2 }}>
            {part}
          </mark>
        ) : (
          part
        )
      )}
    </>
  );
}
