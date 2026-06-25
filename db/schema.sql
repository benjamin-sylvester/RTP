-- RTP Deal Intelligence: Database Schema
-- PostgreSQL 16 (no PostGIS on Railway's default image)
-- Run order: function/extension -> tables -> indexes -> views
-- One database is both the Sale Comp DB (all rows) and the Pipeline (status subset).

-- NOTE: Railway's default Postgres image does NOT ship PostGIS. We use plain
-- latitude/longitude columns + a Haversine distance function (works on vanilla
-- Postgres, fine at RTP's scale). To upgrade to true PostGIS later: redeploy the
-- service on the postgis/postgis image, then migrate lat/long into a GEOGRAPHY point.
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;  -- for address dedup

-- Haversine great-circle distance in miles between two lat/long points.
CREATE OR REPLACE FUNCTION haversine_miles(lat1 numeric, lon1 numeric, lat2 numeric, lon2 numeric)
RETURNS numeric AS $$
  SELECT 3958.7613 * 2 * asin(sqrt(
    power(sin(radians((lat2 - lat1) / 2)), 2) +
    cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians((lon2 - lon1) / 2)), 2)
  ));
$$ LANGUAGE sql IMMUTABLE;

-- =====================================================================
-- listings: master table. One row per unique property listing.
--   Sale Comp DB  = every row.
--   Pipeline      = rows where status IN ('lead','underwriting','under_contract').
--   Comp only     = status = 'comp_only' (logged, never clutters pipeline).
-- =====================================================================
CREATE TABLE listings (
    id              SERIAL PRIMARY KEY,
    external_id     TEXT UNIQUE,                 -- MLS number / source listing id (dedup)
    address         TEXT NOT NULL,
    city            TEXT NOT NULL,
    state           TEXT NOT NULL,
    zip             TEXT,
    latitude        NUMERIC(9,6),                -- geocoded; radius via haversine_miles()
    longitude       NUMERIC(9,6),
    units           INTEGER,
    asking_price    BIGINT,                      -- cents, avoid float rounding
    price_per_unit  INTEGER,                     -- computed: asking_price / units
    year_built      INTEGER,
    building_sf     INTEGER,
    lot_sf          INTEGER,
    property_class  TEXT,                         -- A, B, C
    status          TEXT NOT NULL DEFAULT 'comp_only',
                    -- STATUS_MODEL.md: comp_only | lead | underwriting | loi_sent | under_contract
                    --   | lost | passed  (+ needs_review = system quarantine).
                    -- System auto-moves ONLY comp_only<->lead; the rest are manual + sticky.
                    -- Activeness is by last_seen_at within active_lead_days (no 'stale' status).
    source          TEXT NOT NULL,                -- mls_export | broker_email | costar | manual
    broker_name     TEXT,
    broker_email    TEXT,
    listing_date    DATE,
    date_ingested   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    days_on_market  INTEGER,
    raw_email_id    TEXT,                         -- gmail thread/message id
    raw_data        JSONB,                        -- full unstructured parser output (audit)
    -- Drive document pointers (the structured<->document bridge)
    drive_folder_id TEXT,
    om_url          TEXT,
    boe_url         TEXT,
    notes           TEXT
);

-- =====================================================================
-- listing_financials: one row per listing. From rent rolls, T-12s, OMs.
-- =====================================================================
CREATE TABLE listing_financials (
    listing_id              INTEGER PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    gross_revenue           BIGINT,           -- annual gross scheduled rent (cents)
    vacancy_rate            NUMERIC(5,4),
    effective_gross_income  BIGINT,
    total_expenses          BIGINT,
    expense_ratio           NUMERIC(5,4),
    noi                     BIGINT,
    cap_rate                NUMERIC(5,4),
    avg_rent_per_unit       INTEGER,
    taxes                   BIGINT,
    insurance               BIGINT,
    utilities               BIGINT,
    data_source             TEXT,             -- t12 | rent_roll | om | broker
    confidence              TEXT              -- high | medium | low
);

-- =====================================================================
-- unit_mix: one row per unit type per listing.
-- =====================================================================
CREATE TABLE unit_mix (
    id              SERIAL PRIMARY KEY,
    listing_id      INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    unit_type       TEXT,                     -- Studio, 1BR, 2BR, 3BR ...
    count           INTEGER,
    avg_sf          INTEGER,
    avg_rent        INTEGER,                  -- in-place
    market_rent     INTEGER,                  -- from rent_comps
    rent_delta_pct  NUMERIC(5,4)
);

-- =====================================================================
-- auto_underwriting: one row per listing. System-generated quick screen.
-- =====================================================================
CREATE TABLE auto_underwriting (
    listing_id                  INTEGER PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    meets_buy_box               BOOLEAN,
    buy_box_flags               JSONB,        -- which criteria passed/failed and why
    implied_cap_current         NUMERIC(5,4),
    implied_cap_stabilized      NUMERIC(5,4),
    price_per_unit_vs_market    NUMERIC(5,4),
    rent_upside_pct             NUMERIC(5,4),
    estimated_dscr              NUMERIC(5,3),
    estimated_irr_5yr           NUMERIC(5,4),
    score                       INTEGER,       -- composite 0-100
    summary                     TEXT,          -- AI-generated one-paragraph
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================================
-- rent_comps: market rent observations by market and unit type.
--   Sources: rent rolls shared with RTP + weekly Zillow scan.
--   Feeds BOE market-rent assumptions and stabilized cap.
-- =====================================================================
CREATE TABLE rent_comps (
    id                SERIAL PRIMARY KEY,
    market            TEXT NOT NULL,          -- normalized city/submarket
    address           TEXT,
    latitude          NUMERIC(9,6),
    longitude         NUMERIC(9,6),
    unit_type         TEXT,                   -- Studio, 1BR, 2BR, 3BR
    beds              INTEGER,
    baths             NUMERIC(3,1),
    sqft              INTEGER,
    rent              INTEGER,                -- monthly, dollars
    source            TEXT NOT NULL,          -- rent_roll | zillow | costar | manual
    source_listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    observed_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    raw_data          JSONB
);

-- =====================================================================
-- listing_history: price/status changes over time (trend + motivated seller).
-- =====================================================================
CREATE TABLE listing_history (
    id              SERIAL PRIMARY KEY,
    listing_id      INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    field           TEXT NOT NULL,            -- asking_price | status | ...
    old_value       TEXT,
    new_value       TEXT
);

-- =====================================================================
-- broker_format_config: per-broker MLS export column mappings.
-- =====================================================================
CREATE TABLE broker_format_config (
    id              SERIAL PRIMARY KEY,
    broker_key      TEXT UNIQUE NOT NULL,     -- e.g. mlspin, primemls, porter, candor, northeast_pcg
    display_name    TEXT,
    field_map       JSONB NOT NULL,           -- {"address":"STREET_ADDRESS",...}
    notes           TEXT
);

-- =====================================================================
-- Indexes
-- =====================================================================
CREATE INDEX idx_listings_latlng     ON listings (latitude, longitude);
CREATE INDEX idx_listings_status     ON listings (status);
CREATE INDEX idx_listings_city_state ON listings (city, state);
CREATE INDEX idx_listings_units      ON listings (units);
CREATE INDEX idx_listings_ingested   ON listings (date_ingested);
CREATE INDEX idx_rentcomps_latlng    ON rent_comps (latitude, longitude);
CREATE INDEX idx_rentcomps_market    ON rent_comps (market, unit_type, observed_date);
CREATE INDEX idx_unitmix_listing     ON unit_mix (listing_id);

-- =====================================================================
-- Convenience views
-- =====================================================================
CREATE VIEW v_pipeline AS
SELECT l.*, au.score, au.summary, au.meets_buy_box
FROM listings l
LEFT JOIN auto_underwriting au ON au.listing_id = l.id
WHERE l.status IN ('lead','underwriting','under_contract');

CREATE VIEW v_sale_comps AS
SELECT l.id, l.address, l.city, l.state, l.units, l.asking_price,
       l.price_per_unit, l.year_built, l.status, l.listing_date, l.days_on_market,
       lf.cap_rate, lf.avg_rent_per_unit
FROM listings l
LEFT JOIN listing_financials lf ON lf.listing_id = l.id;
