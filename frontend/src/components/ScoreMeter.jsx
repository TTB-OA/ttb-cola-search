import Icon from './Icon.jsx';

// Raw image-to-image cosine for unrelated labels centres on 0.63 (p90 0.71), so
// the scale starts there: 0.70 -> 0%, same artwork (>= 0.97) -> 90%+.
// Measured with scripts/_diag_scores.py.
const NOISE_FLOOR = 0.7;

function toPct(score) {
  if (score == null) return null;
  const n = ((score - NOISE_FLOOR) / (1 - NOISE_FLOOR)) * 100;
  return Math.round(Math.min(100, Math.max(0, n)));
}

export default function ScoreMeter({ score, compact }) {
  const pct = toPct(score);
  if (pct == null) return null;
  const hue = pct >= 90 ? 'var(--green)' : pct >= 60 ? 'var(--gold-dark)' : 'var(--base)';
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
