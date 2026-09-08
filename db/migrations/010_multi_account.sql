-- Migration 010: multi-account ingestion.
-- Tag each listing with the inbox that first ingested it. NULL = pre-multi-account
-- (the original personal inbox). Additive, nullable, idempotent.
--
-- Dedup is unaffected: it matches on address / MLS# across ALL accounts, so the
-- same deal arriving in a second inbox ENRICHES the existing row rather than
-- creating a duplicate (CLAUDE.md dedup rule). This column is informational —
-- it answers "which inbox is this deal flowing in through" for the dashboard and
-- for verifying the second inbox is actually contributing.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS account TEXT;
CREATE INDEX IF NOT EXISTS idx_listings_account ON listings (account);
