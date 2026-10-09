// Unlisted usage dashboard, linked only from the footer — see the README.

import { useState } from 'react';
import BarList from '../components/charts/BarList.jsx';
import StatTile from '../components/charts/StatTile.jsx';
import TimeSeries from '../components/charts/TimeSeries.jsx';
import { useAsync } from '../hooks/useAsync.js';
import { useDocumentTitle } from '../hooks/useDocumentTitle.js';
import { api } from '../lib/api.js';

const RANGES = [
  { key: '7d', label: '7 days' },
  { key: '14d', label: '14 days' },
  { key: '30d', label: '30 days' },
  { key: '90d', label: '90 days' },
];

const FILTER_LABELS = {
  q: 'Keyword',
  ttbId: 'TTB ID',
  brand: 'Brand',
  fanciful: 'Fanciful name',
  applicant: 'Applicant',
  business: 'Business',
  permit: 'Permit number',
  permitName: 'Permit name',
  permitState: 'Permit state',
  permitCity: 'Permit city',
  submitter: 'Submitter',
  varietal: 'Varietal',
  qualification: 'Qualification',
  labelText: 'Label text',
  commodity: 'Commodity',
  classType: 'Class/Type',
  source: 'Source',
  origin: 'Origin',
  status: 'Status',
  dateFrom: 'Date from',
  dateTo: 'Date to',
  appellation: 'Appellation',
  formula: 'Formula',
  submittedFrom: 'Submitted from',
  submittedTo: 'Submitted to',
};

const LATENCY_COLORS = [
  'var(--accent)',
  'var(--mint)',
  'var(--green)',
  'var(--gold-dark)',
  'var(--red)',
  'var(--base-dark)',
];

const num = (n) => Number(n || 0).toLocaleString();
const pct = (n) => `${Number(n || 0).toFixed(1)}%`;
const ms = (n) => `${Math.round(Number(n || 0))} ms`;

/* ---------- Card ---------- */
function Card({ title, actions, children }) {
  return (
    <section className="an-card panel">
      {actions ? (
        <div className="an-card-head">
          <h2>{title}</h2>
          {actions}
        </div>
      ) : (
        <h2>{title}</h2>
      )}
      {children}
    </section>
  );
}

function Seg({ label, options, value, onChange }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          className={value === o.key ? 'active' : ''}
          aria-pressed={value === o.key}
          onClick={() => onChange(o.key)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ---------- Latency table ---------- */
function LatencyTable({ rows }) {
  if (!rows || rows.length === 0) return <p className="muted an-note">No data for this range yet.</p>;
  return (
    <table className="an-table">
      <thead>
        <tr>
          <th>Endpoint</th>
          <th>Requests</th>
          <th>p50</th>
          <th>p95</th>
          <th>p99</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.endpoint}>
            <td title={r.endpoint}>{r.endpoint}</td>
            <td>{num(r.requests)}</td>
            <td>{ms(r.p50)}</td>
            <td>{ms(r.p95)}</td>
            <td>{ms(r.p99)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ---------- Latency card: table or per-endpoint series ---------- */
function LatencyCard({ rows, overTime }) {
  const [view, setView] = useState('table');
  const [metric, setMetric] = useState('p95');
  const series = (overTime?.endpoints || []).map((endpoint, i) => ({
    key: endpoint,
    label: endpoint,
    color: LATENCY_COLORS[i % LATENCY_COLORS.length],
  }));

  return (
    <Card
      title="Response time by endpoint"
      actions={
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {view === 'chart' ? (
            <Seg
              label="Percentile"
              value={metric}
              onChange={setMetric}
              options={[
                { key: 'p50', label: 'p50' },
                { key: 'p95', label: 'p95' },
              ]}
            />
          ) : null}
          <Seg
            label="View"
            value={view}
            onChange={setView}
            options={[
              { key: 'table', label: 'Table' },
              { key: 'chart', label: 'Over time' },
            ]}
          />
        </div>
      }
    >
      {view === 'table' ? (
        <LatencyTable rows={rows} />
      ) : (
        <TimeSeries
          label={`${metric} response time per endpoint over time, in milliseconds`}
          points={overTime?.[metric]}
          series={series}
          format={ms}
          toggleable
        />
      )}
    </Card>
  );
}

/* ---------- Top COLAs ---------- */
function TopColas({ rows }) {
  if (!rows || rows.length === 0) {
    return (
      <p className="muted an-note">
        No data for this range yet. Detail views only began recording which record was
        viewed in a recent release.
      </p>
    );
  }
  return (
    <table className="an-table">
      <thead>
        <tr>
          <th>Record</th>
          <th>Views</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.colaId}>
            <td>
              <a href={`/cola/${encodeURIComponent(r.colaId)}`}>{r.brandName || r.colaId}</a>
            </td>
            <td>{num(r.views)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ---------- Page ---------- */
export default function AnalyticsPage() {
  useDocumentTitle('Usage dashboard');
  const [range, setRange] = useState('30d');
  const { data, loading, error } = useAsync(
    (signal) => api.analyticsDashboard({ range }, signal),
    [range]
  );

  const totals = data?.totals;
  const panels = data?.panels || {};
  const missing = data?.unavailable || [];

  return (
    <div className="wrap an-page">
      <div className="an-head">
        <h1>Usage dashboard</h1>
        <div className="seg" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              className={range === r.key ? 'active' : ''}
              onClick={() => setRange(r.key)}
            >
              {r.label}
            </button>
          ))}
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
          <h2>Usage data is unavailable</h2>
          <p className="muted">
            {error.status === 404
              ? 'The dashboard is not enabled for this deployment.'
              : 'The reporting service did not respond. Try again in a few minutes.'}
          </p>
        </div>
      ) : (
        <>
          {missing.length > 0 ? (
            <p className="an-warn">
              {missing.length} panel{missing.length === 1 ? '' : 's'} could not be loaded
              and {missing.length === 1 ? 'is' : 'are'} shown empty rather than as zero.
            </p>
          ) : null}

          <div className="an-tiles">
            <StatTile label="Searches" value={num(totals?.searches)} />
            <StatTile label="Sessions" value={num(totals?.sessions)} />
            <StatTile label="Detail views" value={num(totals?.detailViews)} />
            <StatTile
              label="Zero-result rate"
              value={pct(totals?.zeroResultRate)}
              hint="Searches returning nothing"
            />
            <StatTile
              label="Failed requests"
              value={pct(totals?.failureRate)}
              hint="Not an uptime measure"
            />
            <StatTile label="Slowest p95" value={ms(totals?.p95Ms)} hint="Across endpoints" />
          </div>

          <div className="an-grid-2">
            <Card title="Activity over time">
              <TimeSeries
                label="Searches, detail views and sessions over time"
                points={panels.usageOverTime}
                series={[
                  { key: 'searches', label: 'Searches', color: 'var(--accent)' },
                  { key: 'detailViews', label: 'Detail views', color: 'var(--mint)' },
                  { key: 'sessions', label: 'Sessions', color: 'var(--green)' },
                ]}
              />
            </Card>

            <Card title="Searches returning nothing">
              <TimeSeries
                label="Total searches versus zero-result searches"
                points={panels.zeroResultsOverTime}
                series={[
                  { key: 'searches', label: 'Searches', color: 'var(--accent)' },
                  { key: 'zero', label: 'Zero results', color: 'var(--red)' },
                ]}
              />
            </Card>

            <Card title="Most-used filters">
              <BarList
                items={panels.filterUsage}
                format={(k) => FILTER_LABELS[k] || k}
              />
            </Card>

            <Card title="How deep people page">
              <BarList
                items={panels.pagingDepth}
                color="var(--mint)"
                format={(p) => `Page ${p}`}
              />
            </Card>

            <Card title="Sort preference">
              <BarList items={panels.sortUsage} color="var(--mint)" />
            </Card>

            <Card title="Top keyword searches">
              <BarList items={panels.topQueries} />
            </Card>

            <Card title="Keyword searches with no results">
              <BarList items={panels.zeroResultQueries} color="var(--red)" />
            </Card>

            <Card title="Top filter values">
              <BarList
                items={(panels.filterValues || []).map((r) => ({
                  label: `${FILTER_LABELS[r.filter] || r.filter}: ${r.value}`,
                  count: r.count,
                }))}
                color="var(--mint)"
              />
            </Card>

            <Card title="Top artwork descriptions">
              <BarList items={panels.describeQueries} color="var(--gold-dark)" />
            </Card>

            <Card title="Most-viewed records">
              <TopColas rows={panels.topColas} />
            </Card>

            <Card title="Popular commodities">
              <BarList items={panels.commodityUsage} color="var(--green)" />
            </Card>

            <Card title="Popular origins">
              <BarList items={panels.originUsage} color="var(--green)" />
            </Card>

            <LatencyCard rows={panels.latency} overTime={panels.latencyOverTime} />

            <Card title="Request failures">
              <TimeSeries
                label="Total versus failed requests"
                points={panels.reliability}
                series={[
                  { key: 'total', label: 'Requests', color: 'var(--accent)' },
                  { key: 'failed', label: 'Failed', color: 'var(--red)' },
                ]}
              />
            </Card>

            <Card title="Error responses">
              <BarList items={panels.statusCodes} color="var(--red)" />
            </Card>

            <Card title="Image search">
              <TimeSeries
                label="Image searches performed, abandoned and lost"
                points={panels.imageSearchOverTime}
                series={[
                  { key: 'performed', label: 'Performed', color: 'var(--accent)' },
                  { key: 'abandoned', label: 'Abandoned', color: 'var(--gold-dark)' },
                  { key: 'stateLost', label: 'State lost', color: 'var(--red)' },
                ]}
              />
            </Card>

            <Card title="Uploaded image sizes">
              <BarList items={panels.uploadSizes} color="var(--gold-dark)" />
            </Card>

            <Card title="Map usage">
              <TimeSeries
                label="Map viewports, area summaries and label clicks over time"
                points={panels.mapOverTime}
                series={[
                  { key: 'viewports', label: 'Viewports', color: 'var(--accent)' },
                  { key: 'areas', label: 'Areas opened', color: 'var(--mint)' },
                  { key: 'markers', label: 'Labels clicked', color: 'var(--green)' },
                  { key: 'sessions', label: 'Sessions', color: 'var(--base-dark)' },
                ]}
              />
            </Card>

            <Card title="How the map is read">
              <BarList items={panels.mapModeUsage} color="var(--mint)" />
            </Card>

            <Card title="Map filters used">
              <BarList items={panels.mapFilterUsage} format={(k) => FILTER_LABELS[k] || k} />
            </Card>

            <Card title="Map zoom levels">
              <BarList
                items={panels.mapZoomUsage}
                color="var(--green)"
                format={(z) => `Zoom ${z}`}
              />
            </Card>
          </div>

          <p className="an-caption">
            {data?.cached ? 'Served from cache. ' : ''}
            Data as of {new Date(data.generatedAt).toLocaleString()}. Telemetry takes a
            few minutes to become queryable, so the most recent bucket may be
            incomplete.
          </p>
        </>
      )}
    </div>
  );
}
