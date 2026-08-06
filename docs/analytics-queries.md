# Analytics queries

KQL for the Application Insights component (`<namePrefix>-appi`). Run these from
**Logs** on either the component or the underlying Log Analytics workspace.

## Where the data lives

| Table | Contents |
| --- | --- |
| `customEvents` | Everything emitted through `analytics.emit()` — the product usage events |
| `requests` | One row per HTTP request, from OpenTelemetry auto-instrumentation |
| `dependencies` | Postgres statements and outbound calls |
| `traces` | Application logs |
| `exceptions` | Unhandled errors |

Event attributes land in `customDimensions`, which is dynamic — always cast
before comparing or aggregating (`toint()`, `tobool()`, `tostring()`).

Every event carries `session_id`, `origin` (`server` or `client`), and for
server-derived events `status_code` and `duration_ms`.

## Product usage

### Search funnel

How far visitors get. `dcount` on `session_id` rather than raw counts, so one
person paging through results does not look like ten.

```kusto
let window = 30d;
customEvents
| where timestamp > ago(window)
| where name in ("search_performed", "detail_viewed", "similar_requested")
| summarize sessions = dcount(tostring(customDimensions.session_id)) by name
| order by sessions desc
```

### Zero-result rate

The single most actionable search-quality number. A rising line means people are
asking for things the index cannot answer.

```kusto
customEvents
| where timestamp > ago(30d) and name == "search_performed"
| summarize
    searches = count(),
    zero = countif(tobool(customDimensions.zero_results))
  by bin(timestamp, 1d)
| extend zero_rate = round(100.0 * zero / searches, 1)
| render timechart
```

### Which filters actually get used

`filters_used` is a comma-joined list of filter *names*, so it has to be split
before counting. Anything near the bottom is a candidate for removal from the
advanced panel.

```kusto
customEvents
| where timestamp > ago(30d) and name == "search_performed"
| extend used = split(tostring(customDimensions.filters_used), ",")
| mv-expand filter = used to typeof(string)
| where isnotempty(filter)
| summarize searches = count(), sessions = dcount(tostring(customDimensions.session_id)) by filter
| order by searches desc
```

### How many filters at once

Distinguishes "one box and go" from real advanced use, which is the argument for
how much of the advanced panel to keep.

```kusto
customEvents
| where timestamp > ago(30d) and name == "search_performed"
| summarize searches = count() by filter_count = toint(customDimensions.filter_count)
| order by filter_count asc
| render columnchart
```

### Sort and view-mode preferences

```kusto
customEvents
| where timestamp > ago(30d)
| where name in ("search_performed", "view_mode_changed")
| extend choice = coalesce(tostring(customDimensions.sort), tostring(customDimensions.view))
| summarize count() by name, choice
| order by name asc, count_ desc
```

### Do people look past the first few results?

`rank` is the absolute position across pages, so page 2 slot 1 is 13, not 1.

```kusto
customEvents
| where timestamp > ago(30d) and name == "result_clicked"
| summarize clicks = count() by rank = toint(customDimensions.rank)
| where rank > 0
| order by rank asc
```

### Paging depth

Deep paging usually means the ranking is not putting the right thing on page 1.

```kusto
customEvents
| where timestamp > ago(30d) and name == "search_performed"
| summarize searches = count() by page = toint(customDimensions.page)
| order by page asc
```

### Tour completion

```kusto
let tour = customEvents | where timestamp > ago(30d) and name startswith "tour_";
tour
| summarize
    started = countif(name == "tour_started"),
    completed = countif(name == "tour_completed"),
    dismissed = countif(name == "tour_dismissed")
| extend completion_rate = round(100.0 * completed / started, 1)
```

Where people give up:

```kusto
customEvents
| where timestamp > ago(30d) and name == "tour_dismissed"
| summarize count() by step = tostring(customDimensions.step)
| order by count_ desc
```

### Image search

```kusto
customEvents
| where timestamp > ago(30d)
| where name in ("image_search_performed", "image_search_abandoned", "image_search_state_lost")
| summarize count() by name, bin(timestamp, 1d)
| render timechart
```

`image_search_state_lost` fires when a refresh or deep link drops the stashed
upload — a dead end the server never sees, because no request is ever made.

Upload sizes, to sanity-check `MAX_UPLOAD_BYTES`:

```kusto
customEvents
| where timestamp > ago(30d) and name == "image_search_performed"
| summarize count() by bucket = tostring(customDimensions.upload_size)
| order by count_ desc
```

## Operational health

### Latency percentiles by endpoint

```kusto
requests
| where timestamp > ago(7d)
| summarize
    count(),
    p50 = percentile(duration, 50),
    p95 = percentile(duration, 95),
    p99 = percentile(duration, 99)
  by name
| order by p95 desc
```

Or from the events, which excludes blob streaming and so tracks the endpoints
users actually wait on:

```kusto
customEvents
| where timestamp > ago(7d) and tostring(customDimensions.origin) == "server"
| summarize
    p50 = percentile(toint(customDimensions.duration_ms), 50),
    p95 = percentile(toint(customDimensions.duration_ms), 95),
    p99 = percentile(toint(customDimensions.duration_ms), 99)
  by name
| order by p95 desc
```

### Failure rate

```kusto
requests
| where timestamp > ago(7d)
| summarize total = count(), failed = countif(success == false) by bin(timestamp, 1h)
| extend failure_rate = round(100.0 * failed / total, 2)
| render timechart
```

### Statement timeouts

`POSTGRES_STATEMENT_TIMEOUT_MS` surfaces as HTTP 504. A cluster of these means a
filter combination is missing an index.

```kusto
customEvents
| where timestamp > ago(7d) and toint(customDimensions.status_code) == 504
| summarize count() by name, filters = tostring(customDimensions.filters_used)
| order by count_ desc
```

### Slowest database calls

```kusto
dependencies
| where timestamp > ago(7d) and type has "postgres"
| summarize count(), p95 = percentile(duration, 95) by target, name
| order by p95 desc
| take 25
```

### Rate limiting and oversized uploads

```kusto
requests
| where timestamp > ago(7d) and resultCode in ("429", "413")
| summarize count() by resultCode, name, bin(timestamp, 1d)
| render timechart
```

### Client-side API failures

Errors the browser saw. Divergence from the server's own failure rate points at
the network path — proxy, TLS, or ingress — rather than the application.

```kusto
customEvents
| where timestamp > ago(7d) and name == "client_api_error"
| summarize count() by endpoint = tostring(customDimensions.endpoint), status = tostring(customDimensions.status)
| order by count_ desc
```

### Unhandled exceptions

```kusto
exceptions
| where timestamp > ago(7d)
| summarize count() by type, outerMessage
| order by count_ desc
```

## Cost control

Ingestion is billed per GB. Check what dominates before raising the daily cap
(`logsDailyQuotaGb`) or lowering `TELEMETRY_SAMPLING_RATIO`.

```kusto
union withsource = table *
| where timestamp > ago(7d)
| summarize gb = round(sum(_BilledSize) / 1024.0 / 1024 / 1024, 3) by table
| order by gb desc
```

## Notes

- Events are promoted into `customEvents` by the `microsoft.custom_event.name`
  attribute set in `analytics.build_record()`. If an event only shows up in
  `traces`, that attribute did not survive — check `build_record`.
- A client-supplied property whose name collides with a Python `LogRecord` field
  is prefixed with `prop_` (so `module` becomes `prop_module`).
- `total` is capped at 10,000, so `result_total` is a floor whenever
  `total_is_capped` is true. Do not average it without filtering those out.
- Client events are best-effort: a browser closed mid-flush loses the batch.
  Trust the server-derived events for anything that has to reconcile.
