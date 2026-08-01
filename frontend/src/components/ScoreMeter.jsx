import Icon from './Icon.jsx';

// Displays a visual-similarity score (0-100). API scores arrive as 0..1, so we
// normalize any value <= 1 to a percentage.
function toPct(score) {
  if (score == null) return null;
  const n = score <= 1 ? score * 100 : score;
  return Math.round(n);
}

export default function ScoreMeter({ score, compact }) {
  const pct = toPct(score);
  if (pct == null) return null;
  const hue = pct >= 88 ? 'var(--green)' : pct >= 75 ? 'var(--gold-dark)' : 'var(--base)';
  if (compact) {
    return (
      <span className="score-pill" style={{ color: hue }}>
        <b>{pct}%</b>
      </span>
    );
  }
  return (
    <div className="score">
      <div className="score-row">
        <Icon name="sparkle" size={14} /> <b>{pct}%</b> visual match
      </div>
      <div className="score-bar">
        <span style={{ width: pct + '%', background: hue }}></span>
      </div>
    </div>
  );
}

export { toPct };
