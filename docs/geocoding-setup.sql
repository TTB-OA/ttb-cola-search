-- Database prerequisites for the map / geocoding feature.
--
-- The API only reads. Everything created here is owned and populated by the
-- upstream geolocation pipeline; this file exists so the pieces the API depends
-- on can be checked, granted, or stubbed in an environment that does not have
-- the pipeline yet.
--
-- Run as a role that owns the schema. Substitute :schema and :api_role, e.g.
--   psql -v schema=public -v api_role='"ttb-cola-api"' -f docs/geocoding-setup.sql
--
-- Every statement is idempotent. Nothing here drops or rewrites data.

\set ON_ERROR_STOP on

-- psql variables cannot be read from inside a DO block, so they are also parked
-- in settings the block can look up.
SELECT set_config('map.schema', :'schema', false),
       set_config('map.api_role', :'api_role', false);

-- ---------------------------------------------------------------------------
-- 1. Extensions
-- ---------------------------------------------------------------------------
-- PostGIS backs the geography column and the viewport predicate. pg_trgm backs
-- the planned varietal substring filter.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- ---------------------------------------------------------------------------
-- 2. What the API expects to exist
-- ---------------------------------------------------------------------------
-- Run this first. Anything reported missing is upstream work, not an API bug.
SELECT
    obj AS relation,
    to_regclass(:'schema' || '.' || obj) IS NOT NULL AS present,
    CASE
        WHEN to_regclass(:'schema' || '.' || obj) IS NULL THEN NULL
        ELSE has_table_privilege(:api_role, :'schema' || '.' || obj, 'SELECT')
    END AS api_can_read
  FROM unnest(ARRAY[
        'cola_map_search',          -- viewport queries: /map/points, /map/area
        'cola_map_dirty',           -- map index queue depth on /coverage
        'geolocation_observation',  -- "queued for geocoding" on a COLA detail
        'geolocation_selection',    -- "resolved to a point" on a COLA detail
        'cola_coverage_year'        -- geocoding stage counts on /coverage
       ]) AS obj;

-- Columns the coverage page reads. A missing one blanks that stage rather than
-- erroring, so this is worth checking explicitly.
SELECT c.name AS column_name,
       EXISTS (
           SELECT 1 FROM information_schema.columns ic
            WHERE ic.table_schema = :'schema'
              AND ic.table_name = 'cola_coverage_year'
              AND ic.column_name = c.name
       ) AS present
  FROM unnest(ARRAY[
        'origin_geocoded_cola_count',
        'permit_geocoded_cola_count',
        'primary_permit_geocoded_cola_count'
       ]) AS c(name);


-- ---------------------------------------------------------------------------
-- 3. Grants
-- ---------------------------------------------------------------------------
-- The API connects as an Entra principal with no implicit rights. Granted one
-- table at a time, and only where the table exists, so this can be re-run at
-- any point during the upstream rollout.
DO $$
DECLARE
    rel text;
    api_role text := current_setting('map.api_role');
    target_schema text := current_setting('map.schema');
BEGIN
    FOREACH rel IN ARRAY ARRAY[
        'cola_map_search',
        'cola_map_dirty',
        'geolocation_observation',
        'geolocation_selection',
        'geolocation_target',
        'geolocation_result'
    ] LOOP
        IF to_regclass(target_schema || '.' || rel) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON %I.%I TO %s', target_schema, rel, api_role);
            RAISE NOTICE 'granted SELECT on %', rel;
        ELSE
            RAISE NOTICE 'skipped % (does not exist yet)', rel;
        END IF;
    END LOOP;
END $$;

-- So a later pipeline rebuild does not silently drop the API's access.
ALTER DEFAULT PRIVILEGES IN SCHEMA :schema GRANT SELECT ON TABLES TO :api_role;

-- PostGIS installs into whichever schema it was created in; the API's
-- search_path must reach it or ST_MakeEnvelope resolves to nothing.
GRANT USAGE ON SCHEMA :schema TO :api_role;


-- ---------------------------------------------------------------------------
-- 4. Map surface (upstream-owned; here as the contract the API reads)
-- ---------------------------------------------------------------------------
-- One row per COLA per location, not per COLA: a COLA with three permits and a
-- product origin contributes four points, and the API always constrains
-- location_role so a record is never counted more than once in a viewport.
CREATE TABLE IF NOT EXISTS cola_map_search (
    cola_id              text        NOT NULL,
    location_role        varchar     NOT NULL,  -- primary_premise | permit_premise | product_origin
    source_key           varchar     NOT NULL,  -- permit_id or origin_code
    target_kind          varchar     NOT NULL,
    normalizer_version   varchar     NOT NULL,
    target_key           char(64)    NOT NULL,
    result_id            bigint      NOT NULL,
    location             geography(POINT, 4326) NOT NULL,
    latitude             double precision NOT NULL,
    longitude            double precision NOT NULL,
    geolocation_provider varchar     NOT NULL,
    geolocation_quality  varchar     NOT NULL,
    geolocation_method   varchar,
    ct_commodity         text,
    ct_source            text,
    class_type_code      varchar,
    class_type           text,
    origin_code          varchar,
    origin               text,
    completed_date       date,
    application_date     date,
    permit_id            varchar,
    permit_name          text,
    best_image_file_name varchar,
    best_image_blob_url  text,
    best_image_score     numeric,
    _loaded_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cola_id, location_role, source_key)
);

-- Every viewport query starts here; without it a pan is a sequential scan and
-- hits the statement timeout.
CREATE INDEX IF NOT EXISTS cola_map_search_location_gix
    ON cola_map_search USING gist (location);

-- Each filter is paired with completed_date because image mode orders by it.
CREATE INDEX IF NOT EXISTS cola_map_search_role_date_ix
    ON cola_map_search (location_role, completed_date);
CREATE INDEX IF NOT EXISTS cola_map_search_commodity_date_ix
    ON cola_map_search (ct_commodity, completed_date);
CREATE INDEX IF NOT EXISTS cola_map_search_source_date_ix
    ON cola_map_search (ct_source, completed_date);
CREATE INDEX IF NOT EXISTS cola_map_search_class_date_ix
    ON cola_map_search (class_type_code, completed_date);
CREATE INDEX IF NOT EXISTS cola_map_search_origin_date_ix
    ON cola_map_search (origin_code, completed_date);
CREATE INDEX IF NOT EXISTS cola_map_search_quality_date_ix
    ON cola_map_search (geolocation_quality, completed_date);

CREATE TABLE IF NOT EXISTS cola_map_dirty (
    cola_id   text        PRIMARY KEY,
    marked_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cola_map_dirty_marked_ix
    ON cola_map_dirty (marked_at, cola_id);


-- ---------------------------------------------------------------------------
-- 5. Varietal filter (not yet enabled)
-- ---------------------------------------------------------------------------
-- Until this column exists, GET /map/points reports varietalAvailable=false, the
-- UI hides the control, and an explicit ?varietal= is rejected with 400 rather
-- than silently ignored. Adding the column is all that is needed to turn it on;
-- the upstream materialisation must then populate it the same way cola_search
-- does, as a joined list of vartl_name.
--
-- ALTER TABLE cola_map_search ADD COLUMN IF NOT EXISTS grape_varietal text;
-- CREATE INDEX IF NOT EXISTS cola_map_search_varietal_trgm_ix
--     ON cola_map_search USING gin (grape_varietal gin_trgm_ops);


-- ---------------------------------------------------------------------------
-- 6. Verify
-- ---------------------------------------------------------------------------
-- Re-run section 2. Then, as the API role, confirm a viewport query plans
-- against the GiST index rather than a sequential scan:
--
-- EXPLAIN (COSTS OFF)
-- SELECT count(*) FROM cola_map_search
--  WHERE location && ST_MakeEnvelope(-125, 32, -114, 42, 4326)::geography
--    AND location_role = 'primary_premise';
