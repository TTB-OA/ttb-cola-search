export default function Highlight({ text, q }) {
  const str = text == null ? '' : String(text);
  if (!q) return <>{str}</>;
  const idx = str.toLowerCase().indexOf(String(q).toLowerCase());
  if (idx < 0) return <>{str}</>;
  return (
    <>
      {str.slice(0, idx)}
      <mark style={{ background: 'var(--gold)', padding: '0 2px', borderRadius: 2 }}>
        {str.slice(idx, idx + q.length)}
      </mark>
      {str.slice(idx + q.length)}
    </>
  );
}
