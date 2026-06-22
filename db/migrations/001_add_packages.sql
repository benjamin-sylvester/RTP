-- Migration 001: package / portfolio grouping
-- Many RTP deals are multi-building packages sold together (e.g. 377/379/383 Manchester St
-- = one 9-unit deal across three 3-unit parcels; Downtown 3 Pack; Rochester 2 Pack;
-- Hampton Beach 4-property; Tim Baxter Portfolio). Buy box must evaluate on the COMBINED
-- unit count, not per parcel. This adds a deal-level grouping above listings.
-- Idempotent: safe to run once on the live Phase 0 database.

-- A package is one deal made of multiple listings (parcels).
CREATE TABLE IF NOT EXISTS packages (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,            -- e.g. "377-383 Manchester St (9-unit pkg)"
    market          TEXT,
    state           TEXT,
    status          TEXT NOT NULL DEFAULT 'comp_only',
                    -- comp_only | lead | underwriting | under_contract | closed | withdrawn | dead
    asking_price    BIGINT,                   -- cents; package-level ask if quoted as a whole
    total_units     INTEGER,                  -- override; else computed from member parcels
    broker_name     TEXT,
    broker_email    TEXT,
    drive_folder_id TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Link listings (parcels) to their package. NULL = standalone single-property deal.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS package_id INTEGER REFERENCES packages(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_listings_package ON listings (package_id);

-- Deal-level view: standalone listings + rolled-up packages, with effective unit count
-- and effective ask used for buy-box evaluation.
CREATE OR REPLACE VIEW v_deals AS
-- standalone single-property deals
SELECT
    'listing'::text             AS deal_kind,
    l.id                        AS deal_id,
    l.address                   AS name,
    l.city                      AS market,
    l.state,
    l.status,
    l.units                     AS effective_units,
    l.asking_price              AS effective_ask
FROM listings l
WHERE l.package_id IS NULL
UNION ALL
-- packages rolled up from member parcels
SELECT
    'package'::text             AS deal_kind,
    p.id                        AS deal_id,
    p.name,
    p.market,
    p.state,
    p.status,
    COALESCE(p.total_units, SUM(l.units))           AS effective_units,
    COALESCE(p.asking_price, SUM(l.asking_price))   AS effective_ask
FROM packages p
LEFT JOIN listings l ON l.package_id = p.id
GROUP BY p.id, p.name, p.market, p.state, p.status, p.total_units, p.asking_price;

-- NOTE for the underwriter (Phase 2): run the buy-box unit-count test against
-- v_deals.effective_units (floor = 4, max = 34 from buy_box.yaml), NOT listings.units,
-- so packages are judged on combined size.
