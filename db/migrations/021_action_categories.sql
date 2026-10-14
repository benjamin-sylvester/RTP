-- Migration 021: action items become real tasks (Ben, 10/13/26).
-- category (deal / capital / property / admin / network) for grouping, waiting_since set by
-- trigger when an item moves to 'waiting', and v_action_items_open exposes the link ids so
-- the dashboard can open the deal or person. Idempotent.

ALTER TABLE action_items ADD COLUMN IF NOT EXISTS category TEXT
  CHECK (category IS NULL OR category IN ('deal','capital','property','admin','network'));
ALTER TABLE action_items ADD COLUMN IF NOT EXISTS waiting_since TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION rtp_action_waiting_since() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'waiting' AND (OLD.status IS DISTINCT FROM 'waiting') THEN
    NEW.waiting_since = now();
  ELSIF NEW.status <> 'waiting' THEN
    NEW.waiting_since = NULL;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_action_items_waiting ON action_items;
CREATE TRIGGER trg_action_items_waiting BEFORE UPDATE ON action_items
  FOR EACH ROW EXECUTE FUNCTION rtp_action_waiting_since();

UPDATE action_items SET waiting_since = updated_at WHERE status = 'waiting' AND waiting_since IS NULL;

-- default category from what the item is linked to
UPDATE action_items a SET category = CASE
  WHEN a.listing_id IS NOT NULL OR a.package_id IS NOT NULL THEN 'deal'
  WHEN a.property_id IS NOT NULL OR a.entity_id IS NOT NULL THEN 'property'
  WHEN a.person_id IS NOT NULL AND EXISTS (SELECT 1 FROM people p WHERE p.id = a.person_id
         AND p.roles && ARRAY['lp','lp_prospect','capital_partner']::text[]) THEN 'capital'
  WHEN a.person_id IS NOT NULL AND EXISTS (SELECT 1 FROM people p WHERE p.id = a.person_id
         AND p.roles && ARRAY['broker','owner']::text[]) THEN 'deal'
  WHEN a.person_id IS NOT NULL OR a.org_id IS NOT NULL THEN 'network'
  ELSE 'admin' END
WHERE a.category IS NULL;

DROP VIEW IF EXISTS v_action_items_open;
CREATE VIEW v_action_items_open AS
SELECT a.id, a.title, a.details, a.status, a.due_on, a.category, a.waiting_since,
       own.full_name AS owner,
       pe.full_name AS about_person, o.name AS about_org,
       l.address AS about_listing, pk.name AS about_package, pr.address AS about_property, e.short_name AS about_entity,
       a.person_id, a.org_id, a.listing_id, a.package_id, a.property_id, a.entity_id,
       a.source, a.created_at, a.updated_at
FROM action_items a
LEFT JOIN people own ON own.id = a.owner_person_id
LEFT JOIN people pe ON pe.id = a.person_id
LEFT JOIN organizations o ON o.id = a.org_id
LEFT JOIN listings l ON l.id = a.listing_id
LEFT JOIN packages pk ON pk.id = a.package_id
LEFT JOIN properties pr ON pr.id = a.property_id
LEFT JOIN entities e ON e.id = a.entity_id
WHERE a.status IN ('open','waiting')
ORDER BY a.due_on NULLS LAST, a.id;
