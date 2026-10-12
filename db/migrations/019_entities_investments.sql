-- Migration 019: investor relations, part 1. entities and investments (db/DATA_MODEL.md Block 5),
-- plus the deferred entity_id foreign keys from 017. One investment row per LP per entity
-- (Ben, 10/12/26). Idempotent.

CREATE TABLE IF NOT EXISTS entities (
  id                               SERIAL PRIMARY KEY,
  legal_name                       TEXT NOT NULL UNIQUE,
  short_name                       TEXT,
  kind                             TEXT NOT NULL CHECK (kind IN ('sponsor','deal_spv','holding','personal','pm_company')),
  state_of_formation               CHAR(2),
  ein_on_file                      BOOLEAN NOT NULL DEFAULT false,
  formed_on                        DATE,
  registered_agent_org_id          INTEGER REFERENCES organizations(id),
  property_id                      INTEGER REFERENCES properties(id),
  manager                          TEXT,
  operating_agreement_document_id  INTEGER REFERENCES documents(id),
  notes                            TEXT,
  created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_entities_touch ON entities;
CREATE TRIGGER trg_entities_touch BEFORE UPDATE ON entities
  FOR EACH ROW EXECUTE FUNCTION rtp_touch_updated_at();

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_interactions_entity') THEN
    ALTER TABLE interactions ADD CONSTRAINT fk_interactions_entity FOREIGN KEY (entity_id) REFERENCES entities(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_action_items_entity') THEN
    ALTER TABLE action_items ADD CONSTRAINT fk_action_items_entity FOREIGN KEY (entity_id) REFERENCES entities(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_documents_entity') THEN
    ALTER TABLE documents ADD CONSTRAINT fk_documents_entity FOREIGN KEY (entity_id) REFERENCES entities(id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS investments (
  id                SERIAL PRIMARY KEY,
  entity_id         INTEGER NOT NULL REFERENCES entities(id),
  person_id         INTEGER REFERENCES people(id),
  investor_org_id   INTEGER REFERENCES organizations(id),
  share_class       TEXT,
  commitment_cents  BIGINT,
  funded_cents      BIGINT,
  funded_on         DATE,
  ownership_pct     NUMERIC(8,6),
  is_gp             BOOLEAN NOT NULL DEFAULT false,
  document_id       INTEGER REFERENCES documents(id),
  notes             TEXT,
  source            TEXT,
  source_id         TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (person_id IS NOT NULL OR investor_org_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_investments ON investments
  (entity_id, COALESCE(person_id, 0), COALESCE(investor_org_id, 0), COALESCE(share_class, ''));
DROP TRIGGER IF EXISTS trg_investments_touch ON investments;
CREATE TRIGGER trg_investments_touch BEFORE UPDATE ON investments
  FOR EACH ROW EXECUTE FUNCTION rtp_touch_updated_at();

-- Seed: RTP's known entities. State of formation for Rising Tide Partners LLC is unconfirmed
-- (Harbor Compliance notice says Wyoming; capital/CLAUDE.md says Delaware).
INSERT INTO entities (legal_name, short_name, kind, state_of_formation, ein_on_file, property_id, manager, notes)
SELECT v.legal_name, v.short_name, v.kind, v.st, v.ein, p.id, v.manager, v.notes
FROM (VALUES
  ('Rising Tide Partners LLC', 'RTP', 'sponsor', NULL::char(2), true, NULL::text,
   'Ben Sylvester and Justin Kanterman, co-managers',
   'Sponsor / GP entity. State of formation [CONFIRM: WY per Harbor Compliance 10/6 notice vs DE per notes]. Registered agent Harbor Compliance, renew by 11/5/26.'),
  ('Rising Tide Realty Group LLC', 'RTRG', 'deal_spv', 'MA', true, '42-44 Summer St|Leominster|MA',
   'Ben Sylvester and Justin Kanterman',
   'Owns 42-44 Summer St, Leominster. Family LPs. MA annual report due 11/26/26. Sale via H&T planned for early 2027.'),
  ('186 John Street LLC', 'John St LLC', 'deal_spv', 'MA', true, '186 John Street|Fall River|MA',
   'Rising Tide Partners LLC (Manager)',
   'Owns 186 John St, Fall River. 18 outside LPs, ~$431K equity. OA sends the 30 pct promote to RTP LLC as Manager. Annual report paid 8/21/26.'),
  ('BHS Holdings LLC', 'BHS', 'personal', 'DE', false, NULL::text,
   'Ben Sylvester',
   'Ben''s personal Delaware entity; pays some RTP expenses. Registered agent renewal 10/17/26.')
) AS v(legal_name, short_name, kind, st, ein, prop_key, manager, notes)
LEFT JOIN properties p ON v.prop_key IS NOT NULL
  AND p.address_key = rtp_normalize_address(split_part(v.prop_key, '|', 1), split_part(v.prop_key, '|', 2), split_part(v.prop_key, '|', 3))
WHERE NOT EXISTS (SELECT 1 FROM entities e WHERE e.legal_name = v.legal_name);

-- Owned properties follow their entities
UPDATE properties p SET rtp_relationship = 'owned'
FROM entities e WHERE e.property_id = p.id AND e.kind = 'deal_spv' AND p.rtp_relationship <> 'owned';
