-- Migration 018: operations block. job_runs, job_schedule, review_queue, v_jobs_missing
-- (db/DATA_MODEL.md Block 6). Every scheduled job must prove it ran. Idempotent.

CREATE TABLE IF NOT EXISTS job_schedule (
  job             TEXT PRIMARY KEY,
  expected_every  INTERVAL NOT NULL,
  grace           INTERVAL NOT NULL DEFAULT '1 hour',
  enabled         BOOLEAN NOT NULL DEFAULT true,
  notes           TEXT
);
INSERT INTO job_schedule (job, expected_every, grace, notes) VALUES
  ('ingest',        '15 minutes', '2 hours',  'RTP-INGEST cron, both inboxes'),
  ('daily_job',     '1 day',      '3 hours',  'RTP-BRIEFING cron: uw_sync then the exceptions note'),
  ('uw_sync',       '1 day',      '3 hours',  'Drive model metrics -> auto_underwriting / uw_model_versions'),
  ('backup',        '7 days',     '1 day',    'scripts/backup_db.py to the Drive'),
  ('tracker_export','1 day',      '6 hours',  'relationship tracker xlsx regenerated from the DB (P1)')
ON CONFLICT (job) DO NOTHING;

CREATE TABLE IF NOT EXISTS job_runs (
  id           SERIAL PRIMARY KEY,
  job          TEXT NOT NULL,
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  status       TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','warn','error')),
  counts       JSONB,
  message      TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_runs_job_time ON job_runs (job, started_at DESC);

CREATE OR REPLACE VIEW v_jobs_missing AS
SELECT s.job, s.expected_every, s.grace,
       (SELECT max(finished_at) FROM job_runs r WHERE r.job = s.job AND r.status IN ('ok','warn')) AS last_ok,
       (SELECT status FROM job_runs r WHERE r.job = s.job ORDER BY started_at DESC LIMIT 1) AS last_status
FROM job_schedule s
WHERE s.enabled
  AND COALESCE((SELECT max(finished_at) FROM job_runs r WHERE r.job = s.job AND r.status IN ('ok','warn')),
               '1970-01-01'::timestamptz) < now() - s.expected_every - s.grace;

CREATE TABLE IF NOT EXISTS review_queue (
  id           SERIAL PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('listing_needs_review','unmapped_gl_account','unmatched_email',
                                             'parse_failure','duplicate_property','scraper_error',
                                             'model_sync_error','import_conflict','other')),
  ref_table    TEXT,
  ref_id       INTEGER,
  payload      JSONB,
  status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at  TIMESTAMPTZ,
  resolution   TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_queue_open ON review_queue (status, kind);
CREATE UNIQUE INDEX IF NOT EXISTS ux_review_queue_open_ref ON review_queue (kind, ref_table, ref_id)
  WHERE status = 'open' AND ref_table IS NOT NULL AND ref_id IS NOT NULL;

-- Mirror the current needs_review listings into the queue (the status stays until the Inbox tab ships)
INSERT INTO review_queue (kind, ref_table, ref_id, payload)
SELECT 'listing_needs_review', 'listings', l.id,
       jsonb_build_object('address', l.address, 'city', l.city, 'state', l.state, 'units', l.units,
                          'asking_price', l.asking_price, 'source', l.source)
FROM listings l
WHERE l.status = 'needs_review'
ON CONFLICT DO NOTHING;
