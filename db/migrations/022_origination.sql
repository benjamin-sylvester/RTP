-- Migration 022: Origination tab support (v_owner_calls view for the owner CRM).

CREATE OR REPLACE VIEW v_owner_calls AS
SELECT
  p.id AS person_id,
  p.full_name AS owner_name,
  p.owner_tier,
  p.owner_score,
  p.phone,
  p.city AS owner_city,
  p.state AS owner_state,
  o.id AS org_id,
  o.name AS organization,
  COALESCE(
    STRING_AGG(DISTINCT pr.city, ', ' ORDER BY pr.city),
    ''
  ) AS properties_cities,
  COUNT(DISTINCT pr.id) AS property_count,
  SUM(DISTINCT pr.units) FILTER (WHERE pr.units IS NOT NULL) AS total_units,
  STRING_AGG(DISTINCT pr.address, ' | ' ORDER BY pr.address) AS property_addresses,
  (SELECT i.channel FROM interactions i
   WHERE i.person_id = p.id AND i.channel = 'call'
   ORDER BY i.occurred_at DESC LIMIT 1) AS last_contact_channel,
  (SELECT i.occurred_at FROM interactions i
   WHERE i.person_id = p.id AND i.channel = 'call'
   ORDER BY i.occurred_at DESC LIMIT 1) AS last_contact_date,
  (SELECT i.summary FROM interactions i
   WHERE i.person_id = p.id AND i.channel = 'call'
   ORDER BY i.occurred_at DESC LIMIT 1) AS last_contact_outcome,
  (SELECT CASE
     WHEN i.summary ILIKE '%sell now%' THEN 'Sell now'
     WHEN i.summary ILIKE '%sell later%' THEN 'Sell later'
     WHEN i.summary ILIKE '%maybe%' OR i.summary ILIKE '%warm%' THEN 'Maybe / warm'
     WHEN i.summary ILIKE '%not selling%' THEN 'Not selling'
     WHEN i.summary ILIKE '%no answer%' THEN 'No answer'
     WHEN i.summary ILIKE '%wrong%' THEN 'Wrong number'
     ELSE NULL
   END
   FROM interactions i
   WHERE i.person_id = p.id AND i.channel = 'call'
   ORDER BY i.occurred_at DESC LIMIT 1) AS call_status,
  (SELECT a.due_on FROM action_items a
   WHERE a.person_id = p.id AND a.category = 'deal' AND a.status IN ('open','waiting')
   ORDER BY a.due_on NULLS LAST LIMIT 1) AS next_followup_date
FROM people p
LEFT JOIN organizations o ON o.id = p.org_id
LEFT JOIN properties pr ON pr.owner_of_record = o.name OR pr.owner_of_record = p.full_name
WHERE 'owner' = ANY(p.roles) AND p.merged_into_id IS NULL
GROUP BY p.id, p.full_name, p.owner_tier, p.owner_score, p.phone, p.city, p.state,
         o.id, o.name
ORDER BY p.owner_tier, p.owner_score DESC;
