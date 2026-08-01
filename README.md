# ttb-cola-search
A Basic Web Application to Search TTB COLA Images & Characteristics

## Setup

### Prerequisites

- Python 3.13+ 
- [uv](https://docs.astral.sh/uv/) package manager
- MotherDuck account and database

### MotherDuck Configuration

This application connects to a MotherDuck hosted DuckDB database. You'll need to set up environment variables for authentication:

1. **Get your MotherDuck token** from [https://app.motherduck.com/](https://app.motherduck.com/)
   - Go to Settings → API Tokens
   - Create a new token or copy an existing one

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   ```

3. **Edit `.env` with your configuration:**
   ```env
   MOTHERDUCK_TOKEN=your_actual_token_here
   MOTHERDUCK_DATABASE=md:your_database_name
   ```

### Installation and Testing

```bash
# Install dependencies
uv sync

# Test your MotherDuck connection
uv run python test_motherduck.py

# Run the Streamlit app
uv run streamlit run cola_streamlit_app.py
```

### Environment Variables

- `MOTHERDUCK_TOKEN`: Your MotherDuck authentication token (required)
- `MOTHERDUCK_DATABASE`: Database connection string (default: `md:ttb_public_data`)

### Database Schema

The MotherDuck database should contain the following tables and views:

#### Core Tables:

- **`colas`** - Main COLA data with fields like:
  - `cola_id`, `brand_name`, `fanciful_name`, `origin`, `class_type`
  - `permit_num`, `serial_num`, `completed_date`
  - `origin_code`, `class_type_code`, `scraped_on`, `image_count_to_parse`

- **`cola_images`** - Image metadata:
  - `cola_id`, `file_name`, `local_path`, `img_type`, `dimensions_txt`
  - `width_px`, `height_px`, `scraped_on`

- **`cola_image_analysis`** - Image analysis results:
  - `cola_id`, `file_name`, `analysis_model`, `model_version`
  - `analysis_completed_on`, `metadata`

- **`image_analysis_items`** - Detailed analysis items:
  - `id`, `cola_id`, `file_name`, `analysis_model`
  - `analysis_item_type`, `text`, `model_confidence`, `bounding_box`
  - Types: `dense_caption`, `tag`, `object`, `text_block`

- **`cola_analysis`** - COLA-level analysis and violations:
  - `cola_id`, `analysis_model`, `analysis_type`, `model_version`
  - `analysis_completed_on`, `prompt`, `response`, `metadata`

#### Optimized Views (Required):

- **`vw_colas`** - Enhanced COLA view with pre-computed aggregates:
  - All `colas` fields plus computed fields like `ct_commodity`, `ct_source`
  - Pre-computed counts: `cola_analysis_count`, `cola_analysis_with_violations_count`
  - `parsed_image_count`, `downloaded_image_count`, `image_analysis_count`
  - URLs: `cola_details_url`, `cola_form_url`, `cola_internal_url`

- **`vw_cola_images`** - Image view with public URLs:
  - All `cola_images` fields plus `public_url` (derived from `local_path`)

- **`vw_cola_violations_list`** - Flattened violations view:
  - `cola_id`, violation details (`violation_comment`, `violation_type`, etc.)
  - Analysis metadata and brand/class type comparisons

### Application Features

The TTB COLA Data Explorer provides the following search and analysis capabilities:

#### Search & Filter Options:
- **Text Search**: Search across COLA IDs, brand names, permit numbers, image analysis data, and violation comments
- **Date Range**: Filter by COLA completion date
- **Origin & Class Type**: Multi-select dropdowns for geographic origin and beverage class
- **Image Filters**: Show only COLAs with downloaded images or image analysis data
- **Violation Filter**: Show only COLAs with regulatory violations detected

#### Data Display:
- **COLA Summary**: ID, permit info, brand names, origin, class type, completion date
- **Quick Stats**: Visual indicators for image count (📷) and violation count (⚠️)
- **External Links**: Direct links to TTB detail pages and form displays
- **Violation Details**: Type, group, and comment information with search highlighting
- **Image Analysis**: AI-generated captions, tags, objects, and text extraction with confidence scores

#### Performance Optimizations:
- Uses pre-computed database views for fast filtering
- Separate queries for images and violations to reduce load times
- Efficient batch loading of related data
- Smart search indexing across multiple data sources

### Image Handling

The application displays images using:
- **Public URLs**: Primary method using `vw_cola_images.public_url` 
- **Fallback Support**: Legacy local path handling for backwards compatibility

### Troubleshooting

#### Common Issues:

1. **Database Alias Error:**
   ```
   Failed to attach 'database.table': Database aliases are not yet supported by MotherDuck in workspace mode.
   ```
   See `MOTHERDUCK_TROUBLESHOOTING.md` for detailed solutions.

2. **Connection Issues:**
   - Verify your `MOTHERDUCK_TOKEN` is correct and not expired
   - Check the `MOTHERDUCK_DATABASE` name format
   - Ensure you have access permissions to the database

3. **Missing Tables/Views:**
   - Run `uv run python test_motherduck.py` to check database structure
   - Verify all required views (`vw_colas`, `vw_cola_images`, `vw_cola_violations_list`) exist
   - Check that the database contains the expected schema

4. **Performance Issues:**
   - Ensure database views are properly created and indexed
   - Check if pre-computed aggregates in `vw_colas` are up to date
   - Monitor query performance in MotherDuck console

5. **Image Loading:**
   - Verify `public_url` field is properly populated in `vw_cola_images`
   - Check image URL accessibility and CORS settings
   - Local images should be in the `data/` directory (legacy support)

#### Diagnostic Tools:

- **Connection Test:** `uv run python test_motherduck.py`
- **MotherDuck Console:** https://app.motherduck.com/
- **Troubleshooting Guide:** See `MOTHERDUCK_TROUBLESHOOTING.md`

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

