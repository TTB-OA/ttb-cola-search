// Data coverage: how far each year of COLA approvals has moved through the
// ingest and enrichment pipeline. Every number is a record count from
// cola_coverage_year — nothing here is derived from user activity.

import { Link } from 'react-router-dom';
import StatTile from '../components/charts/StatTile.jsx';
import { useAsync } from '../hooks/useAsync.js';
import { api } from '../lib/api.js';
import { fmtDate, fmtDateTime } from '../lib/format.js';

// Pipeline order. Each stage is a subset of the one above it, so `denominator`
// names the field a stage's share is measured against.
const STAGES = [
  {
    key: 'ingestedCount',
    denominator: 'apiCount',
    label: 'Ingested',
    hint: 'Records loaded from the TTB registry',
    color: 'var(--accent)',
  },
  {
    key: 'detailCount',
    denominator: 'ingestedCount',
    label: 'Full detail',
    hint: 'Permit, submitter and qualification data filled in',
    color: 'var(--mint)',
  },
  {
    key: 'imageCount',
    denominator: 'ingestedCount',
    label: 'Label images',
    hint: 'At least one label image stored',
    color: 'var(--mint)',
  },
  {
    key: 'ocrCount',
    denominator: 'ingestedCount',
    label: 'Label text',
    hint: 'Every stored label read by OCR',
    color: 'var(--green)',
  },
  {
    key: 'embeddingCount',
    denominator: 'ingestedCount',
    label: 'Image search',
    hint: 'Every stored label indexed for similarity',
    color: 'var(--green)',
  },
];

const num = (n) => Number(n || 0).toLocaleString();

// The row counts behind these are planner estimates, so they are never shown as
// if they were exact.
const approx = (n) => (n === null || n === undefined ? '—' : `≈ ${num(n)}`);

// Null rather than zero when there is no denominator: "unknown" and "none of
// them" are different statements, and the bar should stay empty for both.
function share(count, total) {
  return total > 0 ? (Number(count || 0) / total) * 100 : null;
}

function fmtPct(value) {
  if (value === null) return '—';
  return `${value >= 99.95 ? 100 : value.toFixed(1)}%`;
}

function Fact({ label, value, hint }) {
  return (
    <div className="cv-fact">
      <div className="d-label">{label}</div>
      <div className="cv-fact-value">{value}</div>
      {hint ? <div className="an-hint muted">{hint}</div> : null}
    </div>
  );
}

function SearchIndex({ search, asOf }) {
  if (!search) {
    return <p className="muted an-note">Search index status is unavailable right now.</p>;
  }
  const pending = Number(search.pendingCount || 0);
  return (
    <div className="cv-facts">
      <Fact
        label="Searchable records"
        value={approx(search.searchableCount)}
        hint="Rows in the search index"
      />
      <Fact
        label="Labels with searchable text"
        value={approx(search.labelTextCount)}
        hint="Records whose label text can be searched"
      />
      <Fact
        label="Awaiting refresh"
        value={pending === 0 ? 'Up to date' : num(pending)}
        hint={
          pending === 0
            ? 'The index matches the ingested data'
            : `Queued since ${fmtDateTime(search.oldestPendingAt)}`
        }
      />
      <Fact
        label="Last rebuilt"
        value={fmtDateTime(asOf)}
        hint="Coverage and the index refresh together"
      />
    </div>
  );
}

// Ends of the fully enriched range: the records that cleared every stage, not
// just the ones the pipeline has reached.
function Bookend({ label, rec }) {
  if (!rec) {
    return <Fact label={label} value="—" hint="Nothing has cleared every stage yet" />;
  }
  return (
    <div className="cv-fact">
      <div className="d-label">{label}</div>
      <div className="cv-fact-value">{fmtDate(rec.approvalDate)}</div>
      <div className="an-hint">
        <Link to={`/cola/${rec.id}`}>{rec.brand || `TTB ID ${rec.ttbId}`}</Link>
        <span className="muted"> · TTB ID {rec.ttbId}</span>
      </div>
    </div>
  );
}

function CompleteRange({ range }) {
  if (!range) {
    return <p className="muted an-note">The fully processed range is unavailable right now.</p>;
  }
  return (
    <div className="cv-facts">
      <Bookend label="Earliest approval" rec={range.earliest} />
      <Bookend label="Latest approval" rec={range.latest} />
    </div>
  );
}

function StageCell({ row, stage }) {
  const value = share(row[stage.key], row[stage.denominator]);
  return (
    <td>
      <div className="cv-cell">
        <span>{num(row[stage.key])}</span>
        <span className="cv-pct muted">{fmtPct(value)}</span>
      </div>
      <div className="score-bar">
        <span style={{ width: `${value ?? 0}%`, background: stage.color }} />
      </div>
    </td>
  );
}

function CoverageTable({ years, totals }) {
  if (!years || years.length === 0) {
    return <p className="muted an-note">No coverage has been recorded yet.</p>;
  }
  return (
    <div className="cv-scroll">
      <table className="an-table cv-table">
        <thead>
          <tr>
            <th>Approval year</th>
            <th>Upstream</th>
            {STAGES.map((s) => (
              <th key={s.key} title={s.hint}>
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((row) => (
            <tr key={row.year}>
              <th scope="row">{row.year}</th>
              <td>{row.apiCount === null || row.apiCount === undefined ? '—' : num(row.apiCount)}</td>
              {STAGES.map((s) => (
                <StageCell key={s.key} row={row} stage={s} />
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">All years</th>
            <td>
              {totals?.apiCount === null || totals?.apiCount === undefined
                ? '—'
                : num(totals.apiCount)}
            </td>
            {STAGES.map((s) => (
              <StageCell key={s.key} row={totals || {}} stage={s} />
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export default function CoveragePage() {
  const { data, loading, error } = useAsync((signal) => api.coverage(signal), []);

  const totals = data?.totals;
  const years = data?.years || [];
  const ingested = totals?.ingestedCount || 0;

  return (
    <div className="wrap an-page">
      <div className="an-head">
        <div>
          <h1>Data coverage</h1>
          <p className="an-caption">
            How much of the TTB Public COLA Registry this site holds, and how far each
            year has been enriched. Search only finds what has been ingested, and the
            label-text and image searches only reach the records shown below.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="an-tiles">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="skel an-tile" style={{ height: 92 }} />
          ))}
        </div>
      ) : error ? (
        <div className="empty panel">
          <h2>Coverage is unavailable</h2>
          <p className="muted">
            Coverage figures could not be loaded. Try again in a few minutes.
          </p>
        </div>
      ) : (
        <>
          <div className="an-tiles">
            <StatTile
              label="Records held"
              value={num(ingested)}
              hint={
                totals?.apiCount
                  ? `${fmtPct(share(ingested, totals.apiCount))} of ${num(totals.apiCount)} upstream`
                  : 'Loaded from the TTB registry'
              }
            />
            {STAGES.slice(1).map((s) => (
              <StatTile
                key={s.key}
                label={s.label}
                value={fmtPct(share(totals?.[s.key], ingested))}
                hint={s.hint}
              />
            ))}
          </div>

          <section className="an-card panel cv-index">
            <h2>Search index</h2>
            <SearchIndex search={data?.search} asOf={data?.asOf} />
          </section>

          <section className="an-card panel cv-index">
            <h2>Fully processed records</h2>
            <CompleteRange range={data?.completeRange} />
            <p className="muted an-note">
              The oldest and newest approvals whose detail, label images, label text and
              image-search indexing have all finished. Records outside this range may
              still be complete; enrichment does not run in approval order.
            </p>
          </section>

          <section className="an-card panel">
            <h2>Coverage by approval year</h2>
            <CoverageTable years={years} totals={totals} />
            <p className="muted an-note">
              Stages are nested: a record counts towards label text only once every one
              of its stored images has been read. Upstream is the number of approvals
              TTB reported for the year, and is blank where the pipeline has not
              recorded one.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
