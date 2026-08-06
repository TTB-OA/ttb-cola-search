// One headline number with a caption. Mirrors the .d-label / .d-value pairing
// used on the detail page so the dashboard reads as part of the same app.

export default function StatTile({ label, value, hint }) {
  return (
    <div className="an-tile panel">
      <div className="d-label">{label}</div>
      <div className="an-stat">{value}</div>
      {hint ? <div className="an-hint muted">{hint}</div> : null}
    </div>
  );
}
