# ttb-cola-search

Search and browse TTB Certificate of Label Approval (COLA) records — by text,
by label content, and by image similarity.

## Architecture

| Layer | Stack |
| --- | --- |
| API | FastAPI, async psycopg 3 (`src/api`) |
| Database | Azure Database for PostgreSQL + pgvector |
| SPA | React 18 + Vite (`frontend/`), plain `fetch` |
| Images | Private Azure Blob Storage, streamed through the API |
| Embeddings | Pluggable provider (Gemini by default) |
| Hosting | One container on Azure Container Apps |

Text search uses Postgres full-text (`tsvector` + GIN); image similarity uses
pgvector HNSW over 768-dimension embeddings. The container serves the built SPA
and the API from the same origin, so production needs no CORS.

Postgres and Blob Storage are reached with Entra tokens via
`DefaultAzureCredential` — a user-assigned managed identity in Azure, your
`az login` session locally. No passwords or connection strings are stored.

## Project layout

```
src/api/            FastAPI app
  main.py           app factory, lifespan, SPA mount
  config.py         pydantic-settings (env / .env)
  db.py             async pool, Entra token auth, per-connection setup
  mappers.py        column lists, row -> model mapping, reference codes
  models.py         Pydantic response models (camelCase aliases)
  ratelimit.py      in-process sliding-window limiter
  routers/          health, reference, colas, search, images
  embedding/        provider registry + implementations
frontend/           Vite SPA
infra/              Bicep for Container Apps
docs/               schema definitions (pcr_schema.dbml is the source of truth)
tests/              pytest suite
```

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- Access to the Postgres database and blob container
- A Gemini API key, if image search should be enabled

## Local development

```bash
uv sync
cp .env.example .env      # fill in the values, then:
az login                  # required when POSTGRES_AUTH_METHOD=entra

uv run python run.py      # API on http://127.0.0.1:8000 (add --reload if wanted)
```

In a second shell:

```bash
cd frontend
npm install
npm run dev               # SPA on http://localhost:5173, proxies /api to :8000
```

Interactive API docs are at <http://127.0.0.1:8000/docs>.

> On Windows, always start the API through `run.py`. psycopg's async driver
> rejects the default `ProactorEventLoop`, and `run.py` installs the selector
> policy before uvicorn creates its loop. The same applies to any standalone
> script that opens the pool.

### Tests

```bash
uv run pytest
```

The suite covers the pure logic that is easy to break silently — SQL
placeholder/parameter alignment in the search filter builder, and rate-limiter
behaviour. It needs no database.

## Configuration

All settings are read from the environment or `.env` (case-insensitive). See
[`.env.example`](.env.example) for a documented starting point.

**Database**

| Variable | Default | Notes |
| --- | --- | --- |
| `POSTGRES_HOST` | — | required |
| `POSTGRES_DB` | — | required |
| `POSTGRES_USER` | — | required; the Entra principal when using token auth |
| `POSTGRES_PORT` | `5432` | |
| `POSTGRES_SCHEMA` | `public` | e.g. `pcr-dev`, `pcr-prod` |
| `POSTGRES_AUTH_METHOD` | `entra` | or `password` |
| `POSTGRES_PASSWORD` | — | ignored under `entra` |
| `POSTGRES_SSLMODE` | `verify-full` | do not weaken under token auth |
| `POSTGRES_SSLROOTCERT` | certifi bundle | |
| `POSTGRES_CONNECT_TIMEOUT` | `30` | |
| `POSTGRES_POOL_MIN` / `_MAX` | `1` / `16` | |
| `POSTGRES_STATEMENT_TIMEOUT_MS` | `15000` | per-statement ceiling; exceeding it returns HTTP 504 |

**Blob storage and embeddings**

| Variable | Default | Notes |
| --- | --- | --- |
| `BLOB_ACCOUNT_URL` / `BLOB_CONTAINER` | — | label image source |
| `EMBEDDING_PROVIDER` | `gemini` | |
| `EMBEDDING_MODEL` | `gemini-embedding-2` | |
| `EMBEDDING_DIM` | `768` | must match the `vector(n)` column |
| `GEMINI_API_KEY` | — | unset disables image search |

**API and limits**

| Variable | Default | Notes |
| --- | --- | --- |
| `API_TITLE` | `TTB COLA Search API` | |
| `CORS_ORIGINS` | `*` | unused in production (single-origin) |
| `SPA_DIR` | unset | path to `frontend/dist`; set in the container |
| `MAX_UPLOAD_BYTES` | `10485760` | image upload cap; over it returns HTTP 413 |
| `IMAGE_SEARCH_RATE_LIMIT` | `10` | image searches allowed per window, per client |
| `IMAGE_SEARCH_RATE_WINDOW_SECONDS` | `60` | over the limit returns HTTP 429 + `Retry-After` |
| `TRUST_FORWARDED_FOR` | `true` | set `false` if not behind a trusted reverse proxy |

`run.py` also honours `API_HOST` and `API_PORT`.

> The rate limiter keeps state in process, so the effective ceiling is the limit
> multiplied by the replica count. It exists to stop one client looping on the
> metered embedding call, not to enforce a precise global quota. `X-Forwarded-For`
> is only consulted when `TRUST_FORWARDED_FOR` is on, because clients can
> otherwise spoof it to reset their own bucket.

**Telemetry and analytics**

| Variable | Default | Notes |
| --- | --- | --- |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | unset | unset disables all export; Bicep injects it in Azure |
| `TELEMETRY_ENABLED` | `true` | master switch |
| `TELEMETRY_SAMPLING_RATIO` | `1.0` | traces only; analytics events are never sampled |
| `ANALYTICS_CAPTURE_QUERY_TEXT` | `false` | records raw `q` text when on — needs privacy sign-off |
| `ANALYTICS_SALT` | `""` | salt for the fallback visitor hash; treat as a secret |

See [Analytics](#analytics) for what is collected and how to query it.


## API endpoints

All routes are mounted under `/api`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness plus database and embedding-provider status |
| `GET` | `/reference` | Filter vocabularies (origins, statuses, categories, permit states); cached in process for 1 hour |
| `GET` | `/colas` | Paged, filtered, faceted search |
| `GET` | `/colas/{cola_id}` | Full COLA detail with images and label analysis |
| `GET` | `/colas/{cola_id}/similar` | Visually similar labels (pgvector ANN) |
| `GET` | `/colas/{cola_id}/images/{file_name}` | Streams a label image; `primary` resolves the front label |
| `POST` | `/search/image` | Reverse image search from an upload |
| `POST` | `/events` | Collects UI interaction events from the SPA; returns 204 |

Responses are camelCase. `GET /colas` accepts `q`, `ttbId`, `brand`, `fanciful`,
`applicant`, `permit`, `permitName`, `permitState`, `permitCity`, `submitter`,
`varietal`, `qualification`, `labelText`, `commodity`, `source`, `origin`,
`status`, `dateFrom`, `dateTo`, `sort`, `page`, `pageSize`, and `facets`.

### Search behaviour

A few semantics are worth knowing before writing queries against it:

- `q` is word- and phrase-based (`websearch_to_tsquery`), not substring — `cab`
  will not match `Cabernet`. It also probes `serial_num`, `permit_num`,
  `primary_permit_id`, and, for all-digit input, `cola_id`.
- `ttbId`, `permit`, and `submitter` match on **prefix**. Identifier input is
  upper-cased before comparison, since the supporting indexes compare bytes.
- `labelText` searches OCR text from the label images via `cola_search_ocr`.
- `total` is capped at 10,000. When the cap is hit, `totalIsCapped` is `true` and
  `total` should be read as a floor. `page` is capped at 500 — narrow the filters
  rather than paging deeper.
- Result ordering always includes `cola_id` as a tiebreaker, so pagination stays
  stable across ties.

## Data model

[`docs/pcr_schema.dbml`](docs/pcr_schema.dbml) is the source of truth.
The API reads a small number of objects:

- **`cola_search`** — a materialised, indexed copy of `vw_colas`, one row per
  COLA. Carries the generated `search_tsv` (weighted: brand/fanciful, then
  applicant/permit, then the rest), a `permits` jsonb rollup, and composite
  indexes pairing each facet column with `completed_date, cola_id`. The API never
  reads `vw_colas` directly — aggregating it per request does not scale.
- **`cola_search_ocr`** — per-COLA OCR text plus its own `ocr_tsv` GIN index,
  kept in a side table so the large text never rides along on list queries.
- **`cola_search_dirty`** — triggers on `colas` and its children push changed
  `cola_id`s here for the materialiser to drain.
- **`cola_images`** — image metadata plus `image_feature_vector` and
  `text_feature_vector` (`vector(768)`, HNSW/cosine), and the blob name used by
  the image proxy.
- **`ref_*`** — reference tables backing the `/reference` vocabularies.

Column selection is explicit (`SUMMARY_COLUMN_LIST` / `DETAIL_COLUMN_LIST` in
`mappers.py`) so list and vector queries never drag along the large jsonb
rollups or OCR text.

## Analytics

Usage and operational telemetry go to Application Insights (workspace-based, in
the same Log Analytics workspace as the container logs). There is **no browser
analytics SDK, no third-party script and no cookie** — everything is either
derived server-side or posted by the SPA to our own `POST /api/events`.

That shape was chosen deliberately. Search terms appear in the URL
(`/results?q=…`), so a page-view-based tracker would ship user-typed text to a
vendor as a side effect of the routing scheme.

**How it fits together**

| Piece | Role |
| --- | --- |
| `src/api/telemetry.py` | Configures Azure Monitor OpenTelemetry — requests, Postgres dependencies, logs |
| `src/api/analytics.py` | Shapes events; no I/O, so it is unit-testable |
| `_analytics` middleware in `main.py` | Emits one event per tracked API route |
| `src/api/routers/events.py` | Allowlisted collector for UI events the server cannot infer |
| `frontend/src/lib/analytics.js` | Batches client events, flushes on a timer and on tab hide |

Server-derived events (`search_performed`, `detail_viewed`, `similar_requested`,
`image_search_performed`) need no client cooperation, so they survive ad
blockers. Client events cover only interactions that produce no request —
opening the advanced panel, switching label faces, or following the outbound
COLA download link.

**What is recorded**

- Which filters were used, as *names* (`filters_used=brand,commodity`), plus the
  filter count, sort, page, page size, and result total.
- Values only for closed vocabularies (`commodity`, `source`, `origin`,
  `status`) — these are drawn from a fixed reference list.
- For free text: `has_query`, `query_length`, and `term_count` — the shape of the
  query, not its content.
- Latency, status code, and a session identifier.

**What is not recorded**

- The text typed into `q` or any other free-text field, unless
  `ANALYTICS_CAPTURE_QUERY_TEXT` is explicitly enabled.
- IP addresses. `DisableIpMasking` is left off in Bicep, so Azure masks them.
- Anything durable about a visitor. The session id comes from `sessionStorage`
  and dies with the tab; when the SPA cannot supply one, the fallback is a
  salted hash that becomes unlinkable as soon as `ANALYTICS_SALT` is rotated.

Health checks and image-blob requests are excluded from tracing
(`EXCLUDED_URLS`) — the blob proxy alone is one request per thumbnail and would
dominate ingestion cost while telling us nothing.

[`docs/analytics-queries.md`](docs/analytics-queries.md) has ready-made KQL for
the search funnel, zero-result rate, filter popularity, and latency percentiles.

> **Open question — DAP.** Federal public websites are generally expected to
> carry the GSA Digital Analytics Program tag (OMB M-23-22 / 21st Century IDEA).
> That is a third-party script and is *not* included here. Confirm with the web
> governance team whether this registry is in scope before launch.

## Troubleshooting

**`Psycopg cannot use the 'ProactorEventLoop'`** — the process started without
the Windows selector policy. Launch via `run.py`, or set
`asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` before
opening the pool in a standalone script.

**Authentication failures against Postgres** — confirm `az login` (locally) and
that `POSTGRES_USER` exactly matches the Entra principal granted access. In
Azure it must equal the managed identity name, `<namePrefix>-app-id`.

**`relation "cola_search" does not exist`** — the materialised search tables have
not been built in the target `POSTGRES_SCHEMA`.

**HTTP 504 from a search** — the query exceeded
`POSTGRES_STATEMENT_TIMEOUT_MS`. Usually a filter with no supporting index;
narrow the search or check the index coverage for that column.

**HTTP 429 from image search** — the per-client rate limit. Honour the
`Retry-After` header, or raise `IMAGE_SEARCH_RATE_LIMIT`.

**Image search returns 503** — the embedding provider is unavailable or
`GEMINI_API_KEY` is unset. The underlying error is logged rather than returned.

---

## Deployment to Azure Container Apps (GitHub Actions)

The app ships as a single container: a multi-stage build compiles the Vite SPA
(`frontend/`) and the FastAPI backend serves both the API (`/api/*`) and the
built SPA (single-origin) via `uvicorn`. At runtime it authenticates to Azure
Database for PostgreSQL (Entra token) and Blob Storage using a **user-assigned
managed identity** — no passwords or connection strings are stored. The image is
pulled from an **existing shared ACR** using registry admin credentials.

### What gets created (`infra/main.bicep`)

Log Analytics workspace, Container Apps managed environment, a user-assigned
managed identity, and the Container App itself (deployed into the existing
resource group). The ACR is **not** created — an existing registry is reused.
Adjust defaults in [`infra/main.parameters.json`](infra/main.parameters.json).

### One-time setup

The pipeline authenticates with a service principal (`azure/login` `creds:`) and
pulls images with the shared ACR's admin credentials, so no OIDC app or role
assignment is required — the SP just needs **Contributor** on the target
resource group.

1. **GitHub secrets** (Settings → Secrets and variables → Actions — these already
   exist at the organization level):
   - `AZURE_CREDENTIALS` — service principal JSON blob (the classic
     `az ad sp create-for-rbac --sdk-auth` output)
   - `ACR_PASSWORD` — admin password for the shared ACR (stored as a Container
     App secret for image pulls)
   - `GEMINI_API_KEY` — embedding provider key (optional; stored as a Container
     App secret). Leave unset to disable image/vector search.

2. **GitHub variables:**
   - `AZURE_RESOURCE_GROUP` — existing target resource group
     (e.g. `ttb-public-testing-resource-group`)
   - `ACR_LOGIN_SERVER` — e.g. `myregistry.azurecr.io`
   - `ACR_USERNAME` — ACR admin username
   - `PG_HOST`, `PG_PORT`, `PG_SSLMODE` — Postgres connection settings
   - `PG_DATABASE`, `PG_SCHEMA` — target database and schema (e.g.
     `ttb-public-cola-registry` / `pcr-prod`)
   - `PG_USER` — Entra principal the app logs in as. **Must equal the managed
     identity name** created by the infra deploy: `<namePrefix>-app-id`
     (e.g. `ttb-pcr-app-id`).

### Provision, then deploy

- **Provision (once / on infra changes):** run the **infra** workflow manually
  (Actions → *infra* → *Run workflow*). It deploys the Bicep into the existing
  resource group. The run summary prints the app URL and the managed identity
  name.

- **Grant the managed identity access** (one-time, after provisioning — the
  identity name is `<namePrefix>-app-id`, e.g. `ttb-pcr-app-id`):

  - **Postgres:** connect as an Entra admin and create a role for the identity,
    then grant it read access to the `pcr-prod` schema (this is the principal
    named in `POSTGRES_USER`).
  - **Blob:** assign **Storage Blob Data Reader** to the identity on the storage
    account / container holding the label images:

    ```bash
    az role assignment create \
      --assignee-object-id <identity principalId> --assignee-principal-type ServicePrincipal \
      --role "Storage Blob Data Reader" \
      --scope <storage account resource ID>
    ```

- **Deploy (automatic):** pushes to `main` that touch app code trigger the
  **deploy** workflow, which builds the image, pushes it to the shared ACR
  (`docker build`/`docker push`), and rolls it out (`az containerapp update`).
  You can also run it manually.

### Build/run the container locally (optional)

```bash
docker build -t ttb-cola-search .
docker run --rm -p 8000:8000 --env-file .env ttb-cola-search
# open http://localhost:8000  (SPA + API served single-origin)
```

Local runs authenticate via whatever `DefaultAzureCredential` finds (e.g. your
`az login`); in Azure it uses the user-assigned managed identity.

