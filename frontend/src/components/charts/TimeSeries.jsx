// Minimal SVG line/area chart. Hand-rolled rather than pulled from a charting
// library: the whole app ships three runtime dependencies, and a chart package
// would roughly double the bundle for one unlisted page.

const W = 640;
const H = 180;
const PAD = { top: 12, right: 12, bottom: 22, left: 40 };

function niceMax(value) {
  if (value <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(value)));
  return Math.ceil(value / mag) * mag;
}

function shortDate(iso) {
  const d = new Date(iso);
  // Buckets are aligned to UTC boundaries, so label them in UTC: rendering the
  // 00:00Z start of today's bucket locally would show it as yesterday.
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric', timeZone: 'UTC' });
}

export default function TimeSeries({ points, series, label }) {
  if (!points || points.length === 0) {
    return <p className="muted an-note">No data for this range yet.</p>;
  }

  const max = niceMax(
    Math.max(
      ...points.map((p) => Math.max(...series.map((s) => Number(p.values?.[s.key] ?? 0))))
    )
  );
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  // A single point has no span to divide, so pin it to the left edge.
  const stepX = points.length > 1 ? innerW / (points.length - 1) : 0;

  const x = (i) => PAD.left + i * stepX;
  const y = (v) => PAD.top + innerH - (Number(v) / max) * innerH;

  const path = (key) =>
    points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.values?.[key] ?? 0)}`).join(' ');

  const ticks = [0, max / 2, max];
  // Cap the axis at a handful of labels so they never collide.
  const every = Math.max(1, Math.ceil(points.length / 6));

  return (
    <div className="an-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} preserveAspectRatio="none">
        {ticks.map((t) => (
          <g key={t}>
            <line className="an-grid" x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
            <text className="an-axis" x={PAD.left - 6} y={y(t) + 4} textAnchor="end">
              {Math.round(t)}
            </text>
          </g>
        ))}
        {points.map((p, i) =>
          i % every === 0 ? (
            <text
              key={p.t}
              className="an-axis"
              x={x(i)}
              y={H - 6}
              textAnchor={i === 0 ? 'start' : 'middle'}
            >
              {shortDate(p.t)}
            </text>
          ) : null
        )}
        {series.map((s) => (
          <path key={s.key} className="an-line" d={path(s.key)} stroke={s.color} fill="none" />
        ))}
        {/* A lone bucket produces a path with no segment to stroke, so mark it. */}
        {points.length === 1 &&
          series.map((s) => (
            <circle
              key={s.key}
              cx={x(0)}
              cy={y(points[0].values?.[s.key] ?? 0)}
              r="3"
              fill={s.color}
            />
          ))}
      </svg>
      <ul className="an-legend">
        {series.map((s) => (
          <li key={s.key}>
            <span className="an-swatch" style={{ background: s.color }} />
            {s.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
