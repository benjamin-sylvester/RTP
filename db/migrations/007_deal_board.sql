-- Migration 007: v_deal_board — the dashboard's read model. One row per DEAL
-- (standalone listing OR package), package-aware, joined to its auto_underwriting
-- score/tier/confidence, plus the fields the table needs (ppu, last_seen, lat/long).
-- All statuses (the dashboard filters/toggles decide what to show). Idempotent.
CREATE OR REPLACE VIEW v_deal_board AS
SELECT 'listing'::text AS deal_kind, l.id AS deal_id, l.address AS name,
       l.city AS market, l.state, l.status,
       l.units AS effective_units, l.asking_price AS effective_ask,
       l.price_per_unit, l.last_seen_at, l.listing_date,
       l.latitude, l.longitude,
       au.score, au.tier, au.score_confidence, au.meets_buy_box
FROM listings l
LEFT JOIN auto_underwriting au ON au.listing_id = l.id
WHERE l.package_id IS NULL
UNION ALL
SELECT 'package'::text, p.id, p.name, p.market, p.state, p.status,
       COALESCE(p.total_units, SUM(lm.units)) AS effective_units,
       COALESCE(p.asking_price, SUM(lm.asking_price)) AS effective_ask,
       CASE WHEN COALESCE(p.total_units, SUM(lm.units)) > 0
            THEN (COALESCE(p.asking_price, SUM(lm.asking_price))
                  / COALESCE(p.total_units, SUM(lm.units)))::int END AS price_per_unit,
       p.last_seen_at, NULL::date,
       NULL::numeric, NULL::numeric,
       au.score, au.tier, au.score_confidence, au.meets_buy_box
FROM packages p
LEFT JOIN listings lm ON lm.package_id = p.id
LEFT JOIN auto_underwriting au ON au.package_id = p.id
GROUP BY p.id, au.score, au.tier, au.score_confidence, au.meets_buy_box;
