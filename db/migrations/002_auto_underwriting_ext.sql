-- Migration 002: extend auto_underwriting for Phase 2 scoring.
-- Adds score_confidence + tier, and lets a row target EITHER a standalone listing
-- OR a package (so package deals get scored on combined size). Adds a deal-level
-- pipeline view that surfaces score/tier/summary for listings AND packages.
-- Idempotent.

ALTER TABLE auto_underwriting ADD COLUMN IF NOT EXISTS score_confidence TEXT;  -- high|medium|low
ALTER TABLE auto_underwriting ADD COLUMN IF NOT EXISTS tier TEXT;              -- Priority|Watch|Pass
ALTER TABLE auto_underwriting ADD COLUMN IF NOT EXISTS package_id INTEGER REFERENCES packages(id) ON DELETE CASCADE;

-- listing_id was PK+NOT NULL; relax so a row can instead target a package.
ALTER TABLE auto_underwriting DROP CONSTRAINT IF EXISTS auto_underwriting_pkey;
ALTER TABLE auto_underwriting ALTER COLUMN listing_id DROP NOT NULL;

-- exactly one target (listing XOR package)
ALTER TABLE auto_underwriting DROP CONSTRAINT IF EXISTS au_one_target;
ALTER TABLE auto_underwriting ADD CONSTRAINT au_one_target
    CHECK ((listing_id IS NOT NULL) <> (package_id IS NOT NULL));

CREATE UNIQUE INDEX IF NOT EXISTS au_listing_uq ON auto_underwriting(listing_id) WHERE listing_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS au_package_uq ON auto_underwriting(package_id) WHERE package_id IS NOT NULL;

-- Deal-level pipeline: standalone leads + package leads, ranked by score.
-- (v_pipeline stays listings-only; this is the package-aware view.)
CREATE OR REPLACE VIEW v_pipeline_deals AS
SELECT d.deal_kind, d.deal_id, d.name, d.market, d.state, d.status,
       d.effective_units, d.effective_ask,
       au.score, au.tier, au.score_confidence, au.meets_buy_box, au.summary
FROM v_deals d
LEFT JOIN auto_underwriting au
       ON (d.deal_kind = 'listing' AND au.listing_id = d.deal_id)
       OR (d.deal_kind = 'package' AND au.package_id = d.deal_id)
WHERE d.status IN ('lead', 'underwriting', 'under_contract')
ORDER BY au.score DESC NULLS LAST;
