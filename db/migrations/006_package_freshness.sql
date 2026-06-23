-- Migration 006: package freshness. A package is as fresh as its most recently seen
-- member parcel, so it can age out of the pipeline like a standalone lead.
-- Idempotent. (The sweep recomputes last_seen_at from members on each run.)
ALTER TABLE packages ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

UPDATE packages p
SET last_seen_at = (SELECT max(l.last_seen_at) FROM listings l WHERE l.package_id = p.id);
