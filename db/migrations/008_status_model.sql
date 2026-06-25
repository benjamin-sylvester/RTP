-- Migration 008: adopt the STATUS_MODEL.md lifecycle.
-- Statuses: comp_only | lead | underwriting | loi_sent | under_contract | lost | passed
--   (+ needs_review = system quarantine, kept). 'dead'/'stale' retired.
-- Activeness is by last_seen_at within pipeline.active_lead_days (app layer), NOT a 'stale'
-- status — so the lead->stale sweep is gone. Idempotent.

UPDATE listings SET status='passed' WHERE status='dead';
UPDATE listings SET status='lead'   WHERE status='stale';
UPDATE packages SET status='passed' WHERE status='dead';
UPDATE packages SET status='lead'   WHERE status='stale';

-- active pipeline status set now includes loi_sent (date-activeness applied in app)
DROP VIEW IF EXISTS v_pipeline;
CREATE VIEW v_pipeline AS
SELECT l.*, au.score, au.summary, au.meets_buy_box
FROM listings l
LEFT JOIN auto_underwriting au ON au.listing_id = l.id
WHERE l.status IN ('lead', 'underwriting', 'loi_sent', 'under_contract');

CREATE OR REPLACE VIEW v_pipeline_deals AS
SELECT d.deal_kind, d.deal_id, d.name, d.market, d.state, d.status,
       d.effective_units, d.effective_ask,
       au.score, au.tier, au.score_confidence, au.meets_buy_box, au.summary
FROM v_deals d
LEFT JOIN auto_underwriting au
       ON (d.deal_kind = 'listing' AND au.listing_id = d.deal_id)
       OR (d.deal_kind = 'package' AND au.package_id = d.deal_id)
WHERE d.status IN ('lead', 'underwriting', 'loi_sent', 'under_contract')
ORDER BY
    CASE au.tier WHEN 'Priority' THEN 0 WHEN 'Watch' THEN 1 WHEN 'Pass' THEN 2 ELSE 3 END,
    CASE au.score_confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END,
    au.score DESC NULLS LAST;
