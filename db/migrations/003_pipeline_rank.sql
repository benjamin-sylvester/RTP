-- Migration 003: rank the pipeline by tier, then score_confidence, then score.
-- A low-confidence high score (e.g. a thin-data deal that pencils to 100) must NOT
-- top the list above a better-supported deal. Idempotent (CREATE OR REPLACE).

CREATE OR REPLACE VIEW v_pipeline_deals AS
SELECT d.deal_kind, d.deal_id, d.name, d.market, d.state, d.status,
       d.effective_units, d.effective_ask,
       au.score, au.tier, au.score_confidence, au.meets_buy_box, au.summary
FROM v_deals d
LEFT JOIN auto_underwriting au
       ON (d.deal_kind = 'listing' AND au.listing_id = d.deal_id)
       OR (d.deal_kind = 'package' AND au.package_id = d.deal_id)
WHERE d.status IN ('lead', 'underwriting', 'under_contract')
ORDER BY
    CASE au.tier WHEN 'Priority' THEN 0 WHEN 'Watch' THEN 1 WHEN 'Pass' THEN 2 ELSE 3 END,
    CASE au.score_confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END,
    au.score DESC NULLS LAST;
