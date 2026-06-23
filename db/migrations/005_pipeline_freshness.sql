-- Migration 005: pipeline freshness.
-- last_seen_at tracks the most recent time a deal was seen (ingested or re-seen via
-- dedup-enrich). A 'lead' whose last_seen_at is older than pipeline.active_lead_days
-- auto-demotes to status 'stale' (stays in the DB as a comp; v_pipeline already
-- excludes anything not in lead/underwriting/under_contract). Idempotent.
--
-- 'stale' joins the status lifecycle:
--   comp_only | lead | underwriting | under_contract | closed | withdrawn
--   | expired | dead | needs_review | stale

ALTER TABLE listings ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

-- Backfill: latest listing_history.changed_at for the row, else date_ingested.
UPDATE listings l
SET last_seen_at = COALESCE(
    (SELECT max(h.changed_at) FROM listing_history h WHERE h.listing_id = l.id),
    l.date_ingested)
WHERE l.last_seen_at IS NULL;

ALTER TABLE listings ALTER COLUMN last_seen_at SET DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings (last_seen_at);
