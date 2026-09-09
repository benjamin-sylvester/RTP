-- Migration 012: listing merge. Addressless duplicates of a real deal (same
-- property ingested without a house number, so dedup couldn't match them) get
-- merged_into_id pointing at the canonical listing. Merged rows are kept for
-- audit but hidden from the deal board, comps, and map. Idempotent.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS merged_into_id INTEGER REFERENCES listings(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_listings_merged ON listings (merged_into_id);

-- v_deal_board: exclude merged listings (the only change vs migration 009).
CREATE OR REPLACE VIEW v_deal_board AS
SELECT 'listing'::text AS deal_kind, l.id AS deal_id, l.address AS name,
       l.city AS market, l.state, l.status,
       l.units AS effective_units, l.asking_price AS effective_ask,
       l.price_per_unit, l.last_seen_at, l.listing_date,
       l.latitude, l.longitude,
       au.score, au.tier, au.score_confidence, au.meets_buy_box,
       l.broker_name, l.broker_email, l.source
FROM listings l
LEFT JOIN auto_underwriting au ON au.listing_id = l.id
WHERE l.package_id IS NULL AND l.merged_into_id IS NULL
UNION ALL
SELECT 'package'::text, p.id, p.name, p.market, p.state, p.status,
       COALESCE(p.total_units, SUM(lm.units)) AS effective_units,
       COALESCE(p.asking_price, SUM(lm.asking_price)) AS effective_ask,
       CASE WHEN COALESCE(p.total_units, SUM(lm.units)) > 0
            THEN (COALESCE(p.asking_price, SUM(lm.asking_price))
                  / COALESCE(p.total_units, SUM(lm.units)))::int END AS price_per_unit,
       p.last_seen_at, NULL::date,
       NULL::numeric, NULL::numeric,
       au.score, au.tier, au.score_confidence, au.meets_buy_box,
       p.broker_name, p.broker_email,
       CASE WHEN p.broker_email IS NOT NULL THEN 'broker_email' ELSE NULL END AS source
FROM packages p
LEFT JOIN listings lm ON lm.package_id = p.id
LEFT JOIN auto_underwriting au ON au.package_id = p.id
GROUP BY p.id, au.score, au.tier, au.score_confidence, au.meets_buy_box;
