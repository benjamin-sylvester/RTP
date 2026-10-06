-- Migration 013: executed-sale comps.
-- Closing announcements ("Just Sold", "Closing Announcement", "Just Closed") carry the
-- real transaction price. Store it beside the ask so the comp DB has both the list price
-- and the executed price. A sold deal is a comp (status comp_only) unless Ben manually
-- advanced it (sticky statuses are never changed by ingestion). Idempotent.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS sale_price BIGINT;            -- cents
ALTER TABLE listings ADD COLUMN IF NOT EXISTS sale_price_per_unit INTEGER;  -- cents
ALTER TABLE listings ADD COLUMN IF NOT EXISTS sale_date DATE;
CREATE INDEX IF NOT EXISTS idx_listings_sale_date ON listings (sale_date);

-- v_deal_board: sale columns appended at the END (CREATE OR REPLACE VIEW can only add
-- trailing columns). Otherwise identical to migration 012.
CREATE OR REPLACE VIEW v_deal_board AS
SELECT 'listing'::text AS deal_kind, l.id AS deal_id, l.address AS name,
       l.city AS market, l.state, l.status,
       l.units AS effective_units, l.asking_price AS effective_ask,
       l.price_per_unit, l.last_seen_at, l.listing_date,
       l.latitude, l.longitude,
       au.score, au.tier, au.score_confidence, au.meets_buy_box,
       l.broker_name, l.broker_email, l.source,
       l.sale_price, l.sale_price_per_unit, l.sale_date
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
       CASE WHEN p.broker_email IS NOT NULL THEN 'broker_email' ELSE NULL END AS source,
       NULL::bigint, NULL::int, NULL::date
FROM packages p
LEFT JOIN listings lm ON lm.package_id = p.id
LEFT JOIN auto_underwriting au ON au.package_id = p.id
GROUP BY p.id, au.score, au.tier, au.score_confidence, au.meets_buy_box;
