-- vw_colas: read-only view backing list, detail and facets.
-- Ports ct_commodity / ct_source derivation and joins parsed detail fields.
-- Applied to the pcr-dev and pcr-prod schemas; schemas without the base
-- tables (e.g. an empty pcr-prod) are skipped. Safe to re-run (CREATE OR REPLACE).
--
-- The view body is held as a template with a __SCHEMA__ token and re-created for
-- each schema. replace() is used instead of format() so the LIKE '%...%' patterns
-- are not mistaken for format placeholders; quote_ident() safely quotes the
-- hyphenated schema names.

DO $do$
DECLARE
    target_schema text;
    ddl_template  text := $view$
CREATE OR REPLACE VIEW __SCHEMA__.vw_colas AS
SELECT
    c.cola_id,
    c.permit_num,
    c.serial_num,
    c.brand_name,
    c.fanciful_name,
    c.origin_code,
    c.origin,
    c.class_type_code,
    c.class_type,
    c.completed_date,
    c.status_code,
    c.status,
    c.received_code,
    c.image_count_to_parse,
    c.scraped_on,

    CASE
        WHEN upper(c.class_type) LIKE '%WINE%'
          OR upper(c.class_type) LIKE '%CIDER%'
          OR upper(c.class_type) LIKE '%MEAD%'
          OR upper(c.class_type) LIKE '%SAKE%'
            THEN 'wine'
        WHEN upper(c.class_type) LIKE '%BEER%'
          OR upper(c.class_type) LIKE '%MALT BEV%'
          OR upper(c.class_type) LIKE '%ALE%'
          OR upper(c.class_type) LIKE '%PORTER%'
            THEN 'beer'
        WHEN c.class_type IS NULL OR btrim(c.class_type) = ''
            THEN 'unknown'
        ELSE 'distilled_spirits'
    END AS ct_commodity,

    CASE
        WHEN upper(c.origin) IN (
            'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
            'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
            'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
            'VA','WA','WV','WI','WY','DC','USA',
            'ALABAMA','ALASKA','ARIZONA','ARKANSAS','CALIFORNIA','COLORADO','CONNECTICUT',
            'DELAWARE','FLORIDA','GEORGIA','HAWAII','IDAHO','ILLINOIS','INDIANA','IOWA',
            'KANSAS','KENTUCKY','LOUISIANA','MAINE','MARYLAND','MASSACHUSETTS','MICHIGAN',
            'MINNESOTA','MISSISSIPPI','MISSOURI','MONTANA','NEBRASKA','NEVADA','NEW HAMPSHIRE',
            'NEW JERSEY','NEW MEXICO','NEW YORK','NORTH CAROLINA','NORTH DAKOTA','OHIO','OKLAHOMA',
            'OREGON','PENNSYLVANIA','RHODE ISLAND','SOUTH CAROLINA','SOUTH DAKOTA','TENNESSEE',
            'TEXAS','UTAH','VERMONT','VIRGINIA','WASHINGTON','WEST VIRGINIA','WISCONSIN','WYOMING',
            'DISTRICT OF COLUMBIA','AMERICAN')
            THEN 'domestic'
        WHEN upper(c.class_type) LIKE '%IMPORT%'
          OR upper(c.class_type) LIKE '%FOREIGN%'
            THEN 'import'
        WHEN c.origin IS NULL OR btrim(c.origin) = ''
            THEN 'unknown'
        ELSE 'import'
    END AS ct_source,

    'https://ttbonline.gov/colasonline/viewColaDetails.do?action=publicDisplaySearchBasic&ttbid='
        || c.cola_id AS cola_details_url,
    'https://ttbonline.gov/colasonline/viewColaDetails.do?action=publicFormDisplay&ttbid='
        || c.cola_id AS cola_form_url,

    -- Parsed detail fields (one-to-one)
    p.applicant_name,
    p.mailing_address,
    p.application_type,
    p.for_sale_in,
    p.bottle_capacity,
    p.vendor_code,
    p.formula,
    p.appelation      AS appellation,
    p.ttb_ct_description,
    p.grape_varietal,
    p.qualifications  AS parsed_qualifications,

    -- origin_flag (STUB): emoji flag keyed on origin_code. Foreign codes map to
    -- their country flag; domestic US-state codes (00-49) fall back to the US
    -- flag because individual US state flags are not representable as emoji
    -- (they would need image assets). Unmapped foreign codes (e.g. 4A, 5D, 6E)
    -- return NULL until the full TTB origin code list is researched/verified.
    -- New view columns must stay at the end (CREATE OR REPLACE VIEW rule).
    CASE
        WHEN c.origin_code ~ '^[0-4][0-9]$' THEN '🇺🇸'  -- 00-49: American / US states
        WHEN c.origin_code = '50' THEN '🇮🇹'  -- Italy
        WHEN c.origin_code = '51' THEN '🇫🇷'  -- France
        WHEN c.origin_code = '52' THEN '🇪🇸'  -- Spain
        WHEN c.origin_code = '53' THEN '🇩🇪'  -- Germany
        WHEN c.origin_code = '54' THEN '🇵🇹'  -- Portugal
        WHEN c.origin_code = '55' THEN '🇩🇰'  -- Denmark
        WHEN c.origin_code = '56' THEN '🇮🇱'  -- Israel
        WHEN c.origin_code = '57' THEN '🇬🇷'  -- Greece
        WHEN c.origin_code = '59' THEN '🇯🇵'  -- Japan
        WHEN c.origin_code = '5B' THEN '🇸🇪'  -- Sweden
        WHEN c.origin_code = '5H' THEN '🇮🇸'  -- Iceland
        WHEN c.origin_code = '62' THEN '🇦🇷'  -- Argentina
        WHEN c.origin_code = '63' THEN '🇦🇺'  -- Australia
        WHEN c.origin_code = '64' THEN '🇦🇹'  -- Austria
        WHEN c.origin_code = '65' THEN '🇧🇪'  -- Belgium
        WHEN c.origin_code = '67' THEN '🇧🇷'  -- Brazil
        WHEN c.origin_code = '68' THEN '🇧🇬'  -- Bulgaria
        WHEN c.origin_code = '69' THEN '🇨🇦'  -- Canada
        WHEN c.origin_code = '70' THEN '🇨🇱'  -- Chile
        WHEN c.origin_code = '72' THEN '🇨🇾'  -- Cyprus
        WHEN c.origin_code = '75' THEN '🇭🇺'  -- Hungary
        WHEN c.origin_code = '7H' THEN '🇬🇭'  -- Ghana
        WHEN c.origin_code = '81' THEN '🇲🇽'  -- Mexico
        WHEN c.origin_code = '83' THEN '🇳🇱'  -- Netherlands
        WHEN c.origin_code = '84' THEN '🇳🇿'  -- New Zealand
        WHEN c.origin_code = '86' THEN '🇷🇴'  -- Romania
        WHEN c.origin_code = '87' THEN '🇨🇭'  -- Switzerland
        WHEN c.origin_code = '8D' THEN '🇳🇦'  -- Namibia
        WHEN c.origin_code = '8F' THEN '🇵🇾'  -- Paraguay
        WHEN c.origin_code = '91' THEN '🇿🇦'  -- South Africa
        WHEN c.origin_code = '92' THEN '🇬🇧'  -- United Kingdom
        WHEN c.origin_code = '93' THEN '🇺🇾'  -- Uruguay
        WHEN c.origin_code = '95' THEN '🇻🇪'  -- Venezuela
        WHEN c.origin_code = '96' THEN '🇨🇳'  -- China
        WHEN c.origin_code = '99' THEN '🇵🇱'  -- Poland
        WHEN c.origin_code = '4U' THEN '🇬🇧'  -- Great Britain
        WHEN c.origin_code = '4W' THEN '🇫🇯'  -- Fiji
        WHEN c.origin_code = 'MC' THEN '🌍'   -- Multiple countries
        ELSE NULL
    END AS origin_flag
FROM __SCHEMA__.colas c
LEFT JOIN __SCHEMA__.cola_parsed_data p ON p.cola_id = c.cola_id;
$view$;
BEGIN
    FOREACH target_schema IN ARRAY ARRAY['pcr-dev', 'pcr-prod']
    LOOP
        -- Skip schemas that do not yet have the base tables (e.g. an empty
        -- pcr-prod). to_regclass returns NULL when the relation is absent.
        IF to_regclass(quote_ident(target_schema) || '.colas') IS NULL THEN
            RAISE NOTICE 'Skipping %.vw_colas: base table %.colas not found', target_schema, target_schema;
            CONTINUE;
        END IF;
        EXECUTE replace(ddl_template, '__SCHEMA__', quote_ident(target_schema));
        RAISE NOTICE 'Created view %.vw_colas', target_schema;
    END LOOP;
END
$do$;
