// Minimal SVG line/area chart. Hand-rolled rather than pulled from a charting
// library: the whole app ships three runtime dependencies, and a chart package
// would roughly double the bundle for one unlisted page.

import { useRef, useState } from 'react';

const W = 640;
const H = 180;
const PAD = { top: 12, right: 12, bottom: 22, left: 40 };

function niceMax(value) {
  if (value <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(value)));
  return Math.ceil(value / mag) * mag;
}

const DAY_MS = 24 * 60 * 60 * 1000;

// The smallest gap between buckets is the bin width the API used, which is
// under a day on the shorter ranges.
function bucketWidth(points) {
  let smallest = Infinity;
  for (let i = 1; i < points.length; i += 1) {
    const gap = new Date(points[i].t) - new Date(points[i - 1].t);
    if (gap > 0 && gap < smallest) smallest = gap;
  }
  return Number.isFinite(smallest) ? smallest : DAY_MS;
}

function formatters(points) {
  // Sub-daily bins need the hour or every label on a day repeats, and an hour
  // is only meaningful in the reader's timezone. Daily bins stay in UTC, since
  // those buckets start at 00:00Z and would otherwise read as the day before.
  const sub = bucketWidth(points) < DAY_MS;
  const timeZone = sub ? 'America/New_York' : 'UTC';
  const axis = new Intl.DateTimeFormat('en-US', {
    month: 'numeric',
    day: 'numeric',
    timeZone,
    ...(sub ? { hour: 'numeric' } : {}),
  });
  const full = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone,
    ...(sub ? { hour: 'numeric', timeZoneName: 'short' } : {}),
  });
  const apply = (fmt) => (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : fmt.format(d).replace(', ', ' ');
  };
  return { tickLabel: apply(axis), fullLabel: apply(full) };
}

const fmtValue = (v) => Number(v || 0).toLocaleString(undefined, { maximumFractionDigits: 1 });

export default function TimeSeries({ points, series, label }) {
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);

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
  const { tickLabel, fullLabel } = formatters(points);

  // The chart is stretched to the card width, so a screen pixel has to be
  // mapped back through the viewBox before it means anything in chart space.
  const indexAt = (clientX) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || stepX === 0) return 0;
    const vx = ((clientX - rect.left) / rect.width) * W;
    return Math.min(points.length - 1, Math.max(0, Math.round((vx - PAD.left) / stepX)));
  };

  const onKeyDown = (event) => {
    const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (delta !== 0) {
      event.preventDefault();
      setHover((prev) => {
        const from = prev === null ? (delta > 0 ? -1 : points.length) : prev;
        return Math.min(points.length - 1, Math.max(0, from + delta));
      });
    } else if (event.key === 'Escape') {
      setHover(null);
    }
  };

  const active = hover === null ? null : points[hover];
  // Keep the readout inside the card when the cursor is near either edge.
  const tipAt = hover === null ? 0 : x(hover) / W;
  const tipShift = tipAt < 0.25 ? '0' : tipAt > 0.75 ? '-100%' : '-50%';

  return (
    <div className="an-chart">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={label}
        preserveAspectRatio="none"
        tabIndex={0}
        onPointerMove={(e) => setHover(indexAt(e.clientX))}
        onPointerDown={(e) => setHover(indexAt(e.clientX))}
        onPointerLeave={() => setHover(null)}
        onKeyDown={onKeyDown}
        onBlur={() => setHover(null)}
      >
        {/* The root SVG only reports pointers over painted children, so the
            plot needs a surface of its own to read the cursor from. */}
        <rect x={PAD.left} y={0} width={W - PAD.left - PAD.right} height={H} fill="transparent" />
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
              {tickLabel(p.t)}
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
        {active ? (
          <g pointerEvents="none">
            <line
              className="an-cursor"
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.top}
              y2={PAD.top + innerH}
            />
            {series.map((s) => (
              <circle
                key={s.key}
                className="an-dot"
                cx={x(hover)}
                cy={y(active.values?.[s.key] ?? 0)}
                r="3.5"
                fill={s.color}
              />
            ))}
          </g>
        ) : null}
      </svg>
      {active ? (
        <div
          className="an-tip"
          role="status"
          style={{ left: `${tipAt * 100}%`, transform: `translateX(${tipShift})` }}
        >
          <div className="an-tip-when">{fullLabel(active.t)}</div>
          {series.map((s) => (
            <div key={s.key} className="an-tip-row">
              <span className="an-swatch" style={{ background: s.color }} />
              {s.label}
              <span className="an-tip-val">{fmtValue(active.values?.[s.key] ?? 0)}</span>
            </div>
          ))}
        </div>
      ) : null}
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
