// Ranked horizontal bars. Widths are relative to the largest row, so the list
// reads as a ranking rather than an absolute scale.

export default function BarList({ items, color = 'var(--accent)', format }) {
  if (!items || items.length === 0) {
    return <p className="muted an-note">No data for this range yet.</p>;
  }
  const max = Math.max(...items.map((i) => i.count), 1);

  return (
    <ul className="an-bars">
      {items.map((item) => (
        <li key={item.label}>
          <div className="an-bar-row">
            <span className="an-bar-label" title={item.label}>
              {format ? format(item.label) : item.label}
            </span>
            <b>{item.count.toLocaleString()}</b>
          </div>
          <div className="score-bar">
            <span style={{ width: (item.count / max) * 100 + '%', background: color }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
