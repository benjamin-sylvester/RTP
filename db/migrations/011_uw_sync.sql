-- Migration 011: daily UW-model sync.
-- Links a deal to its Drive underwriting folder and stores the metrics pulled
-- from its latest model. Additive, idempotent.
--
-- listings.uw_folder  = the deal's folder name under "2.0 Underwriting"
--   (e.g. 'NH, Manchester - Lakeside Landing'). The sync globs
--   <UW_ROOT>/<uw_folder>/4.0 Investment Analysis/*.xlsx and takes the latest.
-- auto_underwriting.model_* = provenance + the extracted figures. model_stats
--   holds every labeled value the extractor found (audit); the typed columns
--   (implied_cap_*, estimated_irr_5yr, estimated_dscr) get the mapped subset.
ALTER TABLE listings          ADD COLUMN IF NOT EXISTS uw_folder       TEXT;
ALTER TABLE auto_underwriting ADD COLUMN IF NOT EXISTS model_file      TEXT;
ALTER TABLE auto_underwriting ADD COLUMN IF NOT EXISTS model_version   TEXT;
ALTER TABLE auto_underwriting ADD COLUMN IF NOT EXISTS model_modified  TIMESTAMPTZ;
ALTER TABLE auto_underwriting ADD COLUMN IF NOT EXISTS model_synced_at TIMESTAMPTZ;
ALTER TABLE auto_underwriting ADD COLUMN IF NOT EXISTS model_stats     JSONB;
