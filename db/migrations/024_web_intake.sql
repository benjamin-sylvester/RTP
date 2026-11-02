-- Migration 024 (11/2/26): website intake. Newsletter signups from rtprei.com land here;
-- investor-interest submissions use the existing people / people_emails / interactions /
-- action_items tables (no schema change). A subscriber is not necessarily a person Ben tracks,
-- so the list is its own table with a nullable link to people. Idempotent.

CREATE TABLE IF NOT EXISTS newsletter_subscribers (
  id                SERIAL PRIMARY KEY,
  email             CITEXT NOT NULL UNIQUE,
  person_id         INTEGER REFERENCES people(id),
  source            TEXT NOT NULL DEFAULT 'website',
  consent_text      TEXT,
  subscribed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  unsubscribed_at   TIMESTAMPTZ,
  unsubscribe_token UUID NOT NULL DEFAULT gen_random_uuid()
);
CREATE INDEX IF NOT EXISTS idx_newsletter_person ON newsletter_subscribers (person_id);

CREATE OR REPLACE VIEW v_newsletter_active AS
SELECT s.id, s.email, s.person_id, p.full_name, s.source, s.subscribed_at, s.unsubscribe_token
FROM newsletter_subscribers s
LEFT JOIN people p ON p.id = s.person_id
WHERE s.unsubscribed_at IS NULL;
