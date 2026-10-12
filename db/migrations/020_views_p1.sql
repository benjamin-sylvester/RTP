-- Migration 020: Phase 1 views (db/DATA_MODEL.md "Views"). Idempotent.
-- v_property_history is rebuilt here because 015's version predates offers and entities.

DROP VIEW IF EXISTS v_property_history;
CREATE VIEW v_property_history AS
SELECT 'listing'::text AS event_kind, p.id AS property_id, p.address, p.city, p.state, p.rtp_relationship,
       l.date_ingested AS event_at, l.id AS ref_id, l.status AS detail_status,
       l.asking_price AS amount_cents, l.source AS detail, l.broker_name
FROM properties p JOIN listings l ON l.property_id = p.id
UNION ALL
SELECT 'sale', p.id, p.address, p.city, p.state, p.rtp_relationship,
       l.sale_date::timestamptz, l.id, 'sold', l.sale_price, l.source, l.broker_name
FROM properties p JOIN listings l ON l.property_id = p.id WHERE l.sale_price IS NOT NULL
UNION ALL
SELECT 'offer', p.id, p.address, p.city, p.state, p.rtp_relationship,
       o.offer_date::timestamptz, o.id, o.response, o.price_cents, o.offer_type || ' ' || o.direction, NULL
FROM properties p JOIN listings l ON l.property_id = p.id JOIN offers o ON o.listing_id = l.id
UNION ALL
SELECT 'package_offer', p.id, p.address, p.city, p.state, p.rtp_relationship,
       o.offer_date::timestamptz, o.id, o.response, o.price_cents, o.offer_type || ' ' || o.direction || ' (package)', NULL
FROM properties p JOIN listings l ON l.property_id = p.id JOIN offers o ON o.package_id = l.package_id
UNION ALL
SELECT 'entity', p.id, p.address, p.city, p.state, p.rtp_relationship,
       COALESCE(e.formed_on::timestamptz, e.created_at), e.id, e.kind, NULL, e.legal_name, NULL
FROM properties p JOIN entities e ON e.property_id = p.id;

CREATE OR REPLACE VIEW v_broker_activity AS
SELECT COALESCE(pe.full_name, l.broker_name) AS broker, l.broker_email, l.broker_person_id,
       date_trunc('month', l.date_ingested)::date AS month,
       count(*) AS listings_sent,
       count(*) FILTER (WHERE l.status IN ('lead','underwriting','loi_sent','under_contract')) AS active_now,
       count(*) FILTER (WHERE l.status IN ('loi_sent','under_contract','lost')) AS bid_on,
       (SELECT max(i.occurred_at) FROM interactions i WHERE i.person_id = l.broker_person_id) AS last_interaction
FROM listings l
LEFT JOIN people pe ON pe.id = l.broker_person_id
WHERE l.merged_into_id IS NULL AND COALESCE(pe.full_name, l.broker_name) IS NOT NULL
GROUP BY 1, 2, 3, 4;

CREATE OR REPLACE VIEW v_lp_pipeline AS
SELECT p.id AS person_id, p.full_name, o.name AS organization, p.roles, p.lp_tier, p.lp_relationship,
       p.lp_indicated_cents, p.lp_next_deal_stage, p.warmth,
       (SELECT e.email FROM people_emails e WHERE e.person_id = p.id ORDER BY e.is_primary DESC, e.id LIMIT 1) AS email,
       (SELECT max(i.occurred_at) FROM interactions i WHERE i.person_id = p.id) AS last_interaction,
       (SELECT i.summary FROM interactions i WHERE i.person_id = p.id ORDER BY i.occurred_at DESC LIMIT 1) AS last_summary,
       (SELECT count(*) FROM investments v WHERE v.person_id = p.id) AS deals_invested,
       (SELECT sum(v.funded_cents) FROM investments v WHERE v.person_id = p.id) AS funded_cents,
       (SELECT a.title FROM action_items a WHERE a.person_id = p.id AND a.status IN ('open','waiting')
          ORDER BY a.due_on NULLS LAST, a.id LIMIT 1) AS next_action,
       (SELECT a.due_on FROM action_items a WHERE a.person_id = p.id AND a.status IN ('open','waiting')
          ORDER BY a.due_on NULLS LAST, a.id LIMIT 1) AS next_action_due
FROM people p
LEFT JOIN organizations o ON o.id = p.org_id
WHERE p.merged_into_id IS NULL
  AND (p.roles && ARRAY['lp','lp_prospect','capital_partner']::text[]);

CREATE OR REPLACE VIEW v_action_items_open AS
SELECT a.id, a.title, a.details, a.status, a.due_on,
       own.full_name AS owner,
       pe.full_name AS about_person, o.name AS about_org,
       l.address AS about_listing, pk.name AS about_package, pr.address AS about_property, e.short_name AS about_entity,
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

CREATE OR REPLACE VIEW v_investor_positions AS
SELECT e.id AS entity_id, e.short_name AS entity, p.id AS person_id, p.full_name AS investor,
       io.name AS investor_entity, v.share_class, v.commitment_cents, v.funded_cents, v.funded_on,
       v.ownership_pct, v.is_gp
FROM investments v
JOIN entities e ON e.id = v.entity_id
LEFT JOIN people p ON p.id = v.person_id
LEFT JOIN organizations io ON io.id = v.investor_org_id
ORDER BY e.id, v.is_gp DESC, v.funded_cents DESC NULLS LAST;
