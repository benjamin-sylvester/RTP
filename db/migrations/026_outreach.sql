-- Migration 026 (11/3/26): LP cold outreach tracking. Ben builds a list of investors he doesn't
-- know yet (LinkedIn first) before there is a deal; see capital/cold-outreach-playbook-v01.md.
-- Four columns on people plus two views. Each stage change is also an interactions row with
-- source 'outreach' and source_id '<person_id>:<stage>', which is what the weekly funnel counts.
-- relationship_established_on is the 506(b) record: date of the first substantive conversation.
-- The likely check size reuses people.lp_indicated_cents. Idempotent.

ALTER TABLE people ADD COLUMN IF NOT EXISTS outreach_segment TEXT;
ALTER TABLE people ADD COLUMN IF NOT EXISTS outreach_stage TEXT;
ALTER TABLE people ADD COLUMN IF NOT EXISTS accredited TEXT;
ALTER TABLE people ADD COLUMN IF NOT EXISTS relationship_established_on DATE;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'people_outreach_segment_check') THEN
    ALTER TABLE people ADD CONSTRAINT people_outreach_segment_check CHECK (outreach_segment IS NULL OR outreach_segment IN
      ('practice_owner', 'trades_owner', 'passive_investor', 'lp_referral', 'other'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'people_outreach_stage_check') THEN
    ALTER TABLE people ADD CONSTRAINT people_outreach_stage_check CHECK (outreach_stage IS NULL OR outreach_stage IN
      ('sourced', 'requested', 'connected', 'conversation', 'call_held', 'nurture', 'closed'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'people_accredited_check') THEN
    ALTER TABLE people ADD CONSTRAINT people_accredited_check CHECK (accredited IS NULL OR accredited IN
      ('yes', 'likely', 'no', 'unknown'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_people_outreach_stage ON people (outreach_stage) WHERE outreach_stage IS NOT NULL;

-- Everyone in outreach, with where they stand and what's next.
CREATE OR REPLACE VIEW v_outreach_pipeline AS
SELECT p.id AS person_id, p.full_name, p.title, o.name AS organization, p.city, p.state, p.linkedin_url,
       p.outreach_segment, p.outreach_stage, p.accredited, p.lp_indicated_cents, p.relationship_established_on,
       (SELECT max(i.occurred_at) FROM interactions i WHERE i.person_id = p.id) AS last_interaction,
       (SELECT i.summary FROM interactions i WHERE i.person_id = p.id ORDER BY i.occurred_at DESC, i.id DESC LIMIT 1) AS last_summary,
       (SELECT a.title FROM action_items a WHERE a.person_id = p.id AND a.status IN ('open', 'waiting') ORDER BY a.due_on NULLS LAST LIMIT 1) AS next_action,
       p.notes
FROM people p
LEFT JOIN organizations o ON o.id = p.org_id
WHERE p.outreach_stage IS NOT NULL AND p.merged_into_id IS NULL;

-- Stage events per week (Monday start) and segment: how many requests went out, how many
-- accepted, how many calls. Built from the interactions rows log_touch.py writes on each stage change.
CREATE OR REPLACE VIEW v_outreach_weekly AS
SELECT date_trunc('week', i.occurred_at)::date AS week_of,
       COALESCE(p.outreach_segment, 'other') AS segment,
       count(*) FILTER (WHERE split_part(i.source_id, ':', 2) = 'requested') AS requested,
       count(*) FILTER (WHERE split_part(i.source_id, ':', 2) = 'connected') AS connected,
       count(*) FILTER (WHERE split_part(i.source_id, ':', 2) = 'conversation') AS conversations,
       count(*) FILTER (WHERE split_part(i.source_id, ':', 2) = 'call_held') AS calls,
       count(*) FILTER (WHERE split_part(i.source_id, ':', 2) = 'nurture') AS to_nurture,
       count(*) FILTER (WHERE split_part(i.source_id, ':', 2) = 'closed') AS closed
FROM interactions i
JOIN people p ON p.id = i.person_id
WHERE i.source = 'outreach'
GROUP BY 1, 2;
