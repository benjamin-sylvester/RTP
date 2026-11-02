-- 025: newsletter audience = everyone. Every person in the database with an email (except
-- internal: Ben, Justin) plus every active website subscriber, one row per email. Anyone who
-- unsubscribed (a newsletter_subscribers row with unsubscribed_at set) is left out, even if they
-- are also a person in the database. The deal list for raises stays separate: people with roles
-- lp / lp_prospect (v_lp_pipeline).
-- `via` says where the address came from: database, website, website_investor (or a mix).

CREATE OR REPLACE VIEW v_newsletter_audience AS
WITH person_email AS (
  SELECT DISTINCT ON (p.id) p.id AS person_id, lower(e.email::text) AS email
  FROM people p JOIN people_emails e ON e.person_id = p.id
  WHERE p.merged_into_id IS NULL AND NOT (p.roles && ARRAY['internal']::text[])
  ORDER BY p.id, e.is_primary DESC NULLS LAST, e.id
),
all_rows AS (
  SELECT email, person_id, 'database' AS via FROM person_email
  UNION ALL
  SELECT lower(s.email::text), s.person_id, s.source FROM newsletter_subscribers s WHERE s.unsubscribed_at IS NULL
),
by_email AS (
  SELECT email, max(person_id) AS person_id, string_agg(DISTINCT via, ', ' ORDER BY via) AS via
  FROM all_rows GROUP BY email
)
SELECT b.email, b.person_id, p.full_name, p.roles, p.lp_tier, b.via
FROM by_email b LEFT JOIN people p ON p.id = b.person_id
WHERE NOT EXISTS (
  SELECT 1 FROM newsletter_subscribers s
  WHERE lower(s.email::text) = b.email AND s.unsubscribed_at IS NOT NULL
);
