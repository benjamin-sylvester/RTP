-- Migration 015: core block, part 1. The properties spine (see db/DATA_MODEL.md, Block 1).
-- A property is one real building, forever; listings, entities and AM tables hang off it.
-- address_key mirrors ingest/dedup.py: house number (low end of a range) | street core without
-- the type suffix | city | state, all lowercase alphanumeric. Idempotent.

CREATE OR REPLACE FUNCTION rtp_normalize_address(addr text, city text, st text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN addr IS NULL OR city IS NULL OR st IS NULL
      OR btrim(addr) = '' OR btrim(city) = '' OR btrim(st) = ''
      OR addr ILIKE 'unknown%' OR city ILIKE 'unknown%' THEN NULL
    ELSE
      COALESCE(substring(btrim(addr) from '^\d+'), '') || '|' ||
      regexp_replace(
        regexp_replace(
          regexp_replace(lower(btrim(addr)), '^\d+[a-z]?(-\d+[a-z]?)?\s*', ''),
          '\m(st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|boulevard|way|ct|court|pl|place|ter|terrace|hwy|highway|cir|circle|sq|square)\M', '', 'g'),
        '[^a-z0-9]', '', 'g')
      || '|' || regexp_replace(lower(city), '[^a-z0-9]', '', 'g')
      || '|' || lower(btrim(st))
  END
$$;

CREATE TABLE IF NOT EXISTS properties (
  id                 SERIAL PRIMARY KEY,
  address            TEXT NOT NULL,
  city               TEXT NOT NULL,
  state              CHAR(2) NOT NULL,
  zip                TEXT,
  county             TEXT,
  address_key        TEXT GENERATED ALWAYS AS (rtp_normalize_address(address, city, state)) STORED,
  address_range_low  INTEGER GENERATED ALWAYS AS (
                       CASE WHEN substring(btrim(address) from '^\d{1,9}') IS NOT NULL
                            THEN substring(btrim(address) from '^\d{1,9}')::int END) STORED,
  latitude           NUMERIC(9,6),
  longitude          NUMERIC(9,6),
  parcel_id          TEXT,
  units              INTEGER,
  year_built         INTEGER,
  building_sf        INTEGER,
  lot_sf             INTEGER,
  property_class     TEXT CHECK (property_class IS NULL OR property_class IN ('A','B','C')),
  rtp_relationship   TEXT NOT NULL DEFAULT 'prospect'
                       CHECK (rtp_relationship IN ('prospect','owned','sold','passed')),
  owner_of_record    TEXT,
  owner_org_id       INTEGER,            -- FK to organizations added in 016
  drive_folder_id    TEXT,
  notes              TEXT,
  merged_into_id     INTEGER REFERENCES properties(id),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_properties_address_key
  ON properties (address_key) WHERE address_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_properties_city_state ON properties (state, city);

-- updated_at trigger (shared helper for all new tables)
CREATE OR REPLACE FUNCTION rtp_touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;
DROP TRIGGER IF EXISTS trg_properties_touch ON properties;
CREATE TRIGGER trg_properties_touch BEFORE UPDATE ON properties
  FOR EACH ROW EXECUTE FUNCTION rtp_touch_updated_at();

-- Backfill: one property per distinct address key in listings. Latest-seen listing supplies
-- the facts (Ben 10/12: latest data wins). Unresolvable addresses (Unknown, no city) are skipped.
INSERT INTO properties (address, city, state, zip, latitude, longitude, units, year_built,
                        building_sf, lot_sf, property_class, rtp_relationship, drive_folder_id)
SELECT DISTINCT ON (rtp_normalize_address(address, city, state))
       btrim(address), btrim(city), upper(btrim(state)), zip, latitude, longitude, units, year_built,
       building_sf, lot_sf,
       CASE WHEN upper(property_class) IN ('A','B','C') THEN upper(property_class) END,
       CASE WHEN status = 'owned' THEN 'owned' ELSE 'prospect' END,
       drive_folder_id
FROM listings
WHERE merged_into_id IS NULL
  AND rtp_normalize_address(address, city, state) IS NOT NULL
  AND length(btrim(state)) = 2
ORDER BY rtp_normalize_address(address, city, state), last_seen_at DESC NULLS LAST, id DESC
ON CONFLICT (address_key) WHERE address_key IS NOT NULL DO NOTHING;

-- Owned asset that never came through the ingest
INSERT INTO properties (address, city, state, units, rtp_relationship, drive_folder_id, notes)
SELECT '6 2nd St', 'Nashua', 'NH', 2, 'owned', '1rJntZ1sUE2WVgyLN3ymlmbO-0dNS0uk_',
       'Owned personally by Ben (FHA house hack, Oct 2021, $400,000). 2 units + garage. EJG manages on Buildium.'
WHERE NOT EXISTS (SELECT 1 FROM properties WHERE address_key = rtp_normalize_address('6 2nd St','Nashua','NH'));

-- Link listings to their property
ALTER TABLE listings ADD COLUMN IF NOT EXISTS property_id INTEGER REFERENCES properties(id);
CREATE INDEX IF NOT EXISTS idx_listings_property ON listings (property_id);
UPDATE listings l SET property_id = p.id
FROM properties p
WHERE l.property_id IS NULL
  AND p.address_key = rtp_normalize_address(l.address, l.city, l.state);

-- Likely-same buildings for manual review: same city, same street core, house numbers within 4
CREATE OR REPLACE VIEW v_duplicate_property_candidates AS
SELECT a.id AS property_a, a.address AS address_a, b.id AS property_b, b.address AS address_b,
       a.city, a.state
FROM properties a
JOIN properties b ON a.id < b.id
  AND a.state = b.state AND lower(a.city) = lower(b.city)
  AND split_part(a.address_key, '|', 2) = split_part(b.address_key, '|', 2)
  AND split_part(a.address_key, '|', 2) <> ''
  AND a.address_range_low IS NOT NULL AND b.address_range_low IS NOT NULL
  AND abs(a.address_range_low - b.address_range_low) <= 4
WHERE a.merged_into_id IS NULL AND b.merged_into_id IS NULL;

-- Every listing a property has generated (offers and entities join in later migrations)
CREATE OR REPLACE VIEW v_property_history AS
SELECT p.id AS property_id, p.address, p.city, p.state, p.rtp_relationship,
       l.id AS listing_id, l.status AS listing_status, l.source, l.date_ingested, l.last_seen_at,
       l.asking_price, l.sale_price, l.sale_date, l.units AS listing_units, l.broker_name
FROM properties p
LEFT JOIN listings l ON l.property_id = p.id
ORDER BY p.id, l.date_ingested;
